"""
Modelo ORM: bitacora_auditoria — registro inmutable de eventos.

Esta tabla es INMUTABLE: la migración instaló dos triggers
(`trg_bitacora_no_update`, `trg_bitacora_no_delete`) que lanzan
`RAISE EXCEPTION` ante cualquier UPDATE o DELETE. Por eso este modelo
solo expone INSERT (via `session.add(EventoBitacora(...))`).

El campo `detalle` (JSONB) nunca debe contener datos personales en claro:
nada de teléfono, ni texto de la denuncia, ni nombres de involucrados.
El servicio que escribe la bitácora es responsable de sanitizar.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.alerta import Alerta


class TipoEvento(str, enum.Enum):
    """Catálogo de eventos auditables."""

    SESION_INICIADA = "SESION_INICIADA"
    SESION_CANCELADA = "SESION_CANCELADA"
    SESION_EXPIRADA = "SESION_EXPIRADA"
    MENSAJE_RECIBIDO = "MENSAJE_RECIBIDO"
    MENSAJE_ENVIADO = "MENSAJE_ENVIADO"
    ESTADO_AVANZADO = "ESTADO_AVANZADO"
    VALIDACION_FALLIDA = "VALIDACION_FALLIDA"
    EVIDENCIA_RECIBIDA = "EVIDENCIA_RECIBIDA"
    EVIDENCIA_RECHAZADA = "EVIDENCIA_RECHAZADA"
    ALERTA_CREADA = "ALERTA_CREADA"
    ALERTA_ACTUALIZADA = "ALERTA_ACTUALIZADA"
    NOTIFICACION_ENVIADA = "NOTIFICACION_ENVIADA"
    NOTIFICACION_FALLIDA = "NOTIFICACION_FALLIDA"
    WEBHOOK_FIRMA_INVALIDA = "WEBHOOK_FIRMA_INVALIDA"
    ERROR_INTERNO = "ERROR_INTERNO"


class ActorBitacora(str, enum.Enum):
    """Actores estándar; se permite texto libre para usuarios admin futuros."""

    CIUDADANO = "CIUDADANO"
    SISTEMA = "SISTEMA"
    META_API = "META_API"


class EventoBitacora(Base):
    """Una entrada en la bitácora. INMUTABLE una vez escrita."""

    __tablename__ = "bitacora_auditoria"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False),
        primary_key=True,
    )

    alerta_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("alertas.id", ondelete="SET NULL"),
        nullable=True,
    )

    evento: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Tipo de evento (ver TipoEvento)",
    )

    actor: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Quién originó el evento (CIUDADANO, SISTEMA, META_API, o admin)",
    )

    detalle: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc=(
            "Información estructurada del evento. "
            "PROHIBIDO incluir datos personales en claro."
        ),
    )

    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ------------------------------------------------------------------
    # Relación opcional con la alerta asociada (puede ser NULL).
    # No usamos back_populates="eventos_bitacora" como dependencia fuerte
    # porque la bitácora también registra eventos previos a la alerta.
    # ------------------------------------------------------------------
    alerta: Mapped[Alerta | None] = relationship(
        "Alerta",
        back_populates="eventos_bitacora",
        lazy="noload",
    )

    __table_args__ = (
        Index("ix_bitacora_alerta_id", "alerta_id"),
        Index("ix_bitacora_evento", "evento"),
        Index("ix_bitacora_timestamp", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<EventoBitacora id={self.id} "
            f"evento={self.evento!r} "
            f"actor={self.actor!r} "
            f"ts={self.timestamp.isoformat() if self.timestamp else None!r}>"
        )
