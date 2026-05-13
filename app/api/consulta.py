"""
Endpoint público de consulta de estado de denuncias.

Sin autenticación: el código público actúa como token único.

  GET /alerta/{codigo}  → {codigo, estado, fecha_registro}

Razones de seguridad:
  - El espacio de códigos es ~32^6 ≈ 1B/año. Adivinar uno por fuerza
    bruta es prácticamente imposible en ventanas razonables.
  - El endpoint solo expone: código (que el caller ya conoce), estado y
    timestamp de registro. NUNCA institución, descripción ni ningún
    dato sensible.
  - Rate limited a 30/min por IP para evitar enumeración masiva.

Si más adelante se quiere endurecer, agregar:
  - Pin de 4 dígitos generado al registrar la denuncia (se manda al
    ciudadano junto al código). Convierte el código + pin en credencial
    de dos factores.
  - Captcha en la URL pública para reducir scraping.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.codigo_publico import es_codigo_valido
from app.database import get_db
from app.models.alerta import Alerta
from app.utils.logger import obtener_logger

log = obtener_logger(__name__)

router = APIRouter(tags=["consulta"])
_limiter = Limiter(key_func=get_remote_address)


@router.get("/alerta/{codigo}")
@_limiter.limit("30/minute")
async def consultar_estado(
    request: Request,
    codigo: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Devuelve el estado público de una denuncia por su código.

    Args:
        codigo: formato ALR-YYYY-XXXXXX (alfabeto sin caracteres ambiguos).

    Returns:
        {
            "codigo": "ALR-2026-K7M2QH",
            "estado": "EN_REVISION",
            "fecha_registro": "2026-05-11T20:00:00+00:00"
        }

    Errores:
        404 — código inválido (formato incorrecto o no existe en BD).
              Devolvemos el mismo error para ambos casos para no permitir
              enumeración (un atacante no puede distinguir entre
              "código mal formado" y "código bien formado pero inexistente").
    """
    # Validación de formato antes de tocar BD (más rápido y evita inyección)
    if not es_codigo_valido(codigo):
        log.info(
            "consulta_codigo_invalido_formato",
            codigo_prefix=codigo[:8] if codigo else None,
        )
        raise HTTPException(status_code=404, detail="Código no encontrado.")

    result = await db.execute(
        select(
            Alerta.codigo_publico,
            Alerta.estado,
            Alerta.timestamp_registro,
        ).where(Alerta.codigo_publico == codigo)
    )
    fila = result.first()
    if not fila:
        log.info("consulta_codigo_inexistente", codigo=codigo)
        raise HTTPException(status_code=404, detail="Código no encontrado.")

    log.info("consulta_estado_ok", codigo=codigo, estado=fila.estado)
    return {
        "codigo": fila.codigo_publico,
        "estado": fila.estado,
        "fecha_registro": fila.timestamp_registro.isoformat(),
    }
