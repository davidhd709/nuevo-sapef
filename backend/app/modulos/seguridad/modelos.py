"""Modelos ORM del módulo de seguridad (EP-01)."""

import uuid
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


class Rol(Base):
    __tablename__ = "rol"
    __table_args__ = (UniqueConstraint("codigo", name="uq_rol_codigo"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    codigo: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    creado_por: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    modificado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    modificado_por: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    permisos: Mapped[list["Permiso"]] = relationship(
        secondary="rol_permiso",
        lazy="selectin",
        order_by="Permiso.codigo",
    )


class Permiso(Base):
    __tablename__ = "permiso"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_permiso_codigo"),
        Index("ix_permiso_modulo", "modulo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    codigo: Mapped[str] = mapped_column(String(100), nullable=False)
    modulo: Mapped[str] = mapped_column(String(40), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False)


class RolPermiso(Base):
    __tablename__ = "rol_permiso"

    rol_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rol.id", ondelete="CASCADE"), primary_key=True
    )
    permiso_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("permiso.id", ondelete="CASCADE"), primary_key=True
    )


class Usuario(Base):
    __tablename__ = "usuario"
    __table_args__ = (
        Index("uq_usuario_nombre_usuario_lower", func.lower(text("nombre_usuario")), unique=True),
        Index("uq_usuario_correo_lower", func.lower(text("correo")), unique=True),
        Index("ix_usuario_rol_id", "rol_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    nombre_usuario: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre_completo: Mapped[str] = mapped_column(String(180), nullable=False)
    identificacion: Mapped[str] = mapped_column(String(40), nullable=False)
    correo: Mapped[str] = mapped_column(String(180), nullable=False)
    hash_clave: Mapped[str | None] = mapped_column(String(255), nullable=True)
    debe_cambiar_clave: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    acepto_condiciones_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    rol_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rol.id", ondelete="RESTRICT"), nullable=False
    )
    intentos_fallidos: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    creado_por: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True
    )
    modificado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    modificado_por: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True
    )

    rol: Mapped[Rol] = relationship(lazy="selectin")
    sedes_asignadas: Mapped[list["UsuarioSede"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )


class UsuarioSede(Base):
    __tablename__ = "usuario_sede"
    __table_args__ = (Index("ix_usuario_sede_sede_id", "sede_id"),)

    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True
    )
    sede_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sede.id", ondelete="RESTRICT"), primary_key=True
    )


class Sesion(Base):
    __tablename__ = "sesion"
    __table_args__ = (
        UniqueConstraint("hash_token_renovacion", name="uq_sesion_hash_token_renovacion"),
        Index("ix_sesion_usuario_id", "usuario_id"),
        Index("ix_sesion_familia", "familia"),
        CheckConstraint("tipo_cliente IN ('web', 'pwa')", name="ck_sesion_tipo_cliente"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False
    )
    hash_token_renovacion: Mapped[str] = mapped_column(String(64), nullable=False)
    familia: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    tipo_cliente: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'web'")
    )
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agente: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)


class TokenRecuperacion(Base):
    __tablename__ = "token_recuperacion"
    __table_args__ = (
        UniqueConstraint("hash_token", name="uq_token_recuperacion_hash"),
        Index("ix_token_recuperacion_usuario_id", "usuario_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False
    )
    hash_token: Mapped[str] = mapped_column(String(64), nullable=False)
    token_cifrado_envio: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_solicitud: Mapped[str | None] = mapped_column(String(45), nullable=True)


class Auditoria(Base):
    __tablename__ = "auditoria"
    __table_args__ = (
        Index("ix_auditoria_instante", "instante"),
        Index("ix_auditoria_usuario_id", "usuario_id"),
        Index("ix_auditoria_sede_id", "sede_id"),
        Index("ix_auditoria_entidad", "entidad", "entidad_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    instante: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    usuario_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True
    )
    sede_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    accion: Mapped[str] = mapped_column(String(60), nullable=False)
    entidad: Mapped[str] = mapped_column(String(80), nullable=False)
    entidad_id: Mapped[str] = mapped_column(String(64), nullable=False)
    antes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    despues: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuditoriaConsulta(Base):
    __tablename__ = "auditoria_consulta"
    __table_args__ = (
        Index("ix_auditoria_consulta_instante", "instante"),
        Index("ix_auditoria_consulta_usuario_id", "usuario_id"),
        Index("ix_auditoria_consulta_sede_id", "sede_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    instante: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="RESTRICT"), nullable=False
    )
    sede_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    recurso: Mapped[str] = mapped_column(String(120), nullable=False)
    parametros_permitidos: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
