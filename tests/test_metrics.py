"""
Tests del endpoint /metrics y de los counters más importantes.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio

from app.main import app


@pytest_asyncio.fixture
async def cliente() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def db_mock():
    class _Session:
        async def execute(self, *args, **kwargs):
            r = MagicMock()
            r.__iter__ = lambda self: iter([])
            return r

    async def _fake_get_db():
        yield _Session()

    from app.database import get_db
    app.dependency_overrides[get_db] = _fake_get_db
    yield
    app.dependency_overrides.clear()


class TestEndpointMetrics:
    @pytest.mark.asyncio
    async def test_metrics_devuelve_formato_prometheus(
        self, cliente: httpx.AsyncClient, db_mock
    ) -> None:
        r = await cliente.get("/metrics")
        assert r.status_code == 200
        # Content-Type debe ser el de OpenMetrics / text/plain
        assert "text/plain" in r.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_metrics_incluye_nombres_esperados(
        self, cliente: httpx.AsyncClient, db_mock
    ) -> None:
        r = await cliente.get("/metrics")
        texto = r.text
        # Verificamos que las definiciones de las métricas clave están presentes
        esperadas = [
            "denunciabot_webhook_requests_total",
            "denunciabot_alertas_creadas_total",
            "denunciabot_evidencias_recibidas_total",
            "denunciabot_mensajes_duplicados_total",
            "denunciabot_webhook_duration_seconds",
        ]
        for nombre in esperadas:
            assert nombre in texto, f"Falta métrica: {nombre}"


class TestCounters:
    def test_webhook_requests_se_puede_incrementar(self) -> None:
        from app.metrics import WEBHOOK_REQUESTS
        # Antes
        antes = WEBHOOK_REQUESTS.labels(resultado="ok")._value.get()
        WEBHOOK_REQUESTS.labels(resultado="ok").inc()
        despues = WEBHOOK_REQUESTS.labels(resultado="ok")._value.get()
        assert despues == antes + 1

    def test_alertas_creadas_es_monotonico(self) -> None:
        from app.metrics import ALERTAS_CREADAS
        antes = ALERTAS_CREADAS._value.get()
        ALERTAS_CREADAS.inc()
        ALERTAS_CREADAS.inc()
        ALERTAS_CREADAS.inc()
        assert ALERTAS_CREADAS._value.get() == antes + 3
