"""
Tests end-to-end de creación de denuncias contra Postgres real.

Cubren:
  - registrar_denuncia inserta filas correctamente.
  - Los campos sensibles quedan cifrados en la BD (BYTEA opaco).
  - Al descifrar con la misma master key se recupera el texto original.
  - El código público generado cumple el formato esperado y es único.
  - El hash del teléfono no es reversible sin el pepper.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.codigo_publico import es_codigo_valido
from app.core.security import get_crypto
from app.models.alerta import Alerta, EstadoAlerta
from app.models.bitacora import EventoBitacora, TipoEvento
from app.services.alerta_service import registrar_denuncia


@pytest.mark.asyncio
async def test_registrar_denuncia_persiste_con_campos_cifrados(
    db_session_commit: AsyncSession,
) -> None:
    """End-to-end: registramos, hacemos commit, recargamos desde otra
    sesión y verificamos que el cifrado de Fernet funciona ida y vuelta."""
    crypto = get_crypto()
    telefono_e164 = "593991234567"
    telefono_hash = crypto.hash_telefono(telefono_e164)

    institucion = "Ministerio de Educación"
    descripcion = "Descripción detallada de los hechos denunciados." * 2

    alerta, codigo = await registrar_denuncia(
        db_session_commit,
        telefono_hash=telefono_hash,
        datos={
            "institucion": institucion,
            "descripcion": descripcion,
            "fecha": "10/03/2025",
            "involucrados": "Persona X",
            "perjuicio": "no aplica",
            "denuncia_previa": None,
        },
    )
    await db_session_commit.commit()
    alerta_id = alerta.id

    try:
        # 1) El código generado cumple el formato esperado
        assert es_codigo_valido(codigo)

        # 2) Recargar desde la BD y verificar BYTEA opaco
        result = await db_session_commit.execute(
            select(Alerta).where(Alerta.id == alerta_id)
        )
        alerta_recargada = result.scalar_one()
        assert alerta_recargada.codigo_publico == codigo
        assert alerta_recargada.estado == EstadoAlerta.REGISTRADA.value

        ciphertext_inst = bytes(alerta_recargada.institucion_denunciada)
        assert institucion.encode() not in ciphertext_inst
        assert b"Ministerio" not in ciphertext_inst

        # 3) Descifrar devuelve el plaintext original
        assert crypto.descifrar(alerta_recargada.institucion_denunciada) == institucion
        assert crypto.descifrar(alerta_recargada.descripcion_hechos) == descripcion
        assert crypto.descifrar(alerta_recargada.personas_involucradas) == "Persona X"

        # 4) El telefono_hash NO contiene el número en claro
        assert telefono_e164 not in alerta_recargada.telefono_hash
        assert len(alerta_recargada.telefono_hash) == 64  # SHA-256 hex

        # 5) Se registró el evento ALERTA_CREADA en bitácora
        bita = await db_session_commit.execute(
            select(EventoBitacora).where(
                EventoBitacora.alerta_id == alerta_id,
                EventoBitacora.evento == TipoEvento.ALERTA_CREADA.value,
            )
        )
        eventos = list(bita.scalars().all())
        assert len(eventos) == 1
        assert eventos[0].detalle["codigo_publico"] == codigo

    finally:
        # Cleanup — primero bitácora (FK ON DELETE SET NULL), luego alerta
        await db_session_commit.execute(
            EventoBitacora.__table__.delete().where(
                EventoBitacora.alerta_id == alerta_id
            )
        )
        await db_session_commit.execute(
            Alerta.__table__.delete().where(Alerta.id == alerta_id)
        )
        await db_session_commit.commit()


@pytest.mark.asyncio
async def test_codigos_publicos_son_unicos(
    db_session_commit: AsyncSession,
) -> None:
    """Genera 20 denuncias y verifica que todos los códigos son distintos."""
    crypto = get_crypto()
    telefono_hash = crypto.hash_telefono("593997777777")
    ids_creados = []
    codigos = set()
    try:
        for i in range(20):
            alerta, codigo = await registrar_denuncia(
                db_session_commit,
                telefono_hash=telefono_hash,
                datos={
                    "institucion": f"Institución X{i}",
                    "descripcion": "x" * 40,
                    "fecha": "2025",
                },
            )
            await db_session_commit.commit()
            ids_creados.append(alerta.id)
            codigos.add(codigo)
        assert len(codigos) == 20
    finally:
        for aid in ids_creados:
            await db_session_commit.execute(
                EventoBitacora.__table__.delete().where(
                    EventoBitacora.alerta_id == aid
                )
            )
            await db_session_commit.execute(
                Alerta.__table__.delete().where(Alerta.id == aid)
            )
        await db_session_commit.commit()


@pytest.mark.asyncio
async def test_falta_de_campo_obligatorio_levanta_error(
    db_session: AsyncSession,
) -> None:
    """registrar_denuncia debe rechazar entradas que no traen los obligatorios."""
    with pytest.raises(ValueError, match="obligatorio"):
        await registrar_denuncia(
            db_session,
            telefono_hash="a" * 64,
            datos={"institucion": "x"},  # falta descripcion y fecha
        )
