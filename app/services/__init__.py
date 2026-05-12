"""
Paquete `app.services` — orquestación de I/O y persistencia.

Cada submódulo encapsula un dominio:
  - `sesion_service`        → Redis (CRUD de sesiones activas).
  - `alerta_service`        → registra una denuncia completa con sus evidencias.
  - `evidencia_service`     → guarda archivos en disco + ClamAV + metadata BD.
  - `notificacion_service`  → actor Dramatiq que envía SMTP al buzón institucional.

Los services SÍ tocan I/O (BD, Redis, SMTP, disco, ClamAV). El motor de
conversación NO depende de ellos — son ellos quienes consumen el motor.
"""

from app.services.alerta_service import (
    ColisionCodigoError,
    registrar_denuncia,
)
from app.services.evidencia_service import (
    ClamAVError,
    escanear_con_clamav,
    persistir_evidencia,
)
from app.services.notificacion_service import (
    configurar_broker_dramatiq,
    enviar_notificacion_alerta,
)
from app.services.orquestador import ejecutar as ejecutar_acciones
from app.services.sesion_service import (
    cerrar_redis,
    eliminar_sesion,
    get_redis,
    guardar_sesion,
    obtener_sesion,
    renovar_ttl,
    ttl_restante,
)

__all__ = [
    # Sesiones (Redis)
    "obtener_sesion",
    "guardar_sesion",
    "eliminar_sesion",
    "renovar_ttl",
    "ttl_restante",
    "get_redis",
    "cerrar_redis",
    # Alertas
    "registrar_denuncia",
    "ColisionCodigoError",
    # Evidencias
    "persistir_evidencia",
    "escanear_con_clamav",
    "ClamAVError",
    # Notificaciones
    "enviar_notificacion_alerta",
    "configurar_broker_dramatiq",
    # Orquestador
    "ejecutar_acciones",
]
