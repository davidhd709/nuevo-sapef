"""Repositorio SQLAlchemy del módulo de configuración."""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modulos.configuracion.modelos import (
    AcuerdoVigencia,
    Barrio,
    Comercializador,
    ConceptoComercial,
    Estado,
    MaestroClase,
    MaestroValor,
    OperacionContable,
    Parametro,
    PlantillaCorreo,
    Sede,
    SedeComercializador,
    Zona,
)

# --- Sedes y comercializadores ---------------------------------------------------------------


def listar_sedes(db: Session, ids: set[int] | None = None) -> list[Sede]:
    stmt = select(Sede).order_by(Sede.id)
    if ids is not None:
        stmt = stmt.where(Sede.id.in_(ids))
    return list(db.execute(stmt).scalars().all())


def obtener_sede(db: Session, sede_id: int) -> Sede | None:
    return db.get(Sede, sede_id)


def obtener_sede_por_codigo(db: Session, codigo: str) -> Sede | None:
    return db.execute(select(Sede).where(Sede.codigo == codigo)).scalar_one_or_none()


def listar_comercializadores(db: Session) -> list[Comercializador]:
    return list(db.execute(select(Comercializador).order_by(Comercializador.id)).scalars().all())


def obtener_comercializador_por_codigo(db: Session, codigo: str) -> Comercializador | None:
    return db.execute(
        select(Comercializador).where(Comercializador.codigo == codigo.strip().lower())
    ).scalar_one_or_none()


def listar_asignaciones_sede(db: Session, sede_id: int) -> list[SedeComercializador]:
    stmt = (
        select(SedeComercializador)
        .where(SedeComercializador.sede_id == sede_id)
        .order_by(SedeComercializador.comercializador_id)
    )
    return list(db.execute(stmt).unique().scalars().all())


def obtener_asignacion(
    db: Session, sede_id: int, comercializador_id: int
) -> SedeComercializador | None:
    return db.get(SedeComercializador, (sede_id, comercializador_id))


# --- Maestros --------------------------------------------------------------------------------


def listar_clases_con_conteo(db: Session) -> list[tuple[MaestroClase, int]]:
    conteo = (
        select(MaestroValor.clase_id, func.count(MaestroValor.id).label("n"))
        .group_by(MaestroValor.clase_id)
        .subquery()
    )
    stmt = (
        select(MaestroClase, func.coalesce(conteo.c.n, 0))
        .outerjoin(conteo, conteo.c.clase_id == MaestroClase.id)
        .order_by(MaestroClase.codigo)
    )
    return [(c, int(n)) for c, n in db.execute(stmt).all()]


def obtener_clase_por_codigo(db: Session, codigo: str) -> MaestroClase | None:
    return db.execute(
        select(MaestroClase).where(MaestroClase.codigo == codigo)
    ).scalar_one_or_none()


def listar_valores(
    db: Session, clase_id: int, *, activo: bool | None = None, buscar: str | None = None
) -> list[MaestroValor]:
    stmt = select(MaestroValor).where(MaestroValor.clase_id == clase_id)
    if activo is not None:
        stmt = stmt.where(MaestroValor.activo.is_(activo))
    if buscar:
        patron = f"%{buscar.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(MaestroValor.codigo).like(patron),
                func.lower(MaestroValor.nombre).like(patron),
            )
        )
    stmt = stmt.order_by(MaestroValor.orden, MaestroValor.codigo)
    return list(db.execute(stmt).scalars().all())


def obtener_valor(db: Session, clase_id: int, valor_id: int) -> MaestroValor | None:
    return db.execute(
        select(MaestroValor).where(MaestroValor.id == valor_id, MaestroValor.clase_id == clase_id)
    ).scalar_one_or_none()


def existe_valor_codigo(db: Session, clase_id: int, codigo: str) -> bool:
    return (
        db.execute(
            select(MaestroValor.id).where(
                MaestroValor.clase_id == clase_id, MaestroValor.codigo == codigo
            )
        ).first()
        is not None
    )


# --- Zonas y barrios ---------------------------------------------------------------------------


def listar_zonas_con_conteo(
    db: Session, sede_id: int, activa: bool | None = None
) -> list[tuple[Zona, int]]:
    conteo = (
        select(Barrio.zona_id, func.count(Barrio.id).label("n"))
        .where(Barrio.sede_id == sede_id)
        .group_by(Barrio.zona_id)
        .subquery()
    )
    stmt = (
        select(Zona, func.coalesce(conteo.c.n, 0))
        .outerjoin(conteo, conteo.c.zona_id == Zona.id)
        .where(Zona.sede_id == sede_id)
        .order_by(Zona.nombre)
    )
    if activa is not None:
        stmt = stmt.where(Zona.activa.is_(activa))
    return [(z, int(n)) for z, n in db.execute(stmt).all()]


