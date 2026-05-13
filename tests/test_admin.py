"""
Tests del panel admin (auth + listado + cambio de estado).

Mockea la BD y settings para no requerir Postgres real. Los tests de
integración cubren queries reales.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio

from app.main import app

# Token de prueba para todos los tests del admin
_ADMIN_TOKEN_TEST = "test-admin-token-1234567890"


@pytest_asyncio.fixture
async def cliente() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _con_admin_token(monkeypatch: pytest.MonkeyPatch):
    """Inyecta un ADMIN_TOKEN en settings y resetea el cache de get_settings."""
    monkeypatch.setenv("ADMIN_TOKEN", _ADMIN_TOKEN_TEST)
    # Limpiar el cache de get_settings para que tome la nueva env
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_mock(monkeypatch: pytest.MonkeyPatch):
    """Mockea get_db para que no toque Postgres."""

    class _Session:
        async def execute(self, *args, **kwargs):
            r = MagicMock()
            r.scalar_one_or_none = lambda: None
            r.scalar = lambda: 0
            r.scalar_one = lambda: 0
            r.scalars = lambda: MagicMock(all=lambda: [])
            r.first = lambda: None
            return r

        async def scalar(self, *args, **kwargs):
            return 0

        async def commit(self): pass
        async def rollback(self): pass
        def add(self, obj): pass

    async def _fake_get_db():
        yield _Session()

    from app.database import get_db
    app.dependency_overrides[get_db] = _fake_get_db
    yield
    app.dependency_overrides.clear()


class TestAuthAdmin:
    @pytest.mark.asyncio
    async def test_acceso_sin_cookie_redirige_a_login(
        self, cliente: httpx.AsyncClient, db_mock
    ) -> None:
        r = await cliente.get("/admin/alertas", follow_redirects=False)
        # FastAPI convierte HTTPException(303) en redirect
        assert r.status_code in (303, 307)
        # Location debe apuntar a /admin/login
        assert "/admin/login" in r.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_login_get_devuelve_form(
        self, cliente: httpx.AsyncClient
    ) -> None:
        r = await cliente.get("/admin/login")
        assert r.status_code == 200
        assert "Acceso al panel" in r.text

    @pytest.mark.asyncio
    async def test_login_con_token_correcto_setea_cookie(
        self, cliente: httpx.AsyncClient
    ) -> None:
        r = await cliente.post(
            "/admin/login",
            data={"token": _ADMIN_TOKEN_TEST},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "denunciabot_admin" in r.headers.get("set-cookie", "")

    @pytest.mark.asyncio
    async def test_login_con_token_incorrecto_devuelve_401(
        self, cliente: httpx.AsyncClient
    ) -> None:
        r = await cliente.post(
            "/admin/login",
            data={"token": "token-equivocado"},
        )
        assert r.status_code == 401
        assert "incorrecto" in r.text.lower()

    @pytest.mark.asyncio
    async def test_acceso_con_cookie_valida_pasa_a_alertas(
        self, cliente: httpx.AsyncClient, db_mock
    ) -> None:
        # Primero hacer login para obtener cookie
        r_login = await cliente.post(
            "/admin/login",
            data={"token": _ADMIN_TOKEN_TEST},
            follow_redirects=False,
        )
        # httpx async sigue cookies automáticamente entre requests
        r = await cliente.get("/admin/alertas")
        assert r.status_code == 200
        assert "Denuncias registradas" in r.text


class TestPanelDeshabilitado:
    @pytest.mark.asyncio
    async def test_sin_admin_token_devuelve_503(
        self, cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ADMIN_TOKEN", "")
        from app.config import get_settings
        get_settings.cache_clear()

        r = await cliente.get("/admin/login")
        assert r.status_code == 503


class TestHealthSinAuth:
    @pytest.mark.asyncio
    async def test_health_admin_no_requiere_auth(
        self, cliente: httpx.AsyncClient
    ) -> None:
        r = await cliente.get("/admin/health")
        assert r.status_code == 200
        assert r.json()["modulo"] == "admin"
