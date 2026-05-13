"""
Servicio de notificaciones — corre en worker Dramatiq.

Define dos actors:
  - `enviar_notificacion_alerta(codigo, timestamp)`: envía un email al
    buzón institucional informando de una nueva denuncia.
  - `enviar_mensaje_cierre(destinatario, codigo)`: envía al ciudadano el
    mensaje de cierre con su código de seguimiento via Meta API.

Ambos viven aquí (en lugar de en archivos separados) porque comparten
el mismo broker y se importan juntos por el worker systemd.

Diseño:
  - `configurar_broker_dramatiq()` debe llamarse UNA vez al arranque del
    proceso (api y worker). Hasta entonces, Dramatiq usa el broker stub.
  - Los actors son síncronos. Para Meta usamos asyncio.run + httpx
    porque la lib es async. Cada llamada crea su propio cliente (evita
    problemas de event loops entre procesos worker).
  - Reintentos automáticos con backoff exponencial.

Política de reintentos:
  - SMTP: max_retries=3, 5s a 5min.
  - Cierre Meta: max_retries=5, 10s a 10min (más generoso porque
    queremos hacer todo lo posible para que el ciudadano reciba su código).
  - Después de los reintentos, los mensajes muertos van a la DLQ
    (cola `<nombre>.DQ`) — el operador puede re-encolarlos manualmente.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

import dramatiq
import httpx
from dramatiq.brokers.redis import RedisBroker

from app.utils.logger import obtener_logger

log = obtener_logger(__name__)


# =========================================================================
# Configuración del broker Dramatiq
# =========================================================================

_broker_configurado: bool = False


def configurar_broker_dramatiq() -> RedisBroker:
    """Configura el broker Redis de Dramatiq. Idempotente.

    Debe llamarse en el lifespan de FastAPI Y en el entry point del worker
    Dramatiq antes de procesar mensajes. Importar este módulo NO conecta
    al broker — solo registra los actors.
    """
    global _broker_configurado
    from app.config import get_settings

    settings = get_settings()
    broker_url = settings.REDIS_URL
    # Forzar la DB de Dramatiq (settings.REDIS_DRAMATIQ_DB) — útil cuando
    # el REDIS_URL trae db=0 por defecto.
    broker = RedisBroker(
        url=broker_url,
        db=settings.REDIS_DRAMATIQ_DB,
    )
    dramatiq.set_broker(broker)
    _broker_configurado = True
    log.info(
        "dramatiq_broker_configurado",
        redis_db=settings.REDIS_DRAMATIQ_DB,
    )
    return broker


# =========================================================================
# Actor de notificación
# =========================================================================

@dramatiq.actor(
    max_retries=3,
    min_backoff=5_000,        # 5 segundos
    max_backoff=5 * 60_000,   # 5 minutos
    queue_name="notificaciones",
)
def enviar_notificacion_alerta(codigo_publico: str, timestamp_iso: str) -> None:
    """Envía un email al buzón institucional anunciando una nueva denuncia.

    NO incluye contenido sensible de la denuncia. Solo informa que hay una
    nueva con su código de seguimiento; la revisión real se hace en el
    sistema (panel admin futuro o export CSV).

    Args:
        codigo_publico: código ALR-YYYY-XXXXXX recién generado.
        timestamp_iso: fecha/hora de registro en formato ISO 8601.
    """
    from app.config import get_settings

    settings = get_settings()

    asunto = f"[DenunciaBot] Nueva denuncia registrada: {codigo_publico}"
    cuerpo_texto = _construir_cuerpo(codigo_publico, timestamp_iso, settings.APP_ENV)

    mensaje = EmailMessage()
    mensaje["From"] = formataddr((settings.SMTP_FROM_NAME, str(settings.SMTP_FROM)))
    mensaje["To"] = str(settings.SMTP_TO)
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo_texto)

    try:
        _enviar_smtp(mensaje, settings)
        log.info("smtp_envio_ok", codigo=codigo_publico)
    except Exception as exc:
        log.error(
            "smtp_envio_falla",
            codigo=codigo_publico,
            error_tipo=type(exc).__name__,
            error_msg=str(exc),
        )
        # Re-lanzamos para que Dramatiq reintente según su política.
        raise


# =========================================================================
# Helpers internos
# =========================================================================

def _construir_cuerpo(codigo: str, timestamp_iso: str, entorno: str) -> str:
    """Construye el cuerpo del email institucional."""
    encabezado_entorno = (
        f"\n[ATENCIÓN: ESTE MENSAJE PROVIENE DEL ENTORNO {entorno.upper()}]\n"
        if entorno != "production"
        else ""
    )
    return (
        f"Estimado equipo de Integridad Pública,\n"
        f"{encabezado_entorno}"
        f"\n"
        f"Se ha registrado una nueva denuncia ciudadana en el sistema "
        f"DenunciaBot.\n"
        f"\n"
        f"Código de seguimiento: {codigo}\n"
        f"Fecha de registro:     {timestamp_iso}\n"
        f"\n"
        f"Por motivos de seguridad, los detalles de la denuncia (institución, "
        f"hechos, personas involucradas) NO se incluyen en este correo. "
        f"Acceda al sistema institucional para revisar el contenido.\n"
        f"\n"
        f"— DenunciaBot\n"
        f"Sistema de Denuncias de Integridad Pública del Ecuador\n"
    )


def _enviar_smtp(mensaje: EmailMessage, settings) -> None:
    """Envía el mensaje vía SMTP usando los settings configurados."""
    timeout = settings.SMTP_TIMEOUT_SECONDS

    if settings.SMTP_USE_TLS:
        # STARTTLS sobre el puerto SMTP estándar (587 típicamente)
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout) as srv:
            srv.ehlo()
            srv.starttls()
            srv.ehlo()
            if settings.SMTP_USERNAME:
                srv.login(
                    settings.SMTP_USERNAME,
                    settings.SMTP_PASSWORD.get_secret_value(),
                )
            srv.send_message(mensaje)
    else:
        # SMTP plano — solo aceptable en redes internas confiables.
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout) as srv:
            if settings.SMTP_USERNAME:
                srv.login(
                    settings.SMTP_USERNAME,
                    settings.SMTP_PASSWORD.get_secret_value(),
                )
            srv.send_message(mensaje)


# =========================================================================
# Actor: envío del mensaje de cierre al ciudadano vía Meta API
# =========================================================================

@dramatiq.actor(
    max_retries=5,
    min_backoff=10_000,         # 10 segundos
    max_backoff=10 * 60_000,    # 10 minutos
    queue_name="cierres",
)
def enviar_mensaje_cierre(destinatario: str, codigo_publico: str) -> None:
    """Envía al ciudadano el mensaje de cierre con su código de seguimiento.

    Ejecutado después de un commit exitoso de `registrar_denuncia`. Si la
    primera llamada a Meta falla (5xx, timeout, rate limit), Dramatiq
    reintenta con backoff exponencial. Después de 5 intentos fallidos,
    el mensaje va a la DLQ (`cierres.DQ`) y el operador puede re-encolarlo
    cuando Meta esté operativo (ver RUNBOOK §4).

    Args:
        destinatario: número del ciudadano en formato E.164 sin '+'.
        codigo_publico: código ALR-YYYY-XXXXXX recién generado.
    """
    # Import tardío para evitar ciclo con app.conversacion en el worker
    from app.conversacion.mensajes import cierre_exitoso

    texto = cierre_exitoso(codigo_publico)
    try:
        asyncio.run(_enviar_meta(destinatario, texto))
        log.info(
            "cierre_meta_envio_ok",
            destinatario_prefix=destinatario[:6],
            codigo=codigo_publico,
        )
    except Exception as exc:
        log.error(
            "cierre_meta_envio_falla",
            destinatario_prefix=destinatario[:6],
            codigo=codigo_publico,
            error_tipo=type(exc).__name__,
            error_msg=str(exc),
        )
        raise  # Dramatiq reintentará


async def _enviar_meta(destinatario: str, texto: str) -> None:
    """Llamada async a Meta API con un cliente httpx efímero.

    No reusamos el singleton de `meta_client` porque el actor corre en un
    proceso distinto al del API y vivir con un cliente reusado en otro
    event loop genera problemas. La sobrecarga de un cliente por mensaje
    es trivial para el volumen del bot.
    """
    from app.config import get_settings

    settings = get_settings()
    phone_id = settings.META_PHONE_NUMBER_ID.get_secret_value()
    token = settings.META_ACCESS_TOKEN.get_secret_value()

    async with httpx.AsyncClient(
        base_url=settings.meta_url_base,
        timeout=10.0,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    ) as client:
        respuesta = await client.post(
            f"/{phone_id}/messages",
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": destinatario,
                "type": "text",
                "text": {"preview_url": False, "body": texto},
            },
        )
        # 2xx → OK. 4xx → permanente (no reintentar por sí solo, pero
        # Dramatiq reintenta de todos modos). 5xx → transitorio.
        respuesta.raise_for_status()
