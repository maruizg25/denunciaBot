"""
Endpoints administrativos mínimos para MVP.

Sin panel admin completo: solo health checks y un contador básico. Pensado
para monitoreo (Prometheus exporter, Nagios, curl manual del equipo de ops).

IMPORTANTE: `/admin/stats` no requiere autenticación en MVP — solo cuenta
filas, no expone datos sensibles. Antes de exponerlo públicamente,
proteger con autenticación o restringir a IPs internas vía la capa de
infra (firewall, reverse proxy del equipo de seguridad).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.alerta import Alerta
from app.models.bitacora import EventoBitacora

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
async def health_admin() -> dict[str, str]:
    """Health check del módulo admin (no toca BD)."""
    return {"status": "ok", "modulo": "admin"}


@router.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Verifica que la BD responde a una query trivial."""
    await db.execute(select(1))
    return {"status": "ok", "db": "alcanzable"}


@router.get("/stats")
async def estadisticas(db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """Conteos básicos: cuántas alertas hay registradas, cuántos eventos en bitácora.

    NO expone datos sensibles — solo cardinalidades.
    """
    total_alertas = await db.scalar(select(func.count()).select_from(Alerta))
    total_bitacora = await db.scalar(select(func.count()).select_from(EventoBitacora))
    return {
        "alertas_totales": int(total_alertas or 0),
        "eventos_bitacora": int(total_bitacora or 0),
    }
