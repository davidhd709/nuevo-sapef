"""Modelos ORM del módulo de activos y mapa (EP-03)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _ahora() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _modificado() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


def _usuario_fk() -> Mapped[int | None]:
    return mapped_column(BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True)


class Lote(Base):
    __tablename__ = "lote"
    __table_args__ = (
        CheckConstraint("consecutivo_inicial <= consecutivo_final", name="ck_lote_rango"),
        CheckConstraint(
            "cantidad = (consecutivo_final - consecutivo_inicial + 1)", name="ck_lote_cantidad"
        ),
        Index("ix_lote_sede_id", "sede_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    consecutivo_inicial: Mapped[int] = mapped_column(Integer, nullable=False)
    consecutivo_final: Mapped[int] = mapped_column(Integer, nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    tecnologia_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("maestro_valor.id", ondelete="RESTRICT"), nullable=False
    )
    potencia_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("maestro_valor.id", ondelete="RESTRICT"), nullable=False
    )
    marca_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("maestro_valor.id", ondelete="RESTRICT"), nullable=True
    )
    es_rural: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    orden_compra: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fecha_orden_compra: Mapped[date | None] = mapped_column(Date, nullable=True)
    entrada_almacen: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fecha_entrada_almacen: Mapped[date | None] = mapped_column(Date, nullable=True)
    creado_en: Mapped[datetime] = _ahora()
    creado_por: Mapped[int | None] = _usuario_fk()


class Luminaria(Base):
    __tablename__ = "luminaria"
    __table_args__ = (
        UniqueConstraint("sede_id", "codigo", name="uq_luminaria_sede_codigo"),
        # La búsqueda por código no distingue mayúsculas (importadores, app de campo, PQRS).
        Index("ix_luminaria_sede_codigo_lower", "sede_id", func.lower(text("codigo"))),
        Index("ix_luminaria_sede_estado", "sede_id", "estado_id"),
        Index("ix_luminaria_sede_barrio", "sede_id", "barrio_id"),
        Index("ix_luminaria_ubicacion", "ubicacion", postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    codigo: Mapped[str] = mapped_column(String(80), nullable=False)
    codigo_externo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    barrio_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("barrio.id", ondelete="RESTRICT"), nullable=True
    )
    ubicacion: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    estado_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("estado.id", ondelete="RESTRICT"), nullable=False
    )
    tecnologia_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("maestro_valor.id", ondelete="RESTRICT"), nullable=True
    )
    potencia_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("maestro_valor.id", ondelete="RESTRICT"), nullable=True
    )
    marca_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("maestro_valor.id", ondelete="RESTRICT"), nullable=True
    )
    tipo_intervencion_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("maestro_valor.id", ondelete="RESTRICT"), nullable=True
    )
    accion_operativa_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("maestro_valor.id", ondelete="RESTRICT"), nullable=True
    )
    mision_objetivo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("maestro_valor.id", ondelete="RESTRICT"), nullable=True
    )
    lote_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("lote.id", ondelete="SET NULL"), nullable=True
    )
    luminaria_reemplazada_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("luminaria.id", ondelete="SET NULL"), nullable=True
    )
    fecha_instalacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_mision: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_baja: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_disposicion_final: Mapped[date | None] = mapped_column(Date, nullable=True)
    mac: Mapped[str | None] = mapped_column(String(80), nullable=True)
    poste: Mapped[str | None] = mapped_column(String(80), nullable=True)
    longitud_brazo: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    es_rural: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    subnormal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    tiene_medida: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    en_transito: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    validado: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    es_comodin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    responsable: Mapped[str | None] = mapped_column(String(160), nullable=True)
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = _ahora()
    modificado_en: Mapped[datetime] = _modificado()
    creado_por: Mapped[int | None] = _usuario_fk()
    modificado_por: Mapped[int | None] = _usuario_fk()


class LuminariaUbicacion(Base):
    __tablename__ = "luminaria_ubicacion"
    __table_args__ = (Index("ix_luminaria_ubicacion_lum", "luminaria_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    luminaria_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("luminaria.id", ondelete="CASCADE"), nullable=False
    )
    ubicacion_anterior: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    ubicacion_nueva: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    origen: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'web'"))
    cambiado_en: Mapped[datetime] = _ahora()
    cambiado_por: Mapped[int | None] = _usuario_fk()


class EventoActivo(Base):
    __tablename__ = "evento_activo"
    __table_args__ = (Index("ix_evento_activo_lum", "luminaria_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    luminaria_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("luminaria.id", ondelete="CASCADE"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    fecha: Mapped[datetime] = _ahora()
    orden_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pqrs_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    estado_anterior_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("estado.id", ondelete="SET NULL"), nullable=True
    )
    estado_nuevo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("estado.id", ondelete="SET NULL"), nullable=True
    )
    detalle: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    creado_por: Mapped[int | None] = _usuario_fk()
