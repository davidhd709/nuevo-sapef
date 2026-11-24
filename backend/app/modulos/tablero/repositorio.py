"""Lectura agregada para el tablero y escritura de sus tablas resumen.

Las agregaciones leen las tablas operativas con SQL de solo lectura y parámetros (sin texto del
usuario): es un modelo de lectura (ADR-009), no lógica de negocio de otros módulos. Solo corren
al recalcular (de noche, tras un corte comercial o a pedido), nunca en cada consulta del tablero.
"""

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modulos.tablero.modelos import (
    ResumenCalculo,
    ResumenComercial,
    ResumenDimension,
    ResumenLuminariaMes,
)

ZONA_HORARIA = "America/Bogota"
ESTADOS_BODEGA = ("123", "124", "125")  # bodega de baja, buena y en garantía (§13)

# (dimensión, clave, etiqueta, grupo, cantidad); el servicio lo convierte al tipo del dominio.
Dim = tuple[str, str, str, str | None, int]
_UN_DIA = timedelta(days=1)

# Parque vigente: sin comodines y sin estados finales (chatarrizada, disposición final).
_PARQUE = """
    FROM luminaria l
    JOIN estado e ON e.id = l.estado_id
    WHERE l.sede_id = :sede_id AND NOT l.es_comodin AND NOT e.final
"""
_EN_CALLE = _PARQUE + " AND e.codigo <> ALL(:bodega)"
_JOIN_MAESTRO = "LEFT JOIN maestro_valor v ON v.id = l.{columna} WHERE"


def _filas(db: Session, sql: str, params: dict[str, Any]) -> Sequence[Any]:
    return db.execute(text(sql), params).all()


# --- Agregados sobre las tablas operativas ------------------------------------------------------


def luminarias_por_mes(db: Session, sede_id: int) -> list[tuple[int, int, int]]:
    filas = _filas(
        db,
        f"""SELECT extract(year FROM l.fecha_instalacion)::int, extract(month FROM
            l.fecha_instalacion)::int, count(*) {_PARQUE} AND l.fecha_instalacion IS NOT NULL
            GROUP BY 1, 2""",  # noqa: S608 - solo fragmentos constantes; datos por parámetros
        {"sede_id": sede_id},
    )
    return [(int(a), int(m), int(c)) for a, m, c in filas]


def dimensiones_luminaria(db: Session, sede_id: int) -> list[Dim]:
    p = {"sede_id": sede_id, "bodega": list(ESTADOS_BODEGA)}
    salida: list[Dim] = []
    for dimension, columna in (("tecnologia", "tecnologia_id"), ("potencia", "potencia_id")):
        for clave, etiqueta, cantidad in _filas(
            db,
            f"""SELECT coalesce(v.codigo, 'SIN_DATO'), coalesce(v.nombre, 'Sin dato'), count(*)
                {_EN_CALLE.replace("WHERE", _JOIN_MAESTRO.format(columna=columna))}
                GROUP BY 1, 2""",
            p,
        ):
            salida.append((dimension, str(clave), str(etiqueta), None, int(cantidad)))
    for clave, etiqueta, cantidad in _filas(
        db, f"SELECT e.codigo, e.nombre, count(*) {_PARQUE} GROUP BY 1, 2", p
    ):
        salida.append(("estado", str(clave), f"{clave} · {etiqueta}", None, int(cantidad)))
    sector = _EN_CALLE.replace(
        "WHERE",
        "LEFT JOIN barrio b ON b.id = l.barrio_id LEFT JOIN zona z ON z.id = b.zona_id WHERE",
    )
    for clave, etiqueta, cantidad in _filas(
        db,
        f"""SELECT coalesce(z.id::text, '0'), coalesce(z.nombre, 'Sin zona'), count(*) {sector}
            GROUP BY 1, 2""",
        p,
    ):
        salida.append(("zona", str(clave), str(etiqueta), None, int(cantidad)))
    for clave, etiqueta, grupo, cantidad in _filas(
        db,
        f"""SELECT coalesce(b.id::text, '0'), coalesce(b.nombre, 'Sin barrio'),
                   coalesce(z.nombre, 'Sin zona'), count(*) {sector} GROUP BY 1, 2, 3""",
        p,
    ):
        salida.append(("barrio", str(clave), str(etiqueta), str(grupo), int(cantidad)))
    return salida


