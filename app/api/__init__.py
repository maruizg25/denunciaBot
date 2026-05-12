"""Paquete `app.api` — routers FastAPI."""

from app.api.admin import router as admin_router
from app.api.webhook import router as webhook_router

__all__ = ["webhook_router", "admin_router"]
