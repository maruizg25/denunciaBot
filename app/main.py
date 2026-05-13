"""
Entry point de DenunciaBot — aplicación FastAPI.

Lifespan:
  Al arrancar:
    1. Configura logging estructurado (structlog → JSON o consola según env).
    2. Conecta el broker de Dramatiq a Redis.
    3. Crea el directorio de evidencias si no existe.
  Al apagar:
    1. Cierra el cliente Meta (httpx.AsyncClient).
    2. Cierra la conexión Redis.
    3. Cierra el pool de SQLAlchemy.

El servicio escucha en el host/puerto definidos en `.env`. El TLS y el
subdominio público los gestiona el equipo de seguridad de SERCOP —
DenunciaBot solo expone HTTP en `127.0.0.1:8000` por defecto.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.admin import router as admin_router
from app.api.consulta import router as consulta_router
from app.api.webhook import router as webhook_router
from app.config import get_settings
from app.core.meta_client import cerrar_meta_client
from app.database import dispose_engine
from app.services.notificacion_service import configurar_broker_dramatiq
from app.services.sesion_service import cerrar_redis
from app.utils.logger import configurar_logging, obtener_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Hook de arranque y apagado."""
    configurar_logging()
    log = obtener_logger(__name__)

    settings = get_settings()

    # Crear directorio de evidencias si no existe
    Path(settings.EVIDENCIAS_DIR).mkdir(parents=True, exist_ok=True)
    (Path(settings.EVIDENCIAS_DIR) / "tmp").mkdir(parents=True, exist_ok=True)

    # Configurar broker Dramatiq (encola notificaciones SMTP)
    configurar_broker_dramatiq()

    log.info(
        "denunciabot_iniciado",
        entorno=settings.APP_ENV,
        host=settings.APP_HOST,
        puerto=settings.APP_PORT,
        evidencias_dir=str(settings.EVIDENCIAS_DIR),
        clamav_habilitado=settings.CLAMAV_ENABLED,
    )

    yield

    log.info("denunciabot_apagando")
    await cerrar_meta_client()
    await cerrar_redis()
    await dispose_engine()
    log.info("denunciabot_apagado_limpio")


# =========================================================================
# Construcción de la app
# =========================================================================

settings = get_settings()

app = FastAPI(
    title="DenunciaBot",
    description=(
        "Chatbot institucional de WhatsApp para denuncias ciudadanas de "
        "corrupción — Secretaría General de Integridad Pública del Ecuador."
    ),
    version="0.1.0",
    lifespan=lifespan,
    # Docs OpenAPI solo en entornos no-productivos
    docs_url="/docs" if not settings.es_produccion else None,
    redoc_url=None,
    openapi_url="/openapi.json" if not settings.es_produccion else None,
)

# Rate limiting (slowapi)
limiter = Limiter(key_func=get_remote_address, default_limits=[])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# =========================================================================
# Rutas
# =========================================================================

app.include_router(webhook_router)
app.include_router(consulta_router)
app.include_router(admin_router)


@app.get("/health", tags=["health"])
async def health_root() -> dict[str, str]:
    """Health check liviano para load balancers / monitoring."""
    return {"status": "ok", "name": settings.APP_NAME, "entorno": settings.APP_ENV}


# =========================================================================
# Handler global de excepciones — última red de seguridad
# =========================================================================

@app.exception_handler(Exception)
async def handler_excepcion_no_capturada(
    request: Request, exc: Exception
) -> JSONResponse:
    """Atrapa cualquier excepción no manejada y responde sin filtrar internals.

    El stack completo va al log estructurado. El cliente solo recibe un
    mensaje genérico — requisito de seguridad #8 del brief.
    """
    log = obtener_logger(__name__)
    log.exception(
        "excepcion_no_capturada",
        path=str(request.url.path),
        method=request.method,
    )
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": "Error interno del servicio"},
    )