def operacion(
    db: Session,
    sede_id: int,
    *,
    hoy: date,
    abiertos: Sequence[str],
    verde_max: int,
    amarillo_max: int,
) -> dict[str, Any]:
    """Indicadores escalares de luminarias, PQRS, órdenes e inventario (HU-093)."""
    p: dict[str, Any] = {
        "sede_id": sede_id,
        "bodega": list(ESTADOS_BODEGA),
        "abiertos": list(abiertos),
        "verde": verde_max,
        "amarillo": amarillo_max,
        "hoy": hoy,
        "inicio_mes": hoy.replace(day=1),
        "inicio_mes_ant": (hoy.replace(day=1) - _UN_DIA).replace(day=1),
        "inicio_anio": hoy.replace(month=1, day=1),
    }
    total, bodega = db.execute(
        text(f"""SELECT count(*), count(*) FILTER (WHERE e.codigo = ANY(:bodega)) {_PARQUE}"""),
        p,
    ).one()
    dias = f"(:hoy - (p.fecha_solicitud AT TIME ZONE '{ZONA_HORARIA}')::date)"
    local = f"(p.fecha_solicitud AT TIME ZONE '{ZONA_HORARIA}')::date"
    cierre = f"(p.fecha_cierre AT TIME ZONE '{ZONA_HORARIA}')::date"
    pq = db.execute(
        text(
            f"""
            SELECT
              count(*) FILTER (WHERE e.codigo = ANY(:abiertos)),
              count(*) FILTER (WHERE e.codigo = ANY(:abiertos) AND {dias} <= :verde),
              count(*) FILTER (WHERE e.codigo = ANY(:abiertos) AND {dias} > :verde
                               AND {dias} <= :amarillo),
              count(*) FILTER (WHERE e.codigo = ANY(:abiertos) AND {dias} > :amarillo),
              count(*) FILTER (WHERE {local} >= :inicio_mes),
              count(*) FILTER (WHERE {local} >= :inicio_mes_ant AND {local} < :inicio_mes),
              count(*) FILTER (WHERE e.codigo = '303' AND {cierre} >= :inicio_mes),
              count(*) FILTER (WHERE e.codigo = '303' AND {cierre} >= :inicio_anio),
              avg(extract(epoch FROM p.fecha_cierre - p.fecha_solicitud) / 3600.0)
                  FILTER (WHERE e.codigo = '303' AND {cierre} >= :inicio_anio)
            FROM pqrs p JOIN estado e ON e.id = p.estado_id
            WHERE p.sede_id = :sede_id
            """  # noqa: S608 - solo fragmentos constantes; datos por parámetros
        ),
        p,
    ).one()
    ejec = f"(o.fecha_ejecucion AT TIME ZONE '{ZONA_HORARIA}')::date"
    mant, mant_ant, abiertas_ot = db.execute(
        text(
            f"""
            SELECT
              count(*) FILTER (WHERE o.tipo = 'mantenimiento' AND e.codigo = '203'
                               AND {ejec} >= :inicio_mes),
              count(*) FILTER (WHERE o.tipo = 'mantenimiento' AND e.codigo = '203'
                               AND {ejec} >= :inicio_mes_ant AND {ejec} < :inicio_mes),
              count(*) FILTER (WHERE NOT e.final)
            FROM orden_trabajo o JOIN estado e ON e.id = o.estado_id
            WHERE o.sede_id = :sede_id
            """  # noqa: S608 - solo fragmentos constantes; datos por parámetros
        ),
        p,
    ).one()
    bajo_minimo = db.execute(
        text(
            """SELECT count(*) FROM material WHERE sede_id = :sede_id AND activo
               AND existencias < existencias_minimas"""
        ),
        p,
    ).scalar_one()
    return {
        "total_luminarias": int(total),
        "en_bodega": int(bodega),
        "en_servicio": int(total) - int(bodega),
        "pqrs_abiertas": int(pq[0]),
        "pqrs_verde": int(pq[1]),
        "pqrs_amarillo": int(pq[2]),
        "pqrs_rojo": int(pq[3]),
        "pqrs_recibidas_mes": int(pq[4]),
        "pqrs_recibidas_mes_anterior": int(pq[5]),
        "pqrs_atendidas_mes": int(pq[6]),
        "pqrs_atendidas_anio": int(pq[7]),
        "tiempo_promedio_atencion_horas": round(float(pq[8]), 1) if pq[8] is not None else None,
        "mantenimientos_mes": int(mant),
        "mantenimientos_mes_anterior": int(mant_ant),
        "ordenes_abiertas": int(abiertas_ot),
        "materiales_bajo_minimo": int(bajo_minimo),
        "umbral_verde_dias": verde_max,
        "umbral_amarillo_dias": amarillo_max,
    }


