"""
Paquete de modelos ORM de DenunciaBot.

Re-exporta los 4 modelos del esquema y sus enums asociados. Importar todos
los módulos aquí garantiza que `Base.metadata` los conozca antes de cualquier
operación de Alembic o de creación de tablas.

Uso típico:
    from app.models import Alerta, EstadoAlerta, Evidencia
"""

from app.models.alerta import Alerta, EstadoAlerta
from app.models.bitacora import ActorBitacora, EventoBitacora, TipoEvento
from app.models.evidencia import Evidencia
from app.models.sesion import EstadoSesion, SesionActiva

__all__ = [
    # Modelos
    "Alerta",
    "Evidencia",
    "SesionActiva",
    "EventoBitacora",
    # Enums
    "EstadoAlerta",
    "EstadoSesion",
    "TipoEvento",
    "ActorBitacora",
]
