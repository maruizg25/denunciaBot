"""
Modelo ORM: sesiones_activas — conversaciones en curso (S0..S12).

Nota arquitectónica: la fuente PRIMARIA de las sesiones activas vive en
Redis (con TTL automático para los timeouts de 4 y 5 minutos). Esta tabla
existe como:
  - Respaldo durable: si Redis se reinicia, podemos recuperar sesiones.
  - Pista de auditoría: queda el rastro de cuántas sesiones se abrieron.

El motor de conversación lee/escribe en Redis; al cerrar la sesión
(REGISTRO o cancelación), persiste el snapshot final aquí.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import TIMESTAMP, CheckConstraint, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EstadoSesion(str, enum.Enum):
    """Estados de la máquina conversacional (12 + auxiliares)."""

    S0_INICIO = "S0_INICIO"
    S1_BIENVENIDA = "S1_BIENVENIDA"
    S2_ACEPTACION = "S2_ACEPTACION"
    S3_INSTITUCION = "S3_INSTITUCION"
    S4_DESCRIPCION = "S4_DESCRIPCION"
    S5_FECHA = "S5_FECHA"
    S6_INVOLUCRADOS = "S6_INVOLUCRADOS"
    S7_PERJUICIO = "S7_PERJUICIO"
    S8_DENUNCIA_PREVIA = "S8_DENUNCIA_PREVIA"
    S9_EVIDENCIA = "S9_EVIDENCIA"
    S10_VALIDACION = "S10_VALIDACION"
    S11_REGISTRO = "S11_REGISTRO"
    S12_CIERRE = "S12_CIERRE"

    # Estados auxiliares
    INACTIVIDAD_AVISO = "INACTIVIDAD_AVISO"
    INACTIVIDAD_CIERRE = "INACTIVIDAD_CIERRE"
    CANCELADA = "CANCELADA"


class SesionActiva(Base):
    """Snapshot persistente de una conversación de WhatsApp en curso."""

    __tablename__ = "sesiones_activas"

    telefono_hash: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        doc="SHA-256(pepper || telefono_e164)",
    )

    estado_actual: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        doc="Estado actual de la máquina (ver EstadoSesion)",
    )

    datos_temporales: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
        default=dict,
        doc="Buffer de respuestas parciales antes de persistir la alerta",
    )

    timestamp_inicio: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    timestamp_ultima: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    intentos_estado: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        default=0,
        doc="Reintentos en el estado actual antes de reformular o cancelar",
    )

    # ------------------------------------------------------------------
    # Restricciones e índices
    # ------------------------------------------------------------------
    __table_args__ = (
        CheckConstraint(
            "intentos_estado >= 0",
            name="ck_sesiones_intentos_no_negativos",
        ),
        Index("ix_sesiones_timestamp_ultima", "timestamp_ultima"),
    )

    def __repr__(self) -> str:
        # NO incluir el telefono_hash completo (aunque sea hash, es identificador):
        # solo prefijo + estado para debugging seguro.
        prefijo = self.telefono_hash[:8] if self.telefono_hash else "????????"
        return (
            f"<SesionActiva telefono_hash={prefijo}... "
            f"estado={self.estado_actual!r} "
            f"intentos={self.intentos_estado}>"
        )
