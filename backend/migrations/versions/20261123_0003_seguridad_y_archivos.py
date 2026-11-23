"""Tablas de sede base, seguridad (EP-01) y archivos/evidencias (F3-1).

Revisión: 0003
Anterior: 0002
Fecha: 2026-11-23
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sede",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("codigo", sa.String(length=40), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("municipio", sa.String(length=120), nullable=False),
        sa.Column("departamento", sa.String(length=120), nullable=False),
        sa.Column("activa", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "modificado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo"),
    )

    op.create_table(
        "permiso",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("codigo", sa.String(length=100), nullable=False),
        sa.Column("modulo", sa.String(length=40), nullable=False),
        sa.Column("descripcion", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo", name="uq_permiso_codigo"),
    )
    op.create_index("ix_permiso_modulo", "permiso", ["modulo"], unique=False)

    op.create_table(
        "rol",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("codigo", sa.String(length=60), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("descripcion", sa.String(length=255), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("creado_por", sa.BigInteger(), nullable=True),
        sa.Column(
            "modificado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("modificado_por", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo", name="uq_rol_codigo"),
    )

    op.create_table(
        "rol_permiso",
        sa.Column("rol_id", sa.BigInteger(), nullable=False),
        sa.Column("permiso_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["permiso_id"], ["permiso.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rol_id"], ["rol.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("rol_id", "permiso_id"),
    )

    op.create_table(
        "usuario",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("nombre_usuario", sa.String(length=80), nullable=False),
        sa.Column("nombre_completo", sa.String(length=180), nullable=False),
        sa.Column("identificacion", sa.String(length=40), nullable=False),
        sa.Column("correo", sa.String(length=180), nullable=False),
        sa.Column("hash_clave", sa.String(length=255), nullable=True),
        sa.Column(
            "debe_cambiar_clave", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("acepto_condiciones_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("rol_id", sa.BigInteger(), nullable=False),
        sa.Column("intentos_fallidos", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("bloqueado_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("creado_por", sa.BigInteger(), nullable=True),
        sa.Column(
            "modificado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("modificado_por", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["creado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["modificado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rol_id"], ["rol.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usuario_rol_id", "usuario", ["rol_id"], unique=False)
    op.create_index(
        "uq_usuario_correo_lower", "usuario", [sa.text("lower(correo)")], unique=True
    )
    op.create_index(
        "uq_usuario_nombre_usuario_lower",
        "usuario",
        [sa.text("lower(nombre_usuario)")],
        unique=True,
    )

    op.create_table(
        "usuario_sede",
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("usuario_id", "sede_id"),
    )
    op.create_index("ix_usuario_sede_sede_id", "usuario_sede", ["sede_id"], unique=False)

    op.create_table(
        "sesion",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("hash_token_renovacion", sa.String(length=64), nullable=False),
        sa.Column("familia", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tipo_cliente", sa.String(length=10), server_default=sa.text("'web'"), nullable=False
        ),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agente", sa.String(length=512), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.CheckConstraint("tipo_cliente IN ('web', 'pwa')", name="ck_sesion_tipo_cliente"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hash_token_renovacion", name="uq_sesion_hash_token_renovacion"),
    )
    op.create_index("ix_sesion_familia", "sesion", ["familia"], unique=False)
    op.create_index("ix_sesion_usuario_id", "sesion", ["usuario_id"], unique=False)

    op.create_table(
        "token_recuperacion",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("hash_token", sa.String(length=64), nullable=False),
        sa.Column("token_cifrado_envio", sa.Text(), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_solicitud", sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hash_token", name="uq_token_recuperacion_hash"),
    )
    op.create_index(
        "ix_token_recuperacion_usuario_id", "token_recuperacion", ["usuario_id"], unique=False
    )

    op.create_table(
        "auditoria",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "instante",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("usuario_id", sa.BigInteger(), nullable=True),
        sa.Column("sede_id", sa.BigInteger(), nullable=True),
        sa.Column("accion", sa.String(length=60), nullable=False),
        sa.Column("entidad", sa.String(length=80), nullable=False),
        sa.Column("entidad_id", sa.String(length=64), nullable=False),
        sa.Column("antes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("despues", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auditoria_entidad", "auditoria", ["entidad", "entidad_id"], unique=False)
    op.create_index("ix_auditoria_instante", "auditoria", ["instante"], unique=False)
    op.create_index("ix_auditoria_sede_id", "auditoria", ["sede_id"], unique=False)
    op.create_index("ix_auditoria_usuario_id", "auditoria", ["usuario_id"], unique=False)

    op.create_table(
        "auditoria_consulta",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "instante",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=True),
        sa.Column("recurso", sa.String(length=120), nullable=False),
        sa.Column(
            "parametros_permitidos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auditoria_consulta_instante", "auditoria_consulta", ["instante"], unique=False
    )
    op.create_index(
        "ix_auditoria_consulta_sede_id", "auditoria_consulta", ["sede_id"], unique=False
    )
    op.create_index(
        "ix_auditoria_consulta_usuario_id", "auditoria_consulta", ["usuario_id"], unique=False
    )

    op.create_table(
        "archivo",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("nombre_original", sa.String(length=255), nullable=False),
        sa.Column("tipo_mime", sa.String(length=120), nullable=False),
        sa.Column("tamano", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("ruta", sa.String(length=500), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("creado_por", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("tamano > 0", name="ck_archivo_tamano_positivo"),
        sa.ForeignKeyConstraint(["creado_por"], ["usuario.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_archivo_sede_id", "archivo", ["sede_id"], unique=False)
    op.create_index("ix_archivo_sede_sha256", "archivo", ["sede_id", "sha256"], unique=False)
    op.create_index(
        "uq_archivo_sede_idempotency",
        "archivo",
        ["sede_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "evidencia",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("entidad", sa.String(length=50), nullable=False),
        sa.Column("entidad_id", sa.String(length=64), nullable=False),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        sa.Column("archivo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=4326,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                spatial_index=False,
            ),
            nullable=True,
        ),
        sa.Column("capturada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("creado_por", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["archivo_id"], ["archivo.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["creado_por"], ["usuario.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidencia_archivo_id", "evidencia", ["archivo_id"], unique=False)
    op.create_index(
        "ix_evidencia_geom", "evidencia", ["geom"], unique=False, postgresql_using="gist"
    )
    op.create_index(
        "ix_evidencia_sede_entidad",
        "evidencia",
        ["sede_id", "entidad", "entidad_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_evidencia_sede_entidad", table_name="evidencia")
    op.drop_index("ix_evidencia_geom", table_name="evidencia", postgresql_using="gist")
    op.drop_index("ix_evidencia_archivo_id", table_name="evidencia")
    op.drop_table("evidencia")

    op.drop_index(
        "uq_archivo_sede_idempotency",
        table_name="archivo",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index("ix_archivo_sede_sha256", table_name="archivo")
    op.drop_index("ix_archivo_sede_id", table_name="archivo")
    op.drop_table("archivo")

    op.drop_index("ix_auditoria_consulta_usuario_id", table_name="auditoria_consulta")
    op.drop_index("ix_auditoria_consulta_sede_id", table_name="auditoria_consulta")
    op.drop_index("ix_auditoria_consulta_instante", table_name="auditoria_consulta")
    op.drop_table("auditoria_consulta")

    op.drop_index("ix_auditoria_usuario_id", table_name="auditoria")
    op.drop_index("ix_auditoria_sede_id", table_name="auditoria")
    op.drop_index("ix_auditoria_instante", table_name="auditoria")
    op.drop_index("ix_auditoria_entidad", table_name="auditoria")
    op.drop_table("auditoria")

    op.drop_index("ix_token_recuperacion_usuario_id", table_name="token_recuperacion")
    op.drop_table("token_recuperacion")

    op.drop_index("ix_sesion_usuario_id", table_name="sesion")
    op.drop_index("ix_sesion_familia", table_name="sesion")
    op.drop_table("sesion")

    op.drop_index("ix_usuario_sede_sede_id", table_name="usuario_sede")
    op.drop_table("usuario_sede")

    op.drop_index("uq_usuario_nombre_usuario_lower", table_name="usuario")
    op.drop_index("uq_usuario_correo_lower", table_name="usuario")
    op.drop_index("ix_usuario_rol_id", table_name="usuario")
    op.drop_table("usuario")

    op.drop_table("rol_permiso")
    op.drop_table("rol")

    op.drop_index("ix_permiso_modulo", table_name="permiso")
    op.drop_table("permiso")

    op.drop_table("sede")
