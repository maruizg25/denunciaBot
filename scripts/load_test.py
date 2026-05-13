#!/usr/bin/env python3
"""
Test de carga / smoke test contra un DenunciaBot ya levantado.

Hace dos tipos de prueba en paralelo:

  1. Webhooks de WhatsApp simulados con firma HMAC válida.
  2. Consultas GET al endpoint público /alerta/{codigo}.

Reporta latencias p50/p95/p99, throughput total, conteo de errores.
Pensado para detectar:
  - Deadlocks bajo concurrencia.
  - Memory leaks (correr `ps` antes/después para comparar RSS).
  - Saturación de pool de conexiones a BD.
  - Comportamiento del rate limiter.

ATENCIÓN:
  - NO usar contra la BD de producción — los webhooks crean sesiones reales.
  - Usar en el entorno local (`make up`) o un staging dedicado.
  - El `--meta-app-secret` debe coincidir con el del bot que se está
    probando (default = 'test-app-secret' del entorno de desarrollo).

Ejemplos:
  python scripts/load_test.py --webhooks 100 --consultas 100 --concurrencia 20
  python scripts/load_test.py --webhooks 1000 --concurrencia 50 --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import secrets
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field

try:
    import httpx
except ImportError:
    print(
        "ERROR  httpx no está instalado. "
        "Corre `pip install -r requirements.txt` antes.",
        file=sys.stderr,
    )
    sys.exit(1)


# =========================================================================
# Configuración por línea de comandos
# =========================================================================

def _construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Test de carga contra un DenunciaBot local.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="URL base del bot a probar (default: http://127.0.0.1:8000)",
    )
    p.add_argument(
        "--webhooks",
        type=int,
        default=100,
        help="Cantidad total de webhooks a enviar (default: 100)",
    )
    p.add_argument(
        "--consultas",
        type=int,
        default=100,
        help="Cantidad total de consultas GET /alerta a enviar (default: 100)",
    )
    p.add_argument(
        "--concurrencia",
        type=int,
        default=20,
        help="Requests concurrentes (default: 20)",
    )
    p.add_argument(
        "--meta-app-secret",
        default="test-app-secret",
        help="App secret de Meta para firmar webhooks (default: test-app-secret)",
    )
    p.add_argument(
        "--codigo",
        default="ALR-2026-AAAAAA",
        help="Código a usar en las consultas (default: ALR-2026-AAAAAA)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout por request en segundos (default: 30)",
    )
    return p


# =========================================================================
# Generadores de tráfico
# =========================================================================

def _firmar_meta(cuerpo: bytes, secret: str) -> str:
    """Calcula el header X-Hub-Signature-256 como lo haría Meta."""
    mac = hmac.new(secret.encode(), cuerpo, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def _construir_payload(telefono: str, texto: str) -> dict:
    """Construye un payload de webhook como el que envía WhatsApp Cloud API."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-loadtest",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "+593000000000",
                                "phone_number_id": "loadtest",
                            },
                            "contacts": [
                                {"wa_id": telefono, "profile": {"name": "LoadTest"}}
                            ],
                            "messages": [
                                {
                                    "from": telefono,
                                    "id": f"wamid.{uuid.uuid4().hex}",
                                    "timestamp": str(int(time.time())),
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


# =========================================================================
# Métricas en memoria
# =========================================================================

@dataclass
class Estadisticas:
    nombre: str
    latencias_ms: list[float] = field(default_factory=list)
    status_counts: dict[int, int] = field(default_factory=dict)
    errores_red: int = 0

    def registrar_exito(self, latencia_ms: float, status: int) -> None:
        self.latencias_ms.append(latencia_ms)
        self.status_counts[status] = self.status_counts.get(status, 0) + 1

    def registrar_error_red(self) -> None:
        self.errores_red += 1

    @property
    def total(self) -> int:
        return len(self.latencias_ms) + self.errores_red

    def reporte(self) -> str:
        if not self.latencias_ms:
            return f"\n=== {self.nombre} ===\n  Sin respuestas exitosas. Errores de red: {self.errores_red}"

        ordenadas = sorted(self.latencias_ms)
        p50 = statistics.median(ordenadas)
        p95 = ordenadas[int(len(ordenadas) * 0.95)] if len(ordenadas) > 1 else ordenadas[0]
        p99 = ordenadas[int(len(ordenadas) * 0.99)] if len(ordenadas) > 1 else ordenadas[0]
        promedio = statistics.mean(ordenadas)

        lineas = [
            f"\n=== {self.nombre} ===",
            f"  Total enviados:      {self.total}",
            f"  Respuestas válidas:  {len(self.latencias_ms)}",
            f"  Errores de red:      {self.errores_red}",
            f"  Latencia (ms):",
            f"    mín  = {min(ordenadas):.1f}",
            f"    p50  = {p50:.1f}",
            f"    p95  = {p95:.1f}",
            f"    p99  = {p99:.1f}",
            f"    máx  = {max(ordenadas):.1f}",
            f"    prom = {promedio:.1f}",
            f"  Status codes:",
        ]
        for status, count in sorted(self.status_counts.items()):
            lineas.append(f"    {status}: {count}")
        return "\n".join(lineas)


# =========================================================================
# Workers
# =========================================================================

async def _worker_webhook(
    cliente: httpx.AsyncClient,
    base_url: str,
    secret: str,
    stats: Estadisticas,
    sem: asyncio.Semaphore,
    indice: int,
) -> None:
    """Envía UN webhook simulado."""
    telefono = f"593{900000000 + indice}"
    cuerpo = json.dumps(_construir_payload(telefono, "hola")).encode()
    firma = _firmar_meta(cuerpo, secret)

    async with sem:
        inicio = time.perf_counter()
        try:
            r = await cliente.post(
                f"{base_url}/webhook",
                content=cuerpo,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": firma,
                },
            )
            latencia = (time.perf_counter() - inicio) * 1000
            stats.registrar_exito(latencia, r.status_code)
        except httpx.HTTPError:
            stats.registrar_error_red()


async def _worker_consulta(
    cliente: httpx.AsyncClient,
    base_url: str,
    codigo: str,
    stats: Estadisticas,
    sem: asyncio.Semaphore,
) -> None:
    """Hace UNA consulta GET /alerta/{codigo}."""
    async with sem:
        inicio = time.perf_counter()
        try:
            r = await cliente.get(f"{base_url}/alerta/{codigo}")
            latencia = (time.perf_counter() - inicio) * 1000
            stats.registrar_exito(latencia, r.status_code)
        except httpx.HTTPError:
            stats.registrar_error_red()


# =========================================================================
# Orquestación
# =========================================================================

async def _correr_loadtest(args) -> int:
    sem = asyncio.Semaphore(args.concurrencia)

    print(f"\nIniciando load test contra {args.base_url}", file=sys.stderr)
    print(
        f"  webhooks={args.webhooks}  consultas={args.consultas}  "
        f"concurrencia={args.concurrencia}  timeout={args.timeout}s",
        file=sys.stderr,
    )

    stats_webhook = Estadisticas("Webhooks POST /webhook")
    stats_consulta = Estadisticas("Consultas GET /alerta/{codigo}")

    inicio = time.perf_counter()
    async with httpx.AsyncClient(timeout=args.timeout) as cliente:
        tareas: list[asyncio.Task] = []

        for i in range(args.webhooks):
            tareas.append(
                asyncio.create_task(
                    _worker_webhook(
                        cliente, args.base_url, args.meta_app_secret,
                        stats_webhook, sem, i,
                    )
                )
            )
        for _ in range(args.consultas):
            tareas.append(
                asyncio.create_task(
                    _worker_consulta(cliente, args.base_url, args.codigo, stats_consulta, sem)
                )
            )

        # Reportar progreso cada segundo
        total = len(tareas)
        while tareas:
            done, pendientes = await asyncio.wait(tareas, timeout=1.0)
            tareas = list(pendientes)
            terminadas = total - len(tareas)
            print(
                f"  ... {terminadas}/{total} requests terminadas",
                file=sys.stderr,
                flush=True,
            )

    duracion = time.perf_counter() - inicio

    print(stats_webhook.reporte())
    print(stats_consulta.reporte())
    print(f"\n=== Resumen global ===")
    total_requests = stats_webhook.total + stats_consulta.total
    rps = total_requests / duracion if duracion > 0 else 0
    print(f"  Duración total:        {duracion:.2f}s")
    print(f"  Throughput:            {rps:.1f} req/s")
    print(f"  Total errores red:     {stats_webhook.errores_red + stats_consulta.errores_red}")

    # Códigos de salida útiles para CI
    if stats_webhook.errores_red > 0 or stats_consulta.errores_red > 0:
        return 1
    return 0


def main() -> int:
    args = _construir_parser().parse_args()
    return asyncio.run(_correr_loadtest(args))


if __name__ == "__main__":
    sys.exit(main())
