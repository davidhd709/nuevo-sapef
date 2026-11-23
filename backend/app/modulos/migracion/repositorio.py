"""Repositorio SQLAlchemy del módulo de migración."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modulos.migracion.modelos import EjecucionMigracion


def crear_ejecucion(db: Session, ejecucion: EjecucionMigracion) -> EjecucionMigracion:
    db.add(ejecucion)
    db.flush()
    return ejecucion


def obtener_ejecucion(
    db: Session, sede_id: int, ejecucion_id: int
) -> EjecucionMigracion | None:
    return db.execute(
        select(EjecucionMigracion).where(
            EjecucionMigracion.id == ejecucion_id,
            EjecucionMigracion.sede_id == sede_id,
        )
    ).scalar_one_or_none()
