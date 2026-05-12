"""
Modelo ORM: alertas_evidencias — archivos adjuntos a una denuncia.

El binario del archivo NO se guarda en la base. Vive en disco con un
nombre = UUID v4 + extensión genérica; `ruta_almacenamiento` apunta a esa
ruta. El nombre real con el que el ciudadano lo envió se guarda cifrado
en `nombre_original` (Fernet).

El `hash_sha256` se calcula sobre el contenido del archivo y permite:
  - Detectar duplicados subidos en una misma denuncia.
  - Verificar integridad si se mueve el archivo.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.alerta import Alerta


class Evidencia(Base):
    """Archivo adjunto (PDF/JPG/PNG) entregado por el ciudadano."""

    __tablename__ = "alertas_evidencias"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False),
        primary_key=True,
    )

    alerta_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("alertas.id", ondelete="CASCADE"),
        nullable=False,
    )

    nombre_original: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
        doc="Nombre del archivo subido, cifrado con Fernet",
    )

    ruta_almacenamiento: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        doc="Path en disco: <EVIDENCIAS_DIR>/<UUID>.<ext>",
    )

    tipo_mime: Mapped[str] = mapped_column(String(100), nullable=False)
    tamanio_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hash_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="SHA-256 del contenido del archivo (64 hex chars)",
    )

    timestamp_subida: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ------------------------------------------------------------------
    # Relaciones
    # ------------------------------------------------------------------
    alerta: Mapped[Alerta] = relationship(
        "Alerta",
        back_populates="evidencias",
        lazy="joined",
    )

    # ------------------------------------------------------------------
    # Restricciones e índices
    # ------------------------------------------------------------------
    __table_args__ = (
        CheckConstraint(
            "tamanio_bytes > 0",
            name="ck_evidencias_tamanio_positivo",
        ),
        CheckConstraint(
            "tamanio_bytes <= 10485760",  # 10 MB
            name="ck_evidencias_tamanio_maximo",
        ),
        Index("ix_evidencias_alerta_id", "alerta_id"),
        Index("ix_evidencias_hash_sha256", "hash_sha256"),
    )

    def __repr__(self) -> str:
        # NO incluir nombre_original (cifrado) ni la ruta absoluta en repr.
        return (
            f"<Evidencia id={self.id} "
            f"alerta_id={self.alerta_id} "
            f"mime={self.tipo_mime!r} "
            f"tamanio={self.tamanio_bytes}>"
        )
