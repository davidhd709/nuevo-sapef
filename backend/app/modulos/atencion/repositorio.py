"""Repositorio SQLAlchemy del módulo de atención."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.modulos.atencion.modelos import Ciudadano, Pqrs, PqrsLuminaria

_LLAVE_CONSECUTIVO_PQRS = 4101
ZONA_HORARIA = "America/Bogota"  # los días del semáforo se cuentan en hora local


def siguiente_numero(db: Session, sede_id: int) -> int:
    """Consecutivo por sede. El candado de transacción serializa a quienes crean a la vez."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(:k, :s)"), {"k": _LLAVE_CONSECUTIVO_PQRS, "s": sede_id}
    )
    actual = db.execute(
        select(func.coalesce(func.max(Pqrs.numero), 0)).where(Pqrs.sede_id == sede_id)
    ).scalar_one()
    return int(actual) + 1


# --- Ciudadanos ---------------------------------------------------------------------------------


def buscar_ciudadanos(
    db: Session, sede_id: int, buscar: str | None, *, page: int, size: int
) -> tuple[list[Ciudadano], int]:
    filtros: list[Any] = [Ciudadano.sede_id == sede_id]
    orden: list[Any] = [Ciudadano.nombre_completo]
    if buscar and buscar.strip():
        termino = buscar.strip().lower()
        nombre_sin_tildes = func.sapef_unaccent(func.lower(Ciudadano.nombre_completo))
        consulta = func.sapef_unaccent(termino)
        filtros.append(
            or_(
                nombre_sin_tildes.like(func.concat("%", consulta, "%")),
                nombre_sin_tildes.op("%")(consulta),
                # Identificación sin distinguir mayúsculas ni puntos/espacios (50.929.069).
                func.replace(
                    func.replace(func.lower(Ciudadano.identificacion), ".", ""), " ", ""
                ).like(termino.replace(".", "").replace(" ", "") + "%"),
            )
        )
        orden = [func.similarity(nombre_sin_tildes, consulta).desc(), *orden]
    total = int(db.execute(select(func.count(Ciudadano.id)).where(*filtros)).scalar_one())
    filas = db.execute(
        select(Ciudadano).where(*filtros).order_by(*orden).offset((page - 1) * size).limit(size)
    ).scalars()
    return list(filas), total


def obtener_ciudadano(db: Session, sede_id: int, ciudadano_id: int) -> Ciudadano | None:
    return db.execute(
        select(Ciudadano).where(Ciudadano.id == ciudadano_id, Ciudadano.sede_id == sede_id)
    ).scalar_one_or_none()


def existe_identificacion(db: Session, sede_id: int, identificacion: str) -> bool:
    return (
        db.execute(
            select(Ciudadano.id).where(
                Ciudadano.sede_id == sede_id, Ciudadano.identificacion == identificacion
            )
        ).first()
        is not None
    )


def ciudadanos_por_ids(db: Session, ids: list[int]) -> dict[int, Ciudadano]:
    if not ids:
        return {}
    filas = db.execute(select(Ciudadano).where(Ciudadano.id.in_(ids))).scalars()
    return {c.id: c for c in filas}


# --- PQRS ---------------------------------------------------------------------------------------