def obtener_zona(db: Session, sede_id: int, zona_id: int) -> Zona | None:
    return db.execute(
        select(Zona).where(Zona.id == zona_id, Zona.sede_id == sede_id)
    ).scalar_one_or_none()


def existe_zona_nombre(
    db: Session, sede_id: int, nombre: str, excluir_id: int | None = None
) -> bool:
    stmt = select(Zona.id).where(
        Zona.sede_id == sede_id, func.lower(Zona.nombre) == nombre.lower()
    )
    if excluir_id is not None:
        stmt = stmt.where(Zona.id != excluir_id)
    return db.execute(stmt).first() is not None


def contar_barrios_zona(db: Session, zona_id: int) -> int:
    return int(
        db.execute(select(func.count(Barrio.id)).where(Barrio.zona_id == zona_id)).scalar_one()
    )


def listar_barrios(
    db: Session,
    sede_id: int,
    *,
    zona_id: int | None = None,
    activo: bool | None = None,
    buscar: str | None = None,
) -> list[tuple[Barrio, str]]:
    stmt = (
        select(Barrio, Zona.nombre)
        .join(Zona, Zona.id == Barrio.zona_id)
        .where(Barrio.sede_id == sede_id)
    )
    if zona_id is not None:
        stmt = stmt.where(Barrio.zona_id == zona_id)
    if activo is not None:
        stmt = stmt.where(Barrio.activo.is_(activo))
    if buscar:
        stmt = stmt.where(
            func.unaccent(func.lower(Barrio.nombre)).like(
                func.unaccent(f"%{buscar.strip().lower()}%")
            )
        )
    stmt = stmt.order_by(Zona.nombre, Barrio.nombre)
    return [(b, zn) for b, zn in db.execute(stmt).all()]


def obtener_barrio(db: Session, sede_id: int, barrio_id: int) -> tuple[Barrio, str] | None:
    fila = db.execute(
        select(Barrio, Zona.nombre)
        .join(Zona, Zona.id == Barrio.zona_id)
        .where(Barrio.id == barrio_id, Barrio.sede_id == sede_id)
    ).first()
    return (fila[0], fila[1]) if fila else None


def existe_barrio_nombre(
    db: Session, zona_id: int, nombre: str, excluir_id: int | None = None
) -> bool:
    stmt = select(Barrio.id).where(
        Barrio.zona_id == zona_id, func.lower(Barrio.nombre) == nombre.lower()
    )
    if excluir_id is not None:
        stmt = stmt.where(Barrio.id != excluir_id)
    return db.execute(stmt).first() is not None


# --- Estados ------------------------------------------------------------------------------------


def listar_estados(
    db: Session, proceso: str | None = None, vigente: bool | None = None
) -> list[Estado]:
    stmt = select(Estado)
    if proceso is not None:
        stmt = stmt.where(Estado.proceso == proceso)
    if vigente is not None:
        stmt = stmt.where(Estado.vigente.is_(vigente))
    stmt = stmt.order_by(Estado.proceso, Estado.orden, Estado.codigo)
    return list(db.execute(stmt).scalars().all())


def obtener_estado(db: Session, estado_id: int) -> Estado | None:
    return db.get(Estado, estado_id)


# --- Parámetros y plantillas -----------------------------------------------------------------


def listar_parametros_visibles(db: Session, sede_id: int) -> list[Parametro]:
    """Los de la sede y los globales que la sede no sobrescribe."""
    propios = list(
        db.execute(select(Parametro).where(Parametro.sede_id == sede_id)).scalars().all()
    )
    codigos_propios = {p.codigo for p in propios}
    globales = [
        p
        for p in db.execute(select(Parametro).where(Parametro.sede_id.is_(None))).scalars().all()
        if p.codigo not in codigos_propios
    ]
    return sorted(propios + globales, key=lambda p: p.codigo)


def obtener_parametro_visible(db: Session, sede_id: int, parametro_id: int) -> Parametro | None:
    return db.execute(
        select(Parametro).where(
            Parametro.id == parametro_id,
            or_(Parametro.sede_id == sede_id, Parametro.sede_id.is_(None)),
        )
    ).scalar_one_or_none()


def obtener_parametro_por_codigo(
    db: Session, codigo: str, sede_id: int | None
) -> Parametro | None:
    filtro = Parametro.sede_id.is_(None) if sede_id is None else Parametro.sede_id == sede_id
    return db.execute(
        select(Parametro).where(Parametro.codigo == codigo, filtro)
    ).scalar_one_or_none()


