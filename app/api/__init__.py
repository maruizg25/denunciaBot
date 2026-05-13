"""Paquete `app.api` — routers FastAPI."""

from app.api.admin import router as admin_router
from app.api.consulta import router as consulta_router
from app.api.webhook import router as webhook_router

__all__ = ["webhook_router", "consulta_router", "admin_router"]
