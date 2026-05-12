"""
Configuración de entorno de Alembic — modo asíncrono.

Lee la URL de la base de datos desde `app.config` (no desde `alembic.ini`)
para mantener los secretos en un solo lugar (.env) y registra el metadata
de los modelos para soportar autogeneración futura.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.database import Base

# Importación de modelos para que Base.metadata los conozca al autogenerar.
# Se importan dentro de try/except porque en PASO 4 todavía no existen;
# quedarán habilitados en PASO 5.
try:
    from app.models import (  # noqa: F401  (efectos colaterales del import)
        alerta,
        bitacora,
        evidencia,
        sesion,
    )
except ImportError:
    # Aún no se han creado los modelos: la migración inicial es manual.
    pass


# ----------------------------------------------------------------------------
# Configuración de Alembic
# ----------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inyecta la URL desde nuestros settings (la fuente única de verdad)
config.set_main_option(
    "sqlalchemy.url",
    get_settings().DATABASE_URL.get_secret_value(),
)

target_metadata = Base.metadata


# ----------------------------------------------------------------------------
# Modo offline — genera SQL sin conectarse
# ----------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Genera el SQL de las migraciones sin abrir conexión real."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ----------------------------------------------------------------------------
# Modo online — ejecuta contra la BD real (async)
# ----------------------------------------------------------------------------
def do_run_migrations(connection: Connection) -> None:
    """Configura el contexto y dispara las migraciones sobre una conexión activa."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Crea un engine async efímero solo para correr las migraciones."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
