"""
Fixtures compartidas de pytest para DenunciaBot.

Estrategia:
  - Los tests del motor y los validadores corren SIN conexión real a BD,
    Redis o Meta API. Usamos fixtures con mocks para mantenerlos rápidos
    y deterministas.
  - Los tests del webhook prueban la conversión Meta→motor y la validación
    HMAC; el orquestador se mockea para no requerir BD/Redis reales.
  - Para tests de integración con BD real (futuros), se podría crear un
    `tests/integration/conftest.py` con un Postgres efímero (docker).

Requisitos para correr:
    pip install pytest pytest-asyncio
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest


# =========================================================================
# Configuración global de pytest-asyncio
# =========================================================================

# Los tests async usan el modo "auto" — no hay que decorar con
# @pytest.mark.asyncio cada función.
def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: tests lentos (>1s)")
    config.addinivalue_line("markers", "integration: requieren BD/Redis reales")


# =========================================================================
# Inyección de variables de entorno mínimas
# =========================================================================

@pytest.fixture(autouse=True, scope="session")
def _env_test() -> Iterator[None]:
    """Provee variables de entorno seguras antes de que la app cargue settings.

    Los tests no deben tocar el .env real del usuario. Estos valores son
    suficientes para que pydantic-settings valide el arranque sin errores.
    """
    valores = {
        "APP_ENV": "development",
        "APP_DEBUG": "false",
        "LOG_FORMAT": "console",
        # Clave Fernet válida (44 chars base64) generada ad-hoc para tests
        "DENUNCIABOT_MASTER_KEY": "cdvWmqdEQH1pPRJB8wEszEHTNH4-OzwUe6cqMRRWS7s=",
        "DENUNCIABOT_PHONE_PEPPER": "pepper-test-1234567890abcdef0123456789",
        "DATABASE_URL": "postgresql+asyncpg://denunciabot:test@localhost:5432/denunciabot_test",
        "REDIS_URL": "redis://localhost:6379/15",  # DB 15 para no chocar con desarrollo
        "META_PHONE_NUMBER_ID": "123456789",
        "META_ACCESS_TOKEN": "test-access-token",
        "META_APP_SECRET": "test-app-secret",
        "META_VERIFY_TOKEN": "test-verify-token",
        "SMTP_HOST": "localhost",
        "SMTP_FROM": "denunciabot@test.local",
        "SMTP_TO": "destino@test.local",
        "EVIDENCIAS_DIR": "/tmp/denunciabot_test_evidencias",
        "CLAMAV_ENABLED": "false",
        # Rate limit absurdamente alto para tests — no debe disparar.
        "RATE_LIMIT_WEBHOOK": "10000/minute",
    }
    anteriores: dict[str, str | None] = {k: os.environ.get(k) for k in valores}
    os.environ.update(valores)
    try:
        yield
    finally:
        for k, v in anteriores.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# =========================================================================
# Fixtures de dominio
# =========================================================================

@pytest.fixture
def telefono_e164() -> str:
    """Número de teléfono ecuatoriano de prueba en formato E.164 sin '+'."""
    return "593991234567"


@pytest.fixture
def telefono_hash_fake() -> str:
    """Hash determinista de 64 chars para sesiones de prueba."""
    return "a" * 64


@pytest.fixture
def datos_alerta_completa() -> dict[str, Any]:
    """Diccionario con TODOS los campos que el motor genera al confirmar S10."""
    return {
        "institucion": "Ministerio de Salud Pública",
        "descripcion": "Descripción detallada de los hechos denunciados " * 2,
        "fecha": "15/03/2025",
        "involucrados": "Juan Pérez, director administrativo",
        "perjuicio": "aprox. 50,000 USD",
        "denuncia_previa": None,
        "evidencias": [],
    }


# =========================================================================
# Mocks de I/O (Meta, Redis, BD) para tests del orquestador
# =========================================================================

@pytest.fixture
def calls_io() -> dict[str, Any]:
    """Diccionario para que los tests inspeccionen llamadas a I/O."""
    return {
        "texto": [],
        "botones": [],
        "leido": [],
        "guardar_sesion": [],
        "eliminar_sesion": [],
        "bitacora": [],
        "registrar_denuncia": [],
        "commit": 0,
        "rollback": 0,
    }
