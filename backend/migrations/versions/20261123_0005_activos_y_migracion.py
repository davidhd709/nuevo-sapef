"""Activos (EP-03) y registro de ejecuciones de migración.

Revisión: 0005
Anterior: 0004
Fecha: 2026-11-23
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ahora(nombre: str) -> sa.Column:
    return sa.Column(
        nombre, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _usuario(nombre: str) -> sa.Column:
    return sa.Column(nombre, sa.BigInteger(), nullable=True)


def _fk_usuario(columna: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([columna], ["usuario.id"], ondelete="SET NULL")


def upgrade() -> None:
    op.create_table(
        "lote",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("consecutivo_inicial", sa.Integer(), nullable=False),
        sa.Column("consecutivo_final", sa.Integer(), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("tecnologia_id", sa.BigInteger(), nullable=False),
        sa.Column("potencia_id", sa.BigInteger(), nullable=False),
        sa.Column("marca_id", sa.BigInteger(), nullable=True),
        sa.Column("es_rural", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("orden_compra", sa.String(length=120), nullable=True),
        sa.Column("fecha_orden_compra", sa.Date(), nullable=True),
        sa.Column("entrada_almacen", sa.String(length=120), nullable=True),
        sa.Column("fecha_entrada_almacen", sa.Date(), nullable=True),
        _ahora("creado_en"),
        _usuario("creado_por"),
        sa.CheckConstraint("consecutivo_inicial <= consecutivo_final", name="ck_lote_rango"),
        sa.CheckConstraint(
            "cantidad = (consecutivo_final - consecutivo_inicial + 1)", name="ck_lote_cantidad"
        ),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tecnologia_id"], ["maestro_valor.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["potencia_id"], ["maestro_valor.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["marca_id"], ["maestro_valor.id"], ondelete="RESTRICT"),
        _fk_usuario("creado_por"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lote_sede_id", "lote", ["sede_id"])

    op.create_table(
        "luminaria",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("codigo", sa.String(length=80), nullable=False),
        sa.Column("codigo_externo", sa.String(length=120), nullable=True),
        sa.Column("barrio_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "ubicacion",
            geoalchemy2.types.Geometry(
                geometry_type="POINT", srid=4326, spatial_index=False, from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
        ),
        sa.Column("estado_id", sa.BigInteger(), nullable=False),
        sa.Column("tecnologia_id", sa.BigInteger(), nullable=True),
        sa.Column("potencia_id", sa.BigInteger(), nullable=True),
        sa.Column("marca_id", sa.BigInteger(), nullable=True),
        sa.Column("tipo_intervencion_id", sa.BigInteger(), nullable=True),
        sa.Column("accion_operativa_id", sa.BigInteger(), nullable=True),
        sa.Column("mision_objetivo_id", sa.BigInteger(), nullable=True),
        sa.Column("lote_id", sa.BigInteger(), nullable=True),
        sa.Column("luminaria_reemplazada_id", sa.BigInteger(), nullable=True),
        sa.Column("fecha_instalacion", sa.Date(), nullable=True),
        sa.Column("fecha_mision", sa.Date(), nullable=True),
        sa.Column("fecha_baja", sa.Date(), nullable=True),
        sa.Column("fecha_disposicion_final", sa.Date(), nullable=True),
        sa.Column("mac", sa.String(length=80), nullable=True),
        sa.Column("poste", sa.String(length=80), nullable=True),
        sa.Column("longitud_brazo", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("es_rural", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("subnormal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tiene_medida", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("en_transito", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("validado", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("es_comodin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("responsable", sa.String(length=160), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        _ahora("creado_en"),
        _ahora("modificado_en"),
        _usuario("creado_por"),
        _usuario("modificado_por"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["barrio_id"], ["barrio.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["estado_id"], ["estado.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tecnologia_id"], ["maestro_valor.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["potencia_id"], ["maestro_valor.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["marca_id"], ["maestro_valor.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tipo_intervencion_id"], ["maestro_valor.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["accion_operativa_id"], ["maestro_valor.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["mision_objetivo_id"], ["maestro_valor.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lote_id"], ["lote.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["luminaria_reemplazada_id"], ["luminaria.id"], ondelete="SET NULL"
        ),
        _fk_usuario("creado_por"),
        _fk_usuario("modificado_por"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sede_id", "codigo", name="uq_luminaria_sede_codigo"),
    )
    op.create_index("ix_luminaria_sede_estado", "luminaria", ["sede_id", "estado_id"])
    op.create_index("ix_luminaria_sede_barrio", "luminaria", ["sede_id", "barrio_id"])
    op.create_index("ix_luminaria_ubicacion", "luminaria", ["ubicacion"], postgresql_using="gist")

    op.create_table(
        "luminaria_ubicacion",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("luminaria_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "ubicacion_anterior",
            geoalchemy2.types.Geometry(
                geometry_type="POINT", srid=4326, spatial_index=False, from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
        ),
        sa.Column(
            "ubicacion_nueva",
            geoalchemy2.types.Geometry(
                geometry_type="POINT", srid=4326, spatial_index=False, from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=False,
        ),
        sa.Column("origen", sa.String(length=30), server_default=sa.text("'web'"), nullable=False),
        _ahora("cambiado_en"),
        _usuario("cambiado_por"),
        sa.ForeignKeyConstraint(["luminaria_id"], ["luminaria.id"], ondelete="CASCADE"),
        _fk_usuario("cambiado_por"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_luminaria_ubicacion_lum", "luminaria_ubicacion", ["luminaria_id"])

    op.create_table(
        "evento_activo",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("luminaria_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        _ahora("fecha"),
        sa.Column("orden_id", sa.BigInteger(), nullable=True),
        sa.Column("pqrs_id", sa.BigInteger(), nullable=True),
        sa.Column("estado_anterior_id", sa.BigInteger(), nullable=True),
        sa.Column("estado_nuevo_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "detalle",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        _usuario("creado_por"),
        sa.ForeignKeyConstraint(["luminaria_id"], ["luminaria.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["estado_anterior_id"], ["estado.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["estado_nuevo_id"], ["estado.id"], ondelete="SET NULL"),
        _fk_usuario("creado_por"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evento_activo_lum", "evento_activo", ["luminaria_id"])

    op.create_table(
        "ejecucion_migracion",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        sa.Column(
            "estado", sa.String(length=20), server_default=sa.text("'completado'"), nullable=False
        ),
        sa.Column(
            "conciliacion",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "errores",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        _ahora("creado_en"),
        _usuario("creado_por"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="CASCADE"),
        _fk_usuario("creado_por"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ejecucion_migracion_sede", "ejecucion_migracion", ["sede_id"])


def downgrade() -> None:
    op.drop_index("ix_ejecucion_migracion_sede", table_name="ejecucion_migracion")
    op.drop_table("ejecucion_migracion")
    op.drop_index("ix_evento_activo_lum", table_name="evento_activo")
    op.drop_table("evento_activo")
    op.drop_index("ix_luminaria_ubicacion_lum", table_name="luminaria_ubicacion")
    op.drop_table("luminaria_ubicacion")
    op.drop_index("ix_luminaria_ubicacion", table_name="luminaria", postgresql_using="gist")
    op.drop_index("ix_luminaria_sede_barrio", table_name="luminaria")
    op.drop_index("ix_luminaria_sede_estado", table_name="luminaria")
    op.drop_table("luminaria")
    op.drop_index("ix_lote_sede_id", table_name="lote")
    op.drop_table("lote")
