"""
Cliente async para Meta Cloud API (WhatsApp Business).

Solo expone operaciones outbound — enviar mensajes y descargar adjuntos.
La recepción de webhooks vive en `app.api.webhook`.

Operaciones soportadas:
  - `enviar_texto(destinatario, texto)` — mensaje de texto plano.
  - `enviar_botones(destinatario, texto, botones)` — interactive buttons
    (usado para SÍ/NO en S2, S8, S10).
  - `marcar_leido(message_id)` — pone los doble-check azules.
  - `descargar_media(media_id)` — recupera el binario de un adjunto.

Política de errores:
  - 4xx (400, 401, 403, 404): error permanente → no reintenta, levanta
    `MetaAPIPermanente`. El servicio que lo invoca decide qué hacer.
  - 429: respeta `Retry-After`, reintenta hasta `_MAX_REINTENTOS`.
  - 5xx, timeouts, errores de red: reintenta con backoff exponencial.

El token de acceso y otros secretos NUNCA aparecen en logs — el
procesador `redactar_sensibles` de structlog y la regla "no incluir
headers en el evento" lo garantizan.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from app.utils.logger import obtener_logger

log = obtener_logger(__name__)


# =========================================================================
# Errores del dominio
# =========================================================================

class MetaAPIError(Exception):
    """Error genérico de Meta API. Base de la jerarquía."""

    def __init__(
        self,
        mensaje: str,
        *,
        status: int | None = None,
        cuerpo: Any = None,
    ) -> None:
        self.status = status
        self.cuerpo = cuerpo
        super().__init__(mensaje)


class MetaAPIPermanente(MetaAPIError):
    """No vale la pena reintentar (4xx, credenciales malas, payload inválido)."""


class MetaAPITransitorio(MetaAPIError):
    """Probablemente se resuelva reintentando (5xx, timeout, red)."""


# =========================================================================
# Configuración de reintentos
# =========================================================================

_MAX_REINTENTOS: int = 3
_TIMEOUT_SEGUNDOS: float = 10.0
_BACKOFF_BASE: float = 1.0       # primer reintento ~1s
_BACKOFF_MAX: float = 30.0       # tope absoluto
_JITTER_FRACTION: float = 0.25   # ±25% jitter para evitar thundering herd


def _backoff(intento: int, retry_after: float | None = None) -> float:
    """Calcula el tiempo de espera antes del próximo reintento.

    Si Meta nos dio Retry-After, lo respetamos (con tope absoluto). Si no,
    backoff exponencial con jitter aleatorio, garantizando que el resultado
    final esté siempre en [0.1, _BACKOFF_MAX].
    """
    if retry_after is not None and retry_after > 0:
        return min(retry_after, _BACKOFF_MAX)
    base = _BACKOFF_BASE * (2 ** intento)
    jitter = base * _JITTER_FRACTION * (random.random() * 2 - 1)
    # Cap final tras aplicar jitter para que el resultado real nunca exceda el tope.
    return max(0.1, min(base + jitter, _BACKOFF_MAX))


# =========================================================================
# Cliente
# =========================================================================

class MetaClient:
    """Cliente async para Meta Cloud API. Singleton por proceso."""

    def __init__(self) -> None:
        self._cliente: httpx.AsyncClient | None = None
        # `_settings` se carga perezosamente para no tocar env al importar
        self._settings = None

    # ---- ciclo de vida -------------------------------------------------------

    async def _ensure_cliente(self) -> httpx.AsyncClient:
        if self._cliente is None:
            from app.config import get_settings

            self._settings = get_settings()
            self._cliente = httpx.AsyncClient(
                base_url=self._settings.meta_url_base,
                timeout=_TIMEOUT_SEGUNDOS,
                headers={
                    "Authorization": (
                        f"Bearer {self._settings.META_ACCESS_TOKEN.get_secret_value()}"
                    ),
                    "Content-Type": "application/json",
                },
            )
        return self._cliente

    async def aclose(self) -> None:
        """Cierra el cliente HTTP. Llamar desde el shutdown de FastAPI."""
        if self._cliente is not None:
            await self._cliente.aclose()
            self._cliente = None

    # ---- request interno con reintentos --------------------------------------

    async def _request(
        self,
        metodo: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        seguir_redirects: bool = False,
    ) -> httpx.Response:
        """Envía un request y maneja los reintentos según la política."""
        cliente = await self._ensure_cliente()
        ultimo_error: Exception | None = None

        for intento in range(_MAX_REINTENTOS + 1):
            try:
                respuesta = await cliente.request(
                    metodo,
                    path,
                    json=json,
                    params=params,
                    follow_redirects=seguir_redirects,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                ultimo_error = exc
                log.warning(
                    "meta_request_red_falla",
                    intento=intento,
                    metodo=metodo,
                    path=path,
                    error_tipo=type(exc).__name__,
                )
                if intento >= _MAX_REINTENTOS:
                    raise MetaAPITransitorio(
                        f"Red caída tras {_MAX_REINTENTOS} reintentos"
                    ) from exc
                await asyncio.sleep(_backoff(intento))
                continue

            # Éxito
            if 200 <= respuesta.status_code < 300:
                return respuesta

            # 4xx permanente (excepto 429)
            if 400 <= respuesta.status_code < 500 and respuesta.status_code != 429:
                cuerpo = _safe_json(respuesta)
                log.error(
                    "meta_request_4xx",
                    metodo=metodo,
                    path=path,
                    status=respuesta.status_code,
                    cuerpo=cuerpo,
                )
                raise MetaAPIPermanente(
                    f"Meta API devolvió {respuesta.status_code}",
                    status=respuesta.status_code,
                    cuerpo=cuerpo,
                )

            # 429 — rate limit
            if respuesta.status_code == 429:
                retry_after = _parse_retry_after(respuesta.headers.get("Retry-After"))
                log.warning(
                    "meta_request_rate_limit",
                    intento=intento,
                    retry_after=retry_after,
                )
                if intento >= _MAX_REINTENTOS:
                    raise MetaAPITransitorio(
                        "Rate limit excedido tras reintentos",
                        status=429,
                    )
                await asyncio.sleep(_backoff(intento, retry_after))
                continue

            # 5xx — transitorio
            if respuesta.status_code >= 500:
                cuerpo = _safe_json(respuesta)
                log.warning(
                    "meta_request_5xx",
                    intento=intento,
                    metodo=metodo,
                    path=path,
                    status=respuesta.status_code,
                )
                if intento >= _MAX_REINTENTOS:
                    raise MetaAPITransitorio(
                        f"Meta API 5xx tras {_MAX_REINTENTOS} reintentos",
                        status=respuesta.status_code,
                        cuerpo=cuerpo,
                    )
                await asyncio.sleep(_backoff(intento))
                continue

            # Status inesperado — tratar como permanente para no esconder bugs
            raise MetaAPIPermanente(
                f"Status inesperado: {respuesta.status_code}",
                status=respuesta.status_code,
            )

        # Path teóricamente inalcanzable
        raise MetaAPIError(
            f"Bucle de reintentos terminó sin éxito ni excepción: {ultimo_error}"
        )

    # ---- métodos públicos ----------------------------------------------------

    async def enviar_texto(
        self,
        destinatario: str,
        texto: str,
        *,
        preview_url: bool = False,
    ) -> dict[str, Any]:
        """Envía un mensaje de texto plano al ciudadano.

        Args:
            destinatario: número en formato E.164 SIN '+' (lo que Meta llama `wa_id`).
            texto: contenido del mensaje (máx ~4096 chars según Meta).
            preview_url: si True, Meta intenta generar preview de URLs presentes.
        """
        await self._ensure_cliente()
        path = self._path_mensajes()
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destinatario,
            "type": "text",
            "text": {
                "preview_url": preview_url,
                "body": texto,
            },
        }
        resp = await self._request("POST", path, json=payload)
        log.info("meta_envio_texto", destinatario_prefix=destinatario[:6])
        return resp.json()

    async def enviar_botones(
        self,
        destinatario: str,
        texto: str,
        botones: list[tuple[str, str]],
    ) -> dict[str, Any]:
        """Envía un mensaje con botones interactivos.

        Args:
            destinatario: número en formato E.164 sin '+'.
            texto: cuerpo del mensaje (máx 1024 chars).
            botones: lista de tuplas (id, etiqueta). Meta acepta máx 3 botones
                por mensaje. La etiqueta visible al usuario es la posición [1];
                el `id` viene de vuelta en el webhook al pulsar el botón.

        Ejemplo:
            await client.enviar_botones(
                "593991234567",
                "¿Aceptas continuar?",
                [("aceptar", "Sí, acepto"), ("rechazar", "No, cancelar")],
            )
        """
        if not 1 <= len(botones) <= 3:
            raise ValueError("Meta permite entre 1 y 3 botones por mensaje")

        await self._ensure_cliente()
        path = self._path_mensajes()
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destinatario,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": texto},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {"id": bid, "title": etiqueta},
                        }
                        for bid, etiqueta in botones
                    ]
                },
            },
        }
        resp = await self._request("POST", path, json=payload)
        log.info(
            "meta_envio_botones",
            destinatario_prefix=destinatario[:6],
            n_botones=len(botones),
        )
        return resp.json()

    async def marcar_leido(self, message_id: str) -> None:
        """Marca un mensaje recibido como leído (los ✓✓ azules)."""
        await self._ensure_cliente()
        path = self._path_mensajes()
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        await self._request("POST", path, json=payload)

    async def descargar_media(self, media_id: str) -> tuple[bytes, str]:
        """Descarga un archivo adjunto enviado por el ciudadano.

        El flujo es de dos pasos según Meta:
          1. GET /{media_id} → devuelve metadata con `url` temporal (5min de vida).
          2. GET <url temporal> → bytes reales del archivo.

        Returns:
            Tupla `(contenido_bytes, mime_type)`.
        """
        cliente = await self._ensure_cliente()

        # Paso 1: pedir la URL temporal
        meta_resp = await self._request("GET", f"/{media_id}")
        meta = meta_resp.json()
        url_temporal = meta.get("url")
        mime_type = meta.get("mime_type", "application/octet-stream")
        if not url_temporal:
            raise MetaAPIPermanente(
                "Respuesta de Meta sin campo `url` al pedir media",
                cuerpo=meta,
            )

        # Paso 2: descargar el binario (URL absoluta, no relativa a base_url).
        # Reusamos el cliente para mantener auth headers.
        descarga = await cliente.get(url_temporal, follow_redirects=True)
        if descarga.status_code != 200:
            raise MetaAPITransitorio(
                f"Falla descargando media: {descarga.status_code}",
                status=descarga.status_code,
            )

        log.info(
            "meta_descarga_media",
            media_id_prefix=media_id[:8],
            mime=mime_type,
            tamanio=len(descarga.content),
        )
        return descarga.content, mime_type

    # ---- helpers privados ----------------------------------------------------

    def _path_mensajes(self) -> str:
        """Construye el path relativo al base_url para POST /messages."""
        assert self._settings is not None
        phone_id = self._settings.META_PHONE_NUMBER_ID.get_secret_value()
        return f"/{phone_id}/messages"


# =========================================================================
# Helpers a nivel de módulo
# =========================================================================

def _safe_json(respuesta: httpx.Response) -> Any:
    """Intenta extraer JSON de la respuesta; si falla devuelve el texto truncado."""
    try:
        return respuesta.json()
    except ValueError:
        return respuesta.text[:500]


def _parse_retry_after(valor: str | None) -> float | None:
    """Parsea el header Retry-After (segundos o fecha HTTP)."""
    if not valor:
        return None
    try:
        return float(valor)
    except ValueError:
        # No implementamos parseo de fecha HTTP: Meta usa segundos.
        return None


# =========================================================================
# Singleton helper para FastAPI
# =========================================================================

_cliente_global: MetaClient | None = None


def get_meta_client() -> MetaClient:
    """Devuelve el singleton del cliente Meta para el proceso.

    No usa `@lru_cache` porque MetaClient mantiene un cliente httpx async que
    debe vivir durante todo el proceso, y queremos exponer `aclose()`
    para el shutdown ordenado.
    """
    global _cliente_global
    if _cliente_global is None:
        _cliente_global = MetaClient()
    return _cliente_global


async def cerrar_meta_client() -> None:
    """Cierra el singleton si existe. Llamar en shutdown de FastAPI."""
    global _cliente_global
    if _cliente_global is not None:
        await _cliente_global.aclose()
        _cliente_global = None
