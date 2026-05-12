"""
Paquete `app.core` — primitivas técnicas reutilizables.

Re-exporta las piezas más usadas para que el resto de la app pueda
escribir `from app.core import get_crypto` sin recordar el submódulo.
"""

from app.core.codigo_publico import (
    es_codigo_valido,
    extraer_anio,
    generar_codigo,
)
from app.core.meta_client import (
    MetaAPIError,
    MetaAPIPermanente,
    MetaAPITransitorio,
    MetaClient,
    cerrar_meta_client,
    get_meta_client,
)
from app.core.security import (
    CifradoError,
    CryptoEngine,
    DescifradoError,
    correlacion_log,
    get_crypto,
    truncar_para_log,
    validar_firma_meta,
)

__all__ = [
    # Cifrado y hashing
    "CryptoEngine",
    "CifradoError",
    "DescifradoError",
    "get_crypto",
    # Webhook
    "validar_firma_meta",
    # Códigos públicos
    "generar_codigo",
    "es_codigo_valido",
    "extraer_anio",
    # Cliente Meta API
    "MetaClient",
    "MetaAPIError",
    "MetaAPIPermanente",
    "MetaAPITransitorio",
    "get_meta_client",
    "cerrar_meta_client",
    # Helpers de logging seguro
    "truncar_para_log",
    "correlacion_log",
]
