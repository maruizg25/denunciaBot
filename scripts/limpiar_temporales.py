#!/usr/bin/env python3
"""
Limpia archivos temporales de evidencias huérfanas.

Borra cualquier archivo en `<EVIDENCIAS_DIR>/tmp/` con `mtime` mayor a la
edad mínima (default 30 min). Estos archivos se generan cuando el webhook
descarga un adjunto de Meta y queda en cola hasta que el ciudadano
confirma la denuncia. Si el ciudadano cancela o la sesión expira sin
persistir, el archivo queda huérfano.

Diseñado para correr periódicamente:
  - Vía cron: `*/30 * * * *  denunciabot  /opt/denunciabot/.venv/bin/python /opt/denunciabot/scripts/limpiar_temporales.py`
  - Vía systemd timer: ver `denunciabot-cleanup.timer` (incluido en repo)

Uso manual:
  python scripts/limpiar_temporales.py                  # default: 30 min
  python scripts/limpiar_temporales.py --minutos 60     # más conservador
  python scripts/limpiar_temporales.py --dry-run        # solo lista, no borra

El script es idempotente: correrlo dos veces seguidas no falla ni duplica
nada — la segunda corrida no encuentra archivos para borrar.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Permite importar el paquete `app` desde scripts/
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Borra archivos huérfanos del directorio de evidencias temporales."
    )
    p.add_argument(
        "--minutos",
        type=int,
        default=30,
        help="Edad mínima en minutos para borrar un archivo (default: 30)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo lista los archivos que se borrarían, sin tocarlos",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Imprime cada archivo procesado",
    )
    return p


def _archivos_huerfanos(tmp_dir: Path, edad_min_seg: float) -> list[Path]:
    """Devuelve la lista de archivos en `tmp_dir` con mtime mayor al umbral."""
    if not tmp_dir.exists():
        return []
    ahora = time.time()
    candidatos: list[Path] = []
    for item in tmp_dir.iterdir():
        if not item.is_file():
            continue
        try:
            edad = ahora - item.stat().st_mtime
        except OSError:
            continue
        if edad >= edad_min_seg:
            candidatos.append(item)
    return candidatos


def main() -> int:
    args = _construir_parser().parse_args()

    # Import tardío para que pydantic-settings cargue solo cuando se ejecuta
    # como script (no al hacer --help).
    from app.config import get_settings
    from app.utils.logger import configurar_logging, obtener_logger

    configurar_logging()
    log = obtener_logger("limpiar_temporales")

    settings = get_settings()
    tmp_dir = Path(settings.EVIDENCIAS_DIR) / "tmp"
    edad_min_seg = args.minutos * 60.0

    huerfanos = _archivos_huerfanos(tmp_dir, edad_min_seg)
    if not huerfanos:
        log.info("temporales_sin_huerfanos", directorio=str(tmp_dir))
        if args.verbose:
            print(f"No hay archivos huérfanos en {tmp_dir}", file=sys.stderr)
        return 0

    total_bytes = 0
    borrados = 0
    errores = 0

    for archivo in huerfanos:
        try:
            tamanio = archivo.stat().st_size
        except OSError:
            tamanio = 0

        if args.dry_run:
            print(f"[DRY-RUN] Borraría: {archivo}  ({tamanio} B)", file=sys.stderr)
            continue

        try:
            archivo.unlink()
            borrados += 1
            total_bytes += tamanio
            if args.verbose:
                print(f"Borrado: {archivo}  ({tamanio} B)", file=sys.stderr)
        except OSError as exc:
            errores += 1
            log.warning(
                "temporal_no_se_pudo_borrar",
                archivo=str(archivo),
                error=str(exc),
            )

    log.info(
        "temporales_limpiados",
        directorio=str(tmp_dir),
        encontrados=len(huerfanos),
        borrados=borrados,
        errores=errores,
        bytes_liberados=total_bytes,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        print(
            f"Borrados {borrados}/{len(huerfanos)} archivos "
            f"({total_bytes:,} bytes liberados, {errores} errores).",
            file=sys.stderr,
        )
    else:
        print(
            f"DRY-RUN: {len(huerfanos)} archivos serían borrados "
            f"({total_bytes:,} bytes).",
            file=sys.stderr,
        )

    return 1 if errores > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
