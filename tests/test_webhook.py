"""
Tests del webhook de Meta — verificación, firma HMAC, parsing.

Estrategia:
  - Usamos `httpx.AsyncClient` con `ASGITransport` para llamar al app sin
    levantar servidor.
  - Mockeamos las dependencias de I/O (orquestador, sesion_service,
    meta_client) con monkeypatch.
  - Para los tests del POST generamos firmas HMAC válidas con el secret
    que el conftest inyecta en el entorno.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.api import webhook as webhook_mod
from app.main import app


# =========================================================================
# Helpers
# =========================================================================

VERIFY_TOKEN = "test-verify-token"
APP_SECRET = "test-app-secret"


def _firmar(cuerpo: bytes, secret: str = APP_SECRET) -> str:
    """Calcula el header X-Hub-Signature-256 que enviaría Meta."""
    mac = hmac.new(secret.encode(), cuerpo, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def _payload_texto(texto: str = "hola", from_: str = "593991234567") -> dict[str, Any]:
    """Construye un payload de WhatsApp con un mensaje de texto."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "...", "phone_number_id": "..."},
                            "contacts": [{"wa_id": from_, "profile": {"name": "Test"}}],
                            "messages": [
                                {
                                    "from": from_,
                                    "id": "wamid.test123",
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _payload_solo_status() -> dict[str, Any]:
    """Payload de notificación de delivery — debe ignorarse."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {},
                            "statuses": [
                                {
                                    "id": "wamid.x",
                                    "recipient_id": "593991234567",
                                    "status": "delivered",
                                    "timestamp": "1700000000",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


@pytest.fixture
async def cliente() -> httpx.AsyncClient:
    """Cliente HTTP que envía requests al app sin levantar servidor real."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _mockear_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reemplaza I/O real del webhook por mocks para que no toque BD/Redis/Meta."""
    monkeypatch.setattr(webhook_mod, "obtener_sesion", AsyncMock(return_value=None))
    monkeypatch.setattr(webhook_mod, "ejecutar", AsyncMock())
    # Por defecto la idempotency dice "mensaje NUEVO" → procesar.
    monkeypatch.setattr(
        webhook_mod, "intentar_marcar_procesado", AsyncMock(return_value=True)
    )

    # Mockear get_db para que devuelva un async generator con sesión mockeada.
    async def _fake_get_db():
        yield AsyncMock()

    # FastAPI usa dependency_overrides para sustituir dependencias en tests.
    from app.database import get_db
    app.dependency_overrides[get_db] = _fake_get_db
    yield
    app.dependency_overrides.clear()


# =========================================================================
# GET /webhook — verificación inicial de Meta
# =========================================================================

class TestVerificacion:
    @pytest.mark.asyncio
    async def test_token_correcto_devuelve_challenge(self, cliente: httpx.AsyncClient) -> None:
        r = await cliente.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "valor-del-challenge",
            },
        )
        assert r.status_code == 200
        assert r.text == "valor-del-challenge"

    @pytest.mark.asyncio
    async def test_token_incorrecto_devuelve_403(self, cliente: httpx.AsyncClient) -> None:
        r = await cliente.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "token-equivocado",
                "hub.challenge": "X",
            },
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_modo_distinto_de_subscribe_403(self, cliente: httpx.AsyncClient) -> None:
        r = await cliente.get(
            "/webhook",
            params={
                "hub.mode": "unsubscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "X",
            },
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_falta_parametro_devuelve_422(self, cliente: httpx.AsyncClient) -> None:
        # FastAPI/Pydantic valida los Query antes que nuestra lógica
        r = await cliente.get("/webhook")
        assert r.status_code in (400, 422)


# =========================================================================
# POST /webhook — validación de firma
# =========================================================================

class TestFirma:
    @pytest.mark.asyncio
    async def test_sin_firma_devuelve_401(self, cliente: httpx.AsyncClient) -> None:
        r = await cliente.post(
            "/webhook",
            content=json.dumps(_payload_texto()).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_firma_invalida_devuelve_401(self, cliente: httpx.AsyncClient) -> None:
        cuerpo = json.dumps(_payload_texto()).encode()
        r = await cliente.post(
            "/webhook",
            content=cuerpo,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=0000000000000000000000000000000000000000000000000000000000000000",
            },
        )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_firma_con_secret_distinto_devuelve_401(self, cliente: httpx.AsyncClient) -> None:
        cuerpo = json.dumps(_payload_texto()).encode()
        firma_atacante = _firmar(cuerpo, secret="secret-equivocado")
        r = await cliente.post(
            "/webhook",
            content=cuerpo,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": firma_atacante},
        )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_firma_correcta_acepta(self, cliente: httpx.AsyncClient) -> None:
        cuerpo = json.dumps(_payload_texto()).encode()
        firma = _firmar(cuerpo)
        r = await cliente.post(
            "/webhook",
            content=cuerpo,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": firma},
        )
        assert r.status_code == 200


# =========================================================================
# POST /webhook — manejo del payload
# =========================================================================

class TestProcesamiento:
    @pytest.mark.asyncio
    async def test_mensaje_de_texto_invoca_orquestador(self, cliente: httpx.AsyncClient) -> None:
        cuerpo = json.dumps(_payload_texto("Hola DenunciaBot")).encode()
        firma = _firmar(cuerpo)
        r = await cliente.post(
            "/webhook",
            content=cuerpo,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": firma},
        )
        assert r.status_code == 200
        # El mock `ejecutar` debió llamarse exactamente 1 vez
        assert webhook_mod.ejecutar.await_count == 1

    @pytest.mark.asyncio
    async def test_payload_solo_status_no_invoca_motor(self, cliente: httpx.AsyncClient) -> None:
        cuerpo = json.dumps(_payload_solo_status()).encode()
        firma = _firmar(cuerpo)
        r = await cliente.post(
            "/webhook",
            content=cuerpo,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": firma},
        )
        assert r.status_code == 200
        assert webhook_mod.ejecutar.await_count == 0

    @pytest.mark.asyncio
    async def test_payload_invalido_se_ignora(self, cliente: httpx.AsyncClient) -> None:
        cuerpo = b'{"invalid": true}'
        firma = _firmar(cuerpo)
        r = await cliente.post(
            "/webhook",
            content=cuerpo,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": firma},
        )
        # Aun con payload raro respondemos 200 para que Meta no reintente
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_excepcion_individual_no_rompe_lote(
        self, cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Si una excepción ocurre procesando UN mensaje, el endpoint igualmente
        responde 200 — Meta no debe reintentar."""

        async def _ejecutar_falla(*args, **kwargs):
            raise RuntimeError("BD caída")

        monkeypatch.setattr(webhook_mod, "ejecutar", _ejecutar_falla)

        cuerpo = json.dumps(_payload_texto()).encode()
        firma = _firmar(cuerpo)
        r = await cliente.post(
            "/webhook",
            content=cuerpo,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": firma},
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_mensaje_duplicado_se_ignora(
        self, cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Idempotency: si Meta reenvía un wamid que ya procesamos, el motor
        NO debe invocarse pero el endpoint responde 200."""
        # Hacemos que intentar_marcar_procesado devuelva False (duplicado)
        monkeypatch.setattr(
            webhook_mod,
            "intentar_marcar_procesado",
            AsyncMock(return_value=False),
        )

        cuerpo = json.dumps(_payload_texto()).encode()
        firma = _firmar(cuerpo)
        r = await cliente.post(
            "/webhook",
            content=cuerpo,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": firma},
        )
        assert r.status_code == 200
        # El orquestador NO se invocó porque era duplicado
        assert webhook_mod.ejecutar.await_count == 0

    @pytest.mark.asyncio
    async def test_redis_caido_responde_con_mensaje_degradado(
        self, cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Si Redis se cae al leer la sesión, el ciudadano recibe un mensaje
        degradado y el motor/BD no se tocan."""

        async def _redis_caido(*args, **kwargs):
            raise webhook_mod.RedisError("Connection refused")

        monkeypatch.setattr(webhook_mod, "obtener_sesion", _redis_caido)

        # Mockear el cliente Meta para inspeccionar el mensaje enviado
        textos_enviados = []

        class _MC:
            async def enviar_texto(self, dest, texto):
                textos_enviados.append((dest, texto))

        monkeypatch.setattr(webhook_mod, "get_meta_client", lambda: _MC())

        cuerpo = json.dumps(_payload_texto()).encode()
        firma = _firmar(cuerpo)
        r = await cliente.post(
            "/webhook",
            content=cuerpo,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": firma},
        )
        assert r.status_code == 200
        # El motor NO se invocó
        assert webhook_mod.ejecutar.await_count == 0
        # Pero al ciudadano sí se le envió un mensaje degradado
        assert len(textos_enviados) == 1
        assert "técnica" in textos_enviados[0][1].lower() or "dificultad" in textos_enviados[0][1].lower()


# =========================================================================
# Health checks
# =========================================================================

class TestHealth:
    @pytest.mark.asyncio
    async def test_health_root(self, cliente: httpx.AsyncClient) -> None:
        r = await cliente.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_admin_health(self, cliente: httpx.AsyncClient) -> None:
        r = await cliente.get("/admin/health")
        assert r.status_code == 200
        assert r.json()["modulo"] == "admin"
