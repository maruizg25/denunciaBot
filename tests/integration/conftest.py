"""
Fixtures para tests de integración con BD y Redis reales.

Requisitos para correr:
  1. `make up` (levanta postgres + redis con docker-compose)
  2. `make migrate` o `make init-db` (aplica el esquema)
  3. `pytest -m integration`

Estos tests usan la BD configurada en `DATABASE_URL`. Por defecto la
fixture `db_session` corre en transacción con rollback automático —
no quedan residuos. Para tests que necesitan probar triggers post-commit
usa `db_session_commit` y limpia manualmente lo que insertes.

Si quieres tests más aislados (cada uno con BD vacía), apunta a una BD
de pruebas distinta en `.env`:

    DATABASE_URL=postgresql+asyncpg://denunciabot:dev@localhost:5432/denunciabot_test
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import dispose_engine, get_session_factory
from app.services.sesion_service import cerrar_redis, get_redis


# Todos los tests de este directorio son `integration` por defecto
pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Sesión de BD real con ROLLBACK automático al terminar el test."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


@pytest_asyncio.fixture
async def db_session_commit() -> AsyncGenerator[AsyncSession, None]:
    """Sesión con COMMIT real — usar solo cuando el test lo requiera.

    El test es responsable de limpiar lo que insertó (típicamente
    borrando filas por id al final).
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _teardown_session() -> AsyncGenerator[None, None]:
    """Al final de toda la sesión de tests, cierra recursos."""
    yield
    await dispose_engine()
    await cerrar_redis()


@pytest_asyncio.fixture
async def redis_limpio() -> AsyncGenerator[None, None]:
    """Borra claves con prefijo `test:*` antes y después del test.

    Solo afecta claves con prefijo `test:` — datos reales (sesion:, wamid:)
    NO se tocan. Usa este prefijo para tus claves de prueba.
    """
    async def _limpiar():
        r = get_redis()
        cursor = 0
        while True:
            cursor, claves = await r.scan(cursor=cursor, match="test:*", count=100)
            if claves:
                await r.delete(*claves)
            if cursor == 0:
                break

    await _limpiar()
    yield
    await _limpiar()
