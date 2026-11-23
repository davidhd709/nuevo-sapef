"""Repositorio SQLAlchemy del módulo de trabajos."""

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.modulos.trabajos.modelos import (
    CargueMasivo,
    Cuadrilla,
    CuadrillaTecnico,
    OrdenLuminaria,
    OrdenTrabajo,
)

_LLAVE_CONSECUTIVO_ORDEN = 4201


def siguiente_numero(db: Session, sede_id: int) -> int:
    """Consecutivo por sede; el candado de transacción serializa a quienes crean a la vez."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(:k, :s)"), {"k": _LLAVE_CONSECUTIVO_ORDEN, "s": sede_id}
    )
    actual = db.execute(
        select(func.coalesce(func.max(OrdenTrabajo.numero), 0)).where(
            OrdenTrabajo.sede_id == sede_id
        )
    ).scalar_one()
    return int(actual) + 1


# --- Cuadrillas ---------------------------------------------------------------------------------


def listar_cuadrillas(db: Session, sede_id: int, activa: bool | None = None) -> list[Cuadrilla]:
    stmt = select(Cuadrilla).where(Cuadrilla.sede_id == sede_id)
    if activa is not None:
        stmt = stmt.where(Cuadrilla.activa.is_(activa))
    return list(db.execute(stmt.order_by(Cuadrilla.nombre)).scalars())


def obtener_cuadrilla(db: Session, sede_id: int, cuadrilla_id: int) -> Cuadrilla | None:
    return db.execute(
        select(Cuadrilla).where(Cuadrilla.id == cuadrilla_id, Cuadrilla.sede_id == sede_id)
    ).scalar_one_or_none()


def existe_cuadrilla(db: Session, sede_id: int, nombre: str, excluir_id: int | None = None) -> bool:
    stmt = select(Cuadrilla.id).where(
        Cuadrilla.sede_id == sede_id, func.lower(Cuadrilla.nombre) == nombre.lower()
    )
    if excluir_id is not None:
        stmt = stmt.where(Cuadrilla.id != excluir_id)
    return db.execute(stmt).first() is not None


def cuadrillas_de_usuario(db: Session, usuario_id: int) -> list[int]:
    return list(
        db.execute(
            select(CuadrillaTecnico.cuadrilla_id).where(CuadrillaTecnico.usuario_id == usuario_id)
        ).scalars()
    )


# --- Órdenes ------------------------------------------------------------------------------------


def listar_ordenes(
    db: Session,
    sede_id: int,
    *,
    page: int,
    size: int,
    tipo: str | None = None,
    estado_id: int | None = None,
    tecnico_id: int | None = None,
    cuadrilla_id: int | None = None,
    pqrs_id: int | None = None,
    luminaria_id: int | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    solo_de_usuario: int | None = None,
) -> tuple[list[OrdenTrabajo], int]:
    filtros: list[Any] = [OrdenTrabajo.sede_id == sede_id]
    for columna, valor in (
        (OrdenTrabajo.tipo, tipo),
        (OrdenTrabajo.estado_id, estado_id),
        (OrdenTrabajo.tecnico_id, tecnico_id),
        (OrdenTrabajo.cuadrilla_id, cuadrilla_id),
        (OrdenTrabajo.pqrs_id, pqrs_id),
    ):
        if valor is not None:
            filtros.append(columna == valor)
    if luminaria_id is not None:
        filtros.append(
            OrdenTrabajo.id.in_(
                select(OrdenLuminaria.orden_id).where(OrdenLuminaria.luminaria_id == luminaria_id)
            )
        )
    if desde is not None:
        filtros.append(OrdenTrabajo.creado_en >= desde)
    if hasta is not None:
        filtros.append(OrdenTrabajo.creado_en <= hasta)
    if solo_de_usuario is not None:
        # trabajos.orden.ver_propias: lo asignado a la persona o a una cuadrilla suya.
        filtros.append(
            or_(
                OrdenTrabajo.tecnico_id == solo_de_usuario,
                OrdenTrabajo.cuadrilla_id.in_(
                    select(CuadrillaTecnico.cuadrilla_id).where(
                        CuadrillaTecnico.usuario_id == solo_de_usuario
                    )
                ),
            )
        )
    total = int(db.execute(select(func.count(OrdenTrabajo.id)).where(*filtros)).scalar_one())
    filas = db.execute(
        select(OrdenTrabajo)
        .where(*filtros)
        .order_by(OrdenTrabajo.creado_en.desc(), OrdenTrabajo.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).scalars()
    return list(filas), total


def obtener_orden(
    db: Session, sede_id: int, orden_id: int, *, bloquear: bool = False
) -> OrdenTrabajo | None:
    stmt = select(OrdenTrabajo).where(OrdenTrabajo.id == orden_id, OrdenTrabajo.sede_id == sede_id)
    if bloquear:
        stmt = stmt.with_for_update(of=OrdenTrabajo)
    return db.execute(stmt).scalar_one_or_none()


def coordenadas_orden(db: Session, orden_id: int) -> tuple[float | None, float | None]:
    fila = db.execute(
        select(func.ST_Y(OrdenTrabajo.ubicacion), func.ST_X(OrdenTrabajo.ubicacion)).where(
            OrdenTrabajo.id == orden_id
        )
    ).first()
    if fila is None or fila[0] is None:
        return None, None
    return float(fila[0]), float(fila[1])


# --- Cargue masivo ------------------------------------------------------------------------------


def obtener_cargue(db: Session, sede_id: int, cargue_id: int) -> CargueMasivo | None:
    return db.execute(
        select(CargueMasivo).where(CargueMasivo.id == cargue_id, CargueMasivo.sede_id == sede_id)
    ).scalar_one_or_none()


def obtener_cargue_por_id(db: Session, cargue_id: int) -> CargueMasivo | None:
    return db.get(CargueMasivo, cargue_id)