def listar_plantillas(db: Session, sede_id: int) -> list[PlantillaCorreo]:
    stmt = (
        select(PlantillaCorreo)
        .where(PlantillaCorreo.sede_id == sede_id)
        .order_by(PlantillaCorreo.codigo)
    )
    return list(db.execute(stmt).scalars().all())


def obtener_plantilla(db: Session, sede_id: int, plantilla_id: int) -> PlantillaCorreo | None:
    return db.execute(
        select(PlantillaCorreo).where(
            PlantillaCorreo.id == plantilla_id, PlantillaCorreo.sede_id == sede_id
        )
    ).scalar_one_or_none()


def obtener_plantilla_por_codigo(
    db: Session, sede_id: int, codigo: str
) -> PlantillaCorreo | None:
    return db.execute(
        select(PlantillaCorreo).where(
            PlantillaCorreo.sede_id == sede_id, PlantillaCorreo.codigo == codigo
        )
    ).scalar_one_or_none()


# --- Acuerdos ------------------------------------------------------------------------------------


def listar_acuerdos(
    db: Session,
    sede_id: int,
    *,
    comercializador_id: int | None = None,
    anio: int | None = None,
    estado: str | None = None,
) -> list[AcuerdoVigencia]:
    stmt = select(AcuerdoVigencia).where(AcuerdoVigencia.sede_id == sede_id)
    if comercializador_id is not None:
        stmt = stmt.where(AcuerdoVigencia.comercializador_id == comercializador_id)
    if anio is not None:
        stmt = stmt.where(AcuerdoVigencia.anio == anio)
    if estado is not None:
        stmt = stmt.where(AcuerdoVigencia.estado == estado)
    stmt = stmt.order_by(
        AcuerdoVigencia.anio.desc(), AcuerdoVigencia.comercializador_id, AcuerdoVigencia.id
    )
    return list(db.execute(stmt).unique().scalars().all())


def obtener_acuerdo(
    db: Session, sede_id: int, acuerdo_id: int, *, bloquear: bool = False
) -> AcuerdoVigencia | None:
    stmt = select(AcuerdoVigencia).where(
        AcuerdoVigencia.id == acuerdo_id, AcuerdoVigencia.sede_id == sede_id
    )
    if bloquear:
        stmt = stmt.with_for_update(of=AcuerdoVigencia)
    return db.execute(stmt).unique().scalar_one_or_none()


def obtener_acuerdo_en_estado(
    db: Session, sede_id: int, comercializador_id: int, anio: int, estado: str
) -> AcuerdoVigencia | None:
    return (
        db.execute(
            select(AcuerdoVigencia).where(
                AcuerdoVigencia.sede_id == sede_id,
                AcuerdoVigencia.comercializador_id == comercializador_id,
                AcuerdoVigencia.anio == anio,
                AcuerdoVigencia.estado == estado,
            )
        )
        .unique()
        .scalar_one_or_none()
    )


def existe_acuerdo(db: Session, sede_id: int, comercializador_id: int, anio: int) -> bool:
    return (
        db.execute(
            select(AcuerdoVigencia.id).where(
                AcuerdoVigencia.sede_id == sede_id,
                AcuerdoVigencia.comercializador_id == comercializador_id,
                AcuerdoVigencia.anio == anio,
            )
        ).first()
        is not None
    )


# --- Catálogos comerciales -------------------------------------------------------------------

ModeloCatalogo = type[ConceptoComercial] | type[OperacionContable]


def listar_catalogo(
    db: Session,
    modelo: ModeloCatalogo,
    *,
    comercializador_id: int | None = None,
    activo: bool | None = None,
) -> list[ConceptoComercial] | list[OperacionContable]:
    stmt = select(modelo)
    if comercializador_id is not None:
        stmt = stmt.where(modelo.comercializador_id == comercializador_id)
    if activo is not None:
        stmt = stmt.where(modelo.activo.is_(activo))
    stmt = stmt.order_by(modelo.comercializador_id, modelo.codigo)
    return list(db.execute(stmt).unique().scalars().all())


def obtener_item_catalogo(
    db: Session, modelo: ModeloCatalogo, item_id: int
) -> ConceptoComercial | OperacionContable | None:
    return db.get(modelo, item_id)


def existe_item_catalogo(
    db: Session, modelo: ModeloCatalogo, comercializador_id: int, codigo: str
) -> bool:
    return (
        db.execute(
            select(modelo.id).where(
                modelo.comercializador_id == comercializador_id, modelo.codigo == codigo
            )
        ).first()
        is not None
    )
