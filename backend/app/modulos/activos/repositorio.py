"""Repositorio SQLAlchemy/PostGIS del módulo de activos y mapa (EP-03)."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.modulos.activos.modelos import (
    EventoActivo,
    Lote,
    Luminaria,
    LuminariaUbicacion,
)


def obtener_por_id(db: Session, sede_id: int, luminaria_id: int) -> Luminaria | None:
    return db.execute(
        select(Luminaria).where(Luminaria.id == luminaria_id, Luminaria.sede_id == sede_id)
    ).scalar_one_or_none()


def obtener_para_actualizar(db: Session, sede_id: int, luminaria_id: int) -> Luminaria | None:
    """Bloquea la fila (FOR UPDATE): dos órdenes no pueden mover la misma luminaria a la vez."""
    return db.execute(
        select(Luminaria)
        .where(Luminaria.id == luminaria_id, Luminaria.sede_id == sede_id)
        .with_for_update()
    ).scalar_one_or_none()


def codigos_por_ids(db: Session, ids: list[int]) -> dict[int, tuple[str, bool]]:
    if not ids:
        return {}
    filas = db.execute(
        select(Luminaria.id, Luminaria.codigo, Luminaria.es_comodin).where(Luminaria.id.in_(ids))
    ).all()
    return {i: (c, bool(e)) for i, c, e in filas}


def obtener_por_codigo(db: Session, sede_id: int, codigo: str) -> Luminaria | None:
    return db.execute(
        select(Luminaria).where(
            Luminaria.sede_id == sede_id,
            func.lower(Luminaria.codigo) == codigo.strip().lower(),
        )
    ).scalar_one_or_none()


def obtener_detalle_fila(
    db: Session, sede_id: int, luminaria_id: int
) -> dict[str, Any] | None:
    sql = text(
        """
        SELECT
            l.id, l.sede_id, l.codigo, l.codigo_externo, l.barrio_id,
            b.nombre AS barrio_nombre, b.zona_id, z.nombre AS zona_nombre,
            ST_Y(l.ubicacion::geometry) AS latitud,
            ST_X(l.ubicacion::geometry) AS longitud,
            l.estado_id, e.codigo AS estado_codigo, e.nombre AS estado_nombre,
            l.tecnologia_id, mt.codigo AS tecnologia_codigo, mt.nombre AS tecnologia_nombre,
            l.potencia_id, mp.codigo AS potencia_codigo, mp.nombre AS potencia_nombre,
            l.marca_id, mm.codigo AS marca_codigo, mm.nombre AS marca_nombre,
            l.tipo_intervencion_id, l.accion_operativa_id, l.mision_objetivo_id,
            l.lote_id, l.luminaria_reemplazada_id,
            l.fecha_instalacion, l.fecha_mision, l.fecha_baja, l.fecha_disposicion_final,
            l.mac, l.poste, l.longitud_brazo,
            l.es_rural, l.subnormal, l.tiene_medida, l.en_transito, l.validado, l.es_comodin,
            l.responsable, l.observaciones, l.creado_en, l.modificado_en
        FROM luminaria l
        JOIN estado e ON e.id = l.estado_id
        LEFT JOIN barrio b ON b.id = l.barrio_id
        LEFT JOIN zona z ON z.id = b.zona_id
        LEFT JOIN maestro_valor mt ON mt.id = l.tecnologia_id
        LEFT JOIN maestro_valor mp ON mp.id = l.potencia_id
        LEFT JOIN maestro_valor mm ON mm.id = l.marca_id
        WHERE l.sede_id = :sede_id AND l.id = :luminaria_id
        """
    )
    fila = db.execute(sql, {"sede_id": sede_id, "luminaria_id": luminaria_id}).mappings().first()
    return dict(fila) if fila else None


def _construir_filtros(
    sede_id: int,
    *,
    texto: str | None = None,
    estado_id: int | None = None,
    zona_id: int | None = None,
    barrio_id: int | None = None,
    tecnologia_id: int | None = None,
    potencia_id: int | None = None,
    marca_id: int | None = None,
    tipo_intervencion_id: int | None = None,
    es_rural: bool | None = None,
    en_transito: bool | None = None,
    validado: bool | None = None,
    fecha_instalacion_desde: date | None = None,
    fecha_instalacion_hasta: date | None = None,
    estado_codigos: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    condiciones = ["l.sede_id = :sede_id"]
    params: dict[str, Any] = {"sede_id": sede_id}
    if estado_codigos:
        params["estado_codigos"] = list(estado_codigos)
        condiciones.append("e.codigo = ANY(:estado_codigos)")

    if texto and texto.strip():
        params["patron"] = f"%{texto.strip()}%"
        condiciones.append(
            "("
            "l.codigo ILIKE :patron OR "
            "COALESCE(l.codigo_externo, '') ILIKE :patron OR "
            "COALESCE(l.poste, '') ILIKE :patron OR "
            "COALESCE(b.nombre, '') ILIKE :patron OR "
            "COALESCE(mm.nombre, '') ILIKE :patron OR "
            "COALESCE(mm.codigo, '') ILIKE :patron"
            ")"
        )
    if estado_id is not None:
        params["estado_id"] = estado_id
        condiciones.append("l.estado_id = :estado_id")
    if zona_id is not None:
        params["zona_id"] = zona_id
        condiciones.append("b.zona_id = :zona_id")
    if barrio_id is not None:
        params["barrio_id"] = barrio_id
        condiciones.append("l.barrio_id = :barrio_id")
    if tecnologia_id is not None:
        params["tecnologia_id"] = tecnologia_id
        condiciones.append("l.tecnologia_id = :tecnologia_id")
    if potencia_id is not None:
        params["potencia_id"] = potencia_id
        condiciones.append("l.potencia_id = :potencia_id")
    if marca_id is not None:
        params["marca_id"] = marca_id
        condiciones.append("l.marca_id = :marca_id")
    if tipo_intervencion_id is not None:
        params["tipo_intervencion_id"] = tipo_intervencion_id
        condiciones.append("l.tipo_intervencion_id = :tipo_intervencion_id")
    if es_rural is not None:
        params["es_rural"] = es_rural
        condiciones.append("l.es_rural = :es_rural")
    if en_transito is not None:
        params["en_transito"] = en_transito
        condiciones.append("l.en_transito = :en_transito")
    if validado is not None:
        params["validado"] = validado
        condiciones.append("l.validado = :validado")
    if fecha_instalacion_desde is not None:
        params["f_desde"] = fecha_instalacion_desde
        condiciones.append("l.fecha_instalacion >= :f_desde")
    if fecha_instalacion_hasta is not None:
        params["f_hasta"] = fecha_instalacion_hasta
        condiciones.append("l.fecha_instalacion <= :f_hasta")

    return " AND ".join(condiciones), params


def listar_luminarias(
    db: Session,
    sede_id: int,
    *,
    page: int,
    size: int,
    texto: str | None = None,
    estado_id: int | None = None,
    zona_id: int | None = None,
    barrio_id: int | None = None,
    tecnologia_id: int | None = None,
    potencia_id: int | None = None,
    marca_id: int | None = None,
    tipo_intervencion_id: int | None = None,
    es_rural: bool | None = None,
    en_transito: bool | None = None,
    validado: bool | None = None,
    fecha_instalacion_desde: date | None = None,
    fecha_instalacion_hasta: date | None = None,
    estado_codigos: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    where_sql, params = _construir_filtros(
        sede_id,
        texto=texto,
        estado_id=estado_id,
        zona_id=zona_id,
        barrio_id=barrio_id,
        tecnologia_id=tecnologia_id,
        potencia_id=potencia_id,
        marca_id=marca_id,
        tipo_intervencion_id=tipo_intervencion_id,
        es_rural=es_rural,
        en_transito=en_transito,
        validado=validado,
        fecha_instalacion_desde=fecha_instalacion_desde,
        fecha_instalacion_hasta=fecha_instalacion_hasta,
        estado_codigos=estado_codigos,
    )
    joins = """
        FROM luminaria l
        JOIN estado e ON e.id = l.estado_id
        LEFT JOIN barrio b ON b.id = l.barrio_id
        LEFT JOIN zona z ON z.id = b.zona_id
        LEFT JOIN maestro_valor mt ON mt.id = l.tecnologia_id
        LEFT JOIN maestro_valor mp ON mp.id = l.potencia_id
        LEFT JOIN maestro_valor mm ON mm.id = l.marca_id
    """
    total = int(
        db.execute(text(f"SELECT COUNT(*) {joins} WHERE {where_sql}"), params).scalar_one()
    )
    params_pag = {**params, "limit": size, "offset": (page - 1) * size}
    filas = db.execute(
        text(
            f"""
            SELECT
                l.id, l.sede_id, l.codigo, l.codigo_externo, l.barrio_id,
                b.nombre AS barrio_nombre, b.zona_id, z.nombre AS zona_nombre,
                ST_Y(l.ubicacion::geometry) AS latitud,
                ST_X(l.ubicacion::geometry) AS longitud,
                l.estado_id, e.codigo AS estado_codigo, e.nombre AS estado_nombre,
                l.tecnologia_id, mt.codigo AS tecnologia_codigo, mt.nombre AS tecnologia_nombre,
                l.potencia_id, mp.codigo AS potencia_codigo, mp.nombre AS potencia_nombre,
                l.marca_id, mm.codigo AS marca_codigo, mm.nombre AS marca_nombre,
                l.tipo_intervencion_id, l.accion_operativa_id, l.mision_objetivo_id,
                l.lote_id, l.luminaria_reemplazada_id,
                l.fecha_instalacion, l.fecha_mision, l.fecha_baja, l.fecha_disposicion_final,
                l.mac, l.poste, l.longitud_brazo,
                l.es_rural, l.subnormal, l.tiene_medida, l.en_transito, l.validado, l.es_comodin,
                l.responsable, l.observaciones, l.creado_en, l.modificado_en
            {joins}
            WHERE {where_sql}
            ORDER BY l.id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params_pag,
    ).mappings().all()
    return [dict(f) for f in filas], total