def listar_pqrs(
    db: Session,
    sede_id: int,
    *,
    page: int,
    size: int,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    estado_id: int | None = None,
    prioridad: int | None = None,
    barrio_id: int | None = None,
    numero: int | None = None,
    ciudadano_id: int | None = None,
) -> tuple[list[Pqrs], int]:
    filtros: list[Any] = [Pqrs.sede_id == sede_id]
    if numero is not None:
        filtros.append(Pqrs.numero == numero)
    else:
        if desde is not None:
            filtros.append(Pqrs.fecha_solicitud >= desde)
        if hasta is not None:
            filtros.append(Pqrs.fecha_solicitud <= hasta)
    if estado_id is not None:
        filtros.append(Pqrs.estado_id == estado_id)
    if prioridad is not None:
        filtros.append(Pqrs.prioridad == prioridad)
    if ciudadano_id is not None:
        filtros.append(Pqrs.ciudadano_id == ciudadano_id)
    if barrio_id is not None:
        filtros.append(
            Pqrs.ciudadano_id.in_(select(Ciudadano.id).where(Ciudadano.barrio_id == barrio_id))
        )
    total = int(db.execute(select(func.count(Pqrs.id)).where(*filtros)).scalar_one())
    filas = db.execute(
        select(Pqrs)
        .where(*filtros)
        .order_by(Pqrs.fecha_solicitud.desc(), Pqrs.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).scalars()
    return list(filas), total


def obtener_pqrs(db: Session, sede_id: int, pqrs_id: int, *, bloquear: bool = False) -> Pqrs | None:
    stmt = select(Pqrs).where(Pqrs.id == pqrs_id, Pqrs.sede_id == sede_id)
    if bloquear:
        stmt = stmt.with_for_update(of=Pqrs)
    return db.execute(stmt).scalar_one_or_none()


def otras_pqrs_abiertas_con_luminaria(
    db: Session, luminaria_id: int, excluir_pqrs_id: int, estados_abiertos_ids: list[int]
) -> int:
    """Cuántas otras PQRS abiertas tienen esa luminaria sin reparar (para devolverla a 121)."""
    return int(
        db.execute(
            select(func.count(PqrsLuminaria.id))
            .join(Pqrs, Pqrs.id == PqrsLuminaria.pqrs_id)
            .where(
                PqrsLuminaria.luminaria_id == luminaria_id,
                PqrsLuminaria.reparada.is_(False),
                PqrsLuminaria.pqrs_id != excluir_pqrs_id,
                Pqrs.estado_id.in_(estados_abiertos_ids),
            )
        ).scalar_one()
    )


# --- Luminarias pendientes (RF-035) ---------------------------------------------------------
# Consulta de solo lectura que une las tablas de activos y configuración para paginar en SQL;
# las escrituras sobre luminarias pasan siempre por el servicio de activos.

_SQL_PENDIENTES = """
    FROM pqrs_luminaria pl
    JOIN pqrs p ON p.id = pl.pqrs_id
    JOIN estado ep ON ep.id = p.estado_id
    JOIN luminaria l ON l.id = pl.luminaria_id
    LEFT JOIN barrio b ON b.id = l.barrio_id
    LEFT JOIN estado er ON er.id = pl.estado_reportado_id
    LEFT JOIN ciudadano c ON c.id = p.ciudadano_id
    WHERE p.sede_id = :sede_id
      AND pl.reparada = false
      AND ep.codigo = ANY(:abiertos)
"""
_SQL_DIAS = (
    f"((now() AT TIME ZONE '{ZONA_HORARIA}')::date"
    f" - (p.fecha_solicitud AT TIME ZONE '{ZONA_HORARIA}')::date)"
)


def listar_pendientes(
    db: Session,
    sede_id: int,
    *,
    abiertos: list[str],
    verde_max: int,
    amarillo_max: int,
    semaforo: str | None,
    barrio_id: int | None,
    prioridad: int | None,
    page: int,
    size: int,
) -> tuple[list[dict[str, Any]], int]:
    condiciones = ""
    params: dict[str, Any] = {"sede_id": sede_id, "abiertos": abiertos}
    if semaforo == "verde":
        condiciones += f" AND {_SQL_DIAS} <= :verde"
    elif semaforo == "amarillo":
        condiciones += f" AND {_SQL_DIAS} > :verde AND {_SQL_DIAS} <= :amarillo"
    elif semaforo == "rojo":
        condiciones += f" AND {_SQL_DIAS} > :amarillo"
    params |= {"verde": verde_max, "amarillo": amarillo_max}
    if barrio_id is not None:
        condiciones += " AND l.barrio_id = :barrio_id"
        params["barrio_id"] = barrio_id
    if prioridad is not None:
        condiciones += " AND p.prioridad = :prioridad"
        params["prioridad"] = prioridad
    total = int(
        db.execute(text(f"SELECT count(*) {_SQL_PENDIENTES} {condiciones}"), params).scalar_one()
    )
    filas = db.execute(
        text(
            f"""
            SELECT p.id AS pqrs_id, p.numero AS pqrs_numero, l.id AS luminaria_id,
                   l.codigo AS luminaria_codigo, b.nombre AS barrio_nombre,
                   er.codigo AS estado_reportado_codigo, p.prioridad,
                   c.nombre_completo AS solicitante,
                   (p.fecha_solicitud AT TIME ZONE '{ZONA_HORARIA}')::date AS fecha_reporte,
                   {_SQL_DIAS} AS dias_abierta,
                   ST_Y(l.ubicacion::geometry) AS latitud, ST_X(l.ubicacion::geometry) AS longitud
            {_SQL_PENDIENTES} {condiciones}
            ORDER BY dias_abierta DESC, p.prioridad, p.numero
            LIMIT :limite OFFSET :desplazamiento
            """
        ),
        {**params, "limite": size, "desplazamiento": (page - 1) * size},
    ).mappings()
    return [dict(f) for f in filas], total


def filas_exportacion(
    db: Session,
    sede_id: int,
    *,
    estado_id: int | None,
    prioridad: int | None,
    desde: date | None,
    hasta: date | None,
) -> list[dict[str, Any]]:
    condiciones = ["p.sede_id = :sede_id"]
    params: dict[str, Any] = {"sede_id": sede_id}
    for campo, valor, sql in (
        ("estado_id", estado_id, "p.estado_id = :estado_id"),
        ("prioridad", prioridad, "p.prioridad = :prioridad"),
        ("desde", desde, f"(p.fecha_solicitud AT TIME ZONE '{ZONA_HORARIA}')::date >= :desde"),
        ("hasta", hasta, f"(p.fecha_solicitud AT TIME ZONE '{ZONA_HORARIA}')::date <= :hasta"),
    ):
        if valor is not None:
            condiciones.append(sql)
            params[campo] = valor
    # Solo se concatenan fragmentos fijos de este archivo; los valores van como parámetros.
    sql = f"""
            SELECT p.numero, p.fecha_solicitud, mv.nombre AS canal, p.prioridad,
                   ep.nombre AS estado, c.identificacion, c.nombre_completo, c.telefono,
                   c.celular, c.correo, l.codigo AS luminaria, b.nombre AS barrio,
                   pl.reparada, pl.fecha_reparacion, p.observacion_solicitante, p.fecha_cierre
            FROM pqrs p
            JOIN estado ep ON ep.id = p.estado_id
            JOIN maestro_valor mv ON mv.id = p.canal_id
            JOIN pqrs_luminaria pl ON pl.pqrs_id = p.id
            JOIN luminaria l ON l.id = pl.luminaria_id
            LEFT JOIN barrio b ON b.id = l.barrio_id
            LEFT JOIN ciudadano c ON c.id = p.ciudadano_id
            WHERE {" AND ".join(condiciones)}
            ORDER BY p.numero, l.codigo
            LIMIT 200000
            """  # noqa: S608
    filas = db.execute(text(sql), params).mappings()
    return [dict(f) for f in filas]


# --- Migración (HU-034) -------------------------------------------------------------------------


def ciudadano_por_identificacion(
    db: Session, sede_id: int, identificacion: str
) -> Ciudadano | None:
    return db.execute(
        select(Ciudadano).where(
            Ciudadano.sede_id == sede_id, Ciudadano.identificacion == identificacion
        )
    ).scalar_one_or_none()


def pqrs_por_id_origen(db: Session, sede_id: int, id_origen: str) -> int | None:
    return db.execute(
        select(Pqrs.id).where(Pqrs.sede_id == sede_id, Pqrs.id_origen == id_origen)
    ).scalar_one_or_none()
