"""
Tests del trigger de inmutabilidad de la bitácora de auditoría.

Estos tests son la única forma de verificar realmente que los triggers
PL/pgSQL están activos. La migración los crea; aquí confirmamos que
PostgreSQL los respeta ante intentos directos de UPDATE/DELETE.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bitacora import ActorBitacora, EventoBitacora, TipoEvento


@pytest.mark.asyncio
async def test_update_de_bitacora_es_rechazado(
    db_session_commit: AsyncSession,
) -> None:
    """Intentar UPDATE en bitacora_auditoria debe lanzar excepción
    con código de privilegio insuficiente."""
    # Insertamos una fila legítima primero
    evento = EventoBitacora(
        evento=TipoEvento.SESION_INICIADA.value,
        actor=ActorBitacora.SISTEMA.value,
        detalle={"prueba": "inmutabilidad"},
    )
    db_session_commit.add(evento)
    await db_session_commit.commit()
    evento_id = evento.id

    try:
        # Intentar modificar la fila DIRECTAMENTE vía SQL crudo
        with pytest.raises(DBAPIError) as exc_info:
            await db_session_commit.execute(
                text(
                    "UPDATE bitacora_auditoria "
                    "SET actor = 'HACKEADO' "
                    "WHERE id = :id"
                ),
                {"id": evento_id},
            )
            await db_session_commit.commit()

        # Verificamos que el error es el de nuestro trigger
        mensaje = str(exc_info.value).lower()
        assert "inmutable" in mensaje or "no permitida" in mensaje
        await db_session_commit.rollback()

        # Confirmamos que la fila NO cambió
        result = await db_session_commit.execute(
            text("SELECT actor FROM bitacora_auditoria WHERE id = :id"),
            {"id": evento_id},
        )
        assert result.scalar() == ActorBitacora.SISTEMA.value

    finally:
        # Cleanup: necesitamos un truncate o un DELETE protegido por superuser.
        # Como el trigger también bloquea DELETE, usamos un workaround:
        # deshabilitar el trigger temporalmente.
        # NOTA: esto requiere permisos de OWNER de la tabla.
        await db_session_commit.execute(
            text("ALTER TABLE bitacora_auditoria DISABLE TRIGGER trg_bitacora_no_delete")
        )
        await db_session_commit.execute(
            text("DELETE FROM bitacora_auditoria WHERE id = :id"),
            {"id": evento_id},
        )
        await db_session_commit.execute(
            text("ALTER TABLE bitacora_auditoria ENABLE TRIGGER trg_bitacora_no_delete")
        )
        await db_session_commit.commit()


@pytest.mark.asyncio
async def test_delete_de_bitacora_es_rechazado(
    db_session_commit: AsyncSession,
) -> None:
    """Intentar DELETE en bitacora_auditoria debe lanzar excepción."""
    evento = EventoBitacora(
        evento=TipoEvento.SESION_INICIADA.value,
        actor=ActorBitacora.SISTEMA.value,
        detalle={"prueba": "no_delete"},
    )
    db_session_commit.add(evento)
    await db_session_commit.commit()
    evento_id = evento.id

    try:
        with pytest.raises(DBAPIError) as exc_info:
            await db_session_commit.execute(
                text("DELETE FROM bitacora_auditoria WHERE id = :id"),
                {"id": evento_id},
            )
            await db_session_commit.commit()

        mensaje = str(exc_info.value).lower()
        assert "inmutable" in mensaje or "no permitida" in mensaje
        await db_session_commit.rollback()

        # La fila sigue existiendo
        result = await db_session_commit.execute(
            text("SELECT COUNT(*) FROM bitacora_auditoria WHERE id = :id"),
            {"id": evento_id},
        )
        assert result.scalar() == 1

    finally:
        # Cleanup con trigger deshabilitado
        await db_session_commit.execute(
            text("ALTER TABLE bitacora_auditoria DISABLE TRIGGER trg_bitacora_no_delete")
        )
        await db_session_commit.execute(
            text("DELETE FROM bitacora_auditoria WHERE id = :id"),
            {"id": evento_id},
        )
        await db_session_commit.execute(
            text("ALTER TABLE bitacora_auditoria ENABLE TRIGGER trg_bitacora_no_delete")
        )
        await db_session_commit.commit()


@pytest.mark.asyncio
async def test_insert_de_bitacora_es_permitido(
    db_session_commit: AsyncSession,
) -> None:
    """INSERT debe seguir funcionando — el trigger solo bloquea UPDATE/DELETE."""
    evento = EventoBitacora(
        evento=TipoEvento.MENSAJE_RECIBIDO.value,
        actor=ActorBitacora.CIUDADANO.value,
        detalle={"contenido": "test"},
    )
    db_session_commit.add(evento)
    await db_session_commit.commit()
    evento_id = evento.id

    try:
        assert evento_id is not None
        result = await db_session_commit.execute(
            text("SELECT evento FROM bitacora_auditoria WHERE id = :id"),
            {"id": evento_id},
        )
        assert result.scalar() == TipoEvento.MENSAJE_RECIBIDO.value
    finally:
        await db_session_commit.execute(
            text("ALTER TABLE bitacora_auditoria DISABLE TRIGGER trg_bitacora_no_delete")
        )
        await db_session_commit.execute(
            text("DELETE FROM bitacora_auditoria WHERE id = :id"),
            {"id": evento_id},
        )
        await db_session_commit.execute(
            text("ALTER TABLE bitacora_auditoria ENABLE TRIGGER trg_bitacora_no_delete")
        )
        await db_session_commit.commit()
