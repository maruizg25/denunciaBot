"""
Endpoints del webhook de Meta (WhatsApp Cloud API).

Dos rutas:

  GET /webhook  — verificación inicial. Meta envía `hub.mode`, `hub.verify_token`
                  y `hub.challenge`. Si el token coincide con `META_VERIFY_TOKEN`,
                  respondemos con el challenge en texto plano. Si no, 403.

  POST /webhook — recepción de mensajes y eventos.
    1. Lee el cuerpo CRUDO (necesario para validar HMAC sin re-serializar).
    2. Valida `X-Hub-Signature-256`. Si falla, 401.
    3. Parsea el payload con Pydantic. Si es inválido, ignora y devuelve 200.
    4. Aplana los mensajes y procesa cada uno con motor + orquestador.
    5. SIEMPRE devuelve 200 (excepto firma inválida): si devolviéramos 5xx,
       Meta reintentaría y crearíamos duplicados.

Cualquier excepción al procesar un mensaje individual se loguea y se ignora —
no detiene el resto del lote.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.conversacion.motor import EvidenciaEntrante, Mensaje, procesar_mensaje
from app.core.meta_client import MetaAPIError, get_meta_client
from app.core.security import correlacion_log, get_crypto, validar_firma_meta
from app.database import get_db
from app.schemas.meta import MetaMessage, MetaWebhookPayload
from app.services.evidencia_service import ClamAVError, escanear_con_clamav
from app.services.idempotency_service import intentar_marcar_procesado
from app.services.orquestador import ejecutar
from app.services.sesion_service import RedisError, obtener_sesion
from app.utils.logger import bind_contexto, clear_contexto, obtener_logger

log = obtener_logger(__name__)

router = APIRouter(tags=["webhook"])


# =========================================================================
# GET /webhook — verificación
# =========================================================================

@router.get("/webhook", response_class=PlainTextResponse)
async def verificar_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> str:
    """Endpoint de verificación que Meta llama al registrar el webhook."""
    settings = get_settings()
    esperado = settings.META_VERIFY_TOKEN.get_secret_value()

    if hub_mode == "subscribe" and hub_verify_token == esperado:
        log.info("webhook_verificado")
        return hub_challenge

    log.warning(
        "webhook_verificacion_fallida",
        hub_mode=hub_mode,
        token_coincide=False,
    )
    raise HTTPException(status_code=403, detail="Verificación fallida")


# =========================================================================
# POST /webhook — recepción
# =========================================================================

@router.post("/webhook")
async def recibir_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, str]:
    """Recibe un evento de WhatsApp, valida firma, despacha al motor."""
    cuerpo = await request.body()

    # 1) Validar firma HMAC sobre el cuerpo CRUDO antes de cualquier parseo.
    if not validar_firma_meta(cuerpo, x_hub_signature_256):
        log.warning(
            "webhook_firma_invalida",
            firma_presente=bool(x_hub_signature_256),
        )
        raise HTTPException(status_code=401, detail="Firma inválida")

    # 2) Parsear payload. Si es malformado, ignoramos y respondemos 200
    #    para que Meta no reintente.
    try:
        payload = MetaWebhookPayload.model_validate_json(cuerpo)
    except ValidationError as exc:
        log.warning("webhook_payload_invalido", errores=exc.errors()[:3])
        return {"status": "ignored"}

    mensajes = payload.mensajes_planos()
    if not mensajes:
        # Los webhooks de status (delivery/read) llegan acá; los ignoramos.
        return {"status": "ok"}

    # 3) Procesar cada mensaje en orden. Los errores individuales no rompen
    #    el lote — los demás mensajes siguen procesándose.
    for mensaje_meta in mensajes:
        try:
            await _procesar_mensaje(mensaje_meta, db)
        except Exception as exc:
            log.error(
                "webhook_mensaje_falla",
                wamid_prefix=mensaje_meta.id[:12] if mensaje_meta.id else None,
                error_tipo=type(exc).__name__,
                error_msg=str(exc),
            )
        finally:
            clear_contexto()

    return {"status": "ok"}


# =========================================================================
# Procesamiento de un mensaje individual
# =========================================================================

async def _procesar_mensaje(mensaje_meta: MetaMessage, db: AsyncSession) -> None:
    """Convierte un MetaMessage en `Mensaje` del motor, busca sesión, ejecuta."""
    telefono_e164 = mensaje_meta.from_
    if not telefono_e164:
        log.warning("webhook_mensaje_sin_remitente")
        return

    settings = get_settings()
    crypto = get_crypto()
    telefono_hash = crypto.hash_telefono(telefono_e164)

    bind_contexto(
        wamid=mensaje_meta.id[:12],
        tipo=mensaje_meta.type,
        ciudadano_corr=correlacion_log(telefono_hash),
    )

    # Idempotency: Meta puede reenviar el mismo wamid si no recibe nuestro 200
    # a tiempo. Descartamos duplicados antes de tocar el motor o la BD.
    if not await intentar_marcar_procesado(mensaje_meta.id):
        return

    # Convertir a `Mensaje` del motor. Si es un tipo no soportado o falla
    # la descarga de media, lo manejamos como rechazo amigable.
    try:
        mensaje_motor = await _convertir_mensaje(mensaje_meta, settings)
    except ClamAVError:
        # Antivirus rechazó el archivo — avisamos al ciudadano sin pasar
        # por el motor para que el flujo no incremente intentos.
        from app.conversacion.mensajes import evidencia_rechazada_antivirus

        await _enviar_directo(telefono_e164, evidencia_rechazada_antivirus())
        log.warning("evidencia_antivirus_rechazada", remitente=telefono_e164[:6])
        return
    except _TipoNoSoportado as exc:
        from app.conversacion.mensajes import comando_no_reconocido

        await _enviar_directo(telefono_e164, comando_no_reconocido())
        log.info("tipo_no_soportado", tipo=mensaje_meta.type, detalle=str(exc))
        return
    except MetaAPIError as exc:
        # Falló la descarga de media. No avisamos al ciudadano para no
        # confundirlo; el siguiente intento del bot lo recolectará.
        log.error("descarga_media_falla", error=str(exc))
        return

    # Leer sesión actual desde Redis. Si Redis está caído, avisamos al
    # ciudadano con un mensaje degradado y abortamos sin tocar el motor
    # ni la BD (sin sesión no podemos saber en qué paso del flujo está).
    try:
        sesion = await obtener_sesion(telefono_hash)
    except RedisError:
        from app.conversacion.mensajes import servicio_no_disponible

        await _enviar_directo(telefono_e164, servicio_no_disponible())
        log.error("webhook_redis_caido", remitente_prefix=telefono_e164[:6])
        return

    # Ejecutar motor
    resultado = procesar_mensaje(
        sesion=sesion,
        mensaje=mensaje_motor,
        telefono_hash=telefono_hash,
        destinatario=telefono_e164,
        max_intentos=settings.MAX_INTENTOS_VALIDACION,
        max_evidencias=settings.EVIDENCIAS_MAX_COUNT,
        tamanio_max_bytes=settings.evidencias_max_size_bytes,
        mimes_permitidos=frozenset(settings.evidencias_mime_lista),
    )

    # Despachar acciones (BD + Redis + Meta)
    await ejecutar(resultado, db)


# =========================================================================
# Conversión Meta → motor
# =========================================================================

class _TipoNoSoportado(Exception):
    """El tipo de mensaje recibido no entra en el flujo del bot."""


async def _convertir_mensaje(m: MetaMessage, settings) -> Mensaje:
    """Construye un `Mensaje` del motor a partir del payload de Meta."""
    if m.type == "text":
        return Mensaje(
            texto=(m.text.body if m.text else "") or "",
            message_id_meta=m.id,
        )

    if m.type == "interactive":
        if m.interactive and m.interactive.button_reply:
            return Mensaje(
                texto=m.interactive.button_reply.title or "",
                boton_id=m.interactive.button_reply.id,
                message_id_meta=m.id,
            )
        if m.interactive and m.interactive.list_reply:
            return Mensaje(
                texto=m.interactive.list_reply.title or "",
                boton_id=m.interactive.list_reply.id,
                message_id_meta=m.id,
            )
        raise _TipoNoSoportado("interactive sin button_reply ni list_reply")

    if m.type == "image":
        if not m.image:
            raise _TipoNoSoportado("image sin metadata")
        evidencia = await _descargar_y_validar_media(
            media_id=m.image.id,
            nombre_sugerido=f"imagen.{_extension_para_mime(m.image.mime_type)}",
            settings=settings,
        )
        return Mensaje(
            evidencia=evidencia,
            texto=m.image.caption or None,
            message_id_meta=m.id,
        )

    if m.type == "document":
        if not m.document:
            raise _TipoNoSoportado("document sin metadata")
        evidencia = await _descargar_y_validar_media(
            media_id=m.document.id,
            nombre_sugerido=m.document.filename or "documento.pdf",
            settings=settings,
        )
        return Mensaje(
            evidencia=evidencia,
            texto=m.document.caption or None,
            message_id_meta=m.id,
        )

    raise _TipoNoSoportado(f"tipo de mensaje no manejado: {m.type}")


def _extension_para_mime(mime: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/jpg": "jpg",
        "application/pdf": "pdf",
    }.get((mime or "").lower(), "bin")


async def _descargar_y_validar_media(
    *,
    media_id: str,
    nombre_sugerido: str,
    settings,
) -> EvidenciaEntrante:
    """Descarga el binario desde Meta, lo escanea (si aplica), lo guarda en /tmp."""
    cliente = get_meta_client()
    contenido, mime = await cliente.descargar_media(media_id)

    if not contenido:
        raise _TipoNoSoportado("media descargada con contenido vacío")

    # Escaneo antivirus si está habilitado. Si falla → ClamAVError propaga
    # y el caller responde al ciudadano con el mensaje de seguridad.
    limpio = await escanear_con_clamav(contenido)
    if not limpio:
        raise ClamAVError("archivo marcado por antivirus")

    # Guardar a disco temporal. El servicio de evidencias lo moverá a su
    # ubicación final al persistir la denuncia (S11).
    tmp_dir = Path(settings.EVIDENCIAS_DIR) / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{uuid.uuid4()}.tmp"
    tmp_path.write_bytes(contenido)

    return EvidenciaEntrante(
        media_id=media_id,
        mime=mime,
        tamanio_bytes=len(contenido),
        nombre_original=nombre_sugerido,
        ruta_temporal=str(tmp_path),
    )


# =========================================================================
# Helper: envío directo (sin pasar por el motor)
# =========================================================================

async def _enviar_directo(destinatario: str, texto: str) -> None:
    """Envía un texto al ciudadano sin pasar por el motor.

    Usado para casos excepcionales donde no queremos que el motor procese
    el mensaje (ej. rechazo por antivirus). No registra en bitácora.
    """
    try:
        await get_meta_client().enviar_texto(destinatario, texto)
    except MetaAPIError as exc:
        log.error("envio_directo_falla", error=str(exc))
