"""Repositorio SQLAlchemy del módulo comercial (cargues y hallazgos). El almacén Parquet está en
`repositorio.almacen`."""

import zlib

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modulos.comercial.modelos import CargueComercial, HallazgoComercial


def agregar(db: Session, objeto: CargueComercial | HallazgoComercial) -> None:
    db.add(objeto)
    db.flush()


def bloquear_corte(db: Session, sede_id: int, comercializador_id: int, periodo: str) -> None:
    """Serializa la publicación o eliminación de un mismo corte (candado de transacción)."""
    clave = zlib.crc32(f"{sede_id}:{comercializador_id}:{periodo}".encode())
    db.execute(text("SELECT pg_advisory_xact_lock(:a, :b)"), {"a": 4301, "b": clave - (1 << 31)})


def obtener_cargue(db: Session, sede_id: int, cargue_id: int) -> CargueComercial | None:
    return db.execute(
        select(CargueComercial).where(
            CargueComercial.id == cargue_id, CargueComercial.sede_id == sede_id
        )
    ).scalar_one_or_none()


def obtener_cargue_por_id(
    db: Session, cargue_id: int, *, bloquear: bool = False
) -> CargueComercial | None:
    stmt = select(CargueComercial).where(CargueComercial.id == cargue_id)
    if bloquear:
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def obtener_por_idempotencia(db: Session, sede_id: int, clave: str) -> CargueComercial | None:
    return db.execute(
        select(CargueComercial).where(
            CargueComercial.sede_id == sede_id, CargueComercial.idempotency_key == clave
        )
    ).scalar_one_or_none()


def listar_cargues(
    db: Session, sede_id: int, comercializador_id: int, *, limite: int = 200
) -> list[CargueComercial]:
    return list(
        db.execute(
            select(CargueComercial)
            .where(
                CargueComercial.sede_id == sede_id,
                CargueComercial.comercializador_id == comercializador_id,
            )
            .order_by(CargueComercial.id.desc())
            .limit(limite)
        ).scalars()
    )


def cargue_publicado(
    db: Session, sede_id: int, comercializador_id: int, periodo: str, *, bloquear: bool = False
) -> CargueComercial | None:
    stmt = select(CargueComercial).where(
        CargueComercial.sede_id == sede_id,
        CargueComercial.comercializador_id == comercializador_id,
        CargueComercial.periodo == periodo,
        CargueComercial.estado == "publicado",
    )
    if bloquear:
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def publicados(db: Session, sede_id: int, comercializador_id: int) -> list[CargueComercial]:
    return list(
        db.execute(
            select(CargueComercial)
            .where(
                CargueComercial.sede_id == sede_id,
                CargueComercial.comercializador_id == comercializador_id,
                CargueComercial.estado == "publicado",
            )
            .order_by(CargueComercial.periodo)
        ).scalars()
    )


def obtener_hallazgo(
    db: Session, sede_id: int, comercializador_id: int, hallazgo_id: int
) -> HallazgoComercial | None:
    return db.execute(
        select(HallazgoComercial).where(
            HallazgoComercial.id == hallazgo_id,
            HallazgoComercial.sede_id == sede_id,
            HallazgoComercial.comercializador_id == comercializador_id,
        )
    ).scalar_one_or_none()


def listar_hallazgos(
    db: Session, sede_id: int, comercializador_id: int, estado: str | None
) -> list[HallazgoComercial]:
    stmt = select(HallazgoComercial).where(
        HallazgoComercial.sede_id == sede_id,
        HallazgoComercial.comercializador_id == comercializador_id,
    )
    if estado:
        stmt = stmt.where(HallazgoComercial.estado == estado)
    return list(db.execute(stmt.order_by(HallazgoComercial.id.desc())).scalars())
