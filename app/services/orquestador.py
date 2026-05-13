"""
Orquestador — traduce las acciones del motor a llamadas reales de I/O.

El motor de conversación devuelve un `ResultadoMotor` con una lista de
acciones puras (dataclasses frozen). Este módulo las ejecuta en orden y
coordina las tres capas externas: PostgreSQL (transaccional), Redis
(extra-transaccional) y Meta API (extra-transaccional).

Modelo transaccional — dos fases:

  Fase 1 (DENTRO de transacción de BD):
    - Todas las acciones que tocan la BD: AccionRegistrarBitacora,
      AccionRegistrarDenuncia.
    - Las acciones de Meta y Redis se ejecutan inline EXCEPTO el envío
      del mensaje de cierre tras un registro, que se difiere.
    - Si CUALQUIER acción de BD falla, rollback completo.

  Fase 2 (POST-commit, sólo si Fase 1 tuvo éxito):
    - Envío del mensaje de cierre con el código generado.
    - Eliminación de la sesión Redis asociada al registro.

Esta separación garantiza que el ciudadano JAMÁS reciba su código de
seguimiento si la denuncia no se persistió. El caso opuesto (denuncia
persistida pero envío de cierre falla por Meta caído) se loguea y queda
para reconciliación posterior — el ciudadano no recibe inmediatamente
su código, pero los datos están a salvo.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.conversacion.motor import (
    AccionEliminarSesion,
    AccionEnviarBotones,
    AccionEnviarTexto,
    AccionGuardarSesion,
    AccionMarcarLeido,
    AccionRegistrarBitacora,
    AccionRegistrarDenuncia,
    ResultadoMotor,
)
from app.core.meta_client import (
    MetaAPIPermanente,
    MetaAPITransitorio,
    get_meta_client,
)
from app.models.bitacora import EventoBitacora
from app.services.alerta_service import registrar_denuncia
from app.services.notificacion_service import enviar_mensaje_cierre
from app.services.sesion_service import (
    eliminar_sesion,
    guardar_sesion,
)
from app.utils.logger import obtener_logger

log = obtener_logger(__name__)


# Clave del diccionario `datos` donde el motor guarda las evidencias.
# Mantenido en sincronía con `app.conversacion.motor.K_EVIDENCIAS`.
_K_EVIDENCIAS = "evidencias"


# =========================================================================
# Estado interno de la ejecución
# =========================================================================

@dataclass
class _CierrePendiente:
    """Trabajo que se ejecuta DESPUÉS del commit de la transacción."""

    destinatario: str
    codigo_publico: str
    telefono_hash: str


# =========================================================================
# API pública
# =========================================================================

async def ejecutar(resultado: ResultadoMotor, db: AsyncSession) -> None:
    """Ejecuta todas las acciones del resultado del motor.

    Garantías:
      - Todas las escrituras a BD comparten transacción: commit o rollback
        atómicos.
      - Si una acción levanta excepción, rollback y se propaga al caller.
      - Las acciones de Meta y Redis se ejecutan inline; las de cierre
        tras un registro se difieren a post-commit.
    """
    cierres_pendientes: list[_CierrePendiente] = []

    try:
        for accion in resultado.acciones:
            cierre = await _ejecutar_accion(accion, db)
            if cierre is not None:
                cierres_pendientes.append(cierre)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    # Fase 2 — solo si el commit fue exitoso.
    for cierre in cierres_pendientes:
        await _ejecutar_cierre(cierre)


# =========================================================================
# Dispatcher de acciones — Fase 1
# =========================================================================

async def _ejecutar_accion(
    accion: object, db: AsyncSession
) -> _CierrePendiente | None:
    """Ejecuta una acción individual. Devuelve un cierre pendiente o `None`."""
    if isinstance(accion, AccionEnviarTexto):
        await _enviar_texto(accion.destinatario, accion.texto)
        return None

    if isinstance(accion, AccionEnviarBotones):
        await _enviar_botones(accion.destinatario, accion.texto, accion.botones)
        return None

    if isinstance(accion, AccionMarcarLeido):
        # No crítico: si falla, el flujo continúa.
        try:
            await get_meta_client().marcar_leido(accion.message_id)
        except (MetaAPITransitorio, MetaAPIPermanente) as exc:
            log.warning("marcar_leido_falla", error=str(exc))
        return None

    if isinstance(accion, AccionGuardarSesion):
        await guardar_sesion(accion.sesion)
        return None

    if isinstance(accion, AccionEliminarSesion):
        await eliminar_sesion(accion.telefono_hash)
        return None

    if isinstance(accion, AccionRegistrarBitacora):
        db.add(
            EventoBitacora(
                alerta_id=accion.alerta_id,
                evento=accion.evento,
                actor=accion.actor,
                detalle=accion.detalle,
            )
        )
        await db.flush()
        return None

    if isinstance(accion, AccionRegistrarDenuncia):
        return await _ejecutar_registrar(accion, db)

    log.warning("orquestador_accion_desconocida", tipo=type(accion).__name__)
    return None


async def _ejecutar_registrar(
    accion: AccionRegistrarDenuncia, db: AsyncSession
) -> _CierrePendiente:
    """Persiste la denuncia. El cierre/eliminación se difiere a post-commit."""
    datos = dict(accion.datos)
    evidencias_buffer = datos.pop(_K_EVIDENCIAS, None) or []

    _, codigo = await registrar_denuncia(
        db,
        telefono_hash=accion.telefono_hash,
        datos=datos,
        evidencias_buffer=evidencias_buffer,
    )

    return _CierrePendiente(
        destinatario=accion.destinatario,
        codigo_publico=codigo,
        telefono_hash=accion.telefono_hash,
    )


# =========================================================================
# Fase 2 — post-commit
# =========================================================================

async def _ejecutar_cierre(cierre: _CierrePendiente) -> None:
    """Tras commit exitoso: encolar el envío del cierre y borrar la sesión.

    Encolamos el mensaje en Dramatiq en lugar de llamar a Meta inline:
      - Si Meta falla momentáneamente, el actor reintenta hasta 5 veces
        con backoff exponencial. El ciudadano recibe su código aunque
        haya un blip de Meta.
      - El response al webhook es más rápido (no espera a Meta).
      - Si todos los reintentos fallan, el mensaje queda en la DLQ
        `cierres.DQ` para inspección/re-procesamiento manual.
    """
    try:
        enviar_mensaje_cierre.send(
            destinatario=cierre.destinatario,
            codigo_publico=cierre.codigo_publico,
        )
        log.info(
            "cierre_encolado",
            codigo=cierre.codigo_publico,
            destinatario_prefix=cierre.destinatario[:6],
        )
    except Exception as exc:
        # Si la cola está caída (Redis Dramatiq inalcanzable), intentamos
        # envío sincrónico como fallback. La denuncia ya está persistida.
        log.error(
            "cierre_no_encolado_fallback_sincrono",
            codigo=cierre.codigo_publico,
            error=str(exc),
        )
        try:
            from app.conversacion.mensajes import cierre_exitoso

            await _enviar_texto(
                cierre.destinatario,
                cierre_exitoso(cierre.codigo_publico),
            )
        except (MetaAPITransitorio, MetaAPIPermanente) as exc_meta:
            log.error(
                "cierre_fallback_tambien_fallo",
                codigo=cierre.codigo_publico,
                error=str(exc_meta),
            )

    try:
        await eliminar_sesion(cierre.telefono_hash)
    except Exception as exc:
        log.error(
            "sesion_no_eliminada_post_registro",
            codigo=cierre.codigo_publico,
            error=str(exc),
        )


# =========================================================================
# Wrappers sobre el cliente Meta
# =========================================================================

async def _enviar_texto(destinatario: str, texto: str) -> None:
    """Envía un texto. Propaga las excepciones para que el caller decida."""
    await get_meta_client().enviar_texto(destinatario, texto)


async def _enviar_botones(
    destinatario: str,
    texto: str,
    botones: tuple[tuple[str, str], ...],
) -> None:
    """Envía un mensaje con botones. Espera tupla `((id, label), ...)`."""
    await get_meta_client().enviar_botones(destinatario, texto, list(botones))
