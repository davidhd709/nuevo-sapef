"""Modelos ORM del módulo comercial. Los datos de los cortes viven en Parquet; PostgreSQL guarda
el registro de cada cargue y lo que se edita o audita (hallazgos revisados)."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

ESTADOS_CARGUE = (
    "recibido",
    "validando",
    "con_errores",
    "no_publicable",
    "publicado",
    "reemplazado",
    "eliminado",
)


def _usuario_fk() -> Mapped[int | None]:
    return mapped_column(BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True)


class CargueComercial(Base):
    __tablename__ = "cargue_comercial"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('recibido', 'validando', 'con_errores', 'no_publicable', 'publicado', "
            "'reemplazado', 'eliminado')",
            name="ck_cargue_comercial_estado",
        ),
        CheckConstraint(
            "periodo ~ '^[0-9]{4}(0[1-9]|1[0-2])$'", name="ck_cargue_comercial_periodo"
        ),
        Index("ix_cargue_comercial_corte", "sede_id", "comercializador_id", "periodo", "estado"),
        # Un Idempotency-Key se usa una sola vez por sede.
        Index(
            "uq_cargue_comercial_idempotencia",
            "sede_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        # Un solo corte publicado por sede, comercializador y periodo.
        Index(
            "uq_cargue_comercial_publicado",
            "sede_id",
            "comercializador_id",
            "periodo",
            unique=True,
            postgresql_where=text("estado = 'publicado'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    comercializador_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("comercializador.id", ondelete="RESTRICT"), nullable=False
    )
    periodo: Mapped[str] = mapped_column(String(6), nullable=False)
    estado: Mapped[str] = mapped_column(String(15), nullable=False, server_default="recibido")
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    huella: Mapped[str] = mapped_column(String(64), nullable=False)
    archivos: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    familias: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    advertencias: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    errores: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    completo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    publicable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    version_adaptador: Mapped[str | None] = mapped_column(String(40), nullable=True)
    origen: Mapped[str] = mapped_column(String(15), nullable=False, server_default="cargue")
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    creado_por: Mapped[int | None] = _usuario_fk()
    procesado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    eliminado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    eliminado_por: Mapped[int | None] = _usuario_fk()


class HallazgoComercial(Base):
    """Bitácora de hallazgos de campo y de análisis (E.5): responsable y decisión obligatorios."""

    __tablename__ = "hallazgo_comercial"
    __table_args__ = (
        CheckConstraint("tipo IN ('RUTA', 'ANOMALIA', 'MOVIMIENTO')", name="ck_hallazgo_tipo"),
        CheckConstraint(
            "estado IN ('ABIERTO', 'EN_REVISION', 'RESUELTO')", name="ck_hallazgo_estado"
        ),
        Index("ix_hallazgo_comercial_sede", "sede_id", "comercializador_id", "estado"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    comercializador_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("comercializador.id", ondelete="RESTRICT"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(12), nullable=False)
    estado: Mapped[str] = mapped_column(String(12), nullable=False)
    responsable: Mapped[str] = mapped_column(String(160), nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    identificador: Mapped[str | None] = mapped_column(String(40), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(200), nullable=True)
    periodo: Mapped[str | None] = mapped_column(String(6), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    creado_por: Mapped[int | None] = _usuario_fk()
    modificado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    modificado_por: Mapped[int | None] = _usuario_fk()
