"""
Tests del endpoint público de consulta GET /alerta/{codigo}.

Mockea la BD para no requerir Postgres real. Los tests de integración
(tests/integration/) cubren el query real.
"""

from __future__ import annotations

import datetime as _dt
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
def db_con_alerta(monkeypatch: pytest.MonkeyPatch):
    """Mockea get_db para devolver una sesión que responde con una alerta de prueba."""
    alerta_fake = MagicMock()
    alerta_fake.codigo_publico = "ALR-2026-K7M2QH"
    alerta_fake.estado = "REGISTRADA"
    alerta_fake.timestamp_registro = _dt.datetime(
        2026, 5, 11, 20, 0, 0, tzinfo=_dt.timezone.utc
    )

    class _Result:
        def first(self):
            return alerta_fake

    class _Session:
        async def execute(self, *args, **kwargs):
            return _Result()

    async def _fake_get_db():
        yield _Session()

    from app.database import get_db
    app.dependency_overrides[get_db] = _fake_get_db
    yield alerta_fake
    app.dependency_overrides.clear()


@pytest.fixture
def db_sin_alerta():
    """Mockea get_db para devolver una sesión que NO encuentra la alerta."""

    class _Result:
        def first(self):
            return None

    class _Session:
        async def execute(self, *args, **kwargs):
            return _Result()

    async def _fake_get_db():
        yield _Session()

    from app.database import get_db
    app.dependency_overrides[get_db] = _fake_get_db
    yield
    app.dependency_overrides.clear()


class TestConsultaPublica:
    @pytest.mark.asyncio
    async def test_codigo_valido_y_existente_devuelve_estado(
        self, cliente: httpx.AsyncClient, db_con_alerta
    ) -> None:
        r = await cliente.get("/alerta/ALR-2026-K7M2QH")
        assert r.status_code == 200
        data = r.json()
        assert data["codigo"] == "ALR-2026-K7M2QH"
        assert data["estado"] == "REGISTRADA"
        assert "2026-05-11" in data["fecha_registro"]

    @pytest.mark.asyncio
    async def test_codigo_inexistente_devuelve_404(
        self, cliente: httpx.AsyncClient, db_sin_alerta
    ) -> None:
        r = await cliente.get("/alerta/ALR-2026-XXXXXX")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_codigo_con_formato_invalido_devuelve_404(
        self, cliente: httpx.AsyncClient, db_sin_alerta
    ) -> None:
        """Mismo 404 que el caso "no existe" — no exponemos el motivo
        para evitar enumeración."""
        r = await cliente.get("/alerta/no-es-un-codigo")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_codigo_con_caracteres_ambiguos_devuelve_404(
        self, cliente: httpx.AsyncClient, db_sin_alerta
    ) -> None:
        """El alfabeto no permite 0/O/1/I/l. Códigos con estos caracteres
        deben rechazarse por formato antes de tocar BD."""
        r = await cliente.get("/alerta/ALR-2026-O0I1L9")
        assert r.status_code == 404
