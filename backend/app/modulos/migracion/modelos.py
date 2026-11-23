"""Modelos ORM del módulo de migración."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EjecucionMigracion(Base):
    __tablename__ = "ejecucion_migracion"
    __table_args__ = (Index("ix_ejecucion_migracion_sede", "sede_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="CASCADE"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'completado'")
    )
    conciliacion: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    errores: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    creado_por: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True
    )
