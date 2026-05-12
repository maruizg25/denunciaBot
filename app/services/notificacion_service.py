"""
Servicio de notificaciones SMTP — corre en worker Dramatiq.

Diseño:
  - Define el actor `enviar_notificacion_alerta`. Importar este módulo lo
    registra automáticamente en el broker actual de Dramatiq.
  - `configurar_broker_dramatiq()` debe llamarse UNA vez al arranque del
    proceso (api o worker) para conectar el broker Redis real. Hasta que
    se llame, Dramatiq usa el broker stub por defecto — útil para tests.
  - El actor es síncrono (Dramatiq lo prefiere así). Usamos `smtplib` de
    la stdlib y abrimos/cerramos la conexión SMTP por mensaje. Para
    volúmenes mayores se podría reusar conexión, pero el bot recibe
    pocas denuncias por día — no amerita complejidad.

Reintentos:
  - `max_retries=3`, backoff de 5s a 5min (configurable en el decorador).
  - Si todos fallan, Dramatiq mueve el mensaje a la dead-letter queue.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr

import dramatiq
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
