"""
Modelo ORM: alertas — denuncias registradas.

Campos sensibles (institucion_denunciada, descripcion_hechos,
personas_involucradas) viajan como `bytes` ya cifrados con Fernet desde
la capa de servicio. El modelo NO cifra ni descifra: ese trabajo vive
en `app.core.security`. Esta separación mantiene el modelo agnóstico y
fácil de testear.

NUNCA agregar el `telefono_hash` ni los campos cifrados al `__repr__`
ni a logs derivados de este objeto.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    Identity,
    Index,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.bitacora import EventoBitacora
    from app.models.evidencia import Evidencia


class EstadoAlerta(str, enum.Enum):
    """Estados de ciclo de vida de una alerta (denuncia)."""

    REGISTRADA = "REGISTRADA"
    EN_REVISION = "EN_REVISION"
    TRAMITADA = "TRAMITADA"
    DESCARTADA = "DESCARTADA"


class Alerta(Base):
    """Denuncia ciudadana registrada por el bot."""

    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False),
        primary_key=True,
    )

    codigo_publico: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
        doc="Formato ALR-YYYY-XXXXXX, alfanumérico sin caracteres ambiguos",
    )

    telefono_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="SHA-256(pepper || telefono_e164) — el número en claro nunca se almacena",
    )

    # Campos cifrados con Fernet — el modelo solo los pasa, no los interpreta
    institucion_denunciada: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    descripcion_hechos: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    personas_involucradas: Mapped[bytes | None] = mapped_column(LargeBinary)

    # Campos no sensibles
    fecha_aproximada: Mapped[str | None] = mapped_column(String(50))
    perjuicio_economico: Mapped[str | None] = mapped_column(String(100))
    denuncia_previa_otra: Mapped[str | None] = mapped_column(Text)

    estado: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=EstadoAlerta.REGISTRADA.value,
        default=EstadoAlerta.REGISTRADA.value,
    )

    timestamp_registro: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    timestamp_actualizacion: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ------------------------------------------------------------------
    # Relaciones
    # ------------------------------------------------------------------
    evidencias: Mapped[list[Evidencia]] = relationship(
        "Evidencia",
        back_populates="alerta",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    eventos_bitacora: Mapped[list[EventoBitacora]] = relationship(
        "EventoBitacora",
        back_populates="alerta",
        lazy="noload",  # La bitácora no se carga automáticamente al traer alertas
    )

    # ------------------------------------------------------------------
    # Restricciones e índices declarativos
    # (la migración ya los crea; aquí quedan declarados para futura coherencia
    #  y para que `alembic revision --autogenerate` no los marque como diff).
    # ------------------------------------------------------------------
    __table_args__ = (
        CheckConstraint(
            "estado IN ('REGISTRADA','EN_REVISION','TRAMITADA','DESCARTADA')",
            name="ck_alertas_estado_valido",
        ),
        Index("ix_alertas_telefono_hash", "telefono_hash"),
        Index("ix_alertas_estado", "estado"),
        Index("ix_alertas_timestamp_registro", "timestamp_registro"),
    )

    def __repr__(self) -> str:
        # NO incluir campos sensibles ni el telefono_hash en repr.
        return (
            f"<Alerta id={self.id} "
            f"codigo={self.codigo_publico!r} "
            f"estado={self.estado!r}>"
        )
