"""
Audit trail firmado de la bitácora — exporte tamper-evident.

Genera un stream JSONL donde cada entrada incluye un hash encadenado con
la anterior (estilo blockchain-ligero). Al final, una entrada `__sello`
trae un HMAC del último hash con un secret distinto al `ADMIN_TOKEN`.

Propiedades de seguridad:
  - **Detección de modificación retroactiva**: si alguien con acceso a la
    BD modifica una fila ya exportada, el hash de las filas posteriores
    deja de coincidir → el verificador detecta el tampering.
  - **Detección de eliminación**: si una fila se borra (aunque el trigger
    PL/pgSQL lo prohíbe, defensa en profundidad), el `id` salta y el
    consumidor del trail puede detectarlo.
  - **Detección de fabricación**: el sello HMAC final requiere conocer
    `AUDIT_HMAC_SECRET`. Sin él, no se puede generar un trail válido.

Limitaciones (honestas):
  - No previene la modificación EN VIVO antes del export. Si un atacante
    altera la BD ANTES de generar el trail, el trail saldrá consistente
    con la BD alterada. Mitigación: generar trails periódicos y comparar
    los hashes entre exports (un trail nuevo debe contener TODAS las filas
    del anterior con los mismos hashes hasta el punto común).
  - El hash no es prueba criptográfica pública (sería un Merkle tree con
    timestamping notarial). Es suficiente para auditoría interna.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bitacora import EventoBitacora


def _hash_fila(fila_dict: dict, hash_anterior: str) -> str:
    """Calcula `SHA-256(hash_anterior || canonical_json(fila))`.

    Usa JSON canónico (sort_keys, separators sin espacios) para que el
    mismo dict siempre produzca el mismo hash, independiente del orden
    en que SQLAlchemy lo serialice.
    """
    canon = json.dumps(fila_dict, sort_keys=True, separators=(",", ":"), default=str)
    h = hashlib.sha256()
    h.update(hash_anterior.encode())
    h.update(b"|")
    h.update(canon.encode())
    return h.hexdigest()


def _fila_a_dict(evento: EventoBitacora) -> dict:
    """Serializa un EventoBitacora a dict plano para exportar."""
    return {
        "id": evento.id,
        "alerta_id": evento.alerta_id,
        "evento": evento.evento,
        "actor": evento.actor,
        "detalle": evento.detalle,
        "timestamp": evento.timestamp.isoformat() if evento.timestamp else None,
    }


async def generar_audit_trail(
    db: AsyncSession,
    *,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    hmac_secret: str,
) -> AsyncIterator[str]:
    """Itera filas de bitácora y devuelve líneas JSONL con hashes encadenados.

    Cada `yield` es una línea de texto terminada en \\n, lista para escribir
    al output. La primera línea es un header con metadata; la última es un
    sello HMAC sobre el último hash de la cadena.

    Args:
        db: sesión de BD async.
        desde/hasta: filtros opcionales por timestamp.
        hmac_secret: clave para el sello final (de settings.AUDIT_HMAC_SECRET).
    """
    if not hmac_secret:
        raise ValueError("hmac_secret no puede estar vacío")

    # Header del trail
    encabezado = {
        "__header": True,
        "version": "1",
        "generado_en": datetime.utcnow().isoformat() + "Z",
        "filtros": {
            "desde": desde.isoformat() if desde else None,
            "hasta": hasta.isoformat() if hasta else None,
        },
    }
    yield json.dumps(encabezado, ensure_ascii=False) + "\n"

    # Hash inicial = SHA-256 del header (raíz de la cadena)
    hash_actual = hashlib.sha256(
        json.dumps(encabezado, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    # Query con orden estricto por id ascendente (clave para la cadena)
    stmt = select(EventoBitacora).order_by(EventoBitacora.id.asc())
    if desde:
        stmt = stmt.where(EventoBitacora.timestamp >= desde)
    if hasta:
        stmt = stmt.where(EventoBitacora.timestamp < hasta)

    contador = 0
    # Stream con buffer para evitar cargar toda la bitácora en memoria.
    result = await db.stream(stmt)
    async for row in result.scalars():
        fila_dict = _fila_a_dict(row)
        hash_actual = _hash_fila(fila_dict, hash_actual)
        fila_dict["__hash"] = hash_actual
        yield json.dumps(fila_dict, ensure_ascii=False, default=str) + "\n"
        contador += 1

    # Sello final: HMAC del último hash de la cadena
    sello = {
        "__sello": True,
        "filas_totales": contador,
        "ultimo_hash": hash_actual,
        "hmac_sha256": hmac.new(
            hmac_secret.encode(),
            hash_actual.encode(),
            hashlib.sha256,
        ).hexdigest(),
        "finalizado_en": datetime.utcnow().isoformat() + "Z",
    }
    yield json.dumps(sello, ensure_ascii=False) + "\n"


def verificar_audit_trail(lineas: list[str], hmac_secret: str) -> tuple[bool, str]:
    """Verifica un trail JSONL exportado. Devuelve (válido, motivo).

    Útil para que un auditor externo (con el secret) confirme que un
    archivo .jsonl no fue alterado. No requiere acceso a BD.

    Returns:
        (True, "ok") si todo cuadra.
        (False, motivo) si la cadena o el sello no son consistentes.
    """
    if not lineas:
        return False, "trail vacío"

    # Parsear header
    try:
        header = json.loads(lineas[0])
    except json.JSONDecodeError:
        return False, "header no es JSON válido"
    if not header.get("__header"):
        return False, "primera línea no es un header"

    hash_esperado = hashlib.sha256(
        json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    contador = 0
    for i, linea in enumerate(lineas[1:-1], start=1):
        try:
            fila = json.loads(linea)
        except json.JSONDecodeError:
            return False, f"línea {i} no es JSON válido"

        hash_almacenado = fila.pop("__hash", None)
        if hash_almacenado is None:
            return False, f"línea {i} sin __hash"

        recalculado = _hash_fila(fila, hash_esperado)
        if not hmac.compare_digest(recalculado, hash_almacenado):
            return False, f"hash inconsistente en línea {i} (¿fila modificada?)"

        hash_esperado = hash_almacenado
        contador += 1

    # Verificar sello final
    try:
        sello = json.loads(lineas[-1])
    except json.JSONDecodeError:
        return False, "sello no es JSON válido"
    if not sello.get("__sello"):
        return False, "última línea no es un sello"
    if sello.get("filas_totales") != contador:
        return False, f"contador del sello ({sello.get('filas_totales')}) ≠ filas reales ({contador})"
    if sello.get("ultimo_hash") != hash_esperado:
        return False, "último hash del sello no coincide con la cadena"

    hmac_esperado = hmac.new(
        hmac_secret.encode(), hash_esperado.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sello.get("hmac_sha256", ""), hmac_esperado):
        return False, "HMAC del sello no verifica (¿secret incorrecto o trail falsificado?)"

    return True, "ok"
