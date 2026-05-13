#!/usr/bin/env python3
"""
Backup automatizado de la base de datos.

Ejecuta `pg_dump -Fc` contra `DATABASE_URL`, escribe el resultado a un
archivo con timestamp dentro del directorio de backups, aplica permisos
0o600 (solo dueño puede leer) y borra dumps con más de N días.

Diseñado para correr a diario vía systemd timer (`denunciabot-backup.timer`).

Uso manual:
  python scripts/backup_db.py
  python scripts/backup_db.py --destino /custom/path --retencion-dias 60
  python scripts/backup_db.py --dry-run

Salida estándar (stderr):
  Mensajes legibles para humanos.
Logs estructurados:
  Eventos JSON (vía structlog) hacia journald.

IMPORTANTE: el dump se guarda EN CLARO — contiene los BYTEA cifrados de
Fernet, pero también la estructura y los metadatos (códigos, timestamps,
hashes de teléfono). Para protección en reposo de los backups, cifrarlos
con GPG antes de moverlos a almacenamiento secundario. Ver RUNBOOK §8.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Permite importar el paquete `app` desde scripts/
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Backup de PostgreSQL con retención automática."
    )
    p.add_argument(
        "--destino",
        type=Path,
        default=None,
        help="Directorio destino de los dumps (default: /var/backups/denunciabot)",
    )
    p.add_argument(
        "--retencion-dias",
        type=int,
        default=30,
        help="Borrar dumps con más de N días (default: 30)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="No genera dump ni borra archivos; solo informa lo que haría",
    )
    return p


def _parsear_database_url(url: str) -> dict[str, str]:
    """Convierte una `postgresql+asyncpg://user:pass@host:port/db` en partes."""
    # pg_dump no entiende el dialecto SQLAlchemy; lo limpiamos.
    if url.startswith("postgresql+asyncpg://"):
        url_pg = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    elif url.startswith("postgres+asyncpg://"):
        url_pg = url.replace("postgres+asyncpg://", "postgresql://", 1)
    else:
        url_pg = url

    parsed = urlparse(url_pg)
    return {
        "user": parsed.username or "",
        "password": parsed.password or "",
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "dbname": (parsed.path or "/").lstrip("/") or "",
    }


def _correr_pg_dump(
    partes: dict[str, str],
    destino_archivo: Path,
    dry_run: bool,
) -> tuple[int, str, int]:
    """Ejecuta pg_dump. Devuelve (returncode, stderr, bytes_escritos)."""
    cmd = [
        "pg_dump",
        "-h", partes["host"],
        "-p", partes["port"],
        "-U", partes["user"],
        "-d", partes["dbname"],
        "-F", "c",       # formato custom (compresión + ágil para restore)
        "-Z", "6",       # nivel de compresión
        "--no-owner",
        "--no-privileges",
        "-f", str(destino_archivo),
    ]

    if dry_run:
        print(f"[DRY-RUN] Ejecutaría: {' '.join(cmd)}", file=sys.stderr)
        return 0, "", 0

    env = os.environ.copy()
    if partes["password"]:
        env["PGPASSWORD"] = partes["password"]

    inicio = time.time()
    proceso = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=3600,  # 1h máximo — para volumen institucional sobra
    )
    duracion = time.time() - inicio

    try:
        bytes_escritos = destino_archivo.stat().st_size
    except OSError:
        bytes_escritos = 0

    print(
        f"  pg_dump terminó en {duracion:.1f}s "
        f"(returncode={proceso.returncode}, {bytes_escritos:,} bytes)",
        file=sys.stderr,
    )
    return proceso.returncode, proceso.stderr, bytes_escritos


def _aplicar_retencion(directorio: Path, dias: int, dry_run: bool) -> int:
    """Borra archivos `.dump` con mtime mayor a `dias`. Devuelve cuántos borró."""
    if dias <= 0 or not directorio.exists():
        return 0
    umbral = time.time() - (dias * 86400)
    borrados = 0
    for archivo in directorio.glob("*.dump"):
        try:
            if archivo.stat().st_mtime < umbral:
                if dry_run:
                    print(f"  [DRY-RUN] Retención: borraría {archivo}", file=sys.stderr)
                else:
                    archivo.unlink()
                    print(f"  Retención: borrado {archivo}", file=sys.stderr)
                borrados += 1
        except OSError as exc:
            print(f"  No se pudo borrar {archivo}: {exc}", file=sys.stderr)
    return borrados


def main() -> int:
    args = _construir_parser().parse_args()

    from app.config import get_settings
    from app.utils.logger import configurar_logging, obtener_logger

    configurar_logging()
    log = obtener_logger("backup_db")

    settings = get_settings()
    destino = args.destino or Path("/var/backups/denunciabot")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    nombre_archivo = f"denunciabot_{timestamp}.dump"

    if args.dry_run:
        print(f"[DRY-RUN] Destino: {destino / nombre_archivo}", file=sys.stderr)
    else:
        # Crear directorio con permisos restrictivos (0o700)
        umask_anterior = os.umask(0o077)
        try:
            destino.mkdir(parents=True, exist_ok=True)
        finally:
            os.umask(umask_anterior)

    ruta_dump = destino / nombre_archivo
    print(f"Iniciando backup → {ruta_dump}", file=sys.stderr)

    partes = _parsear_database_url(settings.DATABASE_URL.get_secret_value())
    rc, stderr, bytes_escritos = _correr_pg_dump(partes, ruta_dump, args.dry_run)

    if rc != 0:
        log.error(
            "backup_falla",
            returncode=rc,
            stderr=stderr[:500],
            destino=str(ruta_dump),
        )
        print(f"ERROR pg_dump falló (rc={rc}):", file=sys.stderr)
        print(stderr, file=sys.stderr)
        # Intentar limpiar el dump parcial
        if not args.dry_run and ruta_dump.exists():
            try:
                ruta_dump.unlink()
            except OSError:
                pass
        return 1

    # Permisos restrictivos en el dump
    if not args.dry_run and ruta_dump.exists():
        try:
            ruta_dump.chmod(0o600)
        except OSError as exc:
            log.warning("backup_chmod_falla", error=str(exc))

    log.info(
        "backup_exitoso",
        archivo=str(ruta_dump),
        bytes=bytes_escritos,
        dry_run=args.dry_run,
    )

    # Retención
    borrados = _aplicar_retencion(destino, args.retencion_dias, args.dry_run)
    log.info(
        "backup_retencion_aplicada",
        dias=args.retencion_dias,
        archivos_borrados=borrados,
        dry_run=args.dry_run,
    )

    print(
        f"OK backup en {ruta_dump} ({bytes_escritos:,} bytes). "
        f"Retención: {borrados} dump(s) antiguos eliminados.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
