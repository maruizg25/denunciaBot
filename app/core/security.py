"""
Primitivas criptográficas y de seguridad de DenunciaBot.

Tres responsabilidades aisladas en este módulo:

  1. **Cifrado simétrico** de campos sensibles (Fernet).
  2. **Hash determinístico** del teléfono del denunciante (SHA-256 con pepper).
  3. **Verificación HMAC-SHA256** de la firma de webhooks de Meta.

Todas las funciones son puras: no tocan base de datos ni emiten logs.
Las claves se leen UNA sola vez desde `app.config.get_settings()` cuando
se instancia `CryptoEngine`, y luego viven en memoria del proceso.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken


class CifradoError(Exception):
    """Falla al cifrar (entrada inválida o configuración incorrecta)."""


class DescifradoError(Exception):
    """Falla al descifrar (token corrupto, clave incorrecta o expirado)."""


# Regex para normalizar teléfono: deja solo dígitos.
_RE_SOLO_DIGITOS = re.compile(r"\D")


class CryptoEngine:
    """Cifra/descifra campos sensibles y hashea teléfonos.

    Se instancia una sola vez por proceso vía `get_crypto()`. La clave
    Fernet y el pepper se guardan en memoria y NUNCA se exponen.
    """

    __slots__ = ("_fernet", "_phone_pepper")

    def __init__(self, master_key: bytes, phone_pepper: bytes) -> None:
        try:
            self._fernet = Fernet(master_key)
        except (ValueError, TypeError) as exc:
            raise CifradoError(
                "La master key proporcionada no es una clave Fernet válida"
            ) from exc
        if not phone_pepper:
            raise CifradoError("El pepper del teléfono no puede estar vacío")
        self._phone_pepper = phone_pepper

    # =====================================================================
    # Cifrado simétrico de campos sensibles
    # =====================================================================

    def cifrar(self, plaintext: str | None) -> bytes | None:
        """Cifra texto plano. Devuelve `None` si la entrada es `None`.

        El resultado es un token Fernet (bytes) listo para guardar en una
        columna BYTEA. Cada llamada produce un ciphertext distinto incluso
        para el mismo plaintext (Fernet usa nonce aleatorio + timestamp).
        """
        if plaintext is None:
            return None
        if not isinstance(plaintext, str):
            raise CifradoError(
                f"cifrar() espera str o None, recibió {type(plaintext).__name__}"
            )
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def descifrar(self, ciphertext: bytes | None) -> str | None:
        """Descifra un token Fernet. Devuelve `None` si la entrada es `None`.

        Levanta `DescifradoError` si el token está corrupto o la clave
        no corresponde — nunca devuelve datos parciales.
        """
        if ciphertext is None:
            return None
        if not isinstance(ciphertext, (bytes, bytearray, memoryview)):
            raise DescifradoError(
                f"descifrar() espera bytes o None, recibió {type(ciphertext).__name__}"
            )
        try:
            return self._fernet.decrypt(bytes(ciphertext)).decode("utf-8")
        except InvalidToken as exc:
            raise DescifradoError("Token Fernet inválido o clave incorrecta") from exc

    # =====================================================================
    # Hash determinístico del teléfono
    # =====================================================================

    def hash_telefono(self, telefono: str) -> str:
        """Calcula `SHA-256(pepper || normalizado(telefono))`.

        Normaliza el teléfono dejando solo dígitos: '+593 99 123 4567' y
        '593991234567' producen el mismo hash. Esto evita falsos negativos
        al buscar sesiones del mismo usuario.

        El pepper hace que el espacio de búsqueda sea inalcanzable por
        fuerza bruta aunque la BD se filtre (un atacante necesitaría
        también extraer el pepper de la memoria del proceso).

        Returns:
            Hex string de 64 caracteres.
        """
        if not isinstance(telefono, str):
            raise ValueError(
                f"hash_telefono() espera str, recibió {type(telefono).__name__}"
            )
        normalizado = _RE_SOLO_DIGITOS.sub("", telefono)
        if not normalizado:
            raise ValueError("Teléfono vacío tras normalizar")

        h = hashlib.sha256()
        h.update(self._phone_pepper)
        h.update(normalizado.encode("utf-8"))
        return h.hexdigest()


@lru_cache(maxsize=1)
def get_crypto() -> CryptoEngine:
    """Devuelve el singleton de CryptoEngine, construido al primer uso."""
    # Importación tardía para no acoplar la importación del módulo a
    # la carga de variables de entorno (útil en tests con mocks).
    from app.config import get_settings

    settings = get_settings()
    return CryptoEngine(
        master_key=settings.DENUNCIABOT_MASTER_KEY.get_secret_value().encode("utf-8"),
        phone_pepper=settings.DENUNCIABOT_PHONE_PEPPER.get_secret_value().encode("utf-8"),
    )


# =========================================================================
# Validación HMAC del webhook de Meta
# =========================================================================

_PREFIJO_FIRMA_META = "sha256="


def validar_firma_meta(
    cuerpo: bytes,
    firma_header: str | None,
    app_secret: str | None = None,
) -> bool:
    """Valida la firma `X-Hub-Signature-256` enviada por Meta.

    Meta firma cada webhook con HMAC-SHA256(app_secret, cuerpo_raw) y lo
    pone en el header con prefijo 'sha256='. La comparación usa
    `hmac.compare_digest` para evitar ataques de timing.

    CRÍTICO: `cuerpo` DEBE ser el cuerpo RAW del request (bytes, sin parsear
    JSON y sin recodificar). Si lo pasas re-serializado, la firma falla
    aunque sea legítima.

    Args:
        cuerpo: bytes crudos del request body.
        firma_header: valor del header X-Hub-Signature-256 (o None si no vino).
        app_secret: si se omite, se lee de settings.META_APP_SECRET.

    Returns:
        True si la firma es válida, False en cualquier otro caso.
        Nunca lanza excepciones — el endpoint que la use puede tratar
        directamente el booleano.
    """
    if not firma_header or not firma_header.startswith(_PREFIJO_FIRMA_META):
        return False
    if not isinstance(cuerpo, (bytes, bytearray)):
        return False

    if app_secret is None:
        from app.config import get_settings

        app_secret = get_settings().META_APP_SECRET.get_secret_value()

    firma_recibida = firma_header[len(_PREFIJO_FIRMA_META) :]
    firma_calculada = hmac.new(
        app_secret.encode("utf-8"),
        bytes(cuerpo),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(firma_recibida, firma_calculada)


# =========================================================================
# Utilidades para logs seguros
# =========================================================================

def truncar_para_log(valor: object, max_chars: int = 12) -> str:
    """Recorta un valor para incluirlo en logs sin filtrar más de lo necesario.

    Útil cuando se quiere dar pista en el log de QUÉ valor falló sin
    exponerlo entero. No es defensa principal contra leakage de PII:
    los datos sensibles simplemente no deben llegar al logger.
    """
    if valor is None:
        return "<None>"
    s = str(valor)
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "..."


def correlacion_log(valor: str) -> str:
    """Devuelve un hash corto (8 hex chars) para correlacionar logs.

    Permite seguir el rastro de un mismo identificador (ej. un telefono_hash)
    a través de varios logs sin escribir el valor real. No es seguro
    criptográficamente — solo sirve para correlación en logs.

    Si necesitas seguridad, usa `CryptoEngine.hash_telefono`.
    """
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()[:8]
