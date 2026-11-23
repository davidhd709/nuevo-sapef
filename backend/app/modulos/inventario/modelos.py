"""Modelos ORM del módulo de inventario (EP-06)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _usuario_fk() -> Mapped[int | None]:
    return mapped_column(BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True)


class Material(Base):
    __tablename__ = "material"
    __table_args__ = (
        # RN-017: la base garantiza que nunca haya existencias negativas.
        CheckConstraint("existencias >= 0", name="ck_material_existencias_no_negativas"),
        CheckConstraint("existencias_minimas >= 0", name="ck_material_minimas_no_negativas"),
        Index("uq_material_sede_codigo", "sede_id", func.lower(text("codigo")), unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    categoria: Mapped[str] = mapped_column(String(60), nullable=False)
    codigo: Mapped[str] = mapped_column(String(60), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False)
    unidad: Mapped[str] = mapped_column(String(20), nullable=False)
    existencias: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, server_default=text("0")
    )
    existencias_minimas: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, server_default=text("0")
    )
    responsable: Mapped[str | None] = mapped_column(String(160), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    creado_por: Mapped[int | None] = _usuario_fk()
    modificado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    modificado_por: Mapped[int | None] = _usuario_fk()


class MovimientoMaterial(Base):
    """Kárdex: cada entrada, salida o ajuste con las existencias que quedaron."""

    __tablename__ = "movimiento_material"
    __table_args__ = (
        CheckConstraint("tipo IN ('entrada', 'salida', 'ajuste')", name="ck_movimiento_tipo"),
        CheckConstraint("delta <> 0", name="ck_movimiento_delta_no_cero"),
        CheckConstraint("existencias_resultantes >= 0", name="ck_movimiento_resultante"),
        Index("ix_movimiento_material_material", "material_id", "creado_en"),
        Index("ix_movimiento_material_orden", "orden_id"),
        # Idempotencia de la app de campo y de reintentos: un uuid_origen se aplica una vez.
        Index(
            "uq_movimiento_sede_uuid_origen",
            "sede_id",
            "uuid_origen",
            unique=True,
            postgresql_where=text("uuid_origen IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    material_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("material.id", ondelete="RESTRICT"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    delta: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    existencias_resultantes: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    origen: Mapped[str] = mapped_column(String(20), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Sin llave foránea: trabajos depende de inventario, no al revés.
    orden_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uuid_origen: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    ubicacion: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    creado_por: Mapped[int | None] = _usuario_fk()


class CargueBodega(Base):
    """Cargue del estado de la bodega desde Excel (RF-053): todo o nada."""

    __tablename__ = "cargue_bodega"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente', 'completado', 'con_errores')", name="ck_cargue_bodega_estado"
        ),
        Index("ix_cargue_bodega_sede", "sede_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    archivo_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("archivo.id", ondelete="RESTRICT"), nullable=False
    )
    estado: Mapped[str] = mapped_column(
        String(15), nullable=False, server_default=text("'pendiente'")
    )
    filas: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    errores: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    creado_por: Mapped[int | None] = _usuario_fk()
    procesado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
