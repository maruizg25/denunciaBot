"""
Servicio de evidencias — manejo de archivos adjuntos.

Responsabilidades:
  - Guardar el binario en disco con nombre = UUID v4 + extensión genérica.
  - Calcular SHA-256 del contenido (para integridad + deduplicación).
  - Cifrar el nombre original con Fernet.
  - Escanear con ClamAV si está habilitado.
  - Insertar la fila en `alertas_evidencias`.

El binario nunca toca la base de datos: solo metadata.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_crypto
from app.models.evidencia import Evidencia
from app.utils.logger import obtener_logger

log = obtener_logger(__name__)


# =========================================================================
# Helpers de extensión por MIME
# =========================================================================

_MIME_A_EXTENSION = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
}


def _extension_para_mime(mime: str) -> str:
    """Devuelve la extensión genérica para el MIME, o 'bin' si desconocido."""
    return _MIME_A_EXTENSION.get((mime or "").lower(), "bin")


# =========================================================================
# Escaneo antivirus (ClamAV)
# =========================================================================

class ClamAVError(Exception):
    """Error al comunicarse con ClamAV."""


async def escanear_con_clamav(contenido: bytes) -> bool:
    """Escanea un buffer con clamd. Devuelve True si está limpio.

    Si ClamAV no está habilitado en settings, devuelve True sin hacer nada.
    Si está habilitado y falla la comunicación con clamd, levanta excepción
    — preferimos rechazar el archivo a aceptarlo sin escanear.
    """
    from app.config import get_settings

    settings = get_settings()
    if not settings.CLAMAV_ENABLED:
        return True

    # `clamd` es sync; lo envolvemos en un thread para no bloquear el loop.
    def _scan_sync() -> tuple[str, str | None]:
        import io

        import clamd  # type: ignore[import-untyped]

        cliente = clamd.ClamdNetworkSocket(
            host=settings.CLAMAV_HOST,
            port=settings.CLAMAV_PORT,
            timeout=settings.CLAMAV_TIMEOUT_SECONDS,
        )
        # clamd.instream devuelve {'stream': ('OK'|'FOUND'|'ERROR', detalle)}
        respuesta = cliente.instream(io.BytesIO(contenido))
        estado, detalle = respuesta.get("stream", ("ERROR", "respuesta vacía"))
        return estado, detalle

    try:
        estado, detalle = await asyncio.to_thread(_scan_sync)
    except Exception as exc:
        log.error("clamav_error_comunicacion", error=str(exc))
        raise ClamAVError(f"No se pudo escanear con ClamAV: {exc}") from exc

    if estado == "OK":
        return True
    if estado == "FOUND":
        log.warning("clamav_archivo_infectado", firma=detalle)
        return False
    log.error("clamav_respuesta_inesperada", estado=estado, detalle=detalle)
    raise ClamAVError(f"ClamAV devolvió estado inesperado: {estado}")


# =========================================================================
# Persistencia en disco
# =========================================================================

def _hash_sha256(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


async def _guardar_en_disco(contenido: bytes, ruta: Path) -> None:
    """Escribe el contenido a disco de forma atómica.

    Estrategia: escribir a `.tmp` y renombrar (rename es atómico en POSIX
    cuando origen y destino están en el mismo filesystem).
    """
    def _escribir_sync() -> None:
        tmp = ruta.with_suffix(ruta.suffix + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        # Permisos 0600: solo el dueño del proceso puede leer/escribir.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, contenido)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(tmp, ruta)

    await asyncio.to_thread(_escribir_sync)


# =========================================================================
# API pública
# =========================================================================

async def persistir_evidencia(
    db: AsyncSession,
    *,
    alerta_id: int,
    contenido: bytes,
    nombre_original: str,
    mime: str,
) -> Evidencia:
    """Guarda un archivo en disco e inserta su metadata en la BD.

    Args:
        db: sesión SQLAlchemy async; el caller maneja commit/rollback.
        alerta_id: FK a la alerta a la que pertenece.
        contenido: bytes del archivo (ya descargado y, opcionalmente, escaneado).
        nombre_original: nombre con el que el ciudadano lo envió.
        mime: tipo MIME ya validado.

    Returns:
        El modelo `Evidencia` recién insertado (con `id` asignado).

    Raises:
        ValueError si el archivo está vacío.
    """
    if not contenido:
        raise ValueError("No se puede persistir un archivo vacío")

    from app.config import get_settings

    settings = get_settings()
    base_dir = Path(settings.EVIDENCIAS_DIR).resolve()

    # Nombre en disco: UUID v4 + extensión genérica.
    # El nombre real va cifrado en la BD.
    nombre_disco = f"{uuid.uuid4()}.{_extension_para_mime(mime)}"
    ruta = base_dir / nombre_disco

    await _guardar_en_disco(contenido, ruta)

    crypto = get_crypto()
    nombre_cifrado = crypto.cifrar(nombre_original) or b""

    evidencia = Evidencia(
        alerta_id=alerta_id,
        nombre_original=nombre_cifrado,
        ruta_almacenamiento=str(ruta),
        tipo_mime=mime,
        tamanio_bytes=len(contenido),
        hash_sha256=_hash_sha256(contenido),
    )
    db.add(evidencia)
    await db.flush()  # asigna el id sin commitear

    log.info(
        "evidencia_persistida",
        evidencia_id=evidencia.id,
        alerta_id=alerta_id,
        mime=mime,
        tamanio_bytes=len(contenido),
    )
    return evidencia
