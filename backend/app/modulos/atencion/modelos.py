"""Modelos ORM del módulo de atención (EP-04)."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _usuario_fk() -> Mapped[int | None]:
    return mapped_column(BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True)


class Ciudadano(Base):
    """Solicitante reutilizable entre PQRS (en SAPEF se copiaba en cada una)."""

    __tablename__ = "ciudadano"
    __table_args__ = (
        UniqueConstraint("sede_id", "identificacion", name="uq_ciudadano_sede_identificacion"),
        # Búsqueda en el servidor sin tildes ni mayúsculas (pg_trgm + unaccent inmutable).
        Index(
            "ix_ciudadano_nombre_trgm",
            text("sapef_unaccent(lower(nombre_completo)) gin_trgm_ops"),
            postgresql_using="gin",
        ),
        Index("ix_ciudadano_sede", "sede_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    identificacion: Mapped[str] = mapped_column(String(40), nullable=False)
    nombre_completo: Mapped[str] = mapped_column(String(180), nullable=False)
    barrio_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("barrio.id", ondelete="SET NULL"), nullable=True
    )
    sector: Mapped[str | None] = mapped_column(String(120), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    celular: Mapped[str | None] = mapped_column(String(40), nullable=True)
    correo: Mapped[str | None] = mapped_column(String(180), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    creado_por: Mapped[int | None] = _usuario_fk()
    modificado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    modificado_por: Mapped[int | None] = _usuario_fk()


class Pqrs(Base):
    __tablename__ = "pqrs"
    __table_args__ = (
        UniqueConstraint("sede_id", "numero", name="uq_pqrs_sede_numero"),
        CheckConstraint("prioridad BETWEEN 0 AND 3", name="ck_pqrs_prioridad"),
        Index("ix_pqrs_sede_fecha", "sede_id", "fecha_solicitud"),
        Index("ix_pqrs_ciudadano", "ciudadano_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    canal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("maestro_valor.id", ondelete="RESTRICT"), nullable=False
    )
    fecha_solicitud: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ciudadano_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ciudadano.id", ondelete="RESTRICT"), nullable=True
    )
    observacion_solicitante: Mapped[str | None] = mapped_column(Text, nullable=True)
    observacion_interna: Mapped[str | None] = mapped_column(Text, nullable=True)
    prioridad: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("2"))
    estado_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("estado.id", ondelete="RESTRICT"), nullable=False
    )
    calidad_servicio: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fecha_cierre: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notificar_cliente: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    motivo_anulacion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    creado_por: Mapped[int | None] = _usuario_fk()
    modificado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    modificado_por: Mapped[int | None] = _usuario_fk()

    luminarias: Mapped[list["PqrsLuminaria"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="PqrsLuminaria.id"
    )


class PqrsLuminaria(Base):
    """Una fila por luminaria reportada: cada una se repara y cierra por separado (RN-010)."""

    __tablename__ = "pqrs_luminaria"
    __table_args__ = (
        UniqueConstraint("pqrs_id", "luminaria_id", name="uq_pqrs_luminaria"),
        Index("ix_pqrs_luminaria_luminaria", "luminaria_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    pqrs_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pqrs.id", ondelete="CASCADE"), nullable=False
    )
    luminaria_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("luminaria.id", ondelete="RESTRICT"), nullable=False
    )
    estado_reportado_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("estado.id", ondelete="RESTRICT"), nullable=True
    )
    observacion_solicitante: Mapped[str | None] = mapped_column(Text, nullable=True)
    observacion_tecnico: Mapped[str | None] = mapped_column(Text, nullable=True)
    reparada: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    fecha_reparacion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Sin llave foránea: trabajos depende de atención, no al revés.
    orden_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
