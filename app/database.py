"""
Capa de acceso a base de datos.

Configura el engine async de SQLAlchemy 2.x sobre asyncpg, expone una factory
de sesiones y un dependency injection (`get_db`) para FastAPI. El engine es
singleton por proceso y se cierra ordenadamente en el shutdown.

Patrón de uso en endpoints:
    from fastapi import Depends
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.database import get_db

    @app.post("/algo")
    async def handler(db: AsyncSession = Depends(get_db)):
        ...
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Base declarativa común a todos los modelos ORM de DenunciaBot."""

    pass


# Singletons inicializados perezosamente para no tocar la BD al importar el módulo
# (importante para tests, scripts y migraciones que pueden necesitar configuración distinta).
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Devuelve el engine async global, creándolo en la primera llamada."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.DATABASE_URL.get_secret_value(),
            echo=settings.DATABASE_ECHO,
            pool_size=settings.DATABASE_POOL_SIZE,
            max_overflow=settings.DATABASE_MAX_OVERFLOW,
            pool_pre_ping=True,    # Verifica viveza antes de entregar conexión
            pool_recycle=3600,     # Recicla conexiones cada hora para evitar timeouts del server
            future=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Devuelve la factory de sesiones, creándola en la primera llamada."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,  # Permite usar objetos tras commit sin recargarlos
            autoflush=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection de FastAPI: una sesión por request.

    Garantiza rollback automático ante cualquier excepción no manejada
    y cierre limpio de la sesión al terminar.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Cierra el pool de conexiones. Llamar desde el shutdown hook de FastAPI."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
