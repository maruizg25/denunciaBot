"""
Paquete `app.conversacion` — máquina de estados del flujo conversacional.

Submódulos:
  - `estados`      — enum EstadoSesion (re-exportado), metadata y transiciones.
  - `mensajes`     — catálogo de textos del bot (español, sin emojis).
  - `validadores`  — validación por estado (S2 SÍ/NO, S4 longitud, S5 fecha, ...).
  - `motor`        — la máquina propiamente: `procesar_mensaje()`.

Para uso típico desde el webhook:
    from app.conversacion.motor import procesar_mensaje
"""

from app.conversacion.estados import (
    ESTADOS_ACTIVOS,
    ESTADOS_TERMINALES,
    METADATA,
    SIGUIENTE_ESTADO,
    EstadoSesion,
    MetadataEstado,
    aplica_timeout,
    es_terminal,
    metadata,
    permite_cancelar,
    siguiente_estado,
)
from app.conversacion.motor import (
    AccionEliminarSesion,
    AccionEnviarBotones,
    AccionEnviarTexto,
    AccionGuardarSesion,
    AccionMarcarLeido,
    AccionRegistrarBitacora,
    AccionRegistrarDenuncia,
    EvidenciaEntrante,
    Mensaje,
    ResultadoMotor,
    Sesion,
    procesar_mensaje,
    procesar_timeout,
)

__all__ = [
    # Estados
    "EstadoSesion",
    "MetadataEstado",
    "METADATA",
    "SIGUIENTE_ESTADO",
    "ESTADOS_TERMINALES",
    "ESTADOS_ACTIVOS",
    "metadata",
    "es_terminal",
    "permite_cancelar",
    "aplica_timeout",
    "siguiente_estado",
    # Motor
    "Mensaje",
    "Sesion",
    "EvidenciaEntrante",
    "ResultadoMotor",
    "procesar_mensaje",
    "procesar_timeout",
    # Acciones
    "AccionEnviarTexto",
    "AccionEnviarBotones",
    "AccionMarcarLeido",
    "AccionGuardarSesion",
    "AccionEliminarSesion",
    "AccionRegistrarDenuncia",
    "AccionRegistrarBitacora",
]
