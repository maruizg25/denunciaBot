"""Utilidades transversales — logging, helpers que no encajan en otro módulo."""

from app.utils.logger import (
    bind_contexto,
    clear_contexto,
    configurar_logging,
    obtener_logger,
)

__all__ = [
    "configurar_logging",
    "obtener_logger",
    "bind_contexto",
    "clear_contexto",
]
