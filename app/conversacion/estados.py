"""
Metadata y transiciones de la máquina de estados conversacional.

El enum `EstadoSesion` ya vive en `app.models.sesion` (para no duplicar entre
modelo de BD y máquina). Este módulo agrega:

  - `METADATA`: información estática por estado (terminal, permite cancelar,
    sujeto a timeout, etc.).
  - `SIGUIENTE_ESTADO`: tabla del "camino feliz" — qué estado sigue cuando
    el input es válido. Los saltos no lineales (NO en S2 → CANCELADA;
    "editar" en S10 → S3) los maneja el motor explícitamente, no se
    intentan codificar como tabla de despacho.
  - Helpers consultivos: `es_terminal`, `siguiente_estado`, `permite_input_libre`,
    `aplica_timeout`.

Aquí NO hay lógica — solo datos. La máquina vive en `app.conversacion.motor`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.sesion import EstadoSesion

__all__ = [
    "EstadoSesion",
    "MetadataEstado",
    "METADATA",
    "SIGUIENTE_ESTADO",
    "ESTADOS_TERMINALES",
    "ESTADOS_ACTIVOS",
    "es_terminal",
    "siguiente_estado",
    "permite_cancelar",
    "aplica_timeout",
    "metadata",
]


# =========================================================================
# Estructuras
# =========================================================================

@dataclass(frozen=True)
class MetadataEstado:
    """Información estática sobre un estado de la máquina."""

    estado: EstadoSesion
    es_terminal: bool = False
    """Sesión termina al entrar a este estado; no se procesan más mensajes."""

    permite_cancelar: bool = True
    """El ciudadano puede escribir 'cancelar' para abortar desde aquí."""

    aplica_timeout: bool = True
    """Sujeto a inactividad (4 min aviso, 5 min cierre)."""

    requiere_input: bool = True
    """El motor espera un mensaje del ciudadano antes de avanzar."""

    descripcion: str = ""


# =========================================================================
# Catálogo de metadata por estado
# =========================================================================

METADATA: dict[EstadoSesion, MetadataEstado] = {
    EstadoSesion.S0_INICIO: MetadataEstado(
        estado=EstadoSesion.S0_INICIO,
        permite_cancelar=False,
        aplica_timeout=False,
        requiere_input=False,
        descripcion="Detección del primer mensaje; no se persiste sesión.",
    ),
    EstadoSesion.S1_BIENVENIDA: MetadataEstado(
        estado=EstadoSesion.S1_BIENVENIDA,
        permite_cancelar=False,
        aplica_timeout=False,
        requiere_input=False,
        descripcion="Envío del mensaje obligatorio de bienvenida y requisitos.",
    ),
    EstadoSesion.S2_ACEPTACION: MetadataEstado(
        estado=EstadoSesion.S2_ACEPTACION,
        descripcion="Espera consentimiento SÍ/NO.",
    ),
    EstadoSesion.S3_INSTITUCION: MetadataEstado(
        estado=EstadoSesion.S3_INSTITUCION,
        descripcion="Recolecta la institución denunciada (3..200 chars).",
    ),
    EstadoSesion.S4_DESCRIPCION: MetadataEstado(
        estado=EstadoSesion.S4_DESCRIPCION,
        descripcion="Recolecta la descripción de los hechos (30..2000 chars).",
    ),
    EstadoSesion.S5_FECHA: MetadataEstado(
        estado=EstadoSesion.S5_FECHA,
        descripcion="Recolecta la fecha aproximada (varios formatos o 'no recuerdo').",
    ),
    EstadoSesion.S6_INVOLUCRADOS: MetadataEstado(
        estado=EstadoSesion.S6_INVOLUCRADOS,
        descripcion="Personas involucradas (opcional; acepta 'no conozco').",
    ),
    EstadoSesion.S7_PERJUICIO: MetadataEstado(
        estado=EstadoSesion.S7_PERJUICIO,
        descripcion="Perjuicio económico (opcional; acepta 'no aplica' / 'no sé').",
    ),
    EstadoSesion.S8_DENUNCIA_PREVIA: MetadataEstado(
        estado=EstadoSesion.S8_DENUNCIA_PREVIA,
        descripcion="¿Denunció antes en otra entidad? SÍ → pide entidad; NO → avanza.",
    ),
    EstadoSesion.S9_EVIDENCIA: MetadataEstado(
        estado=EstadoSesion.S9_EVIDENCIA,
        descripcion="Adjuntos (PDF/JPG/PNG, máx 5×10 MB) o 'no tengo'.",
    ),
    EstadoSesion.S10_VALIDACION: MetadataEstado(
        estado=EstadoSesion.S10_VALIDACION,
        descripcion="Muestra resumen y pide confirmar / editar / cancelar.",
    ),
    EstadoSesion.S11_REGISTRO: MetadataEstado(
        estado=EstadoSesion.S11_REGISTRO,
        permite_cancelar=False,
        aplica_timeout=False,
        requiere_input=False,
        descripcion="Persiste alerta, genera código, encola notificación.",
    ),
    EstadoSesion.S12_CIERRE: MetadataEstado(
        estado=EstadoSesion.S12_CIERRE,
        es_terminal=True,
        permite_cancelar=False,
        aplica_timeout=False,
        requiere_input=False,
        descripcion="Despedida con código de seguimiento; sesión cerrada.",
    ),
    # ---- Estados auxiliares ----
    EstadoSesion.INACTIVIDAD_AVISO: MetadataEstado(
        estado=EstadoSesion.INACTIVIDAD_AVISO,
        permite_cancelar=False,
        aplica_timeout=False,  # el aviso es transitorio; el timeout sigue corriendo
        requiere_input=False,
        descripcion="Aviso de inactividad enviado al ciudadano (4 min).",
    ),
    EstadoSesion.INACTIVIDAD_CIERRE: MetadataEstado(
        estado=EstadoSesion.INACTIVIDAD_CIERRE,
        es_terminal=True,
        permite_cancelar=False,
        aplica_timeout=False,
        requiere_input=False,
        descripcion="Sesión descartada por inactividad (5 min sin respuesta).",
    ),
    EstadoSesion.CANCELADA: MetadataEstado(
        estado=EstadoSesion.CANCELADA,
        es_terminal=True,
        permite_cancelar=False,
        aplica_timeout=False,
        requiere_input=False,
        descripcion="Cancelación voluntaria por el ciudadano.",
    ),
}


# =========================================================================
# Camino feliz: estado actual → siguiente en flujo lineal exitoso.
# Los saltos no-lineales los decide el motor (NO en S2 → CANCELADA, etc.).
# =========================================================================

SIGUIENTE_ESTADO: dict[EstadoSesion, EstadoSesion | None] = {
    EstadoSesion.S0_INICIO: EstadoSesion.S1_BIENVENIDA,
    EstadoSesion.S1_BIENVENIDA: EstadoSesion.S2_ACEPTACION,
    EstadoSesion.S2_ACEPTACION: EstadoSesion.S3_INSTITUCION,
    EstadoSesion.S3_INSTITUCION: EstadoSesion.S4_DESCRIPCION,
    EstadoSesion.S4_DESCRIPCION: EstadoSesion.S5_FECHA,
    EstadoSesion.S5_FECHA: EstadoSesion.S6_INVOLUCRADOS,
    EstadoSesion.S6_INVOLUCRADOS: EstadoSesion.S7_PERJUICIO,
    EstadoSesion.S7_PERJUICIO: EstadoSesion.S8_DENUNCIA_PREVIA,
    EstadoSesion.S8_DENUNCIA_PREVIA: EstadoSesion.S9_EVIDENCIA,
    EstadoSesion.S9_EVIDENCIA: EstadoSesion.S10_VALIDACION,
    EstadoSesion.S10_VALIDACION: EstadoSesion.S11_REGISTRO,
    EstadoSesion.S11_REGISTRO: EstadoSesion.S12_CIERRE,
    EstadoSesion.S12_CIERRE: None,                  # terminal
    EstadoSesion.INACTIVIDAD_AVISO: None,           # no avanza por flujo
    EstadoSesion.INACTIVIDAD_CIERRE: None,
    EstadoSesion.CANCELADA: None,
}


# =========================================================================
# Conjuntos derivados — útiles para queries rápidas
# =========================================================================

ESTADOS_TERMINALES: frozenset[EstadoSesion] = frozenset(
    estado for estado, meta in METADATA.items() if meta.es_terminal
)

ESTADOS_ACTIVOS: frozenset[EstadoSesion] = frozenset(
    estado
    for estado, meta in METADATA.items()
    if not meta.es_terminal and meta.requiere_input
)


# =========================================================================
# Helpers consultivos
# =========================================================================

def metadata(estado: EstadoSesion) -> MetadataEstado:
    """Devuelve la metadata del estado o falla con KeyError explícito."""
    if estado not in METADATA:
        raise KeyError(f"Estado sin metadata definida: {estado}")
    return METADATA[estado]


def es_terminal(estado: EstadoSesion) -> bool:
    return metadata(estado).es_terminal


def permite_cancelar(estado: EstadoSesion) -> bool:
    return metadata(estado).permite_cancelar


def aplica_timeout(estado: EstadoSesion) -> bool:
    return metadata(estado).aplica_timeout


def siguiente_estado(actual: EstadoSesion) -> EstadoSesion | None:
    """Estado siguiente en el camino feliz, o None si es terminal."""
    return SIGUIENTE_ESTADO.get(actual)
