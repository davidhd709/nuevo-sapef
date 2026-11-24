"""Modelos ORM del módulo de trabajos (EP-05, ADR-004: orden de trabajo única)."""

import uuid
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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _usuario_fk() -> Mapped[int | None]:
    return mapped_column(BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True)


class Cuadrilla(Base):
    __tablename__ = "cuadrilla"
    __table_args__ = (
        Index("uq_cuadrilla_sede_nombre", "sede_id", func.lower(text("nombre")), unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    modificado_por: Mapped[int | None] = _usuario_fk()

    tecnicos: Mapped[list["CuadrillaTecnico"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )


class CuadrillaTecnico(Base):
    __tablename__ = "cuadrilla_tecnico"
    __table_args__ = (Index("ix_cuadrilla_tecnico_usuario", "usuario_id"),)

    cuadrilla_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cuadrilla.id", ondelete="CASCADE"), primary_key=True
    )
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True
    )


class OrdenTrabajo(Base):
    __tablename__ = "orden_trabajo"
    __table_args__ = (
        UniqueConstraint("sede_id", "numero", name="uq_orden_sede_numero"),
        CheckConstraint(
            "tipo IN ('mantenimiento', 'modernizacion', 'expansion', 'reubicacion')",
            name="ck_orden_tipo",
        ),
        CheckConstraint("prioridad BETWEEN 0 AND 3", name="ck_orden_prioridad"),
        CheckConstraint("origen IN ('web', 'cargue', 'campo')", name="ck_orden_origen"),
        Index("ix_orden_sede_estado", "sede_id", "estado_id"),
        Index("ix_orden_sede_creado", "sede_id", "creado_en"),
        Index("ix_orden_tecnico", "tecnico_id"),
        Index("ix_orden_pqrs", "pqrs_id"),
        # Idempotencia de la app de campo (Fase 3): un mismo uuid se aplica una sola vez.
        Index(
            "uq_orden_sede_uuid_origen",
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
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    estado_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("estado.id", ondelete="RESTRICT"), nullable=False
    )
    prioridad: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("2"))
    pqrs_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pqrs.id", ondelete="RESTRICT"), nullable=True
    )
    tecnico_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="RESTRICT"), nullable=True
    )
    cuadrilla_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cuadrilla.id", ondelete="RESTRICT"), nullable=True
    )
    fecha_programada: Mapped[date | None] = mapped_column(Date, nullable=True)
    asignada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_ejecucion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ubicacion: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    motivo_anulacion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    origen: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'web'"))
    cargue_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cargue_masivo.id", ondelete="SET NULL"), nullable=True
    )
    uuid_origen: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    creado_por: Mapped[int | None] = _usuario_fk()
    modificado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    modificado_por: Mapped[int | None] = _usuario_fk()

    luminarias: Mapped[list["OrdenLuminaria"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="OrdenLuminaria.id"
    )
    mantenimiento: Mapped["OrdenMantenimiento | None"] = relationship(
        lazy="selectin", cascade="all, delete-orphan", uselist=False
    )
    instalacion: Mapped["OrdenInstalacion | None"] = relationship(
        lazy="selectin", cascade="all, delete-orphan", uselist=False
    )


class OrdenAsignacion(Base):
    """Historial de asignaciones: permite avisar a la app de campo qué órdenes se le retiraron
    a un técnico (anuladas o reasignadas) mientras estaba sin señal."""

    __tablename__ = "orden_asignacion"
    __table_args__ = (
        Index("ix_orden_asignacion_orden", "orden_id"),
        Index("ix_orden_asignacion_tecnico", "tecnico_id"),
        Index("ix_orden_asignacion_cuadrilla", "cuadrilla_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    orden_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orden_trabajo.id", ondelete="CASCADE"), nullable=False
    )
    tecnico_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="CASCADE"), nullable=True
    )
    cuadrilla_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cuadrilla.id", ondelete="CASCADE"), nullable=True
    )
    asignada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    asignada_por: Mapped[int | None] = _usuario_fk()


class OrdenLuminaria(Base):
    __tablename__ = "orden_luminaria"
    __table_args__ = (
        UniqueConstraint("orden_id", "luminaria_id", "rol", name="uq_orden_luminaria_rol"),
        CheckConstraint(
            "rol IN ('intervenida', 'instalada', 'desmontada')", name="ck_orden_luminaria_rol"
        ),
        Index("ix_orden_luminaria_luminaria", "luminaria_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    orden_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orden_trabajo.id", ondelete="CASCADE"), nullable=False
    )
    luminaria_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("luminaria.id", ondelete="RESTRICT"), nullable=False
    )
    rol: Mapped[str] = mapped_column(String(12), nullable=False)


class OrdenMantenimiento(Base):
    """Detalle del cierre de un mantenimiento (RF-030), con el checklist de 12 componentes."""

    __tablename__ = "orden_mantenimiento"

    orden_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orden_trabajo.id", ondelete="CASCADE"), primary_key=True
    )
    sitio_arreglo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quien_recibe: Mapped[str | None] = mapped_column(String(160), nullable=True)
    observacion_tecnica: Mapped[str | None] = mapped_column(Text, nullable=True)
    requiere_desmonte: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    causal_desmonte: Mapped[str | None] = mapped_column(String(255), nullable=True)
    luminaria_reemplazo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("luminaria.id", ondelete="RESTRICT"), nullable=True
    )
    destino_desmontada: Mapped[str | None] = mapped_column(String(10), nullable=True)
    componentes: Mapped[dict[str, bool]] = mapped_column(JSONB, nullable=False)


class OrdenInstalacion(Base):
    """Detalle del cierre de expansión, modernización o reubicación (RF-032 a RF-034)."""

    __tablename__ = "orden_instalacion"

    orden_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orden_trabajo.id", ondelete="CASCADE"), primary_key=True
    )
    # Tipo de expansión (complementaria, prioritaria, vegetativa) o de modernización.
    tipo_valor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("maestro_valor.id", ondelete="RESTRICT"), nullable=True
    )
    barrio_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("barrio.id", ondelete="RESTRICT"), nullable=True
    )
    marca_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("maestro_valor.id", ondelete="RESTRICT"), nullable=True
    )
    poste: Mapped[str | None] = mapped_column(String(80), nullable=True)
    longitud_brazo: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(255), nullable=True)
    novedades: Mapped[str | None] = mapped_column(Text, nullable=True)
    destino_desmontada: Mapped[str | None] = mapped_column(String(10), nullable=True)
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)


class CargueMasivo(Base):
    """Cargue de órdenes ya ejecutadas desde Excel: se valida todo y se aplica todo o nada."""

    __tablename__ = "cargue_masivo"
    __table_args__ = (
        CheckConstraint(
            "tipo IN ('expansion', 'modernizacion', 'reubicacion')", name="ck_cargue_masivo_tipo"
        ),
        CheckConstraint(
            "estado IN ('pendiente', 'completado', 'con_errores')", name="ck_cargue_masivo_estado"
        ),
        Index("ix_cargue_masivo_sede", "sede_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    archivo_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("archivo.id", ondelete="RESTRICT"), nullable=False
    )
    estado: Mapped[str] = mapped_column(
        String(15), nullable=False, server_default=text("'pendiente'")
    )
    filas: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    ordenes_creadas: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    errores: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    creado_por: Mapped[int | None] = _usuario_fk()
    procesado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