def listar_para_exportar(
    db: Session,
    sede_id: int,
    *,
    texto: str | None = None,
    estado_id: int | None = None,
    zona_id: int | None = None,
    barrio_id: int | None = None,
    tecnologia_id: int | None = None,
    potencia_id: int | None = None,
    marca_id: int | None = None,
) -> list[dict[str, Any]]:
    filas, _ = listar_luminarias(
        db,
        sede_id,
        page=1,
        size=50000,
        texto=texto,
        estado_id=estado_id,
        zona_id=zona_id,
        barrio_id=barrio_id,
        tecnologia_id=tecnologia_id,
        potencia_id=potencia_id,
        marca_id=marca_id,
    )
    return filas


def buscar_luminarias(db: Session, sede_id: int, q: str, limite: int = 30) -> list[dict[str, Any]]:
    filas, _ = listar_luminarias(db, sede_id, page=1, size=min(limite, 100), texto=q)
    return filas


def crear_luminaria(db: Session, lum: Luminaria) -> Luminaria:
    db.add(lum)
    db.flush()
    return lum


def crear_evento(db: Session, evento: EventoActivo) -> EventoActivo:
    db.add(evento)
    db.flush()
    return evento


def crear_ubicacion_historial(db: Session, reg: LuminariaUbicacion) -> LuminariaUbicacion:
    db.add(reg)
    db.flush()
    return reg


