"""Extensiones de PostgreSQL que usa el sistema.

Revisión: 0001
Anterior: ninguna
Fecha: 2026-11-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def downgrade() -> None:
    # No se eliminan: otras bases del mismo servidor podrían depender de ellas,
    # y PostGIS no se puede quitar si hay columnas geográficas.
    pass
