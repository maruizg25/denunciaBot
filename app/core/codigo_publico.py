"""
Generación y validación de códigos públicos de alerta.

Formato:    PREFIJO-YYYY-XXXXXX
Ejemplo:    ALR-2026-K7M2QH

  - PREFIJO: configurable vía `CODIGO_PREFIJO` (default 'ALR').
  - YYYY: año actual en UTC (4 dígitos).
  - XXXXXX: caracteres aleatorios del alfabeto sin caracteres ambiguos.

El alfabeto por defecto (`23456789ABCDEFGHJKLMNPQRSTUVWXYZ`, 32 chars) omite
0/O/1/I/l para que el código sea legible al dictarlo por teléfono. Con
6 posiciones el espacio es 32**6 ≈ 1.07e9 combinaciones por año — la
probabilidad de colisión es despreciable para volumen institucional.

La unicidad real se garantiza con `UNIQUE` en la columna `codigo_publico`
de la tabla `alertas`. El servicio de creación debe reintentar ante una
violación de unique (eventualidad astronómicamente rara, pero contemplada).
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from functools import lru_cache


def generar_codigo(anio: int | None = None) -> str:
    """Genera un nuevo código público.

    Usa `secrets.choice` (criptográficamente seguro). NUNCA usar `random`
    para esto — los códigos no deben ser predecibles.

    Args:
        anio: año a usar; si es `None`, se toma el actual en UTC.

    Returns:
        String con formato `PREFIJO-YYYY-XXXXXX`.

    Raises:
        ValueError: si el año está fuera del rango 1900–9999.
    """
    # Import tardío para que cambios de settings en tests se reflejen.
    from app.config import get_settings

    settings = get_settings()

    if anio is None:
        anio = datetime.now(timezone.utc).year
    if not (1900 <= anio <= 9999):
        raise ValueError(f"Año fuera de rango: {anio}")

    sufijo = "".join(
        secrets.choice(settings.CODIGO_ALFABETO)
        for _ in range(settings.CODIGO_LONGITUD)
    )
    return f"{settings.CODIGO_PREFIJO}-{anio:04d}-{sufijo}"


@lru_cache(maxsize=1)
def _regex_codigo() -> re.Pattern[str]:
    """Construye y cachea la regex de validación según los settings.

    Como settings se cachea en `get_settings()`, esta regex también queda
    estable por proceso. Si en tests cambias settings, limpia ambos caches.
    """
    from app.config import get_settings

    s = get_settings()
    return re.compile(
        rf"^{re.escape(s.CODIGO_PREFIJO)}-"
        rf"\d{{4}}-"
        rf"[{re.escape(s.CODIGO_ALFABETO)}]{{{s.CODIGO_LONGITUD}}}$"
    )


def es_codigo_valido(codigo: str) -> bool:
    """True si `codigo` cumple el formato PREFIJO-YYYY-XXXXXX con alfabeto válido.

    Útil para validar input antes de pegarle a la base de datos.
    No verifica que el código EXISTA en BD, solo el formato.
    """
    if not isinstance(codigo, str):
        return False
    return bool(_regex_codigo().match(codigo))


def extraer_anio(codigo: str) -> int | None:
    """Extrae el año del código si tiene formato válido, o `None`."""
    if not es_codigo_valido(codigo):
        return None
    return int(codigo.split("-")[1])
