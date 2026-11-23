"""Fase 2: inventario (materiales, kárdex, bodega), atención (ciudadanos, PQRS) y trabajos
(órdenes, cuadrillas, cargue masivo).

Revisión: 0006
Anterior: 0005
Fecha: 2026-11-23 22:23:33.992918+00:00
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# unaccent() no es IMMUTABLE (depende del diccionario de la sesión) y no sirve para un índice;
# esta envoltura fija el diccionario y sí se puede indexar.
_FUNCION_UNACCENT = """
CREATE OR REPLACE FUNCTION sapef_unaccent(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$
"""


def upgrade() -> None:
    op.execute(_FUNCION_UNACCENT)
    op.create_table(
        "cuadrilla",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("activa", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("modificado_por", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["modificado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_cuadrilla_sede_nombre",
        "cuadrilla",
        ["sede_id", sa.literal_column("lower(nombre)")],
        unique=True,
    )
    op.create_table(
        "material",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("categoria", sa.String(length=60), nullable=False),
        sa.Column("codigo", sa.String(length=60), nullable=False),
        sa.Column("descripcion", sa.String(length=255), nullable=False),
        sa.Column("unidad", sa.String(length=20), nullable=False),
        sa.Column(
            "existencias",
            sa.Numeric(precision=14, scale=3),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "existencias_minimas",
            sa.Numeric(precision=14, scale=3),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("responsable", sa.String(length=160), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("creado_por", sa.BigInteger(), nullable=True),
        sa.Column(
            "modificado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("modificado_por", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("existencias >= 0", name="ck_material_existencias_no_negativas"),
        sa.CheckConstraint("existencias_minimas >= 0", name="ck_material_minimas_no_negativas"),
        sa.ForeignKeyConstraint(["creado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["modificado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_material_sede_codigo",
        "material",
        ["sede_id", sa.literal_column("lower(codigo)")],
        unique=True,
    )
    op.create_table(
        "cargue_bodega",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("archivo_id", sa.UUID(), nullable=False),
        sa.Column(
            "estado", sa.String(length=15), server_default=sa.text("'pendiente'"), nullable=False
        ),
        sa.Column("filas", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "errores",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("creado_por", sa.BigInteger(), nullable=True),
        sa.Column("procesado_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('pendiente', 'completado', 'con_errores')", name="ck_cargue_bodega_estado"
        ),
        sa.ForeignKeyConstraint(["archivo_id"], ["archivo.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["creado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cargue_bodega_sede", "cargue_bodega", ["sede_id"], unique=False)
    op.create_table(
        "cargue_masivo",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("archivo_id", sa.UUID(), nullable=False),
        sa.Column(
            "estado", sa.String(length=15), server_default=sa.text("'pendiente'"), nullable=False
        ),
        sa.Column("filas", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("ordenes_creadas", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "errores",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("creado_por", sa.BigInteger(), nullable=True),
        sa.Column("procesado_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('pendiente', 'completado', 'con_errores')", name="ck_cargue_masivo_estado"
        ),
        sa.CheckConstraint(
            "tipo IN ('expansion', 'modernizacion', 'reubicacion')", name="ck_cargue_masivo_tipo"
        ),
        sa.ForeignKeyConstraint(["archivo_id"], ["archivo.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["creado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cargue_masivo_sede", "cargue_masivo", ["sede_id"], unique=False)
    op.create_table(
        "cuadrilla_tecnico",
        sa.Column("cuadrilla_id", sa.BigInteger(), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["cuadrilla_id"], ["cuadrilla.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("cuadrilla_id", "usuario_id"),
    )
    op.create_index(
        "ix_cuadrilla_tecnico_usuario", "cuadrilla_tecnico", ["usuario_id"], unique=False
    )
    op.create_table(
        "movimiento_material",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("material_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo", sa.String(length=10), nullable=False),
        sa.Column("cantidad", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("delta", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("existencias_resultantes", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("origen", sa.String(length=20), nullable=False),
        sa.Column("descripcion", sa.String(length=255), nullable=True),
        sa.Column("orden_id", sa.BigInteger(), nullable=True),
        sa.Column("uuid_origen", sa.UUID(), nullable=True),
        sa.Column(
            "ubicacion",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
        ),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("creado_por", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("tipo IN ('entrada', 'salida', 'ajuste')", name="ck_movimiento_tipo"),
        sa.CheckConstraint("delta <> 0", name="ck_movimiento_delta_no_cero"),
        sa.CheckConstraint("existencias_resultantes >= 0", name="ck_movimiento_resultante"),
        sa.ForeignKeyConstraint(["creado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["material_id"], ["material.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_movimiento_material_material",
        "movimiento_material",
        ["material_id", "creado_en"],
        unique=False,
    )
    op.create_index(
        "ix_movimiento_material_orden", "movimiento_material", ["orden_id"], unique=False
    )
    op.create_index(
        "uq_movimiento_sede_uuid_origen",
        "movimiento_material",
        ["sede_id", "uuid_origen"],
        unique=True,
        postgresql_where=sa.text("uuid_origen IS NOT NULL"),
    )
    op.create_table(
        "ciudadano",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("identificacion", sa.String(length=40), nullable=False),
        sa.Column("nombre_completo", sa.String(length=180), nullable=False),
        sa.Column("barrio_id", sa.BigInteger(), nullable=True),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("telefono", sa.String(length=40), nullable=True),
        sa.Column("celular", sa.String(length=40), nullable=True),
        sa.Column("correo", sa.String(length=180), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("creado_por", sa.BigInteger(), nullable=True),
        sa.Column(
            "modificado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("modificado_por", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["barrio_id"], ["barrio.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["creado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["modificado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sede_id", "identificacion", name="uq_ciudadano_sede_identificacion"),
    )
    op.create_index(
        "ix_ciudadano_nombre_trgm",
        "ciudadano",
        [sa.literal_column("sapef_unaccent(lower(nombre_completo)) gin_trgm_ops")],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index("ix_ciudadano_sede", "ciudadano", ["sede_id"], unique=False)
    op.create_table(
        "pqrs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("canal_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "fecha_solicitud",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ciudadano_id", sa.BigInteger(), nullable=True),
        sa.Column("observacion_solicitante", sa.Text(), nullable=True),
        sa.Column("observacion_interna", sa.Text(), nullable=True),
        sa.Column("prioridad", sa.SmallInteger(), server_default=sa.text("2"), nullable=False),
        sa.Column("estado_id", sa.BigInteger(), nullable=False),
        sa.Column("calidad_servicio", sa.String(length=40), nullable=True),
        sa.Column("fecha_cierre", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "notificar_cliente", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("motivo_anulacion", sa.String(length=500), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("creado_por", sa.BigInteger(), nullable=True),
        sa.Column(
            "modificado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("modificado_por", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("prioridad BETWEEN 0 AND 3", name="ck_pqrs_prioridad"),
        sa.ForeignKeyConstraint(["canal_id"], ["maestro_valor.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ciudadano_id"], ["ciudadano.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["creado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["estado_id"], ["estado.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["modificado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sede_id", "numero", name="uq_pqrs_sede_numero"),
    )
    op.create_index("ix_pqrs_ciudadano", "pqrs", ["ciudadano_id"], unique=False)
    op.create_index("ix_pqrs_sede_fecha", "pqrs", ["sede_id", "fecha_solicitud"], unique=False)
    op.create_table(
        "orden_trabajo",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("sede_id", sa.BigInteger(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("estado_id", sa.BigInteger(), nullable=False),
        sa.Column("prioridad", sa.SmallInteger(), server_default=sa.text("2"), nullable=False),
        sa.Column("pqrs_id", sa.BigInteger(), nullable=True),
        sa.Column("tecnico_id", sa.BigInteger(), nullable=True),
        sa.Column("cuadrilla_id", sa.BigInteger(), nullable=True),
        sa.Column("fecha_programada", sa.Date(), nullable=True),
        sa.Column("asignada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_ejecucion", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ubicacion",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
        ),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("motivo_anulacion", sa.String(length=500), nullable=True),
        sa.Column("origen", sa.String(length=10), server_default=sa.text("'web'"), nullable=False),
        sa.Column("cargue_id", sa.BigInteger(), nullable=True),
        sa.Column("uuid_origen", sa.UUID(), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("creado_por", sa.BigInteger(), nullable=True),
        sa.Column(
            "modificado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("modificado_por", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("origen IN ('web', 'cargue', 'campo')", name="ck_orden_origen"),
        sa.CheckConstraint(
            "tipo IN ('mantenimiento', 'modernizacion', 'expansion', 'reubicacion')",
            name="ck_orden_tipo",
        ),
        sa.CheckConstraint("prioridad BETWEEN 0 AND 3", name="ck_orden_prioridad"),
        sa.ForeignKeyConstraint(["cargue_id"], ["cargue_masivo.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["creado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cuadrilla_id"], ["cuadrilla.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["estado_id"], ["estado.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["modificado_por"], ["usuario.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pqrs_id"], ["pqrs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sede_id"], ["sede.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tecnico_id"], ["usuario.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sede_id", "numero", name="uq_orden_sede_numero"),
    )
    op.create_index("ix_orden_pqrs", "orden_trabajo", ["pqrs_id"], unique=False)
    op.create_index("ix_orden_sede_creado", "orden_trabajo", ["sede_id", "creado_en"], unique=False)
    op.create_index("ix_orden_sede_estado", "orden_trabajo", ["sede_id", "estado_id"], unique=False)
    op.create_index("ix_orden_tecnico", "orden_trabajo", ["tecnico_id"], unique=False)
    op.create_index(
        "uq_orden_sede_uuid_origen",
        "orden_trabajo",
        ["sede_id", "uuid_origen"],
        unique=True,
        postgresql_where=sa.text("uuid_origen IS NOT NULL"),
    )
    op.create_table(
        "pqrs_luminaria",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("pqrs_id", sa.BigInteger(), nullable=False),
        sa.Column("luminaria_id", sa.BigInteger(), nullable=False),
        sa.Column("estado_reportado_id", sa.BigInteger(), nullable=True),
        sa.Column("observacion_solicitante", sa.Text(), nullable=True),
        sa.Column("observacion_tecnico", sa.Text(), nullable=True),
        sa.Column("reparada", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("fecha_reparacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orden_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["estado_reportado_id"], ["estado.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["luminaria_id"], ["luminaria.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pqrs_id"], ["pqrs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pqrs_id", "luminaria_id", name="uq_pqrs_luminaria"),
    )
    op.create_index("ix_pqrs_luminaria_luminaria", "pqrs_luminaria", ["luminaria_id"], unique=False)
    op.create_table(
        "orden_instalacion",
        sa.Column("orden_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo_valor_id", sa.BigInteger(), nullable=True),
        sa.Column("barrio_id", sa.BigInteger(), nullable=True),
        sa.Column("marca_id", sa.BigInteger(), nullable=True),
        sa.Column("poste", sa.String(length=80), nullable=True),
        sa.Column("longitud_brazo", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("referencia", sa.String(length=255), nullable=True),
        sa.Column("novedades", sa.Text(), nullable=True),
        sa.Column("destino_desmontada", sa.String(length=10), nullable=True),
        sa.Column("comentario", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["barrio_id"], ["barrio.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["marca_id"], ["maestro_valor.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["orden_id"], ["orden_trabajo.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tipo_valor_id"], ["maestro_valor.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("orden_id"),
    )
    op.create_table(
        "orden_luminaria",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("orden_id", sa.BigInteger(), nullable=False),
        sa.Column("luminaria_id", sa.BigInteger(), nullable=False),
        sa.Column("rol", sa.String(length=12), nullable=False),
        sa.CheckConstraint(
            "rol IN ('intervenida', 'instalada', 'desmontada')", name="ck_orden_luminaria_rol"
        ),
        sa.ForeignKeyConstraint(["luminaria_id"], ["luminaria.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["orden_id"], ["orden_trabajo.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("orden_id", "luminaria_id", "rol", name="uq_orden_luminaria_rol"),
    )
    op.create_index(
        "ix_orden_luminaria_luminaria", "orden_luminaria", ["luminaria_id"], unique=False
    )
    op.create_table(
        "orden_mantenimiento",
        sa.Column("orden_id", sa.BigInteger(), nullable=False),
        sa.Column("sitio_arreglo", sa.String(length=255), nullable=True),
        sa.Column("quien_recibe", sa.String(length=160), nullable=True),
        sa.Column("observacion_tecnica", sa.Text(), nullable=True),
        sa.Column(
            "requiere_desmonte", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("causal_desmonte", sa.String(length=255), nullable=True),
        sa.Column("luminaria_reemplazo_id", sa.BigInteger(), nullable=True),
        sa.Column("destino_desmontada", sa.String(length=10), nullable=True),
        sa.Column("componentes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["luminaria_reemplazo_id"], ["luminaria.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["orden_id"], ["orden_trabajo.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("orden_id"),
    )


def downgrade() -> None:
    op.drop_table("orden_mantenimiento")
    op.drop_index("ix_orden_luminaria_luminaria", table_name="orden_luminaria")
    op.drop_table("orden_luminaria")
    op.drop_table("orden_instalacion")
    op.drop_index("ix_pqrs_luminaria_luminaria", table_name="pqrs_luminaria")
    op.drop_table("pqrs_luminaria")
    op.drop_index(
        "uq_orden_sede_uuid_origen",
        table_name="orden_trabajo",
        postgresql_where=sa.text("uuid_origen IS NOT NULL"),
    )
    op.drop_index("ix_orden_tecnico", table_name="orden_trabajo")
    op.drop_index("ix_orden_sede_estado", table_name="orden_trabajo")
    op.drop_index("ix_orden_sede_creado", table_name="orden_trabajo")
    op.drop_index("ix_orden_pqrs", table_name="orden_trabajo")
    op.drop_table("orden_trabajo")
    op.drop_index("ix_pqrs_sede_fecha", table_name="pqrs")
    op.drop_index("ix_pqrs_ciudadano", table_name="pqrs")
    op.drop_table("pqrs")
    op.drop_index("ix_ciudadano_sede", table_name="ciudadano")
    op.drop_index("ix_ciudadano_nombre_trgm", table_name="ciudadano", postgresql_using="gin")
    op.drop_table("ciudadano")
    op.drop_index(
        "uq_movimiento_sede_uuid_origen",
        table_name="movimiento_material",
        postgresql_where=sa.text("uuid_origen IS NOT NULL"),
    )
    op.drop_index("ix_movimiento_material_orden", table_name="movimiento_material")
    op.drop_index("ix_movimiento_material_material", table_name="movimiento_material")
    op.drop_table("movimiento_material")
    op.drop_index("ix_cuadrilla_tecnico_usuario", table_name="cuadrilla_tecnico")
    op.drop_table("cuadrilla_tecnico")
    op.drop_index("ix_cargue_masivo_sede", table_name="cargue_masivo")
    op.drop_table("cargue_masivo")
    op.drop_index("ix_cargue_bodega_sede", table_name="cargue_bodega")
    op.drop_table("cargue_bodega")
    op.drop_index("uq_material_sede_codigo", table_name="material")
    op.drop_table("material")
    op.drop_index("uq_cuadrilla_sede_nombre", table_name="cuadrilla")
    op.drop_table("cuadrilla")
    op.execute("DROP FUNCTION IF EXISTS sapef_unaccent(text)")
