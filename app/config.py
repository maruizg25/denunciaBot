"""
Configuración global de DenunciaBot.

Carga las variables de entorno desde el archivo `.env` (o desde el ambiente del
proceso, que tiene prioridad) usando pydantic-settings, las tipa y las valida
en el arranque. Si una variable obligatoria falta o tiene formato inválido,
la aplicación falla al instante con un mensaje claro — preferimos un crash
explícito al inicio a un error silencioso a medio camino.

Uso típico:
    from app.config import get_settings
    settings = get_settings()
    print(settings.APP_NAME)
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración tipada de toda la aplicación.

    Las variables se cargan desde `.env` y luego se sobrescriben con las
    variables de entorno del proceso. El nombre del campo debe coincidir
    exactamente con la variable (case-sensitive).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # Ignora variables extra del .env (entornos compartidos)
    )

    # =========================================================================
    # Aplicación
    # =========================================================================
    APP_NAME: str = "DenunciaBot"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = Field(default=8000, ge=1024, le=65535)
    APP_LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    APP_DEBUG: bool = False

    # =========================================================================
    # Seguridad — Cifrado y hashing
    # =========================================================================
    DENUNCIABOT_MASTER_KEY: SecretStr
    DENUNCIABOT_PHONE_PEPPER: SecretStr

    # =========================================================================
    # Base de datos — PostgreSQL 16
    # =========================================================================
    DATABASE_URL: SecretStr
    DATABASE_POOL_SIZE: int = Field(default=10, ge=1, le=100)
    DATABASE_MAX_OVERFLOW: int = Field(default=5, ge=0, le=50)
    DATABASE_ECHO: bool = False

    # =========================================================================
    # Redis 7 — Sesiones y cola Dramatiq
    # =========================================================================
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_SESIONES_DB: int = Field(default=0, ge=0, le=15)
    REDIS_DRAMATIQ_DB: int = Field(default=1, ge=0, le=15)

    # =========================================================================
    # Meta Cloud API — WhatsApp Business
    # =========================================================================
    META_API_VERSION: str = "v18.0"
    META_PHONE_NUMBER_ID: SecretStr
    META_ACCESS_TOKEN: SecretStr
    META_APP_SECRET: SecretStr
    META_VERIFY_TOKEN: SecretStr

    # =========================================================================
    # SMTP — Notificación de denuncias al buzón institucional
    # =========================================================================
    SMTP_HOST: str
    SMTP_PORT: int = Field(default=587, ge=1, le=65535)
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: SecretStr = SecretStr("")
    SMTP_USE_TLS: bool = True
    SMTP_FROM: EmailStr
    SMTP_FROM_NAME: str = "DenunciaBot — Integridad Pública"
    SMTP_TO: EmailStr
    SMTP_TIMEOUT_SECONDS: int = Field(default=30, ge=5, le=300)

    # =========================================================================
    # Evidencias — Archivos adjuntos
    # =========================================================================
    EVIDENCIAS_DIR: Path = Path("./evidencias")
    EVIDENCIAS_MAX_SIZE_MB: int = Field(default=10, ge=1, le=100)
    EVIDENCIAS_MAX_COUNT: int = Field(default=5, ge=1, le=20)
    EVIDENCIAS_MIME_PERMITIDOS: str = "application/pdf,image/jpeg,image/png"

    # =========================================================================
    # ClamAV — Escaneo antivirus
    # =========================================================================
    CLAMAV_ENABLED: bool = False
    CLAMAV_HOST: str = "127.0.0.1"
    CLAMAV_PORT: int = Field(default=3310, ge=1, le=65535)
    CLAMAV_TIMEOUT_SECONDS: int = Field(default=30, ge=5, le=300)

    # =========================================================================
    # Conversación — Tiempos y límites del flujo
    # =========================================================================
    SESION_TIMEOUT_AVISO_SECONDS: int = Field(default=240, ge=30, le=3600)
    SESION_TIMEOUT_CIERRE_SECONDS: int = Field(default=300, ge=60, le=3600)
    MAX_INTENTOS_VALIDACION: int = Field(default=3, ge=1, le=10)

    # =========================================================================
    # Códigos públicos de alerta
    # =========================================================================
    CODIGO_PREFIJO: str = Field(default="ALR", min_length=2, max_length=6)
    CODIGO_ALFABETO: str = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    CODIGO_LONGITUD: int = Field(default=6, ge=4, le=12)

    # =========================================================================
    # Rate limiting (slowapi)
    # =========================================================================
    RATE_LIMIT_WEBHOOK: str = "120/minute"

    # =========================================================================
    # Observabilidad
    # =========================================================================
    LOG_FORMAT: Literal["json", "console"] = "json"
    LOG_FILE: str = ""  # Vacío → stdout (recomendado con systemd/journald)

    # =========================================================================
    # Validadores de campo
    # =========================================================================

    @field_validator("DENUNCIABOT_MASTER_KEY")
    @classmethod
    def _validar_master_key(cls, v: SecretStr) -> SecretStr:
        """La master key debe ser una clave Fernet válida (44 chars base64url)."""
        try:
            Fernet(v.get_secret_value().encode())
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "DENUNCIABOT_MASTER_KEY no es una clave Fernet válida. "
                "Generar con: "
                "python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            ) from exc
        return v

    @field_validator("DENUNCIABOT_PHONE_PEPPER")
    @classmethod
    def _validar_phone_pepper(cls, v: SecretStr) -> SecretStr:
        """Pepper mínimo 16 caracteres — si es más corto, no aporta seguridad."""
        if len(v.get_secret_value()) < 16:
            raise ValueError(
                "DENUNCIABOT_PHONE_PEPPER debe tener al menos 16 caracteres. "
                "Generar con: "
                "python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def _validar_database_url(cls, v: SecretStr) -> SecretStr:
        """Exigimos el driver async `asyncpg` — el ORM síncrono está prohibido."""
        url = v.get_secret_value()
        if not url.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL debe usar el driver async. "
                "Formato esperado: postgresql+asyncpg://usuario:pass@host:5432/bd"
            )
        return v

    @field_validator("REDIS_URL")
    @classmethod
    def _validar_redis_url(cls, v: str) -> str:
        if not v.startswith(("redis://", "rediss://", "unix://")):
            raise ValueError(
                "REDIS_URL debe empezar con redis://, rediss:// o unix://"
            )
        return v

    @field_validator("CODIGO_ALFABETO")
    @classmethod
    def _validar_alfabeto(cls, v: str) -> str:
        """El alfabeto del código público no debe tener caracteres repetidos."""
        if len(v) < 10:
            raise ValueError(
                "CODIGO_ALFABETO debe contener al menos 10 caracteres distintos"
            )
        if len(set(v)) != len(v):
            raise ValueError("CODIGO_ALFABETO no puede contener caracteres repetidos")
        return v

    @field_validator("CODIGO_PREFIJO")
    @classmethod
    def _validar_prefijo(cls, v: str) -> str:
        """El prefijo del código público debe ser alfanumérico mayúsculo."""
        if not v.isalnum() or not v.isupper():
            raise ValueError(
                "CODIGO_PREFIJO debe ser alfanumérico en mayúsculas (ej. ALR)"
            )
        return v

    @field_validator("EVIDENCIAS_MIME_PERMITIDOS")
    @classmethod
    def _validar_mime(cls, v: str) -> str:
        """Lista CSV no vacía. La separación se hace en la property derivada."""
        valores = [m.strip() for m in v.split(",") if m.strip()]
        if not valores:
            raise ValueError(
                "EVIDENCIAS_MIME_PERMITIDOS no puede estar vacío. "
                "Ejemplo: application/pdf,image/jpeg,image/png"
            )
        return v

    @field_validator("RATE_LIMIT_WEBHOOK")
    @classmethod
    def _validar_rate_limit(cls, v: str) -> str:
        """Validación mínima del formato esperado por slowapi: 'N/periodo'."""
        if "/" not in v:
            raise ValueError(
                "RATE_LIMIT_WEBHOOK debe seguir el formato '<n>/<periodo>'. "
                "Ejemplos: '120/minute', '5/second', '10000/day'"
            )
        return v

    # =========================================================================
    # Validador global — coherencia entre campos
    # =========================================================================

    @model_validator(mode="after")
    def _validar_consistencia(self) -> "Settings":
        """Reglas que cruzan varios campos."""
        # Timeout de aviso debe ser estrictamente menor al de cierre
        if self.SESION_TIMEOUT_AVISO_SECONDS >= self.SESION_TIMEOUT_CIERRE_SECONDS:
            raise ValueError(
                "SESION_TIMEOUT_AVISO_SECONDS debe ser menor a "
                "SESION_TIMEOUT_CIERRE_SECONDS — primero se avisa, luego se cierra"
            )

        # En producción, ciertos flags peligrosos están prohibidos
        if self.APP_ENV == "production":
            if self.APP_DEBUG:
                raise ValueError("APP_DEBUG=true está prohibido en producción")
            if self.DATABASE_ECHO:
                raise ValueError("DATABASE_ECHO=true está prohibido en producción")
            if self.LOG_FORMAT != "json":
                raise ValueError("LOG_FORMAT debe ser 'json' en producción")

        return self

    # =========================================================================
    # Propiedades derivadas — utilidades para el resto de la app
    # =========================================================================

    @property
    def es_produccion(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def es_desarrollo(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def evidencias_mime_lista(self) -> list[str]:
        """MIME types permitidos como lista de strings normalizados."""
        return [
            m.strip().lower()
            for m in self.EVIDENCIAS_MIME_PERMITIDOS.split(",")
            if m.strip()
        ]

    @property
    def evidencias_max_size_bytes(self) -> int:
        return self.EVIDENCIAS_MAX_SIZE_MB * 1024 * 1024

    @property
    def meta_url_base(self) -> str:
        """URL base de Meta Graph API para construir endpoints."""
        return f"https://graph.facebook.com/{self.META_API_VERSION}"

    @property
    def meta_url_mensajes(self) -> str:
        """Endpoint para enviar mensajes salientes."""
        phone_id = self.META_PHONE_NUMBER_ID.get_secret_value()
        return f"{self.meta_url_base}/{phone_id}/messages"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Carga y cachea la configuración una sola vez por proceso.

    Usar como dependencia de FastAPI:
        from fastapi import Depends
        from app.config import Settings, get_settings

        @app.get("/")
        def root(settings: Settings = Depends(get_settings)):
            return {"app": settings.APP_NAME}
    """
    return Settings()
