"""Tablas resumen del tablero (ADR-009). Se recalculan de noche y tras cada corte comercial
publicado; el tablero solo lee de aquí, nunca agrega sobre las tablas operativas al consultar."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, SmallInteger, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ResumenCalculo(Base):
    """Una fila por sede: cuándo se calculó y los indicadores escalares de la operación."""

    __tablename__ = "resumen_calculo"

    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="CASCADE"), primary_key=True
    )
    calculado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    operacion: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class ResumenLuminariaMes(Base):
    """Luminarias instaladas por mes (HU-090), por fecha de instalación."""

    __tablename__ = "resumen_luminaria_mes"

    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="CASCADE"), primary_key=True
    )
    anio: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    mes: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)


class ResumenDimension(Base):
    """Conteos por dimensión: tecnología, potencia, estado, zona, barrio (HU-091) y PQRS por
    barrio (HU-093). `grupo` lleva la zona del barrio."""

    __tablename__ = "resumen_dimension"

    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="CASCADE"), primary_key=True
    )
    dimension: Mapped[str] = mapped_column(String(20), primary_key=True)
    clave: Mapped[str] = mapped_column(String(120), primary_key=True)
    etiqueta: Mapped[str] = mapped_column(String(200), nullable=False)
    grupo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)


class ResumenComercial(Base):
    """Informe gerencial comercial del último corte de cada comercializador (HU-092)."""

    __tablename__ = "resumen_comercial"

    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="CASCADE"), primary_key=True
    )
    comercializador: Mapped[str] = mapped_column(String(20), primary_key=True)
    periodo: Mapped[str] = mapped_column(String(6), nullable=False)
    datos: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
