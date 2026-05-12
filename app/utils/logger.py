"""
Configuración global de logging con structlog.

Decisiones:
  - JSON en producción/staging para que el SIEM/journald lo indexen sin parseo.
  - Consola legible (colores opcionales) en desarrollo.
  - Sanitización automática: claves con nombres conocidos como sensibles
    (telefono, descripcion, master_key, access_token, etc.) se reemplazan
    por "<redactado>" antes de llegar al output. Es defensa secundaria —
    la primaria es NO pasar esos datos al logger.

Uso:
    from app.utils.logger import configurar_logging, obtener_logger

    configurar_logging()                       # una sola vez al arranque
    log = obtener_logger(__name__)
    log.info("alerta_creada", codigo="ALR-2026-K7M2QH", estado="REGISTRADA")
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor


# Conjunto de nombres de campo considerados sensibles. Se compara en minúsculas.
# Estos NUNCA deben aparecer en logs en claro — el procesador los redacta.
CAMPOS_SENSIBLES: frozenset[str] = frozenset(
    {
        # Datos del denunciante / contenido de la denuncia
        "telefono",
        "telefono_e164",
        "phone",
        "phone_number",
        "from",
        "descripcion",
        "descripcion_hechos",
        "institucion_denunciada",
        "personas_involucradas",
        "denuncia_previa_otra",
        "nombre_original",
        # Secretos de la app
        "master_key",
        "phone_pepper",
        "access_token",
        "app_secret",
        "password",
        "smtp_password",
        "authorization",
        # Tokens de Meta
        "verify_token",
        "bearer",
    }
)

_REDACTADO = "<redactado>"


def redactar_sensibles(
    logger: logging.Logger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Procesador de structlog: sustituye valores de claves sensibles.

    Si una clave del event_dict coincide (case-insensitive) con
    `CAMPOS_SENSIBLES`, su valor se reemplaza por "<redactado>".

    Esta función NO recorre estructuras anidadas: si un dict completo va
    como valor (ej. `payload={...con telefono adentro...}`), el redactor
    no lo destripa. La regla es: no pongas estructuras completas como
    valor — pásalas como kwargs separados.
    """
    for clave in list(event_dict.keys()):
        if clave.lower() in CAMPOS_SENSIBLES:
            event_dict[clave] = _REDACTADO
    return event_dict


def _construir_procesadores(formato: str, en_desarrollo: bool) -> list[Processor]:
    """Construye la cadena de procesadores según el formato elegido."""
    procesadores: list[Processor] = [
        # Mezcla contexto thread/async-local (request_id, etc.)
        structlog.contextvars.merge_contextvars,
        # Filtra por nivel ANTES de construir el resto del event_dict
        structlog.stdlib.filter_by_level,
        # Metadatos estándar
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        # Sanitización: SIEMPRE corre antes del renderer
        redactar_sensibles,
        # Manejo de excepciones e info de stack
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if formato == "json":
        procesadores.append(structlog.processors.JSONRenderer())
    else:
        procesadores.append(
            structlog.dev.ConsoleRenderer(colors=en_desarrollo)
        )

    return procesadores


def configurar_logging() -> None:
    """Configura structlog y la stdlib logging. Idempotente.

    Llamar UNA sola vez al arranque (típicamente en `app.main.lifespan` o
    al entrar a un script). Llamarlo varias veces no rompe nada, pero
    duplica procesadores en algunos escenarios — mejor evitarlo.
    """
    # Import tardío para no acoplar el import del módulo a settings.
    from app.config import get_settings

    settings = get_settings()
    nivel = getattr(logging, settings.APP_LOG_LEVEL, logging.INFO)

    # Configura la stdlib `logging`: structlog re-usa sus handlers.
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(nivel)
    logging.basicConfig(
        format="%(message)s",
        level=nivel,
        handlers=[handler],
        force=True,
    )

    procesadores = _construir_procesadores(
        formato=settings.LOG_FORMAT,
        en_desarrollo=settings.es_desarrollo,
    )

    structlog.configure(
        processors=procesadores,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Silenciar el ruido típico de librerías que loguea httpx en DEBUG.
    if not settings.APP_DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)


def obtener_logger(nombre: str | None = None) -> structlog.stdlib.BoundLogger:
    """Devuelve un logger estructurado.

    Args:
        nombre: nombre del logger, típicamente `__name__` del módulo.

    Returns:
        Logger listo para uso: `log.info("evento", clave=valor, ...)`.
    """
    return structlog.get_logger(nombre)


def bind_contexto(**kwargs: Any) -> None:
    """Atajo para vincular contexto al request actual (request_id, alerta_id, etc.).

    Lo bound aquí aparece en TODOS los logs subsecuentes del mismo task
    async hasta `clear_contexto()`. Útil para correlación.
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_contexto() -> None:
    """Limpia el contexto vinculado al task async actual."""
    structlog.contextvars.clear_contextvars()
