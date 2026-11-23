"""Modelos ORM del módulo de configuración (EP-02)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _creado_en() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _modificado_en() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


def _usuario_fk() -> Mapped[int | None]:
    return mapped_column(BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True)


class Sede(Base):
    __tablename__ = "sede"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    municipio: Mapped[str] = mapped_column(String(120), nullable=False)
    departamento: Mapped[str] = mapped_column(String(120), nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    creado_en: Mapped[datetime] = _creado_en()
    modificado_en: Mapped[datetime] = _modificado_en()


class Comercializador(Base):
    __tablename__ = "comercializador"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_comercializador_codigo"),
        CheckConstraint(
            "periodicidad IN ('mensual', 'bimestral')", name="ck_comercializador_periodicidad"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    # Cómo se llama el usuario en sus archivos: nic (Afinia), cuenta (Celsia), cliente (Vatia).
    identificador_usuario: Mapped[str] = mapped_column(String(20), nullable=False)
    # Forma del acuerdo tarifario que aplica (None = sin control tarifario).
    regla_tarifaria: Mapped[str | None] = mapped_column(String(40), nullable=True)
    periodicidad: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'mensual'")
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    creado_en: Mapped[datetime] = _creado_en()
    modificado_en: Mapped[datetime] = _modificado_en()


class SedeComercializador(Base):
    __tablename__ = "sede_comercializador"
    __table_args__ = (Index("ix_sede_comercializador_comercializador", "comercializador_id"),)

    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="CASCADE"), primary_key=True
    )
    comercializador_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("comercializador.id", ondelete="RESTRICT"), primary_key=True
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    modificado_en: Mapped[datetime] = _modificado_en()
    modificado_por: Mapped[int | None] = _usuario_fk()

    comercializador: Mapped[Comercializador] = relationship(lazy="joined")


class MaestroClase(Base):
    __tablename__ = "maestro_clase"
    __table_args__ = (UniqueConstraint("codigo", name="uq_maestro_clase_codigo"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    codigo: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)


class MaestroValor(Base):
    __tablename__ = "maestro_valor"
    __table_args__ = (
        UniqueConstraint("clase_id", "codigo", name="uq_maestro_valor_clase_codigo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    clase_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("maestro_clase.id", ondelete="RESTRICT"), nullable=False
    )
    codigo: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    creado_en: Mapped[datetime] = _creado_en()
    creado_por: Mapped[int | None] = _usuario_fk()
    modificado_en: Mapped[datetime] = _modificado_en()
    modificado_por: Mapped[int | None] = _usuario_fk()


class Zona(Base):
    __tablename__ = "zona"
    __table_args__ = (
        # Permite que barrio referencie (zona_id, sede_id) y la base garantice la misma sede.
        UniqueConstraint("id", "sede_id", name="uq_zona_id_sede"),
        Index("uq_zona_sede_nombre", "sede_id", func.lower(text("nombre")), unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    creado_en: Mapped[datetime] = _creado_en()
    creado_por: Mapped[int | None] = _usuario_fk()
    modificado_en: Mapped[datetime] = _modificado_en()
    modificado_por: Mapped[int | None] = _usuario_fk()


class Barrio(Base):
    __tablename__ = "barrio"
    __table_args__ = (
        ForeignKeyConstraint(
            ["zona_id", "sede_id"],
            ["zona.id", "zona.sede_id"],
            name="fk_barrio_zona_misma_sede",
            ondelete="RESTRICT",
        ),
        Index("uq_barrio_zona_nombre", "zona_id", func.lower(text("nombre")), unique=True),
        Index("ix_barrio_sede_id", "sede_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    zona_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    creado_en: Mapped[datetime] = _creado_en()
    creado_por: Mapped[int | None] = _usuario_fk()
    modificado_en: Mapped[datetime] = _modificado_en()
    modificado_por: Mapped[int | None] = _usuario_fk()


class Estado(Base):
    __tablename__ = "estado"
    __table_args__ = (
        UniqueConstraint("proceso", "codigo", name="uq_estado_proceso_codigo"),
        CheckConstraint(
            "proceso IN ('luminaria', 'pqrs', 'orden', 'solicitud')", name="ck_estado_proceso"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    proceso: Mapped[str] = mapped_column(String(20), nullable=False)
    codigo: Mapped[str] = mapped_column(String(10), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    final: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Los no vigentes son del modelo anterior de SAPEF: solo sirven para migrar.
    vigente: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    modificado_en: Mapped[datetime] = _modificado_en()
    modificado_por: Mapped[int | None] = _usuario_fk()


class Parametro(Base):
    __tablename__ = "parametro"
    __table_args__ = (
        Index(
            "uq_parametro_sede_codigo",
            "sede_id",
            "codigo",
            unique=True,
            postgresql_where=text("sede_id IS NOT NULL"),
        ),
        Index(
            "uq_parametro_global_codigo",
            "codigo",
            unique=True,
            postgresql_where=text("sede_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # None = parámetro global (aplica a todas las sedes).
    sede_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="CASCADE"), nullable=True
    )
    codigo: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    valor: Mapped[Any] = mapped_column(JSONB, nullable=False)
    editable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    modificado_en: Mapped[datetime] = _modificado_en()
    modificado_por: Mapped[int | None] = _usuario_fk()


class PlantillaCorreo(Base):
    __tablename__ = "plantilla_correo"
    __table_args__ = (UniqueConstraint("sede_id", "codigo", name="uq_plantilla_sede_codigo"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="CASCADE"), nullable=False
    )
    codigo: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    asunto: Mapped[str] = mapped_column(String(255), nullable=False)
    cuerpo_html: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    modificado_en: Mapped[datetime] = _modificado_en()
    modificado_por: Mapped[int | None] = _usuario_fk()


class AcuerdoVigencia(Base):
    __tablename__ = "acuerdo_vigencia"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('borrador', 'aprobado', 'reemplazado')", name="ck_acuerdo_estado"
        ),
        CheckConstraint("anio BETWEEN 2000 AND 2200", name="ck_acuerdo_anio"),
        # Una sola vigencia aprobada y un solo borrador por (sede, comercializador, año).
        Index(
            "uq_acuerdo_aprobado",
            "sede_id",
            "comercializador_id",
            "anio",
            unique=True,
            postgresql_where=text("estado = 'aprobado'"),
        ),
        Index(
            "uq_acuerdo_borrador",
            "sede_id",
            "comercializador_id",
            "anio",
            unique=True,
            postgresql_where=text("estado = 'borrador'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    comercializador_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("comercializador.id", ondelete="RESTRICT"), nullable=False
    )
    anio: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    estado: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default=text("'borrador'")
    )
    uvt: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    umbral_kwh: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    tolerancia: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    base_costo_variable: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reglas: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    fuente: Mapped[str | None] = mapped_column(String(500), nullable=True)
    origen_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("acuerdo_vigencia.id", ondelete="SET NULL"), nullable=True
    )
    aprobado_por: Mapped[int | None] = _usuario_fk()
    aprobado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    creado_en: Mapped[datetime] = _creado_en()
    creado_por: Mapped[int | None] = _usuario_fk()
    modificado_en: Mapped[datetime] = _modificado_en()
    modificado_por: Mapped[int | None] = _usuario_fk()

    comercializador: Mapped[Comercializador] = relationship(lazy="joined")
    tarifas: Mapped[list["AcuerdoTarifa"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="AcuerdoTarifa.orden",
    )
    excepciones: Mapped[list["AcuerdoExcepcion"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="AcuerdoExcepcion.identificador",
    )


class AcuerdoTarifa(Base):
    __tablename__ = "acuerdo_tarifa"
    __table_args__ = (UniqueConstraint("vigencia_id", "tarifa", name="uq_acuerdo_tarifa"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    vigencia_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("acuerdo_vigencia.id", ondelete="CASCADE"), nullable=False
    )
    tarifa: Mapped[str] = mapped_column(String(80), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    tipo_regla: Mapped[str | None] = mapped_column(String(40), nullable=True)
    factor_uvt_minimo: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    porcentaje_costo_variable: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    valor_urbano: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    valor_rural: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)


class AcuerdoExcepcion(Base):
    """Contribuyente especial (NIC o cuenta) con su factor UVT o regla propia."""

    __tablename__ = "acuerdo_excepcion"
    __table_args__ = (
        UniqueConstraint("vigencia_id", "identificador", name="uq_acuerdo_excepcion"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    vigencia_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("acuerdo_vigencia.id", ondelete="CASCADE"), nullable=False
    )
    identificador: Mapped[str] = mapped_column(String(40), nullable=False)
    nombre: Mapped[str | None] = mapped_column(String(200), nullable=True)
    factor_uvt: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    regla: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class _CatalogoComercial:
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    comercializador_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("comercializador.id", ondelete="RESTRICT"), nullable=False
    )
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(200), nullable=False)
    entra_al_calculo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    modificado_en: Mapped[datetime] = _modificado_en()
    modificado_por: Mapped[int | None] = _usuario_fk()


class ConceptoComercial(_CatalogoComercial, Base):
    __tablename__ = "concepto_comercial"
    __table_args__ = (
        UniqueConstraint("comercializador_id", "codigo", name="uq_concepto_comercial"),
    )

    comercializador: Mapped[Comercializador] = relationship(lazy="joined")


class OperacionContable(_CatalogoComercial, Base):
    __tablename__ = "operacion_contable"
    __table_args__ = (
        UniqueConstraint("comercializador_id", "codigo", name="uq_operacion_contable"),
    )

    comercializador: Mapped[Comercializador] = relationship(lazy="joined")
