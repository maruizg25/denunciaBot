"""
Servicio de sesiones conversacionales.

Redis es la fuente PRIMARIA durante el flujo activo:
  - Una sesión vive en `sesion:<telefono_hash>` con TTL automático.
  - El TTL se renueva en cada actualización (sliding expiration).
  - Cuando la sesión termina (registro, cancelación, timeout), se BORRA.

La tabla `sesiones_activas` queda como esquema para auditoría futura, pero
en MVP no se escribe — la bitácora cubre la auditoría.

Decisiones:
  - Una sola clave por sesión, JSON serializado → operación atómica.
  - El TTL se setea siempre al guardar (no necesitamos otra ronda).
  - El cliente Redis es singleton lazy por proceso.
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from app.conversacion.motor import Sesion
from app.models.sesion import EstadoSesion
from app.utils.logger import obtener_logger

log = obtener_logger(__name__)


# =========================================================================
# Cliente Redis singleton
# =========================================================================

_redis: Redis | None = None


def get_redis() -> Redis:
    """Devuelve el cliente Redis singleton, creándolo perezosamente."""
    global _redis
    if _redis is None:
        from app.config import get_settings

        settings = get_settings()
        _redis = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )
    return _redis


async def cerrar_redis() -> None:
    """Cierra la conexión Redis. Llamar desde el shutdown de FastAPI."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


# =========================================================================
# Serialización Sesion <-> dict para Redis
# =========================================================================

def _sesion_a_dict(sesion: Sesion) -> dict[str, Any]:
    """Serializa la sesión a un dict JSON-compatible."""
    return {
        "telefono_hash": sesion.telefono_hash,
        "destinatario": sesion.destinatario,
        "estado_actual": sesion.estado_actual.value,
        "datos": sesion.datos,
        "intentos_estado": sesion.intentos_estado,
    }


def _dict_a_sesion(d: dict[str, Any]) -> Sesion:
    """Reconstruye la sesión desde el dict almacenado en Redis."""
    return Sesion(
        telefono_hash=d["telefono_hash"],
        destinatario=d["destinatario"],
        estado_actual=EstadoSesion(d["estado_actual"]),
        datos=d.get("datos") or {},
        intentos_estado=int(d.get("intentos_estado", 0)),
    )


def _clave(telefono_hash: str) -> str:
    return f"sesion:{telefono_hash}"


# =========================================================================
# API pública
# =========================================================================

async def obtener_sesion(telefono_hash: str) -> Sesion | None:
    """Lee la sesión actual del ciudadano, o `None` si no existe / expiró."""
    redis = get_redis()
    raw = await redis.get(_clave(telefono_hash))
    if raw is None:
        return None
    try:
        return _dict_a_sesion(json.loads(raw))
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        # Sesión corrupta — la tratamos como si no existiera.
        log.warning(
            "sesion_corrupta",
            telefono_hash_prefix=telefono_hash[:8],
            error=type(exc).__name__,
        )
        await redis.delete(_clave(telefono_hash))
        return None


async def guardar_sesion(sesion: Sesion) -> None:
    """Persiste la sesión en Redis con TTL fresco.

    El TTL renueva el reloj de inactividad: cada interacción del ciudadano
    le da otros 5 minutos. Si no responde, Redis la expira sola.
    """
    from app.config import get_settings

    settings = get_settings()
    redis = get_redis()
    raw = json.dumps(_sesion_a_dict(sesion), ensure_ascii=False)
    await redis.set(
        _clave(sesion.telefono_hash),
        raw,
        ex=settings.SESION_TIMEOUT_CIERRE_SECONDS,
    )


async def eliminar_sesion(telefono_hash: str) -> None:
    """Borra la sesión. Idempotente (no falla si no existía)."""
    redis = get_redis()
    await redis.delete(_clave(telefono_hash))


async def renovar_ttl(telefono_hash: str) -> bool:
    """Renueva el TTL sin tocar el contenido. True si existía."""
    from app.config import get_settings

    settings = get_settings()
    redis = get_redis()
    return bool(
        await redis.expire(
            _clave(telefono_hash),
            settings.SESION_TIMEOUT_CIERRE_SECONDS,
        )
    )


async def ttl_restante(telefono_hash: str) -> int | None:
    """Segundos restantes antes de que expire, o `None` si no existe."""
    redis = get_redis()
    ttl = await redis.ttl(_clave(telefono_hash))
    if ttl < 0:
        return None
    return int(ttl)
