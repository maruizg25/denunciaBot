"""
Servicio de idempotency para el webhook de Meta.

Problema: Meta tiene entrega *at-least-once*. Si nuestro 200 OK no llega
en ~20 segundos, Meta reenvía exactamente el mismo evento con el mismo
`wamid` (id del mensaje). Sin defensa, el ciudadano podría:

  - Recibir respuestas duplicadas (mala UX).
  - Provocar dos `AccionRegistrarDenuncia` al pulsar Confirmar → dos
    denuncias con códigos distintos para los mismos hechos.

Solución: antes de procesar un mensaje, intentamos marcar su `wamid`
en Redis con `SET key value NX EX 86400`:

  - Si la clave NO existía: la marcamos, procesamos normalmente.
  - Si YA existía: es un duplicado, lo ignoramos (respondemos 200 igual,
    para que Meta deje de reintentar).

`SET ... NX EX` es atómico en Redis: dos workers procesando el mismo
mensaje en paralelo verán uno True y otro False; solo el primero procesa.

TTL de 24h: suficiente para cubrir cualquier escenario realista de
reintento de Meta (su política máxima de retry es de varias horas) sin
inflar Redis con millones de claves de meses atrás.
"""

from __future__ import annotations

from app.services.sesion_service import get_redis
from app.utils.logger import obtener_logger

log = obtener_logger(__name__)


# 24 horas — Meta tiende a dejar de reintentar mucho antes.
_TTL_IDEMPOTENCY_SEGUNDOS: int = 24 * 60 * 60


def _clave(wamid: str) -> str:
    return f"wamid:{wamid}"


async def intentar_marcar_procesado(wamid: str) -> bool:
    """Intenta registrar `wamid` como ya procesado.

    Args:
        wamid: el id que Meta asigna al mensaje (`wamid.XXX`).

    Returns:
        True  → el mensaje es NUEVO, hay que procesarlo.
        False → el mensaje YA fue procesado (es duplicado, ignorar).

    Si Redis está caído, devolvemos True (failure-open): preferimos
    procesar el mensaje y arriesgar un duplicado raro a perder un
    mensaje legítimo. El error se loguea para auditoría.
    """
    if not wamid:
        # Sin id no podemos hacer idempotency. Aceptamos y procesamos.
        return True

    try:
        redis = get_redis()
        resultado = await redis.set(
            _clave(wamid),
            "1",
            ex=_TTL_IDEMPOTENCY_SEGUNDOS,
            nx=True,
        )
    except Exception as exc:
        log.warning(
            "idempotency_redis_falla",
            wamid_prefix=wamid[:12],
            error=type(exc).__name__,
        )
        return True  # failure-open

    # redis-py devuelve True si se seteó, None si no (porque NX y ya existía).
    if resultado is True:
        return True

    log.info("webhook_duplicado_ignorado", wamid_prefix=wamid[:12])
    return False


async def olvidar_wamid(wamid: str) -> None:
    """Borra la marca de un wamid. Solo para tests — no se usa en producción.

    En producción nunca queremos re-procesar un mensaje ya visto, pero en
    tests necesitamos limpiar el estado entre cases.
    """
    if not wamid:
        return
    try:
        redis = get_redis()
        await redis.delete(_clave(wamid))
    except Exception:
        # Tests aceptan que Redis pueda no estar disponible.
        pass
