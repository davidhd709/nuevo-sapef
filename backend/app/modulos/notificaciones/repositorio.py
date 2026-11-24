"""Repositorio SQLAlchemy del módulo de notificaciones."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modulos.notificaciones.modelos import SuscripcionPush


def obtener_por_endpoint(db: Session, endpoint: str) -> SuscripcionPush | None:
    return db.execute(
        select(SuscripcionPush).where(SuscripcionPush.endpoint == endpoint)
    ).scalar_one_or_none()


def agregar(db: Session, suscripcion: SuscripcionPush) -> SuscripcionPush:
    db.add(suscripcion)
    db.flush()
    return suscripcion


def borrar_de_usuario(db: Session, usuario_id: int, endpoint: str) -> int:
    resultado = db.execute(
        delete(SuscripcionPush).where(
            SuscripcionPush.usuario_id == usuario_id, SuscripcionPush.endpoint == endpoint
        )
    )
    return int(resultado.rowcount or 0)  # type: ignore[attr-defined]


def listar_de_usuarios(db: Session, usuario_ids: list[int]) -> list[SuscripcionPush]:
    return list(
        db.execute(
            select(SuscripcionPush)
            .where(SuscripcionPush.usuario_id.in_(usuario_ids))
            .order_by(SuscripcionPush.id)
        ).scalars()
    )


def borrar(db: Session, suscripcion: SuscripcionPush) -> None:
    db.delete(suscripcion)
