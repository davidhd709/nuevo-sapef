"""Tablas de la cola de tareas (Procrastinate 3.12).

Revisión: 0002
Anterior: 0001
Fecha: 2026-11-21

Si se actualiza Procrastinate a otra versión menor, hay que crear una revisión nueva que aplique
los archivos de `procrastinate/sql/migrations/` correspondientes (por eso la versión está fijada
con `~=3.12.0` en pyproject.toml).
"""

from collections.abc import Sequence

from alembic import op
from procrastinate.schema import SchemaManager

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(SchemaManager.get_schema())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers, "
               "procrastinate_jobs, procrastinate_workers CASCADE")
    # Funciones y tipos de Procrastinate (todos llevan el prefijo procrastinate_).
    op.execute("""
        DO $$
        DECLARE f record;
        BEGIN
            FOR f IN SELECT p.oid::regprocedure AS firma FROM pg_proc p
                     JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname = 'public' AND p.proname LIKE 'procrastinate%'
            LOOP
                EXECUTE 'DROP FUNCTION IF EXISTS ' || f.firma || ' CASCADE';
            END LOOP;
        END $$;
    """)
    # Tipos propios (enum y compuestos independientes), sin lista fija: cambian entre versiones.
    op.execute("""
        DO $$
        DECLARE t record;
        BEGIN
            FOR t IN SELECT ty.typname FROM pg_type ty
                     JOIN pg_namespace n ON n.oid = ty.typnamespace
                     LEFT JOIN pg_class c ON c.oid = ty.typrelid
                     WHERE n.nspname = 'public' AND ty.typname LIKE 'procrastinate%'
                       AND (ty.typtype = 'e' OR (ty.typtype = 'c' AND c.relkind = 'c'))
            LOOP
                EXECUTE 'DROP TYPE IF EXISTS ' || quote_ident(t.typname) || ' CASCADE';
            END LOOP;
        END $$;
    """)
