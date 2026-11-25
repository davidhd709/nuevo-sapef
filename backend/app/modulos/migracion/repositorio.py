"""Repositorio SQLAlchemy del módulo de migración."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modulos.migracion.modelos import EjecucionMigracion


def crear_ejecucion(db: Session, ejecucion: EjecucionMigracion) -> EjecucionMigracion:
    db.add(ejecucion)
    db.flush()
    return ejecucion


def obtener_ejecucion(db: Session, sede_id: int, ejecucion_id: int) -> EjecucionMigracion | None:
    return db.execute(
        select(EjecucionMigracion).where(
            EjecucionMigracion.id == ejecucion_id,
            EjecucionMigracion.sede_id == sede_id,
        )
    ).scalar_one_or_none()


def obtener_ejecucion_por_id(db: Session, ejecucion_id: int) -> EjecucionMigracion | None:
    """Para el worker, que recibe solo el id (la sede va en la ejecución)."""
    return db.get(EjecucionMigracion, ejecucion_id, populate_existing=True)


def listar_ejecuciones(
    db: Session, sede_id: int, tipos: list[str], limite: int
) -> list[EjecucionMigracion]:
    return list(
        db.execute(
            select(EjecucionMigracion)
            .where(EjecucionMigracion.sede_id == sede_id, EjecucionMigracion.tipo.in_(tipos))
            .order_by(EjecucionMigracion.id.desc())
            .limit(limite)
        ).scalars()
    )
