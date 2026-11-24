"""Modelos ORM del módulo de sincronización de la app de campo."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class OperacionCampo(Base):
    """Registro de cada operación que llega de la app de campo, por su uuid (generado en el
    teléfono). Una operación aplicada no se vuelve a aplicar: el reintento responde
    «ya_aplicada». Las que quedan en conflicto o con error se ven en la oficina."""

    __tablename__ = "operacion_campo"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('aplicada', 'conflicto', 'error')", name="ck_operacion_campo_estado"
        ),
        Index("ix_operacion_campo_sede_estado", "sede_id", "estado", "recibida_en"),
        Index("ix_operacion_campo_usuario", "usuario_id"),
        Index("ix_operacion_campo_orden", "orden_id"),
    )

    uuid: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), nullable=False
    )
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="RESTRICT"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    orden_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("orden_trabajo.id", ondelete="SET NULL"), nullable=True
    )
    estado: Mapped[str] = mapped_column(String(10), nullable=False)
    motivo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    creada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recibida_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    actualizada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
