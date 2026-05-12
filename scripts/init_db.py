#!/usr/bin/env python3
"""
Inicializa la base de datos de DenunciaBot.

Pasos:
  1. Verifica conexión a PostgreSQL.
  2. Ejecuta `alembic upgrade head` (aplica todas las migraciones pendientes).
  3. Verifica que los triggers de seguridad existan (bitácora inmutable,
     actualización automática de timestamps).
  4. Reporta resumen.

Uso:
    python scripts/init_db.py

Idempotente: correr varias veces no rompe nada (alembic detecta el estado).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

# Asegura que el paquete `app` sea importable cuando se corre como script.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.database import dispose_engine, get_engine  # noqa: E402


# Triggers que la migración inicial debe haber creado.
TRIGGERS_OBLIGATORIOS: dict[str, str] = {
    "trg_bitacora_no_update": "bitacora_auditoria",
    "trg_bitacora_no_delete": "bitacora_auditoria",
    "trg_alertas_tocar_timestamp": "alertas",
    "trg_sesiones_tocar_timestamp": "sesiones_activas",
}


async def _verificar_conexion() -> str:
    """Confirma que PostgreSQL responde. Devuelve la versión."""
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version()"))
        return result.scalar_one()


def _correr_alembic() -> tuple[int, str, str]:
    """Ejecuta `alembic upgrade head` sincrono y devuelve (rc, stdout, stderr)."""
    proceso = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    return proceso.returncode, proceso.stdout, proceso.stderr


async def _verificar_triggers() -> dict[str, bool]:
    """Devuelve dict trigger → existe?."""
    engine = get_engine()
    encontrados: dict[str, bool] = {nombre: False for nombre in TRIGGERS_OBLIGATORIOS}
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT tgname FROM pg_trigger "
                "WHERE NOT tgisinternal AND tgname = ANY(:nombres)"
            ),
            {"nombres": list(TRIGGERS_OBLIGATORIOS.keys())},
        )
        for fila in result:
            encontrados[fila[0]] = True
    return encontrados


async def _contar_tablas() -> int:
    """Cuenta las tablas del esquema público (sanity check)."""
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        )
        return int(result.scalar_one())


async def main() -> int:
    print("DenunciaBot — inicialización de base de datos")
    print("=" * 60)

    # Paso 1
    print("\n[1/3] Verificando conexión a PostgreSQL...")
    try:
        version = await _verificar_conexion()
    except Exception as exc:
        print(f"  ERROR no se pudo conectar: {exc}", file=sys.stderr)
        await dispose_engine()
        return 1
    print(f"  OK  {version[:80]}")
    await dispose_engine()

    # Paso 2
    print("\n[2/3] Aplicando migraciones (alembic upgrade head)...")
    rc, out, err = _correr_alembic()
    if out.strip():
        for linea in out.strip().splitlines():
            print(f"      {linea}")
    if rc != 0:
        print(f"  ERROR alembic falló (rc={rc}):", file=sys.stderr)
        print(err, file=sys.stderr)
        return 1
    print("  OK  migraciones aplicadas")

    # Paso 3
    print("\n[3/3] Verificando triggers de seguridad...")
    encontrados = await _verificar_triggers()
    todos_ok = True
    for nombre, tabla in TRIGGERS_OBLIGATORIOS.items():
        if encontrados[nombre]:
            print(f"  OK    {nombre} (tabla {tabla})")
        else:
            print(f"  FALTA {nombre} (tabla {tabla})", file=sys.stderr)
            todos_ok = False

    tablas = await _contar_tablas()
    print(f"\nTablas en el esquema público: {tablas}")
    await dispose_engine()

    if not todos_ok:
        print(
            "\nERROR  Faltan triggers obligatorios. La migración no se aplicó "
            "completamente — revisar alembic.",
            file=sys.stderr,
        )
        return 2

    print("\nBase de datos inicializada correctamente.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
