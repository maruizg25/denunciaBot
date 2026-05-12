"""
Validadores puros del flujo conversacional.

Cada función recibe el input crudo del ciudadano (texto y/o id de botón) y
devuelve un `ResultadoValidacion` con:
  - `valido`: bool
  - `valor_normalizado`: forma canónica del input para guardar/mostrar
  - `motivo`: si no es válido, mensaje breve user-friendly para incluir
    en la respuesta del bot.

Diseño:
  - Funciones puras: sin I/O, sin acceso a BD, sin globales mutables.
  - La normalización del texto (lowercase, sin tildes) es interna; los
    callers pasan el texto tal cual lo envió el ciudadano.
  - Para validar SÍ/NO se aceptan: el id del botón interactivo de Meta y
    una lista generosa de sinónimos en español.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.conversacion.mensajes import (
    BTN_ID_ACEPTAR,
    BTN_ID_CANCELAR,
    BTN_ID_CONFIRMAR,
    BTN_ID_EDITAR,
    BTN_ID_NO,
    BTN_ID_RECHAZAR,
    BTN_ID_SI,
    BTN_ID_TERMINAR_EVIDENCIAS,
)

# =========================================================================
# Tipos de retorno
# =========================================================================

@dataclass(frozen=True)
class ResultadoValidacion:
    """Resultado de validar un campo de texto/botón."""

    valido: bool
    valor_normalizado: str | None = None
    motivo: str | None = None


@dataclass(frozen=True)
class ResultadoValidacionEvidencia:
    """Resultado de validar un archivo adjunto (sin escaneo antivirus)."""

    valido: bool
    motivo: Literal["tipo_no_permitido", "tamanio_excedido", "archivo_vacio", None] = None
    detalle: str | None = None
    mime_normalizado: str | None = None


# =========================================================================
# Sinónimos — se comparan tras normalizar (lowercase, sin tildes, strip)
# =========================================================================

SINONIMOS_SI: frozenset[str] = frozenset(
    {
        "si",
        "yes",
        "ok",
        "okay",
        "claro",
        "acepto",
        "afirmativo",
        "afirmo",
        "esta bien",
        "de acuerdo",
        "dale",
        "1",
        "y",
        "s",
    }
)

SINONIMOS_NO: frozenset[str] = frozenset(
    {
        "no",
        "negativo",
        "rechazo",
        "rechazar",
        "no acepto",
        "no, gracias",
        "no gracias",
        "2",
        "n",
    }
)

SINONIMOS_NO_CONOZCO: frozenset[str] = frozenset(
    {
        "no conozco",
        "no se",
        "no lo se",
        "prefiero no decir",
        "no quiero decir",
        "ninguno",
        "ninguna",
        "n/a",
        "na",
    }
)

SINONIMOS_NO_APLICA: frozenset[str] = frozenset(
    {
        "no aplica",
        "no se",
        "no lo se",
        "n/a",
        "na",
        "ninguno",
        "0",
        "cero",
    }
)

SINONIMOS_NO_RECUERDO: frozenset[str] = frozenset(
    {
        "no recuerdo",
        "no me acuerdo",
        "no se",
        "no lo se",
        "olvide",
        "olvido",
    }
)

SINONIMOS_NO_TENGO: frozenset[str] = frozenset(
    {
        "no tengo",
        "no",
        "ninguno",
        "ya no",
        "listo",
        "terminado",
        "no tengo mas",
        "no mas",
        "ya esta",
        "ya está",
    }
)

SINONIMOS_CANCELAR: frozenset[str] = frozenset(
    {"cancelar", "cancelo", "abortar", "salir", "terminar", "stop", "fin"}
)

SINONIMOS_CONFIRMAR: frozenset[str] = frozenset(
    {"confirmar", "confirmo", "aceptar", "si", "ok", "registrar", "enviar"}
)

SINONIMOS_EDITAR: frozenset[str] = frozenset(
    {"editar", "modificar", "cambiar", "corregir", "rectificar"}
)


# =========================================================================
# Normalización
# =========================================================================

def normalizar(texto: str) -> str:
    """Quita tildes, pasa a minúsculas, recorta espacios.

    Operación pura para comparar contra los frozensets de sinónimos.
    NUNCA se aplica a un texto que se va a persistir como contenido de la
    denuncia — eso debe preservarse tal cual el ciudadano lo escribió.
    """
    if not texto:
        return ""
    sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    return sin_tildes.lower().strip()


# =========================================================================
# Detector global — comando "cancelar" desde cualquier estado activo
# =========================================================================

def es_comando_cancelar(texto: str | None, boton_id: str | None = None) -> bool:
    """True si el input expresa intención de cancelar el flujo."""
    if boton_id in (BTN_ID_CANCELAR, BTN_ID_RECHAZAR):
        return True
    if not texto:
        return False
    return normalizar(texto) in SINONIMOS_CANCELAR


# =========================================================================
# S2 — Aceptación de términos
# =========================================================================

def validar_aceptacion(
    texto: str | None, boton_id: str | None = None
) -> ResultadoValidacion:
    """SÍ → True; NO → False; cualquier otro input → no válido (reintento)."""
    if boton_id == BTN_ID_ACEPTAR:
        return ResultadoValidacion(True, valor_normalizado="SI")
    if boton_id == BTN_ID_RECHAZAR:
        return ResultadoValidacion(True, valor_normalizado="NO")

    if texto:
        t = normalizar(texto)
        if t in SINONIMOS_SI:
            return ResultadoValidacion(True, valor_normalizado="SI")
        if t in SINONIMOS_NO:
            return ResultadoValidacion(True, valor_normalizado="NO")

    return ResultadoValidacion(
        False,
        motivo="No se pudo interpretar la respuesta.",
    )


# =========================================================================
# S3 — Institución denunciada
# =========================================================================

_MIN_INSTITUCION = 3
_MAX_INSTITUCION = 200


def validar_institucion(texto: str | None) -> ResultadoValidacion:
    if not texto:
        return ResultadoValidacion(
            False, motivo="No recibí texto. Indique el nombre de la institución."
        )
    valor = texto.strip()
    if len(valor) < _MIN_INSTITUCION:
        return ResultadoValidacion(
            False,
            motivo=(
                f"El nombre debe tener al menos {_MIN_INSTITUCION} caracteres "
                f"(usted envió {len(valor)})."
            ),
        )
    if len(valor) > _MAX_INSTITUCION:
        return ResultadoValidacion(
            False,
            motivo=(
                f"El nombre no debe exceder {_MAX_INSTITUCION} caracteres "
                f"(usted envió {len(valor)})."
            ),
        )
    return ResultadoValidacion(True, valor_normalizado=valor)


# =========================================================================
# S4 — Descripción de hechos
# =========================================================================

_MIN_DESCRIPCION = 30
_MAX_DESCRIPCION = 2000


def validar_descripcion(texto: str | None) -> ResultadoValidacion:
    if not texto:
        return ResultadoValidacion(
            False, motivo="No recibí texto. Describa los hechos por favor."
        )
    valor = texto.strip()
    if len(valor) < _MIN_DESCRIPCION:
        return ResultadoValidacion(
            False,
            motivo=(
                f"La descripción debe tener al menos {_MIN_DESCRIPCION} "
                f"caracteres (usted envió {len(valor)})."
            ),
        )
    if len(valor) > _MAX_DESCRIPCION:
        return ResultadoValidacion(
            False,
            motivo=(
                f"La descripción no debe exceder {_MAX_DESCRIPCION} "
                f"caracteres (usted envió {len(valor)})."
            ),
        )
    return ResultadoValidacion(True, valor_normalizado=valor)


# =========================================================================
# S5 — Fecha aproximada
# Acepta: dd/mm/yyyy, dd-mm-yyyy, mm/yyyy, yyyy, "no recuerdo".
# Valida que NO sea futura.
# =========================================================================

_RE_FECHA_DMY = re.compile(r"^\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\s*$")
_RE_FECHA_MY = re.compile(r"^\s*(\d{1,2})[/\-](\d{4})\s*$")
_RE_FECHA_Y = re.compile(r"^\s*(\d{4})\s*$")
_ANIO_MIN_RAZONABLE = 1900


def validar_fecha(texto: str | None) -> ResultadoValidacion:
    if not texto:
        return ResultadoValidacion(
            False, motivo="No recibí texto. Indique la fecha aproximada."
        )

    # "no recuerdo" y sinónimos
    if normalizar(texto) in SINONIMOS_NO_RECUERDO:
        return ResultadoValidacion(True, valor_normalizado="No recuerdo")

    hoy = date.today()

    if m := _RE_FECHA_DMY.match(texto):
        dia, mes, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if anio < _ANIO_MIN_RAZONABLE:
            return ResultadoValidacion(
                False, motivo="El año parece demasiado antiguo."
            )
        try:
            fecha = date(anio, mes, dia)
        except ValueError:
            return ResultadoValidacion(
                False, motivo="La fecha no existe; revise día y mes."
            )
        if fecha > hoy:
            return ResultadoValidacion(
                False, motivo="La fecha no puede ser futura."
            )
        return ResultadoValidacion(True, valor_normalizado=fecha.strftime("%d/%m/%Y"))

    if m := _RE_FECHA_MY.match(texto):
        mes, anio = int(m.group(1)), int(m.group(2))
        if not 1 <= mes <= 12:
            return ResultadoValidacion(
                False, motivo="El mes debe estar entre 1 y 12."
            )
        if anio < _ANIO_MIN_RAZONABLE:
            return ResultadoValidacion(
                False, motivo="El año parece demasiado antiguo."
            )
        primer_dia = date(anio, mes, 1)
        if primer_dia > hoy:
            return ResultadoValidacion(
                False, motivo="La fecha no puede ser futura."
            )
        return ResultadoValidacion(True, valor_normalizado=f"{mes:02d}/{anio:04d}")

    if m := _RE_FECHA_Y.match(texto):
        anio = int(m.group(1))
        if anio < _ANIO_MIN_RAZONABLE:
            return ResultadoValidacion(
                False, motivo="El año parece demasiado antiguo."
            )
        if anio > hoy.year:
            return ResultadoValidacion(
                False, motivo="El año no puede ser futuro."
            )
        return ResultadoValidacion(True, valor_normalizado=f"{anio:04d}")

    return ResultadoValidacion(
        False,
        motivo=(
            "No pude interpretar la fecha. Use uno de los formatos: "
            "dd/mm/aaaa, mm/aaaa, aaaa, o escriba 'no recuerdo'."
        ),
    )


# =========================================================================
# S6 — Personas involucradas (opcional)
# Siempre válido si tiene longitud razonable.
# Si "no conozco" → valor_normalizado es None (señal de campo vacío).
# =========================================================================

_MAX_INVOLUCRADOS = 1000


def validar_involucrados(texto: str | None) -> ResultadoValidacion:
    if not texto:
        return ResultadoValidacion(True, valor_normalizado=None)
    valor = texto.strip()
    if normalizar(valor) in SINONIMOS_NO_CONOZCO:
        return ResultadoValidacion(True, valor_normalizado=None)
    if len(valor) > _MAX_INVOLUCRADOS:
        return ResultadoValidacion(
            False,
            motivo=(
                f"El texto no debe exceder {_MAX_INVOLUCRADOS} caracteres "
                f"(usted envió {len(valor)})."
            ),
        )
    return ResultadoValidacion(True, valor_normalizado=valor)


# =========================================================================
# S7 — Perjuicio económico (opcional)
# Acepta número, rango, descripción libre, o "no aplica".
# =========================================================================

_MAX_PERJUICIO = 100


def validar_perjuicio(texto: str | None) -> ResultadoValidacion:
    if not texto:
        return ResultadoValidacion(True, valor_normalizado=None)
    valor = texto.strip()
    if normalizar(valor) in SINONIMOS_NO_APLICA:
        return ResultadoValidacion(True, valor_normalizado=None)
    if len(valor) > _MAX_PERJUICIO:
        return ResultadoValidacion(
            False,
            motivo=(
                f"El texto no debe exceder {_MAX_PERJUICIO} caracteres "
                f"(usted envió {len(valor)})."
            ),
        )
    return ResultadoValidacion(True, valor_normalizado=valor)


# =========================================================================
# S8 — Denuncia previa en otra entidad
# =========================================================================

def validar_denuncia_previa(
    texto: str | None, boton_id: str | None = None
) -> ResultadoValidacion:
    """SÍ → True (se pedirá entidad después); NO → False."""
    if boton_id == BTN_ID_SI:
        return ResultadoValidacion(True, valor_normalizado="SI")
    if boton_id == BTN_ID_NO:
        return ResultadoValidacion(True, valor_normalizado="NO")

    if texto:
        t = normalizar(texto)
        if t in SINONIMOS_SI:
            return ResultadoValidacion(True, valor_normalizado="SI")
        if t in SINONIMOS_NO:
            return ResultadoValidacion(True, valor_normalizado="NO")

    return ResultadoValidacion(False, motivo="Por favor responda Sí o No.")


_MAX_ENTIDAD_PREVIA = 500


def validar_entidad_previa(texto: str | None) -> ResultadoValidacion:
    """Texto libre describiendo la entidad y momento de la denuncia previa."""
    if not texto:
        return ResultadoValidacion(
            False, motivo="Indique brevemente ante qué entidad denunció."
        )
    valor = texto.strip()
    if len(valor) < 3:
        return ResultadoValidacion(
            False, motivo="Indique un nombre o referencia más completa."
        )
    if len(valor) > _MAX_ENTIDAD_PREVIA:
        return ResultadoValidacion(
            False,
            motivo=(
                f"El texto no debe exceder {_MAX_ENTIDAD_PREVIA} caracteres "
                f"(usted envió {len(valor)})."
            ),
        )
    return ResultadoValidacion(True, valor_normalizado=valor)


# =========================================================================
# S9 — Evidencias (validación de archivo)
# El escaneo antivirus se hace en la capa de servicio, NO aquí.
# =========================================================================

def validar_evidencia(
    *,
    tamanio_bytes: int,
    mime: str,
    mimes_permitidos: frozenset[str] | set[str] | list[str],
    tamanio_max_bytes: int,
) -> ResultadoValidacionEvidencia:
    """Valida tipo MIME y tamaño de un adjunto.

    Args:
        tamanio_bytes: peso del archivo en bytes.
        mime: tipo MIME reportado por Meta (ej. 'application/pdf').
        mimes_permitidos: lista/set normalizado de MIMEs aceptados.
        tamanio_max_bytes: tope superior (settings.evidencias_max_size_bytes).

    Returns:
        `ResultadoValidacionEvidencia` con `valido`/`motivo`/`mime_normalizado`.
    """
    mime_norm = (mime or "").lower().strip()
    permitidos_norm = {m.lower().strip() for m in mimes_permitidos}

    if mime_norm not in permitidos_norm:
        return ResultadoValidacionEvidencia(
            False, motivo="tipo_no_permitido", detalle=mime_norm or "<sin tipo>"
        )

    if tamanio_bytes <= 0:
        return ResultadoValidacionEvidencia(
            False, motivo="archivo_vacio", detalle="0 bytes"
        )

    if tamanio_bytes > tamanio_max_bytes:
        mb = tamanio_bytes / (1024 * 1024)
        return ResultadoValidacionEvidencia(
            False, motivo="tamanio_excedido", detalle=f"{mb:.2f} MB"
        )

    return ResultadoValidacionEvidencia(True, mime_normalizado=mime_norm)


def es_indicador_no_tengo_mas(
    texto: str | None, boton_id: str | None = None
) -> bool:
    """True si el ciudadano quiere terminar la etapa de evidencias."""
    if boton_id == BTN_ID_TERMINAR_EVIDENCIAS:
        return True
    if not texto:
        return False
    return normalizar(texto) in SINONIMOS_NO_TENGO


# =========================================================================
# S10 — Validación / confirmación / edición / cancelación
# =========================================================================

def validar_confirmacion(
    texto: str | None, boton_id: str | None = None
) -> ResultadoValidacion:
    """Decide si el ciudadano quiere confirmar, editar o cancelar.

    Devuelve `valor_normalizado` ∈ {'confirmar', 'editar', 'cancelar'} si
    se entendió, o `valido=False` con motivo si no.
    """
    if boton_id == BTN_ID_CONFIRMAR:
        return ResultadoValidacion(True, valor_normalizado="confirmar")
    if boton_id == BTN_ID_EDITAR:
        return ResultadoValidacion(True, valor_normalizado="editar")
    if boton_id == BTN_ID_CANCELAR:
        return ResultadoValidacion(True, valor_normalizado="cancelar")

    if texto:
        t = normalizar(texto)
        if t in SINONIMOS_CONFIRMAR:
            return ResultadoValidacion(True, valor_normalizado="confirmar")
        if t in SINONIMOS_EDITAR:
            return ResultadoValidacion(True, valor_normalizado="editar")
        if t in SINONIMOS_CANCELAR:
            return ResultadoValidacion(True, valor_normalizado="cancelar")

    return ResultadoValidacion(
        False, motivo="Por favor pulse Confirmar, Editar o Cancelar."
    )
