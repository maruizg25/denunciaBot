#!/usr/bin/env python3
"""
Exporta denuncias registradas a un archivo CSV.

CRÍTICO — este script descifra los campos sensibles localmente:
  - El CSV resultante contiene datos en CLARO (institución, descripción,
    personas involucradas, nombres de archivos de evidencia).
  - El archivo de salida debe vivir con permisos restrictivos (umask 077).
  - NUNCA debe enviarse por canales no cifrados ni quedar en directorios
    accesibles por otros usuarios del servidor.

Uso:
    python scripts/export_alertas.py --salida alertas_2026Q1.csv \\
        --desde 2026-01-01 --hasta 2026-04-01

    python scripts/export_alertas.py --estado REGISTRADA --salida pendientes.csv

    python scripts/export_alertas.py --salida -    # imprime a stdout

Argumentos:
    --desde YYYY-MM-DD     fecha inicial (inclusive). Default: sin límite.
    --hasta YYYY-MM-DD     fecha final (exclusive). Default: sin límite.
    --estado X             filtra por estado (REGISTRADA / EN_REVISION / etc.)
    --salida PATH          path del archivo CSV, o '-' para stdout.
    --con-evidencias       incluye una columna con nombres de adjuntos.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Asegura que `app` sea importable cuando se corre como script.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.core.security import get_crypto  # noqa: E402
from app.database import dispose_engine, get_session_factory  # noqa: E402
from app.models.alerta import Alerta  # noqa: E402
from app.models.evidencia import Evidencia  # noqa: E402


COLUMNAS_BASE = [
    "id",
    "codigo_publico",
    "estado",
    "institucion_denunciada",
    "descripcion_hechos",
    "fecha_aproximada",
    "personas_involucradas",
    "perjuicio_economico",
    "denuncia_previa_otra",
    "timestamp_registro",
    "timestamp_actualizacion",
]


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Fecha inválida: {s!r}. Formato esperado: YYYY-MM-DD."
        ) from exc


def _construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Exporta denuncias a CSV con campos sensibles descifrados.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "ADVERTENCIA: el CSV resultante contiene datos sensibles "
            "EN CLARO. Maneje el archivo con cuidado y restrinja permisos."
        ),
    )
    p.add_argument("--desde", type=_parse_date, default=None,
                   help="Fecha inicial inclusive (YYYY-MM-DD)")
    p.add_argument("--hasta", type=_parse_date, default=None,
                   help="Fecha final exclusiva (YYYY-MM-DD)")
    p.add_argument("--estado", type=str, default=None,
                   help="Filtra por estado (REGISTRADA, EN_REVISION, TRAMITADA, DESCARTADA)")
    p.add_argument("--salida", type=str, default="-",
                   help='Path del CSV (- para stdout). Default: -')
    p.add_argument("--con-evidencias", action="store_true",
                   help="Incluye columna con nombres de archivos adjuntos (descifrados)")
    return p


async def _consultar_alertas(
    desde: date | None,
    hasta: date | None,
    estado: str | None,
    incluir_evidencias: bool,
) -> list[Alerta]:
    """Lee alertas filtradas. Carga evidencias por eager loading si se piden."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Alerta).order_by(Alerta.timestamp_registro)
        if incluir_evidencias:
            stmt = stmt.options(selectinload(Alerta.evidencias))
        if desde:
            stmt = stmt.where(
                Alerta.timestamp_registro
                >= datetime.combine(desde, datetime.min.time(), tzinfo=timezone.utc)
            )
        if hasta:
            stmt = stmt.where(
                Alerta.timestamp_registro
                < datetime.combine(hasta, datetime.min.time(), tzinfo=timezone.utc)
            )
        if estado:
            stmt = stmt.where(Alerta.estado == estado)
        result = await session.execute(stmt)
        return list(result.scalars().all())


def _fila_de_alerta(
    a: Alerta, crypto, incluir_evidencias: bool
) -> list[str]:
    """Construye una fila CSV con campos descifrados."""
    fila = [
        str(a.id),
        a.codigo_publico,
        a.estado,
        crypto.descifrar(a.institucion_denunciada) or "",
        crypto.descifrar(a.descripcion_hechos) or "",
        a.fecha_aproximada or "",
        crypto.descifrar(a.personas_involucradas) or "",
        a.perjuicio_economico or "",
        a.denuncia_previa_otra or "",
        a.timestamp_registro.isoformat() if a.timestamp_registro else "",
        a.timestamp_actualizacion.isoformat() if a.timestamp_actualizacion else "",
    ]
    if incluir_evidencias:
        nombres = []
        for ev in (a.evidencias or []):
            nombre = crypto.descifrar(ev.nombre_original) or "<sin nombre>"
            nombres.append(f"{nombre} ({ev.tipo_mime}, {ev.tamanio_bytes} bytes)")
        fila.append(" | ".join(nombres))
    return fila


def _abrir_salida(path: str):
    """Abre el archivo de salida con permisos seguros (0o600)."""
    if path == "-":
        return sys.stdout, False
    # umask temporal para crear el archivo con 0600
    umask_anterior = os.umask(0o077)
    try:
        archivo = open(path, "w", encoding="utf-8", newline="")
    finally:
        os.umask(umask_anterior)
    return archivo, True


async def main() -> int:
    args = _construir_parser().parse_args()

    if args.desde and args.hasta and args.desde >= args.hasta:
        print("ERROR  --desde debe ser anterior a --hasta", file=sys.stderr)
        return 1

    print(
        f"Exportando alertas (desde={args.desde}, hasta={args.hasta}, "
        f"estado={args.estado}, con_evidencias={args.con_evidencias})",
        file=sys.stderr,
    )

    crypto = get_crypto()
    alertas = await _consultar_alertas(
        args.desde, args.hasta, args.estado, args.con_evidencias
    )
    await dispose_engine()

    salida, hay_que_cerrar = _abrir_salida(args.salida)
    try:
        writer = csv.writer(salida, quoting=csv.QUOTE_MINIMAL)
        columnas = list(COLUMNAS_BASE)
        if args.con_evidencias:
            columnas.append("evidencias")
        writer.writerow(columnas)
        for alerta in alertas:
            try:
                writer.writerow(_fila_de_alerta(alerta, crypto, args.con_evidencias))
            except Exception as exc:
                print(
                    f"  ADVERTENCIA  Fallo al exportar alerta id={alerta.id}: {exc}",
                    file=sys.stderr,
                )
    finally:
        if hay_que_cerrar:
            salida.close()

    print(
        f"Exportadas {len(alertas)} alertas a "
        f"{'stdout' if args.salida == '-' else args.salida}",
        file=sys.stderr,
    )
    if hay_que_cerrar:
        print(f"Permisos del archivo: 0o600 (solo el dueño puede leerlo).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
