"""Configuración (EP-02): comercializadores, maestros, zonas y barrios, estados,
parámetros, plantillas, acuerdos tarifarios y catálogos comerciales.

Los datos semilla no van aquí: los carga `python -m app.semillas` (idempotente).

Revisión: 0004
Anterior: 0003
Fecha: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
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
        "comercializador",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("codigo", sa.String(length=40), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("identificador_usuario", sa.String(length=20), nullable=False),
        sa.Column("regla_tarifaria", sa.String(length=40), nullable=True),
        sa.Column(
            "periodicidad", sa.String(length=10), server_default=sa.text("'mensual'"),
            nullable=False,
        ),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _ahora("creado_en"),
        _ahora("modificado_en"),
        sa.CheckConstraint(
            "periodicidad IN ('mensual', 'bimestral')", name="ck_comercializador_periodicidad"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo", name="uq_comercializador_codigo"),
    )

    op.create_table(
        "sede_comercializador",
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("comercializador_id", sa.BigInteger(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("desde", sa.Date(), nullable=True),
        _ahora("modificado_en"),
        _usuario("modificado_por"),
        sa.ForeignKeyConstraint(
            ["comercializador_id"], ["comercializador.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="CASCADE"),
        _fk_usuario("modificado_por"),
        sa.PrimaryKeyConstraint("sede_id", "comercializador_id"),
    )
    op.create_index(
        "ix_sede_comercializador_comercializador", "sede_comercializador", ["comercializador_id"]
    )

    op.create_table(
        "maestro_clase",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("codigo", sa.String(length=60), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo", name="uq_maestro_clase_codigo"),
    )

    op.create_table(
        "maestro_valor",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("clase_id", sa.BigInteger(), nullable=False),
        sa.Column("codigo", sa.String(length=60), nullable=False),
        sa.Column("nombre", sa.String(length=160), nullable=False),
        sa.Column("orden", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _ahora("creado_en"),
        _usuario("creado_por"),
        _ahora("modificado_en"),
        _usuario("modificado_por"),
        sa.ForeignKeyConstraint(["clase_id"], ["maestro_clase.id"], ondelete="RESTRICT"),
        _fk_usuario("creado_por"),
        _fk_usuario("modificado_por"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clase_id", "codigo", name="uq_maestro_valor_clase_codigo"),
    )

    op.create_table(
        "zona",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("activa", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _ahora("creado_en"),
        _usuario("creado_por"),
        _ahora("modificado_en"),
        _usuario("modificado_por"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        _fk_usuario("creado_por"),
        _fk_usuario("modificado_por"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "sede_id", name="uq_zona_id_sede"),
    )
    op.create_index(
        "uq_zona_sede_nombre", "zona", ["sede_id", sa.text("lower(nombre)")], unique=True
    )

    op.create_table(
        "barrio",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("zona_id", sa.BigInteger(), nullable=False),
        sa.Column("nombre", sa.String(length=160), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _ahora("creado_en"),
        _usuario("creado_por"),
        _ahora("modificado_en"),
        _usuario("modificado_por"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        # El barrio y su zona son siempre de la misma sede (lo garantiza la base).
        sa.ForeignKeyConstraint(
            ["zona_id", "sede_id"],
            ["zona.id", "zona.sede_id"],
            name="fk_barrio_zona_misma_sede",
            ondelete="RESTRICT",
        ),
        _fk_usuario("creado_por"),
        _fk_usuario("modificado_por"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_barrio_sede_id", "barrio", ["sede_id"])
    op.create_index(
        "uq_barrio_zona_nombre", "barrio", ["zona_id", sa.text("lower(nombre)")], unique=True
    )

    op.create_table(
        "estado",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("proceso", sa.String(length=20), nullable=False),
        sa.Column("codigo", sa.String(length=10), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("orden", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("final", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("vigente", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _ahora("modificado_en"),
        _usuario("modificado_por"),
        sa.CheckConstraint(
            "proceso IN ('luminaria', 'pqrs', 'orden', 'solicitud')", name="ck_estado_proceso"
        ),
        _fk_usuario("modificado_por"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proceso", "codigo", name="uq_estado_proceso_codigo"),
    )

    op.create_table(
        "parametro",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=True),
        sa.Column("codigo", sa.String(length=80), nullable=False),
        sa.Column("nombre", sa.String(length=160), nullable=False),
        sa.Column("valor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("editable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _ahora("modificado_en"),
        _usuario("modificado_por"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="CASCADE"),
        _fk_usuario("modificado_por"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_parametro_sede_codigo",
        "parametro",
        ["sede_id", "codigo"],
        unique=True,
        postgresql_where=sa.text("sede_id IS NOT NULL"),
    )
    op.create_index(
        "uq_parametro_global_codigo",
        "parametro",
        ["codigo"],
        unique=True,
        postgresql_where=sa.text("sede_id IS NULL"),
    )

    op.create_table(
        "plantilla_correo",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("codigo", sa.String(length=80), nullable=False),
        sa.Column("nombre", sa.String(length=160), nullable=False),
        sa.Column("asunto", sa.String(length=255), nullable=False),
        sa.Column("cuerpo_html", sa.Text(), nullable=False),
        sa.Column(
            "variables",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("activa", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _ahora("modificado_en"),
        _usuario("modificado_por"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="CASCADE"),
        _fk_usuario("modificado_por"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sede_id", "codigo", name="uq_plantilla_sede_codigo"),
    )

    op.create_table(
        "acuerdo_vigencia",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("comercializador_id", sa.BigInteger(), nullable=False),
        sa.Column("anio", sa.SmallInteger(), nullable=False),
        sa.Column(
            "estado", sa.String(length=12), server_default=sa.text("'borrador'"), nullable=False
        ),
        sa.Column("uvt", sa.Numeric(14, 2), nullable=True),
        sa.Column("umbral_kwh", sa.Numeric(10, 2), nullable=True),
        sa.Column("tolerancia", sa.Numeric(14, 2), nullable=True),
        sa.Column("base_costo_variable", sa.String(length=60), nullable=True),
        sa.Column(
            "reglas",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("fuente", sa.String(length=500), nullable=True),
        sa.Column("origen_id", sa.BigInteger(), nullable=True),
        _usuario("aprobado_por"),
        sa.Column("aprobado_en", sa.DateTime(timezone=True), nullable=True),
        _ahora("creado_en"),
        _usuario("creado_por"),
        _ahora("modificado_en"),
        _usuario("modificado_por"),
        sa.CheckConstraint(
            "estado IN ('borrador', 'aprobado', 'reemplazado')", name="ck_acuerdo_estado"
        ),
        sa.CheckConstraint("anio BETWEEN 2000 AND 2200", name="ck_acuerdo_anio"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["comercializador_id"], ["comercializador.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["origen_id"], ["acuerdo_vigencia.id"], ondelete="SET NULL"),
        _fk_usuario("aprobado_por"),
        _fk_usuario("creado_por"),
        _fk_usuario("modificado_por"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_acuerdo_aprobado",
        "acuerdo_vigencia",
        ["sede_id", "comercializador_id", "anio"],
        unique=True,
        postgresql_where=sa.text("estado = 'aprobado'"),
    )
    op.create_index(
        "uq_acuerdo_borrador",
        "acuerdo_vigencia",
        ["sede_id", "comercializador_id", "anio"],
        unique=True,
        postgresql_where=sa.text("estado = 'borrador'"),
    )

    op.create_table(
        "acuerdo_tarifa",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("vigencia_id", sa.BigInteger(), nullable=False),
        sa.Column("tarifa", sa.String(length=80), nullable=False),
        sa.Column("orden", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tipo_regla", sa.String(length=40), nullable=True),
        sa.Column("factor_uvt_minimo", sa.Numeric(10, 4), nullable=True),
        sa.Column("porcentaje_costo_variable", sa.Numeric(10, 6), nullable=True),
        sa.Column("valor_urbano", sa.Numeric(14, 2), nullable=True),
        sa.Column("valor_rural", sa.Numeric(14, 2), nullable=True),
        sa.ForeignKeyConstraint(["vigencia_id"], ["acuerdo_vigencia.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vigencia_id", "tarifa", name="uq_acuerdo_tarifa"),
    )

    op.create_table(
        "acuerdo_excepcion",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("vigencia_id", sa.BigInteger(), nullable=False),
        sa.Column("identificador", sa.String(length=40), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=True),
        sa.Column("factor_uvt", sa.Numeric(10, 4), nullable=True),
        sa.Column("regla", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["vigencia_id"], ["acuerdo_vigencia.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vigencia_id", "identificador", name="uq_acuerdo_excepcion"),
    )

    for tabla, unica in (
        ("concepto_comercial", "uq_concepto_comercial"),
        ("operacion_contable", "uq_operacion_contable"),
    ):
        op.create_table(
            tabla,
            sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
            sa.Column("comercializador_id", sa.BigInteger(), nullable=False),
            sa.Column("codigo", sa.String(length=20), nullable=False),
            sa.Column("descripcion", sa.String(length=200), nullable=False),
            sa.Column(
                "entra_al_calculo", sa.Boolean(), server_default=sa.text("false"), nullable=False
            ),
            sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            _ahora("modificado_en"),
            _usuario("modificado_por"),
            sa.ForeignKeyConstraint(
                ["comercializador_id"], ["comercializador.id"], ondelete="RESTRICT"
            ),
            _fk_usuario("modificado_por"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("comercializador_id", "codigo", name=unica),
        )


def downgrade() -> None:
    op.drop_table("operacion_contable")
    op.drop_table("concepto_comercial")
    op.drop_table("acuerdo_excepcion")
    op.drop_table("acuerdo_tarifa")
    op.drop_index(
        "uq_acuerdo_borrador",
        table_name="acuerdo_vigencia",
        postgresql_where=sa.text("estado = 'borrador'"),
    )
    op.drop_index(
        "uq_acuerdo_aprobado",
        table_name="acuerdo_vigencia",
        postgresql_where=sa.text("estado = 'aprobado'"),
    )
    op.drop_table("acuerdo_vigencia")
    op.drop_table("plantilla_correo")
    op.drop_index(
        "uq_parametro_global_codigo",
        table_name="parametro",
        postgresql_where=sa.text("sede_id IS NULL"),
    )
    op.drop_index(
        "uq_parametro_sede_codigo",
        table_name="parametro",
        postgresql_where=sa.text("sede_id IS NOT NULL"),
    )
    op.drop_table("parametro")
    op.drop_table("estado")
    op.drop_index("uq_barrio_zona_nombre", table_name="barrio")
    op.drop_index("ix_barrio_sede_id", table_name="barrio")
    op.drop_table("barrio")
    op.drop_index("uq_zona_sede_nombre", table_name="zona")
    op.drop_table("zona")
    op.drop_table("maestro_valor")
    op.drop_table("maestro_clase")
    op.drop_index("ix_sede_comercializador_comercializador", table_name="sede_comercializador")
    op.drop_table("sede_comercializador")
    op.drop_table("comercializador")
