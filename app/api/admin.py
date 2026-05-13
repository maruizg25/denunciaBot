"""
Panel administrativo del bot — web mínimo con autenticación por token.

Endpoints:
  - GET  /admin/health            health check (sin auth)
  - GET  /admin/health/db         verifica BD (sin auth)
  - GET  /admin/stats             cardinalidades (sin auth)
  - GET  /admin/login             form de inicio de sesión
  - POST /admin/login             valida token, setea cookie
  - POST /admin/logout            limpia cookie
  - GET  /admin/alertas           listado paginado con filtros
  - GET  /admin/alertas/{id}      detalle con descifrado
  - POST /admin/alertas/{id}/estado  cambia estado (auditado en bitácora)

Auth: cookie HTTP-only con HMAC del ADMIN_TOKEN. Si `ADMIN_TOKEN` está
vacío en settings, todos los endpoints HTML devuelven 503 — el panel
queda EXPLÍCITAMENTE deshabilitado.

Seguridad:
  - Cookie `Secure` solo se setea si APP_ENV=production (en dev local
    sobre HTTP no funcionaría).
  - SameSite=Lax para mitigar CSRF en GETs; para POSTs el token cookie
    es la única auth, suficiente para volúmenes pequeños.
  - Cada cambio de estado registra en `bitacora_auditoria` con el actor
    "ADMIN" y el id de sesión (8 chars del HMAC). NO firmamos con un
    usuario individual porque el panel es de uso compartido — si se
    necesita trazabilidad personal, agregar campo `admin_user` después.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.security import get_crypto
from app.database import get_db
from app.models.alerta import Alerta, EstadoAlerta
from app.models.bitacora import ActorBitacora, EventoBitacora, TipoEvento
from app.utils.logger import obtener_logger

log = obtener_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Template engine — la ruta es absoluta para que funcione tanto en local
# como bajo gunicorn/systemd con WorkingDirectory=/opt/denunciabot.
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_TAMANIO_PAGINA: int = 25


# =========================================================================
# Auth — cookie firmada con HMAC
# =========================================================================

def _firmar_cookie(token: str) -> str:
    """Devuelve un valor de cookie = HMAC-SHA256(token, token) truncado.

    No es una sesión real (sin server-side storage); es una "señal" de que
    el bearer conoció el token alguna vez. Para volumen institucional
    chico es suficiente.
    """
    return hmac.new(token.encode(), token.encode(), hashlib.sha256).hexdigest()


def _validar_cookie(cookie_valor: str | None, settings) -> bool:
    if not cookie_valor:
        return False
    token = settings.ADMIN_TOKEN.get_secret_value()
    if not token:
        return False
    esperado = _firmar_cookie(token)
    return hmac.compare_digest(cookie_valor, esperado)


def _exigir_admin_token(settings) -> None:
    """503 si el panel está deshabilitado (sin ADMIN_TOKEN configurado)."""
    if not settings.ADMIN_TOKEN.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Panel admin deshabilitado — configurar ADMIN_TOKEN en .env",
        )


async def autenticado(
    request: Request,
    cookie: str | None = Cookie(default=None, alias="denunciabot_admin"),
) -> str:
    """Dependency que asegura sesión válida. Redirige a /admin/login si no.

    Devuelve el identificador corto de sesión (8 chars del HMAC) para
    incluir en bitácora.
    """
    settings = get_settings()
    _exigir_admin_token(settings)

    # El nombre real de la cookie viene de settings — pero FastAPI exige
    # nombres literales en el parámetro. Usamos el default y validamos.
    nombre_esperado = settings.ADMIN_COOKIE_NAME
    cookie_val = request.cookies.get(nombre_esperado)
    if not _validar_cookie(cookie_val, settings):
        # Para handlers HTML redirigimos al login; HTMX necesita 401.
        if "HX-Request" in request.headers:
            raise HTTPException(status_code=401, detail="Sesión expirada")
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/admin/login"},
        )
    return cookie_val[:8]  # identificador corto para auditoría


# =========================================================================
# Health & stats (sin auth — útiles para monitoreo)
# =========================================================================

@router.get("/health")
async def health_admin() -> dict[str, str]:
    return {"status": "ok", "modulo": "admin"}


@router.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    await db.execute(select(1))
    return {"status": "ok", "db": "alcanzable"}


@router.get("/stats")
async def estadisticas(db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    total_alertas = await db.scalar(select(func.count()).select_from(Alerta))
    total_bitacora = await db.scalar(select(func.count()).select_from(EventoBitacora))
    return {
        "alertas_totales": int(total_alertas or 0),
        "eventos_bitacora": int(total_bitacora or 0),
    }


# =========================================================================
# Login / Logout
# =========================================================================

@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> Response:
    settings = get_settings()
    _exigir_admin_token(settings)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "usuario_autenticado": False, "error": None},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    token: str = Form(...),
) -> Response:
    settings = get_settings()
    _exigir_admin_token(settings)
    esperado = settings.ADMIN_TOKEN.get_secret_value()

    if not hmac.compare_digest(token, esperado):
        log.warning("admin_login_fallido", ip=request.client.host if request.client else None)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "usuario_autenticado": False,
                "error": "Token incorrecto.",
            },
            status_code=401,
        )

    cookie_valor = _firmar_cookie(esperado)
    response = RedirectResponse(url="/admin/alertas", status_code=303)
    response.set_cookie(
        key=settings.ADMIN_COOKIE_NAME,
        value=cookie_valor,
        max_age=settings.ADMIN_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.es_produccion,
        samesite="lax",
    )
    log.info("admin_login_ok", sesion_prefix=cookie_valor[:8])
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    settings = get_settings()
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(key=settings.ADMIN_COOKIE_NAME)
    return response


# =========================================================================
# Listado de alertas
# =========================================================================

@router.get("/alertas", response_class=HTMLResponse)
async def listar_alertas(
    request: Request,
    estado: str | None = None,
    codigo: str | None = None,
    pagina: int = 1,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(autenticado),
) -> Response:
    """Listado paginado de alertas con filtros simples."""
    if pagina < 1:
        pagina = 1

    estados_validos = [e.value for e in EstadoAlerta]
    if estado and estado not in estados_validos:
        estado = None

    base_stmt = select(Alerta).options(selectinload(Alerta.evidencias))
    if estado:
        base_stmt = base_stmt.where(Alerta.estado == estado)
    if codigo:
        base_stmt = base_stmt.where(Alerta.codigo_publico.ilike(f"%{codigo.strip().upper()}%"))

    # Count total para paginación
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = int((await db.scalar(count_stmt)) or 0)
    total_paginas = max(1, (total + _TAMANIO_PAGINA - 1) // _TAMANIO_PAGINA)
    if pagina > total_paginas:
        pagina = total_paginas

    listado_stmt = (
        base_stmt.order_by(Alerta.timestamp_registro.desc())
        .offset((pagina - 1) * _TAMANIO_PAGINA)
        .limit(_TAMANIO_PAGINA)
    )
    result = await db.execute(listado_stmt)
    alertas_raw = result.scalars().all()

    # Adjuntamos el conteo de evidencias para mostrarlo en la tabla
    alertas = []
    for a in alertas_raw:
        a.num_evidencias = len(a.evidencias)  # type: ignore[attr-defined]
        alertas.append(a)

    return templates.TemplateResponse(
        "alertas.html",
        {
            "request": request,
            "usuario_autenticado": True,
            "alertas": alertas,
            "total": total,
            "total_paginas": total_paginas,
            "pagina_tamanio": _TAMANIO_PAGINA,
            "estados_validos": estados_validos,
            "filtros": {"estado": estado, "codigo": codigo, "pagina": pagina},
        },
    )


# =========================================================================
# Detalle de una alerta (descifra al vuelo)
# =========================================================================

@router.get("/alertas/{alerta_id}", response_class=HTMLResponse)
async def detalle_alerta(
    alerta_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(autenticado),
) -> Response:
    """Detalle completo descifrando los campos sensibles con Fernet."""
    result = await db.execute(
        select(Alerta)
        .options(selectinload(Alerta.evidencias))
        .where(Alerta.id == alerta_id)
    )
    alerta = result.scalar_one_or_none()
    if not alerta:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    # Bitácora reciente (últimos 20 eventos)
    eventos_q = await db.execute(
        select(EventoBitacora)
        .where(EventoBitacora.alerta_id == alerta_id)
        .order_by(EventoBitacora.timestamp.desc())
        .limit(20)
    )
    eventos = list(eventos_q.scalars().all())

    crypto = get_crypto()
    datos_descifrados = {
        "institucion": crypto.descifrar(alerta.institucion_denunciada),
        "descripcion": crypto.descifrar(alerta.descripcion_hechos),
        "involucrados": crypto.descifrar(alerta.personas_involucradas),
    }

    # Descifrar nombres de evidencias
    evidencias_render = []
    for ev in alerta.evidencias:
        try:
            nombre = crypto.descifrar(ev.nombre_original) or "<sin nombre>"
        except Exception:
            nombre = "<error al descifrar>"
        ev.nombre_descifrado = nombre  # type: ignore[attr-defined]
        evidencias_render.append(ev)

    return templates.TemplateResponse(
        "alerta_detalle.html",
        {
            "request": request,
            "usuario_autenticado": True,
            "alerta": alerta,
            "datos": datos_descifrados,
            "evidencias": evidencias_render,
            "eventos": eventos,
            "estados_disponibles": [e.value for e in EstadoAlerta],
        },
    )


# =========================================================================
# Cambio de estado (POST HTMX → devuelve el chip actualizado)
# =========================================================================

@router.post("/alertas/{alerta_id}/estado", response_class=HTMLResponse)
async def cambiar_estado(
    alerta_id: int,
    request: Request,
    nuevo_estado: str = Form(...),
    db: AsyncSession = Depends(get_db),
    sesion_id: str = Depends(autenticado),
) -> Response:
    """Cambia el estado de una alerta y registra el cambio en bitácora."""
    estados_validos = {e.value for e in EstadoAlerta}
    if nuevo_estado not in estados_validos:
        raise HTTPException(status_code=400, detail="Estado no válido")

    result = await db.execute(select(Alerta).where(Alerta.id == alerta_id))
    alerta = result.scalar_one_or_none()
    if not alerta:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    estado_anterior = alerta.estado
    if estado_anterior == nuevo_estado:
        # No hacemos nada — pero devolvemos el chip actual para que HTMX no rompa.
        return templates.TemplateResponse(
            "_chip_estado.html",
            {"request": request, "estado": estado_anterior},
        )

    alerta.estado = nuevo_estado
    db.add(
        EventoBitacora(
            alerta_id=alerta_id,
            evento=TipoEvento.ALERTA_ACTUALIZADA.value,
            actor=f"ADMIN:{sesion_id}",
            detalle={
                "estado_anterior": estado_anterior,
                "estado_nuevo": nuevo_estado,
            },
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Conflicto al actualizar estado")

    log.info(
        "admin_estado_cambiado",
        alerta_id=alerta_id,
        de=estado_anterior,
        a=nuevo_estado,
        sesion=sesion_id,
    )
    return templates.TemplateResponse(
        "_chip_estado.html",
        {"request": request, "estado": nuevo_estado},
    )
