"""Repositorio SQLAlchemy del módulo de inventario."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modulos.inventario.modelos import CargueBodega, Material, MovimientoMaterial


def listar_materiales(
    db: Session,
    sede_id: int,
    *,
    page: int,
    size: int,
    buscar: str | None = None,
    categoria: str | None = None,
    bajo_minimo: bool | None = None,
    activo: bool | None = None,
) -> tuple[list[Material], int]:
    filtros = [Material.sede_id == sede_id]
    if buscar:
        patron = f"%{buscar.strip().lower()}%"
        filtros.append(
            or_(
                func.lower(Material.codigo).like(patron),
                func.lower(Material.descripcion).like(patron),
            )
        )
    if categoria:
        filtros.append(func.lower(Material.categoria) == categoria.strip().lower())
    if bajo_minimo is True:
        filtros.append(Material.existencias < Material.existencias_minimas)
    elif bajo_minimo is False:
        filtros.append(Material.existencias >= Material.existencias_minimas)
    if activo is not None:
        filtros.append(Material.activo.is_(activo))
    total = int(db.execute(select(func.count(Material.id)).where(*filtros)).scalar_one())
    filas = db.execute(
        select(Material)
        .where(*filtros)
        .order_by(Material.categoria, Material.codigo)
        .offset((page - 1) * size)
        .limit(size)
    ).scalars()
    return list(filas), total


def obtener_material(
    db: Session, sede_id: int, material_id: int, *, bloquear: bool = False
) -> Material | None:
    stmt = select(Material).where(Material.id == material_id, Material.sede_id == sede_id)
    if bloquear:
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def existe_codigo(db: Session, sede_id: int, codigo: str) -> bool:
    return (
        db.execute(
            select(Material.id).where(
                Material.sede_id == sede_id, func.lower(Material.codigo) == codigo.lower()
            )
        ).first()
        is not None
    )


def obtener_movimiento_por_uuid(
    db: Session, sede_id: int, uuid_origen: UUID
) -> MovimientoMaterial | None:
    return db.execute(
        select(MovimientoMaterial).where(
            MovimientoMaterial.sede_id == sede_id, MovimientoMaterial.uuid_origen == uuid_origen
        )
    ).scalar_one_or_none()


def listar_movimientos(
    db: Session,
    sede_id: int,
    *,
    material_id: int | None = None,
    orden_id: int | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    page: int = 1,
    size: int = 100,
) -> tuple[list[tuple[MovimientoMaterial, str]], int]:
    filtros = [MovimientoMaterial.sede_id == sede_id]
    if material_id is not None:
        filtros.append(MovimientoMaterial.material_id == material_id)
    if orden_id is not None:
        filtros.append(MovimientoMaterial.orden_id == orden_id)
    if desde is not None:
        filtros.append(MovimientoMaterial.creado_en >= desde)
    if hasta is not None:
        filtros.append(MovimientoMaterial.creado_en <= hasta)
    total = int(db.execute(select(func.count(MovimientoMaterial.id)).where(*filtros)).scalar_one())
    filas = db.execute(
        select(MovimientoMaterial, Material.codigo)
        .join(Material, Material.id == MovimientoMaterial.material_id)
        .where(*filtros)
        .order_by(MovimientoMaterial.creado_en.desc(), MovimientoMaterial.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return [(m, c) for m, c in filas], total


def obtener_cargue(db: Session, sede_id: int, cargue_id: int) -> CargueBodega | None:
    return db.execute(
        select(CargueBodega).where(CargueBodega.id == cargue_id, CargueBodega.sede_id == sede_id)
    ).scalar_one_or_none()


def obtener_cargue_por_id(db: Session, cargue_id: int) -> CargueBodega | None:
    return db.get(CargueBodega, cargue_id)


def materiales_activos(db: Session, sede_id: int) -> list[Material]:
    return list(
        db.execute(
            select(Material)
            .where(Material.sede_id == sede_id, Material.activo.is_(True))
            .order_by(Material.categoria, Material.descripcion)
        ).scalars()
    )


def material_por_codigo(db: Session, sede_id: int, codigo: str) -> Material | None:
    return db.execute(
        select(Material)
        .where(Material.sede_id == sede_id, func.lower(Material.codigo) == codigo.lower())
        .with_for_update()
    ).scalar_one_or_none()
