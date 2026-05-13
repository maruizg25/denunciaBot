"""
Métricas Prometheus de DenunciaBot.

Definiciones centralizadas (counters, histograms, gauges) que el resto de
la app importa y actualiza desde los puntos críticos del flujo. El
endpoint `/metrics` (en `app.api.metrics`) las expone en formato OpenMetrics.

Diseño:
  - Todas las métricas tienen prefijo `denunciabot_` para distinguir de
    otras apps en el mismo Prometheus.
  - Las labels se mantienen acotadas: sólo cardinalidades pequeñas
    (estados, tipos de error). NUNCA `telefono_hash` ni datos por-ciudadano
    — explotaría la cardinalidad del storage de Prometheus.
  - Las métricas son monotónicas/incrementales (counters) o instantáneas
    (gauges). Histograms tienen buckets afinados para latencias típicas
    de Meta (sub-segundo a varios segundos).

Uso típico desde el código de la app:

    from app.metrics import WEBHOOK_REQUESTS, WEBHOOK_DURATION

    WEBHOOK_REQUESTS.labels(resultado="ok").inc()
    with WEBHOOK_DURATION.time():
        ...
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


# =========================================================================
# Webhook — actividad de entrada
# =========================================================================

WEBHOOK_REQUESTS = Counter(
    "denunciabot_webhook_requests_total",
    "Total de requests POST al webhook por resultado",
    labelnames=["resultado"],  # ok | firma_invalida | payload_invalido | error
)

WEBHOOK_DURATION = Histogram(
    "denunciabot_webhook_duration_seconds",
    "Tiempo total de procesamiento de un webhook (recepción → respuesta 200)",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

MENSAJES_DUPLICADOS = Counter(
    "denunciabot_mensajes_duplicados_total",
    "Mensajes descartados por idempotency (Meta reintentó un wamid ya procesado)",
)


# =========================================================================
# Motor de conversación — flujo y resultado
# =========================================================================

ESTADO_TRANSICIONES = Counter(
    "denunciabot_estado_transiciones_total",
    "Transiciones de estado del motor",
    labelnames=["desde", "hasta"],
)

VALIDACIONES_FALLIDAS = Counter(
    "denunciabot_validaciones_fallidas_total",
    "Validaciones de input fallidas por estado",
    labelnames=["estado"],
)

SESIONES_CANCELADAS = Counter(
    "denunciabot_sesiones_canceladas_total",
    "Sesiones canceladas por motivo",
    labelnames=["motivo"],  # usuario | agotamiento | timeout | estado_invalido
)


# =========================================================================
# Alertas — éxito y composición
# =========================================================================

ALERTAS_CREADAS = Counter(
    "denunciabot_alertas_creadas_total",
    "Total de alertas registradas exitosamente",
)

ALERTAS_POR_ESTADO = Gauge(
    "denunciabot_alertas_por_estado",
    "Snapshot del conteo de alertas por estado (actualizado periódicamente)",
    labelnames=["estado"],
)

EVIDENCIAS_RECIBIDAS = Counter(
    "denunciabot_evidencias_recibidas_total",
    "Evidencias adjuntas procesadas por resultado",
    labelnames=["resultado"],  # aceptada | rechazada_tipo | rechazada_tamanio | rechazada_antivirus
)


# =========================================================================
# Sesiones — estado actual
# =========================================================================

SESIONES_ACTIVAS = Gauge(
    "denunciabot_sesiones_activas",
    "Sesiones de conversación activas en Redis (snapshot)",
)


# =========================================================================
# Meta API — latencia y errores
# =========================================================================

META_API_DURATION = Histogram(
    "denunciabot_meta_api_duration_seconds",
    "Tiempo de respuesta de Meta API por operación",
    labelnames=["operacion"],  # enviar_texto | enviar_botones | descargar_media | marcar_leido
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

META_API_ERRORES = Counter(
    "denunciabot_meta_api_errores_total",
    "Errores de Meta API por tipo",
    labelnames=["operacion", "tipo"],  # tipo: 4xx_permanente | 5xx_transitorio | timeout | red
)


# =========================================================================
# SMTP — notificaciones al buzón institucional
# =========================================================================

SMTP_ENVIOS = Counter(
    "denunciabot_smtp_envios_total",
    "Total de envíos SMTP por resultado",
    labelnames=["resultado"],  # ok | falla
)


# =========================================================================
# Cierres (mensaje al ciudadano con su código)
# =========================================================================

CIERRES_ENCOLADOS = Counter(
    "denunciabot_cierres_encolados_total",
    "Mensajes de cierre encolados en Dramatiq",
)

CIERRES_ENVIADOS = Counter(
    "denunciabot_cierres_enviados_total",
    "Mensajes de cierre efectivamente entregados al ciudadano",
    labelnames=["resultado"],  # ok | falla
)


# =========================================================================
# BD — operaciones críticas
# =========================================================================

BD_CONEXIONES_FALLAS = Counter(
    "denunciabot_bd_conexiones_fallas_total",
    "Fallas de conexión a la base de datos",
)


# =========================================================================
# Helper: actualizar el gauge de alertas_por_estado de una vez
# =========================================================================

async def actualizar_gauge_alertas_por_estado(db) -> None:
    """Refresca el gauge `denunciabot_alertas_por_estado` con conteos actuales.

    Pensado para llamarse desde un job periódico (cada ~1 min) o desde el
    endpoint /metrics si se quiere actualización on-demand. Hace una sola
    query agregada.
    """
    from sqlalchemy import func, select

    from app.models.alerta import Alerta

    estados_posibles = ("REGISTRADA", "EN_REVISION", "TRAMITADA", "DESCARTADA")

    result = await db.execute(
        select(Alerta.estado, func.count(Alerta.id)).group_by(Alerta.estado)
    )
    conteos: dict[str, int] = {fila[0]: fila[1] for fila in result}

    # Setea TODOS los estados (los que no tienen filas quedan en 0)
    for estado in estados_posibles:
        ALERTAS_POR_ESTADO.labels(estado=estado).set(conteos.get(estado, 0))
