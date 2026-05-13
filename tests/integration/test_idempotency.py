"""
Tests del idempotency service contra Redis real.

Verifica que `SET NX EX` se comporta atómicamente y que los wamid
ya vistos se detectan como duplicados.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.idempotency_service import (
    intentar_marcar_procesado,
    olvidar_wamid,
)


@pytest.mark.asyncio
async def test_primer_intento_devuelve_true(redis_limpio) -> None:
    wamid = "test:wamid.primero"
    try:
        assert await intentar_marcar_procesado(wamid) is True
    finally:
        await olvidar_wamid(wamid)


@pytest.mark.asyncio
async def test_segundo_intento_devuelve_false(redis_limpio) -> None:
    wamid = "test:wamid.duplicado"
    try:
        primero = await intentar_marcar_procesado(wamid)
        segundo = await intentar_marcar_procesado(wamid)
        tercero = await intentar_marcar_procesado(wamid)
        assert primero is True
        assert segundo is False
        assert tercero is False
    finally:
        await olvidar_wamid(wamid)


@pytest.mark.asyncio
async def test_wamids_distintos_son_independientes(redis_limpio) -> None:
    wamids = [f"test:wamid.{i}" for i in range(5)]
    try:
        resultados = [await intentar_marcar_procesado(w) for w in wamids]
        assert all(r is True for r in resultados)

        # Segunda ronda — todos deben ser False
        resultados_2 = [await intentar_marcar_procesado(w) for w in wamids]
        assert all(r is False for r in resultados_2)
    finally:
        for w in wamids:
            await olvidar_wamid(w)


@pytest.mark.asyncio
async def test_concurrencia_solo_uno_gana(redis_limpio) -> None:
    """Si dos workers procesan el mismo wamid en paralelo, solo uno
    debe devolver True (gracias al NX atómico de Redis)."""
    wamid = "test:wamid.concurrente"
    try:
        # 10 corutinas intentando marcar el mismo wamid simultáneamente
        resultados = await asyncio.gather(
            *(intentar_marcar_procesado(wamid) for _ in range(10))
        )
        assert sum(1 for r in resultados if r is True) == 1
        assert sum(1 for r in resultados if r is False) == 9
    finally:
        await olvidar_wamid(wamid)


@pytest.mark.asyncio
async def test_wamid_vacio_no_bloquea() -> None:
    """Si Meta enviara un mensaje sin id (no debería), aceptamos procesarlo."""
    assert await intentar_marcar_procesado("") is True
    assert await intentar_marcar_procesado("") is True  # idempotent
