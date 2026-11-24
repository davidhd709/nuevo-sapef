"""Modelos ORM del módulo de notificaciones."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SuscripcionPush(Base):
    """Suscripción Web Push de un navegador o teléfono (RF-105). El endpoint identifica al
    dispositivo: si otra persona inicia sesión en el mismo teléfono, la suscripción pasa a ella."""

    __tablename__ = "suscripcion_push"
    __table_args__ = (
        Index("uq_suscripcion_push_endpoint", "endpoint", unique=True),
        Index("ix_suscripcion_push_usuario", "usuario_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(String(2048), nullable=False)
    p256dh: Mapped[str] = mapped_column(String(200), nullable=False)
    auth: Mapped[str] = mapped_column(String(100), nullable=False)
    agente: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fallos: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    ultimo_envio_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
