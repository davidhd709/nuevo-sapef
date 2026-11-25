"""R1: importadores de migración en el worker e importadores históricos de la operación.

- `ejecucion_migracion` guarda los archivos recibidos (se procesan en el worker), las
  advertencias y cuándo terminó; el estado arranca en «pendiente».
- `pqrs.id_origen` y `orden_trabajo.id_origen`: llave natural del SAPEF de origen para que los
  importadores sean repetibles (índice único parcial por sede).
- `orden_trabajo.origen` admite «migracion» (órdenes históricas, que no tocan luminarias ni
  kárdex al importarse).

Revisión: 0010
Anterior: 0009
Fecha: 2026-11-25 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ejecucion_migracion",
        sa.Column(
            "archivos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "ejecucion_migracion",
        sa.Column(
            "advertencias",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "ejecucion_migracion",
        sa.Column("procesado_en", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("ejecucion_migracion", "estado", server_default=sa.text("'pendiente'"))
    op.create_check_constraint(
        "ck_ejecucion_migracion_estado",
        "ejecucion_migracion",
        "estado IN ('pendiente', 'procesando', 'completado', 'con_errores', 'error')",
    )

    # Búsqueda de luminaria por código sin distinguir mayúsculas: era un recorrido completo de la
    # tabla en cada fila de los importadores y en cada búsqueda por código.
    op.create_index(
        "ix_luminaria_sede_codigo_lower",
        "luminaria",
        ["sede_id", sa.text("lower(codigo)")],
    )

    op.add_column("pqrs", sa.Column("id_origen", sa.String(length=80), nullable=True))
    op.create_index(
        "uq_pqrs_sede_id_origen",
        "pqrs",
        ["sede_id", "id_origen"],
        unique=True,
        postgresql_where=sa.text("id_origen IS NOT NULL"),
    )

    op.add_column("orden_trabajo", sa.Column("id_origen", sa.String(length=80), nullable=True))
    op.create_index(
        "uq_orden_sede_id_origen",
        "orden_trabajo",
        ["sede_id", "id_origen"],
        unique=True,
        postgresql_where=sa.text("id_origen IS NOT NULL"),
    )
    op.drop_constraint("ck_orden_origen", "orden_trabajo", type_="check")
    op.create_check_constraint(
        "ck_orden_origen",
        "orden_trabajo",
        "origen IN ('web', 'cargue', 'campo', 'migracion')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_orden_origen", "orden_trabajo", type_="check")
    op.execute("DELETE FROM orden_trabajo WHERE origen = 'migracion'")
    op.create_check_constraint(
        "ck_orden_origen", "orden_trabajo", "origen IN ('web', 'cargue', 'campo')"
    )
    op.drop_index("uq_orden_sede_id_origen", table_name="orden_trabajo")
    op.drop_column("orden_trabajo", "id_origen")
    op.drop_index("uq_pqrs_sede_id_origen", table_name="pqrs")
    op.drop_column("pqrs", "id_origen")
    op.drop_index("ix_luminaria_sede_codigo_lower", table_name="luminaria")
    op.drop_constraint("ck_ejecucion_migracion_estado", "ejecucion_migracion", type_="check")
    op.alter_column("ejecucion_migracion", "estado", server_default=sa.text("'completado'"))
    op.drop_column("ejecucion_migracion", "procesado_en")
    op.drop_column("ejecucion_migracion", "advertencias")
    op.drop_column("ejecucion_migracion", "archivos")