def listar_eventos_luminaria(db: Session, luminaria_id: int) -> list[EventoActivo]:
    stmt = (
        select(EventoActivo)
        .where(EventoActivo.luminaria_id == luminaria_id)
        .order_by(EventoActivo.fecha.desc(), EventoActivo.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


def listar_ubicaciones_luminaria(db: Session, luminaria_id: int) -> list[dict[str, Any]]:
    sql = text(
        """
        SELECT
            id, luminaria_id,
            ST_Y(ubicacion_anterior::geometry) AS latitud_anterior,
            ST_X(ubicacion_anterior::geometry) AS longitud_anterior,
            ST_Y(ubicacion_nueva::geometry) AS latitud_nueva,
            ST_X(ubicacion_nueva::geometry) AS longitud_nueva,
            origen, cambiado_en, cambiado_por
        FROM luminaria_ubicacion
        WHERE luminaria_id = :luminaria_id
        ORDER BY cambiado_en DESC, id DESC
        """
    )
    return [dict(f) for f in db.execute(sql, {"luminaria_id": luminaria_id}).mappings().all()]


def existe_lote_solapado(
    db: Session, sede_id: int, consecutivo_inicial: int, consecutivo_final: int
) -> bool:
    stmt = select(Lote.id).where(
        Lote.sede_id == sede_id,
        Lote.consecutivo_inicial <= consecutivo_final,
        Lote.consecutivo_final >= consecutivo_inicial,
    )
    return db.execute(stmt).first() is not None


def existen_codigos_luminaria(db: Session, sede_id: int, codigos: list[str]) -> bool:
    if not codigos:
        return False
    stmt = select(Luminaria.id).where(
        Luminaria.sede_id == sede_id, Luminaria.codigo.in_(codigos)
    )
    return db.execute(stmt).first() is not None


def listar_lotes(db: Session, sede_id: int, *, page: int, size: int) -> tuple[list[Lote], int]:
    total = int(
        db.execute(select(func.count(Lote.id)).where(Lote.sede_id == sede_id)).scalar_one()
    )
    stmt = (
        select(Lote)
        .where(Lote.sede_id == sede_id)
        .order_by(Lote.id.desc())
        .limit(size)
        .offset((page - 1) * size)
    )
    return list(db.execute(stmt).scalars().all()), total


def crear_lote(db: Session, lote: Lote) -> Lote:
    db.add(lote)
    db.flush()
    return lote


_MVT_FILTROS_SQL = """
    l.sede_id = :sede_id
    AND l.ubicacion IS NOT NULL
    AND ST_Transform(l.ubicacion, 3857) && bounds.env
    AND (CAST(:patron AS TEXT) IS NULL OR (
        l.codigo ILIKE CAST(:patron AS TEXT)
        OR COALESCE(l.codigo_externo, '') ILIKE CAST(:patron AS TEXT)
        OR COALESCE(l.poste, '') ILIKE CAST(:patron AS TEXT)
        OR COALESCE(b.nombre, '') ILIKE CAST(:patron AS TEXT)
        OR COALESCE(mm.nombre, '') ILIKE CAST(:patron AS TEXT)
        OR COALESCE(mm.codigo, '') ILIKE CAST(:patron AS TEXT)
    ))
    AND (CAST(:estado_id AS BIGINT) IS NULL OR l.estado_id = CAST(:estado_id AS BIGINT))
    AND (CAST(:zona_id AS BIGINT) IS NULL OR b.zona_id = CAST(:zona_id AS BIGINT))
    AND (CAST(:barrio_id AS BIGINT) IS NULL OR l.barrio_id = CAST(:barrio_id AS BIGINT))
    AND (
        CAST(:tecnologia_id AS BIGINT) IS NULL
        OR l.tecnologia_id = CAST(:tecnologia_id AS BIGINT)
    )
    AND (CAST(:potencia_id AS BIGINT) IS NULL OR l.potencia_id = CAST(:potencia_id AS BIGINT))
    AND (CAST(:marca_id AS BIGINT) IS NULL OR l.marca_id = CAST(:marca_id AS BIGINT))
    AND (CAST(:validado AS BOOLEAN) IS NULL OR l.validado = CAST(:validado AS BOOLEAN))
    AND (CAST(:en_transito AS BOOLEAN) IS NULL OR l.en_transito = CAST(:en_transito AS BOOLEAN))
    AND (
        CAST(:en_bodega AS BOOLEAN) IS NULL
        OR (CAST(:en_bodega AS BOOLEAN) = true AND e.codigo IN ('124', '123', '125', '112'))
        OR (CAST(:en_bodega AS BOOLEAN) = false AND e.codigo NOT IN ('124', '123', '125', '112'))
    )
"""

_SQL_MVT_AGRUPADO = text(
    f"""
    WITH bounds AS (SELECT ST_TileEnvelope(:z, :x, :y) AS env),
    raw AS (
        SELECT
            l.id, l.codigo, e.codigo AS estado_codigo, mt.codigo AS tecnologia_codigo,
            ST_Transform(l.ubicacion, 3857) AS g3857
        FROM luminaria l
        JOIN estado e ON e.id = l.estado_id
        LEFT JOIN barrio b ON b.id = l.barrio_id
        LEFT JOIN maestro_valor mt ON mt.id = l.tecnologia_id
        LEFT JOIN maestro_valor mm ON mm.id = l.marca_id
        CROSS JOIN bounds
        WHERE {_MVT_FILTROS_SQL}
    ),
    grupos AS (
        SELECT
            COUNT(*)::int AS total,
            MIN(id) AS id,
            MIN(codigo) AS codigo,
            MIN(estado_codigo) AS estado_codigo,
            MIN(tecnologia_codigo) AS tecnologia_codigo,
            ST_Centroid(ST_Collect(g3857)) AS centro
        FROM raw
        GROUP BY ST_SnapToGrid(
            g3857,
            (ST_XMax((SELECT env FROM bounds)) - ST_XMin((SELECT env FROM bounds))) / 16.0
        )
    ),
    pts AS (
        SELECT
            id, codigo, estado_codigo, tecnologia_codigo, total,
            (total > 1) AS es_grupo,
            ST_AsMVTGeom(centro, (SELECT env FROM bounds), 4096, 256, true) AS geom
        FROM grupos
    )
    SELECT COALESCE(ST_AsMVT(pts.*, 'luminarias', 4096, 'geom'), ''::bytea)
    FROM pts WHERE geom IS NOT NULL
    """  # noqa: S608 - constantes estáticas internas, filtros enlazados
)

_SQL_MVT_DETALLE = text(
    f"""
    WITH bounds AS (SELECT ST_TileEnvelope(:z, :x, :y) AS env),
    pts AS (
        SELECT
            l.id, l.codigo, e.codigo AS estado_codigo, mt.codigo AS tecnologia_codigo,
            1::int AS total, false AS es_grupo,
            ST_AsMVTGeom(
                ST_Transform(l.ubicacion, 3857), bounds.env, 4096, 256, true
            ) AS geom
        FROM luminaria l
        JOIN estado e ON e.id = l.estado_id
        LEFT JOIN barrio b ON b.id = l.barrio_id
        LEFT JOIN maestro_valor mt ON mt.id = l.tecnologia_id
        LEFT JOIN maestro_valor mm ON mm.id = l.marca_id
        CROSS JOIN bounds
        WHERE {_MVT_FILTROS_SQL}
    )
    SELECT COALESCE(ST_AsMVT(pts.*, 'luminarias', 4096, 'geom'), ''::bytea)
    FROM pts WHERE geom IS NOT NULL
    """  # noqa: S608 - constantes estáticas internas, filtros enlazados
)


def obtener_tesela_mvt(
    db: Session,
    sede_id: int,
    z: int,
    x: int,
    y: int,
    *,
    estado_id: int | None = None,
    tecnologia_id: int | None = None,
    potencia_id: int | None = None,
    marca_id: int | None = None,
    zona_id: int | None = None,
    barrio_id: int | None = None,
    en_bodega: bool | None = None,
    validado: bool | None = None,
    en_transito: bool | None = None,
    texto: str | None = None,
) -> bytes:
    params = {
        "sede_id": sede_id,
        "z": z,
        "x": x,
        "y": y,
        "patron": f"%{texto.strip()}%" if texto and texto.strip() else None,
        "estado_id": estado_id,
        "zona_id": zona_id,
        "barrio_id": barrio_id,
        "tecnologia_id": tecnologia_id,
        "potencia_id": potencia_id,
        "marca_id": marca_id,
        "validado": validado,
        "en_transito": en_transito,
        "en_bodega": en_bodega,
    }
    sql = _SQL_MVT_AGRUPADO if z <= 12 else _SQL_MVT_DETALLE
    resultado = db.execute(sql, params).scalar_one()
    return bytes(resultado) if resultado else b""


def listar_para_campo(
    db: Session, sede_id: int, desde: datetime | None, estado_codigos: list[str] | None = None
) -> list[dict[str, Any]]:
    """Ficha compacta de las luminarias de la sede para la app de campo (sin la comodín)."""
    sql = text(
        """
        SELECT
            l.id, l.codigo, e.codigo AS estado_codigo, l.barrio_id, l.poste,
            ST_Y(l.ubicacion::geometry) AS latitud, ST_X(l.ubicacion::geometry) AS longitud,
            mt.nombre AS tecnologia, mp.nombre AS potencia, mm.nombre AS marca
        FROM luminaria l
        JOIN estado e ON e.id = l.estado_id
        LEFT JOIN maestro_valor mt ON mt.id = l.tecnologia_id
        LEFT JOIN maestro_valor mp ON mp.id = l.potencia_id
        LEFT JOIN maestro_valor mm ON mm.id = l.marca_id
        WHERE l.sede_id = :sede_id
          AND NOT l.es_comodin
          AND (CAST(:desde AS timestamptz) IS NULL OR l.modificado_en > CAST(:desde AS timestamptz))
          AND (CAST(:estados AS text[]) IS NULL OR e.codigo = ANY(CAST(:estados AS text[])))
        ORDER BY l.id
        """
    )
    filas = db.execute(
        sql, {"sede_id": sede_id, "desde": desde, "estados": estado_codigos}
    ).mappings()
    return [dict(f) for f in filas]