def pqrs_por_barrio(db: Session, sede_id: int, *, inicio_anio: date) -> list[Dim]:
    """PQRS del año por barrio de la luminaria reportada (una PQRS cuenta una vez por barrio)."""
    filas = _filas(
        db,
        f"""
        SELECT coalesce(b.id::text, '0'), coalesce(b.nombre, 'Sin barrio'),
               coalesce(z.nombre, 'Sin zona'), count(DISTINCT p.id)
        FROM pqrs p
        JOIN pqrs_luminaria pl ON pl.pqrs_id = p.id
        JOIN luminaria l ON l.id = pl.luminaria_id
        LEFT JOIN barrio b ON b.id = l.barrio_id
        LEFT JOIN zona z ON z.id = b.zona_id
        WHERE p.sede_id = :sede_id
          AND (p.fecha_solicitud AT TIME ZONE '{ZONA_HORARIA}')::date >= :inicio
        GROUP BY 1, 2, 3
        """,  # noqa: S608 - solo fragmentos constantes; datos por parámetros
        {"sede_id": sede_id, "inicio": inicio_anio},
    )
    return [("pqrs_barrio", str(c), str(e), str(g), int(n)) for c, e, g, n in filas]


def tiene_cortes_publicados(db: Session, sede_ids: Sequence[int]) -> set[int]:
    filas = _filas(
        db,
        """SELECT DISTINCT sede_id FROM cargue_comercial
           WHERE sede_id = ANY(:ids) AND estado = 'publicado' AND eliminado_en IS NULL""",
        {"ids": list(sede_ids)},
    )
    return {int(f[0]) for f in filas}


def ids_sedes_activas(db: Session) -> list[int]:
    return [int(f[0]) for f in _filas(db, "SELECT id FROM sede WHERE activa ORDER BY id", {})]


# --- Tablas resumen -----------------------------------------------------------------------------


def reemplazar_resumen(
    db: Session,
    sede_id: int,
    *,
    meses: list[tuple[int, int, int]],
    dimensiones: list[Dim],
    operacion_datos: dict[str, Any],
    comercial: list[dict[str, Any]],
) -> None:
    """Sustituye el resumen de la sede en una sola transacción (el lector nunca ve medio
    cálculo)."""
    for modelo in (ResumenLuminariaMes, ResumenDimension, ResumenComercial):
        db.execute(delete(modelo).where(modelo.sede_id == sede_id))
    if meses:
        db.execute(
            insert(ResumenLuminariaMes),
            [{"sede_id": sede_id, "anio": a, "mes": m, "cantidad": c} for a, m, c in meses],
        )
    if dimensiones:
        db.execute(
            insert(ResumenDimension),
            [
                {
                    "sede_id": sede_id,
                    "dimension": dim,
                    "clave": clave[:120],
                    "etiqueta": etiqueta[:200],
                    "grupo": grupo[:200] if grupo else None,
                    "cantidad": cantidad,
                }
                for dim, clave, etiqueta, grupo, cantidad in dimensiones
            ],
        )
    if comercial:
        db.execute(
            insert(ResumenComercial),
            [
                {
                    "sede_id": sede_id,
                    "comercializador": c["comercializador"],
                    "periodo": c["periodo"],
                    "datos": c,
                }
                for c in comercial
            ],
        )
    stmt = insert(ResumenCalculo).values(sede_id=sede_id, operacion=operacion_datos)
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=[ResumenCalculo.sede_id],
            set_={"operacion": stmt.excluded.operacion, "calculado_en": text("now()")},
        )
    )


def leer_calculos(db: Session, sede_ids: Sequence[int]) -> dict[int, ResumenCalculo]:
    filas = db.execute(select(ResumenCalculo).where(ResumenCalculo.sede_id.in_(sede_ids)))
    return {r.sede_id: r for r in filas.scalars()}


def leer_meses(db: Session, sede_ids: Sequence[int]) -> dict[int, list[tuple[int, int, int]]]:
    salida: dict[int, list[tuple[int, int, int]]] = {i: [] for i in sede_ids}
    for r in db.execute(
        select(ResumenLuminariaMes).where(ResumenLuminariaMes.sede_id.in_(sede_ids))
    ).scalars():
        salida[r.sede_id].append((r.anio, r.mes, r.cantidad))
    return salida


def leer_dimensiones(db: Session, sede_ids: Sequence[int]) -> dict[int, list[Dim]]:
    salida: dict[int, list[Dim]] = {i: [] for i in sede_ids}
    for r in db.execute(
        select(ResumenDimension).where(ResumenDimension.sede_id.in_(sede_ids))
    ).scalars():
        salida[r.sede_id].append((r.dimension, r.clave, r.etiqueta, r.grupo, r.cantidad))
    return salida


def leer_comercial(db: Session, sede_ids: Sequence[int]) -> dict[int, list[dict[str, Any]]]:
    salida: dict[int, list[dict[str, Any]]] = {i: [] for i in sede_ids}
    for r in db.execute(
        select(ResumenComercial)
        .where(ResumenComercial.sede_id.in_(sede_ids))
        .order_by(ResumenComercial.comercializador)
    ).scalars():
        salida[r.sede_id].append(dict(r.datos))
    return salida
