"""
Servicio de alertas — persistencia de denuncias.

`registrar_denuncia` es la operación atómica que cierra el flujo:
  1. Genera un código público único (reintenta ante violación UNIQUE).
  2. Cifra los campos sensibles con Fernet.
  3. Inserta la fila `alertas`.
  4. Persiste las evidencias (delegando a `evidencia_service`).
  5. Inserta entrada de bitácora `ALERTA_CREADA`.
  6. Encola notificación SMTP en Dramatiq.

Todo dentro de UNA transacción de BD. Si algo falla, rollback completo y
el ciudadano puede reintentar al pulsar Confirmar de nuevo.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.codigo_publico import generar_codigo
from app.core.security import get_crypto
from app.models.alerta import Alerta, EstadoAlerta
from app.models.bitacora import ActorBitacora, EventoBitacora, TipoEvento
from app.services.evidencia_service import persistir_evidencia
from app.utils.logger import obtener_logger

log = obtener_logger(__name__)


# Máximo de intentos para generar un código único ante colisión.
# Con 32**6 ≈ 1B combinaciones por año, una colisión es casi imposible,
# pero protegemos contra desviaciones estadísticas.
_MAX_REINTENTOS_CODIGO = 5


class ColisionCodigoError(Exception):
    """Se agotaron los reintentos generando código público — situación anómala."""


async def registrar_denuncia(
    db: AsyncSession,
    *,
    telefono_hash: str,
    datos: dict[str, Any],
    evidencias_buffer: list[dict[str, Any]] | None = None,
) -> tuple[Alerta, str]:
    """Persiste una denuncia completa y devuelve `(alerta, codigo_publico)`.

    Args:
        db: sesión SQLAlchemy async. El caller decide commit/rollback.
        telefono_hash: hash del teléfono del denunciante.
        datos: dict con las claves del motor (`K_INSTITUCION`, `K_DESCRIPCION`, ...).
        evidencias_buffer: lista de dicts con metadata + bytes en disco temporal.
            Cada dict requiere: 'media_id', 'nombre_original', 'mime',
            'tamanio_bytes', 'ruta_temporal' (path al binario ya descargado).

    Returns:
        Tupla `(Alerta, codigo_publico)`.

    Raises:
        ColisionCodigoError: si fallan todos los reintentos de código (anómalo).
        ValueError: si falta un campo obligatorio en `datos`.
    """
    # Validación mínima de inputs (defensa frente a llamadas erradas).
    institucion = datos.get("institucion")
    descripcion = datos.get("descripcion")
    fecha = datos.get("fecha")
    if not institucion or not descripcion or not fecha:
        raise ValueError(
            "Faltan campos obligatorios para registrar la denuncia: "
            "se requieren 'institucion', 'descripcion' y 'fecha'."
        )

    crypto = get_crypto()
    inst_cifrada = crypto.cifrar(institucion) or b""
    desc_cifrada = crypto.cifrar(descripcion) or b""
    involucrados_cifrado = crypto.cifrar(datos.get("involucrados"))

    # Construir la alerta, intentando hasta _MAX_REINTENTOS_CODIGO si hay colisión
    for intento in range(_MAX_REINTENTOS_CODIGO):
        codigo = generar_codigo()
        alerta = Alerta(
            codigo_publico=codigo,
            telefono_hash=telefono_hash,
            institucion_denunciada=inst_cifrada,
            descripcion_hechos=desc_cifrada,
            personas_involucradas=involucrados_cifrado,
            fecha_aproximada=fecha,
            perjuicio_economico=datos.get("perjuicio"),
            denuncia_previa_otra=datos.get("denuncia_previa"),
            estado=EstadoAlerta.REGISTRADA.value,
        )
        db.add(alerta)
        try:
            await db.flush()
            break
        except IntegrityError as exc:
            await db.rollback()
            log.warning(
                "codigo_publico_colision",
                intento=intento + 1,
                codigo=codigo,
            )
            if intento == _MAX_REINTENTOS_CODIGO - 1:
                raise ColisionCodigoError(
                    f"No se pudo generar código único tras "
                    f"{_MAX_REINTENTOS_CODIGO} intentos"
                ) from exc

    # Persistir cada evidencia válida en disco + fila en BD
    if evidencias_buffer:
        for ev in evidencias_buffer:
            contenido = _leer_temporal_y_borrar(ev["ruta_temporal"])
            await persistir_evidencia(
                db,
                alerta_id=alerta.id,
                contenido=contenido,
                nombre_original=ev["nombre_original"],
                mime=ev["mime"],
            )

    # Bitácora: ALERTA_CREADA
    db.add(
        EventoBitacora(
            alerta_id=alerta.id,
            evento=TipoEvento.ALERTA_CREADA.value,
            actor=ActorBitacora.SISTEMA.value,
            detalle={
                "codigo_publico": codigo,
                "num_evidencias": len(evidencias_buffer or []),
            },
        )
    )
    await db.flush()

    log.info(
        "alerta_registrada",
        alerta_id=alerta.id,
        codigo=codigo,
        num_evidencias=len(evidencias_buffer or []),
    )

    # Encolar notificación SMTP (no bloquea esta transacción).
    # Import tardío para evitar configurar Dramatiq al importar el módulo.
    try:
        from app.services.notificacion_service import enviar_notificacion_alerta

        timestamp_iso = (alerta.timestamp_registro or datetime.now(timezone.utc)).isoformat()
        enviar_notificacion_alerta.send(codigo_publico=codigo, timestamp_iso=timestamp_iso)
    except Exception as exc:
        # Si la cola está caída, no abortamos la transacción.
        # La denuncia ya está registrada; un job de reconciliación puede
        # detectar alertas sin notificación y reintentar.
        log.error(
            "notificacion_no_encolada",
            codigo=codigo,
            alerta_id=alerta.id,
            error=str(exc),
        )

    return alerta, codigo


def _leer_temporal_y_borrar(ruta: str) -> bytes:
    """Lee un archivo temporal a memoria y lo borra del disco."""
    path = Path(ruta)
    contenido = path.read_bytes()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return contenido
