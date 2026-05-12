"""crea esquema inicial de DenunciaBot

Esta migración construye las 4 tablas del MVP y los triggers de seguridad:

    1. alertas                 — denuncias registradas; campos sensibles en BYTEA cifrado.
    2. alertas_evidencias      — archivos adjuntos por denuncia.
    3. sesiones_activas        — conversaciones en curso (S0..S12).
    4. bitacora_auditoria      — registro inmutable de eventos (trigger bloquea UPDATE/DELETE).

Notas de diseño:
    - El cifrado de campos sensibles se hace en la aplicación con Fernet, no con
      pgcrypto. La base solo guarda BYTEA opaco; la clave nunca llega al servidor.
    - Los PK usan IDENTITY (SQL:2003) en lugar de SERIAL, que está siendo
      desplazado por el equipo de PostgreSQL.
    - Todos los timestamps son TIMESTAMPTZ (con zona) y se guardan en UTC.

Revision ID: 0001_inicial
Revises:
Create Date: 2026-05-11
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Identificadores de Alembic
revision: str = "0001_inicial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # =========================================================================
    # 1. Tabla: alertas
    # =========================================================================
    op.create_table(
        "alertas",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column(
            "codigo_publico",
            sa.String(20),
            nullable=False,
            unique=True,
            comment="Formato ALR-YYYY-XXXXXX, alfanumérico sin caracteres ambiguos",
        ),
        sa.Column(
            "telefono_hash",
            sa.String(64),
            nullable=False,
            comment="SHA-256(pepper || telefono_e164) — el número en claro NUNCA se persiste",
        ),
        sa.Column(
            "institucion_denunciada",
            sa.LargeBinary,
            nullable=False,
            comment="Cifrado con Fernet en la aplicación",
        ),
        sa.Column(
            "descripcion_hechos",
            sa.LargeBinary,
            nullable=False,
            comment="Cifrado con Fernet en la aplicación",
        ),
        sa.Column("fecha_aproximada", sa.String(50), nullable=True),
        sa.Column(
            "personas_involucradas",
            sa.LargeBinary,
            nullable=True,
            comment="Cifrado con Fernet en la aplicación (opcional)",
        ),
        sa.Column("perjuicio_economico", sa.String(100), nullable=True),
        sa.Column("denuncia_previa_otra", sa.Text, nullable=True),
        sa.Column(
            "estado",
            sa.String(30),
            nullable=False,
            server_default="REGISTRADA",
        ),
        sa.Column(
            "timestamp_registro",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "timestamp_actualizacion",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "estado IN ('REGISTRADA','EN_REVISION','TRAMITADA','DESCARTADA')",
            name="ck_alertas_estado_valido",
        ),
        comment="Denuncias recibidas. Campos sensibles cifrados con Fernet en la app.",
    )
    op.create_index("ix_alertas_telefono_hash", "alertas", ["telefono_hash"])
    op.create_index("ix_alertas_estado", "alertas", ["estado"])
    op.create_index(
        "ix_alertas_timestamp_registro", "alertas", ["timestamp_registro"]
    )

    # =========================================================================
    # 2. Tabla: alertas_evidencias
    # =========================================================================
    op.create_table(
        "alertas_evidencias",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column(
            "alerta_id",
            sa.BigInteger,
            sa.ForeignKey("alertas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "nombre_original",
            sa.LargeBinary,
            nullable=False,
            comment="Cifrado con Fernet — el nombre real del archivo subido",
        ),
        sa.Column(
            "ruta_almacenamiento",
            sa.String(500),
            nullable=False,
            comment="Path en disco; nombre = UUID v4 + extensión genérica",
        ),
        sa.Column("tipo_mime", sa.String(100), nullable=False),
        sa.Column("tamanio_bytes", sa.BigInteger, nullable=False),
        sa.Column(
            "hash_sha256",
            sa.String(64),
            nullable=False,
            comment="SHA-256 del contenido del archivo, para detección de duplicados e integridad",
        ),
        sa.Column(
            "timestamp_subida",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "tamanio_bytes > 0", name="ck_evidencias_tamanio_positivo"
        ),
        sa.CheckConstraint(
            "tamanio_bytes <= 10485760",  # 10 MB
            name="ck_evidencias_tamanio_maximo",
        ),
        comment="Archivos adjuntos por denuncia. El contenido vive en disco.",
    )
    op.create_index(
        "ix_evidencias_alerta_id", "alertas_evidencias", ["alerta_id"]
    )
    op.create_index(
        "ix_evidencias_hash_sha256", "alertas_evidencias", ["hash_sha256"]
    )

    # =========================================================================
    # 3. Tabla: sesiones_activas
    # =========================================================================
    op.create_table(
        "sesiones_activas",
        sa.Column(
            "telefono_hash",
            sa.String(64),
            primary_key=True,
            comment="SHA-256(pepper || telefono_e164)",
        ),
        sa.Column(
            "estado_actual",
            sa.String(30),
            nullable=False,
            comment="Estado de la máquina S0..S12",
        ),
        sa.Column(
            "datos_temporales",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Buffer de respuestas parciales antes de persistir la alerta",
        ),
        sa.Column(
            "timestamp_inicio",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "timestamp_ultima",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "intentos_estado",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.CheckConstraint(
            "intentos_estado >= 0", name="ck_sesiones_intentos_no_negativos"
        ),
        comment=(
            "Sesiones de conversación en curso. Nota: aunque Redis es la fuente "
            "primaria por TTL, esta tabla queda como respaldo y para auditoría."
        ),
    )
    op.create_index(
        "ix_sesiones_timestamp_ultima",
        "sesiones_activas",
        ["timestamp_ultima"],
    )

    # =========================================================================
    # 4. Tabla: bitacora_auditoria (INMUTABLE)
    # =========================================================================
    op.create_table(
        "bitacora_auditoria",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column(
            "alerta_id",
            sa.BigInteger,
            sa.ForeignKey("alertas.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "evento",
            sa.String(50),
            nullable=False,
            comment="Tipo de evento: ALERTA_CREADA, SESION_INICIADA, MENSAJE_RECIBIDO, etc.",
        ),
        sa.Column(
            "actor",
            sa.String(100),
            nullable=False,
            comment="Quién originó el evento: 'CIUDADANO', 'SISTEMA', usuario admin, etc.",
        ),
        sa.Column(
            "detalle",
            postgresql.JSONB,
            nullable=True,
            comment="Detalle estructurado del evento. NUNCA debe contener datos personales en claro.",
        ),
        sa.Column(
            "timestamp",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        comment="Bitácora inmutable de auditoría. UPDATE y DELETE bloqueados por trigger.",
    )
    op.create_index("ix_bitacora_alerta_id", "bitacora_auditoria", ["alerta_id"])
    op.create_index("ix_bitacora_evento", "bitacora_auditoria", ["evento"])
    op.create_index("ix_bitacora_timestamp", "bitacora_auditoria", ["timestamp"])

    # =========================================================================
    # Función + triggers: bitácora inmutable
    # Bloquea cualquier UPDATE o DELETE — solo INSERT permitido.
    # =========================================================================
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_bitacora_bloquear_modificacion()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'La tabla bitacora_auditoria es inmutable: operación % no permitida',
                TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_bitacora_no_update
            BEFORE UPDATE ON bitacora_auditoria
            FOR EACH ROW
            EXECUTE FUNCTION fn_bitacora_bloquear_modificacion();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_bitacora_no_delete
            BEFORE DELETE ON bitacora_auditoria
            FOR EACH ROW
            EXECUTE FUNCTION fn_bitacora_bloquear_modificacion();
        """
    )

    # =========================================================================
    # Función + trigger: actualización automática de timestamp_actualizacion
    # =========================================================================
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_alertas_tocar_timestamp()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.timestamp_actualizacion = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_alertas_tocar_timestamp
            BEFORE UPDATE ON alertas
            FOR EACH ROW
            EXECUTE FUNCTION fn_alertas_tocar_timestamp();
        """
    )

    # =========================================================================
    # Función + trigger: actualización automática de timestamp_ultima en sesiones
    # =========================================================================
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_sesiones_tocar_timestamp()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.timestamp_ultima = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sesiones_tocar_timestamp
            BEFORE UPDATE ON sesiones_activas
            FOR EACH ROW
            EXECUTE FUNCTION fn_sesiones_tocar_timestamp();
        """
    )


def downgrade() -> None:
    # Orden inverso: primero triggers/funciones, después tablas (las FKs caen con las tablas).
    op.execute("DROP TRIGGER IF EXISTS trg_sesiones_tocar_timestamp ON sesiones_activas;")
    op.execute("DROP TRIGGER IF EXISTS trg_alertas_tocar_timestamp ON alertas;")
    op.execute("DROP TRIGGER IF EXISTS trg_bitacora_no_delete ON bitacora_auditoria;")
    op.execute("DROP TRIGGER IF EXISTS trg_bitacora_no_update ON bitacora_auditoria;")
    op.execute("DROP FUNCTION IF EXISTS fn_sesiones_tocar_timestamp();")
    op.execute("DROP FUNCTION IF EXISTS fn_alertas_tocar_timestamp();")
    op.execute("DROP FUNCTION IF EXISTS fn_bitacora_bloquear_modificacion();")

    op.drop_table("bitacora_auditoria")
    op.drop_table("sesiones_activas")
    op.drop_table("alertas_evidencias")
    op.drop_table("alertas")
