"""
Endpoint `/metrics` — exposición de métricas Prometheus.

  GET /metrics  → texto plano en formato OpenMetrics

Diseño:
  - Sin autenticación: las métricas son contadores agregados, no PII.
  - Si el equipo de seguridad lo requiere, restringir por IP en el
    reverse proxy o agregar `Authorization: Bearer <token>` aquí.
  - Antes de servir, refresca el gauge de `alertas_por_estado` con una
    query barata. Si Postgres está caído, las métricas se sirven igual
    (el gauge mantiene el último valor conocido — no rompe el endpoint).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.metrics import actualizar_gauge_alertas_por_estado
from app.utils.logger import obtener_logger

log = obtener_logger(__name__)

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_class=Response, include_in_schema=False)
async def metrics(db: AsyncSession = Depends(get_db)) -> Response:
    """Devuelve todas las métricas en formato Prometheus.

    Refresca el gauge de alertas_por_estado on-demand antes de exportar.
    Si la query falla (BD caída), se loguea pero el endpoint sigue
    devolviendo lo que tiene en memoria.
    """
    try:
        await actualizar_gauge_alertas_por_estado(db)
    except Exception as exc:
        log.warning(
            "metrics_refresh_alertas_falla",
            error_tipo=type(exc).__name__,
            error_msg=str(exc),
        )

    payload = generate_latest()
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
