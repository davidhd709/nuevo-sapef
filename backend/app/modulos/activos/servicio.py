"""Servicio público del módulo de activos y mapa (EP-03)."""

import io
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException
from openpyxl import Workbook
from procrastinate.exceptions import AppNotOpen
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import obtener_configuracion
from app.core.tareas import app_tareas
from app.modulos.activos import dominio, repositorio
from app.modulos.activos.esquemas import (
    EventoActivoSalida,
    HistorialLuminariaSalida,
    LoteCrearEntrada,
    LoteSalida,
    LuminariaCrearEntrada,
    LuminariaEditarEntrada,
    LuminariaExportarEntrada,
    LuminariaMoverEntrada,
    LuminariaSalida,
    Pagina,
    TareaExportacionSalida,
    UbicacionHistorialSalida,
)
from app.modulos.activos.modelos import EventoActivo, Lote, Luminaria, LuminariaUbicacion
from app.modulos.archivos import servicio as archivos_servicio
from app.modulos.configuracion import servicio as config_servicio
from app.modulos.seguridad import servicio as seguridad_servicio
from app.modulos.seguridad.servicio import SedeResumen, UsuarioAutenticado


def _traducir_error(exc: dominio.ErrorDominioActivo) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _a_luminaria_salida(fila: dict[str, Any]) -> LuminariaSalida:
    lat = float(fila["latitud"]) if fila["latitud"] is not None else None
    lng = float(fila["longitud"]) if fila["longitud"] is not None else None
    return LuminariaSalida(
        **{**fila, "latitud": lat, "longitud": lng},
        google_maps_url=dominio.construir_url_google_maps(lat, lng),
    )


def _validar_referencias_luminaria(
    db: Session,
    sede_id: int,
    *,
    barrio_id: int | None = None,
    estado_id: int | None = None,
    tecnologia_id: int | None = None,
    potencia_id: int | None = None,
    marca_id: int | None = None,
    tipo_intervencion_id: int | None = None,
    accion_operativa_id: int | None = None,
    mision_objetivo_id: int | None = None,
    luminaria_reemplazada_id: int | None = None,
) -> None:
    if (
        barrio_id is not None
        and config_servicio.resolver_barrio_sede(db, sede_id, barrio_id) is None
    ):
        raise HTTPException(status_code=404, detail="El barrio no pertenece a la sede activa.")
    if (
        estado_id is not None
        and config_servicio.obtener_estado_por_id_o_codigo(db, "luminaria", estado_id=estado_id)
        is None
    ):
        raise HTTPException(status_code=422, detail="El estado de luminaria no existe.")
    for clase, valor_id in (
        ("LUMINARIA_TECNOLOGIA", tecnologia_id),
        ("LUMINARIA_POTENCIA", potencia_id),
        ("LUMINARIA_MARCA", marca_id),
        ("TIPO_INTERVENCION", tipo_intervencion_id),
        ("ACCION_OPERATIVA", accion_operativa_id),
        ("MISION_OBJETIVO", mision_objetivo_id),
    ):
        if (
            valor_id is not None
            and config_servicio.obtener_valor_maestro(db, clase, valor_id=valor_id) is None
        ):
            raise HTTPException(
                status_code=422, detail=f"Valor inválido para catálogo {clase}."
            )
    if (
        luminaria_reemplazada_id is not None
        and repositorio.obtener_por_id(db, sede_id, luminaria_reemplazada_id) is None
    ):
        raise HTTPException(status_code=404, detail="Luminaria reemplazada no encontrada.")


def _geom_wkt(coords: tuple[float, float] | None) -> str | None:
    if coords is None:
        return None
    lat, lng = coords
    return f"SRID=4326;POINT({lng} {lat})"


def listar_luminarias(
    db: Session,
    sede: SedeResumen,
    *,
    page: int = 1,
    size: int = 20,
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
) -> Pagina[LuminariaSalida]:
    filas, total = repositorio.listar_luminarias(
        db,
        sede.id,
        page=page,
        size=size,
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
    )
    return Pagina[LuminariaSalida](
        items=[_a_luminaria_salida(f) for f in filas],
        total=total,
        page=page,
        size=size,
    )


def buscar_luminarias(db: Session, sede: SedeResumen, q: str) -> list[LuminariaSalida]:
    filas = repositorio.buscar_luminarias(db, sede.id, q)
    return [_a_luminaria_salida(f) for f in filas]


def obtener_luminaria(db: Session, sede: SedeResumen, luminaria_id: int) -> LuminariaSalida:
    fila = repositorio.obtener_detalle_fila(db, sede.id, luminaria_id)
    if fila is None:
        raise HTTPException(status_code=404, detail="Luminaria no encontrada.")
    return _a_luminaria_salida(fila)


def crear_luminaria(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    entrada: LuminariaCrearEntrada,
) -> LuminariaSalida:
    try:
        codigo = dominio.normalizar_codigo_luminaria(entrada.codigo)
        coords = dominio.validar_coordenadas(entrada.latitud, entrada.longitud)
    except dominio.ErrorDominioActivo as exc:
        raise _traducir_error(exc) from exc

    if repositorio.obtener_por_codigo(db, sede.id, codigo) is not None:
        raise HTTPException(status_code=409, detail="Ya existe una luminaria con ese código.")

    _validar_referencias_luminaria(
        db,
        sede.id,
        barrio_id=entrada.barrio_id,
        estado_id=entrada.estado_id,
        tecnologia_id=entrada.tecnologia_id,
        potencia_id=entrada.potencia_id,
        marca_id=entrada.marca_id,
        tipo_intervencion_id=entrada.tipo_intervencion_id,
        accion_operativa_id=entrada.accion_operativa_id,
        mision_objetivo_id=entrada.mision_objetivo_id,
        luminaria_reemplazada_id=entrada.luminaria_reemplazada_id,
    )

    lum = Luminaria(
        sede_id=sede.id,
        codigo=codigo,
        codigo_externo=entrada.codigo_externo.strip() if entrada.codigo_externo else None,
        barrio_id=entrada.barrio_id,
        ubicacion=_geom_wkt(coords),
        estado_id=entrada.estado_id,
        tecnologia_id=entrada.tecnologia_id,
        potencia_id=entrada.potencia_id,
        marca_id=entrada.marca_id,
        tipo_intervencion_id=entrada.tipo_intervencion_id,
        accion_operativa_id=entrada.accion_operativa_id,
        mision_objetivo_id=entrada.mision_objetivo_id,
        fecha_instalacion=entrada.fecha_instalacion,
        fecha_mision=entrada.fecha_mision,
        fecha_baja=entrada.fecha_baja,
        fecha_disposicion_final=entrada.fecha_disposicion_final,
        mac=entrada.mac.strip() if entrada.mac else None,
        poste=entrada.poste.strip() if entrada.poste else None,
        longitud_brazo=entrada.longitud_brazo,
        es_rural=entrada.es_rural,
        subnormal=entrada.subnormal,
        tiene_medida=entrada.tiene_medida,
        en_transito=entrada.en_transito,
        validado=entrada.validado,
        responsable=entrada.responsable.strip() if entrada.responsable else None,
        observaciones=entrada.observaciones,
        luminaria_reemplazada_id=entrada.luminaria_reemplazada_id,
        creado_por=actor.id,
        modificado_por=actor.id,
    )
    try:
        repositorio.crear_luminaria(db, lum)
        repositorio.crear_evento(
            db,
            EventoActivo(
                luminaria_id=lum.id,
                tipo="alta",
                estado_nuevo_id=lum.estado_id,
                detalle={"codigo": lum.codigo},
                creado_por=actor.id,
            ),
        )
        seguridad_servicio.registrar_auditoria(
            db,
            usuario_id=actor.id,
            sede_id=sede.id,
            accion="crear",
            entidad="luminaria",
            entidad_id=str(lum.id),
            despues={"codigo": lum.codigo, "estado_id": lum.estado_id},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Ya existe una luminaria con ese código."
        ) from exc

    fila = repositorio.obtener_detalle_fila(db, sede.id, lum.id)
    assert fila is not None
    return _a_luminaria_salida(fila)


def editar_luminaria(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    luminaria_id: int,
    entrada: LuminariaEditarEntrada,
) -> LuminariaSalida:
    lum = repositorio.obtener_por_id(db, sede.id, luminaria_id)
    if lum is None:
        raise HTTPException(status_code=404, detail="Luminaria no encontrada.")

    cambios = entrada.model_dump(exclude_unset=True)
    _validar_referencias_luminaria(
        db,
        sede.id,
        barrio_id=cambios.get("barrio_id"),
        estado_id=cambios.get("estado_id"),
        tecnologia_id=cambios.get("tecnologia_id"),
        potencia_id=cambios.get("potencia_id"),
        marca_id=cambios.get("marca_id"),
        tipo_intervencion_id=cambios.get("tipo_intervencion_id"),
        accion_operativa_id=cambios.get("accion_operativa_id"),
        mision_objetivo_id=cambios.get("mision_objetivo_id"),
    )

    estado_anterior = lum.estado_id
    antes = {"estado_id": lum.estado_id, "poste": lum.poste, "barrio_id": lum.barrio_id}
    for campo, valor in cambios.items():
        if isinstance(valor, str) and campo in {"codigo_externo", "mac", "poste", "responsable"}:
            valor = valor.strip() or None
        setattr(lum, campo, valor)
    lum.modificado_por = actor.id
    db.flush()

    if "estado_id" in cambios and cambios["estado_id"] != estado_anterior:
        repositorio.crear_evento(
            db,
            EventoActivo(
                luminaria_id=lum.id,
                tipo="cambio_estado",
                estado_anterior_id=estado_anterior,
                estado_nuevo_id=lum.estado_id,
                detalle={"origen": "web"},
                creado_por=actor.id,
            ),
        )

    seguridad_servicio.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="editar",
        entidad="luminaria",
        entidad_id=str(lum.id),
        antes=antes,
        despues={"estado_id": lum.estado_id, "poste": lum.poste, "barrio_id": lum.barrio_id},
    )
    db.commit()

    fila = repositorio.obtener_detalle_fila(db, sede.id, lum.id)
    assert fila is not None
    return _a_luminaria_salida(fila)


def mover_ubicacion_luminaria(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    luminaria_id: int,
    entrada: LuminariaMoverEntrada,
) -> LuminariaSalida:
    try:
        coords = dominio.validar_coordenadas(entrada.latitud, entrada.longitud)
    except dominio.ErrorDominioActivo as exc:
        raise _traducir_error(exc) from exc
    assert coords is not None

    lum = repositorio.obtener_por_id(db, sede.id, luminaria_id)
    if lum is None:
        raise HTTPException(status_code=404, detail="Luminaria no encontrada.")

    ubicacion_anterior = lum.ubicacion
    nueva_wkt = _geom_wkt(coords)
    assert nueva_wkt is not None
    lum.ubicacion = nueva_wkt
    lum.modificado_por = actor.id

    repositorio.crear_ubicacion_historial(
        db,
        LuminariaUbicacion(
            luminaria_id=lum.id,
            ubicacion_anterior=ubicacion_anterior,
            ubicacion_nueva=nueva_wkt,
            origen=entrada.origen.strip(),
            cambiado_por=actor.id,
        ),
    )
    repositorio.crear_evento(
        db,
        EventoActivo(
            luminaria_id=lum.id,
            tipo="cambio_ubicacion",
            detalle={
                "latitud": coords[0],
                "longitud": coords[1],
                "origen": entrada.origen.strip(),
            },
            creado_por=actor.id,
        ),
    )
    db.commit()

    fila = repositorio.obtener_detalle_fila(db, sede.id, lum.id)
    assert fila is not None
    return _a_luminaria_salida(fila)


def obtener_historial_luminaria(
    db: Session, sede: SedeResumen, luminaria_id: int
) -> HistorialLuminariaSalida:
    fila = repositorio.obtener_detalle_fila(db, sede.id, luminaria_id)
    if fila is None:
        raise HTTPException(status_code=404, detail="Luminaria no encontrada.")

    eventos = [
        EventoActivoSalida(
            id=e.id,
            luminaria_id=e.luminaria_id,
            tipo=e.tipo,
            fecha=e.fecha,
            orden_id=e.orden_id,
            pqrs_id=e.pqrs_id,
            estado_anterior_id=e.estado_anterior_id,
            estado_nuevo_id=e.estado_nuevo_id,
            detalle=e.detalle,
            creado_por=e.creado_por,
        )
        for e in repositorio.listar_eventos_luminaria(db, luminaria_id)
    ]
    ubicaciones = [
        UbicacionHistorialSalida(**u)
        for u in repositorio.listar_ubicaciones_luminaria(db, luminaria_id)
    ]
    return HistorialLuminariaSalida(
        luminaria=_a_luminaria_salida(fila),
        eventos=eventos,
        ubicaciones=ubicaciones,
        pqrs=[],
        ordenes=[],
    )


async def encolar_exportacion_luminarias(
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    entrada: LuminariaExportarEntrada | None = None,
) -> TareaExportacionSalida:
    deferrer = app_tareas.configure_task(name="activos.exportar_luminarias")
    texto = entrada.texto if entrada else None
    try:
        job_id = await deferrer.defer_async(
            sede_id=sede.id, usuario_id=actor.id, texto=texto
        )
    except AppNotOpen:
        async with app_tareas.open_async():
            job_id = await deferrer.defer_async(
                sede_id=sede.id, usuario_id=actor.id, texto=texto
            )
    return TareaExportacionSalida(id=job_id, tarea_id=job_id, tareaId=job_id, estado="encolada")


def procesar_exportacion_luminarias(
    db: Session, *, sede_id: int, usuario_id: int, texto: str | None = None
) -> str:
    filas = repositorio.listar_para_exportar(db, sede_id, texto=texto)
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Luminarias"
    ws.append(
        [
            "Código",
            "Código externo",
            "Zona",
            "Barrio",
            "Estado",
            "Tecnología",
            "Potencia",
            "Marca",
            "Poste",
            "Latitud",
            "Longitud",
            "Fecha instalación",
        ]
    )
    for f in filas:
        ws.append(
            [
                f["codigo"],
                f["codigo_externo"] or "",
                f["zona_nombre"] or "",
                f["barrio_nombre"] or "",
                f["estado_nombre"] or "",
                f["tecnologia_nombre"] or "",
                f["potencia_nombre"] or "",
                f["marca_nombre"] or "",
                f["poste"] or "",
                f["latitud"],
                f["longitud"],
                f["fecha_instalacion"].isoformat() if f["fecha_instalacion"] else "",
            ]
        )
    buf = io.BytesIO()
    wb.save(buf)
    meta, _ = archivos_servicio.guardar_archivo(
        db,
        sede_id=sede_id,
        archivo_bytes=buf.getvalue(),
        nombre=f"luminarias_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        categoria="cargue",
        subido_por_id=usuario_id,
    )
    return str(meta.id)


# === Lotes ======================================================================================


def _a_lote_salida(lote: Lote) -> LoteSalida:
    return LoteSalida(
        id=lote.id,
        sede_id=lote.sede_id,
        consecutivo_inicial=lote.consecutivo_inicial,
        consecutivo_final=lote.consecutivo_final,
        cantidad=lote.cantidad,
        tecnologia_id=lote.tecnologia_id,
        potencia_id=lote.potencia_id,
        marca_id=lote.marca_id,
        es_rural=lote.es_rural,
        orden_compra=lote.orden_compra,
        fecha_orden_compra=lote.fecha_orden_compra,
        entrada_almacen=lote.entrada_almacen,
        fecha_entrada_almacen=lote.fecha_entrada_almacen,
        creado_en=lote.creado_en,
    )


def listar_lotes(
    db: Session, sede: SedeResumen, *, page: int = 1, size: int = 20
) -> Pagina[LoteSalida]:
    lotes, total = repositorio.listar_lotes(db, sede.id, page=page, size=size)
    return Pagina[LoteSalida](
        items=[_a_lote_salida(lote) for lote in lotes],
        total=total,
        page=page,
        size=size,
    )


def crear_lote(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    entrada: LoteCrearEntrada,
) -> LoteSalida:
    try:
        codigos = dominio.validar_lote_consecutivos(
            entrada.consecutivo_inicial, entrada.consecutivo_final, entrada.cantidad
        )
    except dominio.ErrorDominioActivo as exc:
        raise _traducir_error(exc) from exc

    _validar_referencias_luminaria(
        db,
        sede.id,
        tecnologia_id=entrada.tecnologia_id,
        potencia_id=entrada.potencia_id,
        marca_id=entrada.marca_id,
    )
    estado_bodega = config_servicio.obtener_estado_por_id_o_codigo(db, "luminaria", codigo="124")
    if estado_bodega is None:
        raise HTTPException(status_code=500, detail="Falta el estado semilla 124 (Bodega buena).")

    if repositorio.existe_lote_solapado(
        db, sede.id, entrada.consecutivo_inicial, entrada.consecutivo_final
    ):
        raise HTTPException(
            status_code=409,
            detail="El rango de consecutivos se cruza con un lote ya registrado en la sede.",
        )
    if repositorio.existen_codigos_luminaria(db, sede.id, codigos):
        raise HTTPException(
            status_code=409,
            detail="Uno o más consecutivos del lote ya existen como luminarias en la sede.",
        )

    lote = Lote(
        sede_id=sede.id,
        consecutivo_inicial=entrada.consecutivo_inicial,
        consecutivo_final=entrada.consecutivo_final,
        cantidad=entrada.cantidad,
        tecnologia_id=entrada.tecnologia_id,
        potencia_id=entrada.potencia_id,
        marca_id=entrada.marca_id,
        es_rural=entrada.es_rural,
        orden_compra=entrada.orden_compra.strip() if entrada.orden_compra else None,
        fecha_orden_compra=entrada.fecha_orden_compra,
        entrada_almacen=entrada.entrada_almacen.strip() if entrada.entrada_almacen else None,
        fecha_entrada_almacen=entrada.fecha_entrada_almacen,
        creado_por=actor.id,
    )
    repositorio.crear_lote(db, lote)

    for codigo in codigos:
        lum = Luminaria(
            sede_id=sede.id,
            codigo=codigo,
            estado_id=estado_bodega["id"],
            tecnologia_id=entrada.tecnologia_id,
            potencia_id=entrada.potencia_id,
            marca_id=entrada.marca_id,
            es_rural=entrada.es_rural,
            lote_id=lote.id,
            creado_por=actor.id,
            modificado_por=actor.id,
        )
        repositorio.crear_luminaria(db, lum)
        repositorio.crear_evento(
            db,
            EventoActivo(
                luminaria_id=lum.id,
                tipo="alta",
                estado_nuevo_id=estado_bodega["id"],
                detalle={"lote_id": lote.id, "codigo": codigo},
                creado_por=actor.id,
            ),
        )

    seguridad_servicio.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="crear",
        entidad="lote",
        entidad_id=str(lote.id),
        despues={
            "inicial": lote.consecutivo_inicial,
            "final": lote.consecutivo_final,
            "cantidad": lote.cantidad,
        },
    )
    db.commit()
    db.refresh(lote)
    return _a_lote_salida(lote)


# === Mapa MVT y PMTiles =========================================================================


def generar_mvt_luminarias(
    db: Session,
    sede: SedeResumen,
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
    try:
        dominio.validar_coordenadas_tesela(z, x, y)
    except dominio.ErrorDominioActivo as exc:
        raise _traducir_error(exc) from exc
    return repositorio.obtener_tesela_mvt(
        db,
        sede.id,
        z,
        x,
        y,
        estado_id=estado_id,
        tecnologia_id=tecnologia_id,
        potencia_id=potencia_id,
        marca_id=marca_id,
        zona_id=zona_id,
        barrio_id=barrio_id,
        en_bodega=en_bodega,
        validado=validado,
        en_transito=en_transito,
        texto=texto,
    )


def obtener_pmtiles_sede(
    db: Session,
    usuario: UsuarioAutenticado,
    sede_codigo: str,
    range_header: str | None,
) -> tuple[bytes, int, int, int, int]:
    """Devuelve (contenido, status_code, start, end, total)."""
    codigo = sede_codigo.strip().lower()
    sede_info = config_servicio.obtener_sede_por_codigo_publico(db, codigo)
    if sede_info is None:
        raise HTTPException(status_code=404, detail="Mapa base de sede no encontrado.")
    if sede_info["id"] not in {s.id for s in usuario.sedes}:
        raise HTTPException(status_code=403, detail="No tiene acceso a la sede solicitada.")

    ruta_disco = obtener_configuracion().archivos_dir / "mapa" / f"{codigo}.pmtiles"
    if ruta_disco.is_file():
        datos = ruta_disco.read_bytes()
    elif codigo in {"montelibano", "alcala"}:
        datos = dominio.construir_pmtiles_base_sede(codigo)
    else:
        raise HTTPException(
            status_code=404, detail="Mapa base PMTiles aún no disponible para esta sede."
        )

    total = len(datos)
    if range_header:
        try:
            inicio, fin = dominio.parsear_rango_bytes(range_header, total)
        except dominio.ErrorDominioActivo as exc:
            raise HTTPException(
                status_code=416,
                detail=exc.detail,
                headers={"Content-Range": f"bytes */{total}"},
            ) from exc
        return datos[inicio : fin + 1], 206, inicio, fin, total
    return datos, 200, 0, total - 1, total


# === Helpers públicos para otros módulos (migración, atención, trabajos, tablero) ==============


def asegurar_luminaria_importada(
    db: Session,
    *,
    sede_id: int,
    codigo: str,
    estado_id: int,
    barrio_id: int | None = None,
    latitud: float | None = None,
    longitud: float | None = None,
    tecnologia_id: int | None = None,
    potencia_id: int | None = None,
    marca_id: int | None = None,
    tipo_intervencion_id: int | None = None,
    codigo_externo: str | None = None,
    fecha_instalacion: date | None = None,
    fecha_mision: date | None = None,
    fecha_baja: date | None = None,
    poste: str | None = None,
    es_rural: bool = False,
    observaciones: str | None = None,
    actor_id: int | None = None,
) -> tuple[int, bool]:
    """Upsert idempotente por (sede_id, codigo) para importadores de migración."""
    codigo_norm = dominio.normalizar_codigo_luminaria(codigo)
    coords = dominio.validar_coordenadas(latitud, longitud)
    existente = repositorio.obtener_por_codigo(db, sede_id, codigo_norm)
    if existente is None:
        lum = Luminaria(
            sede_id=sede_id,
            codigo=codigo_norm,
            codigo_externo=codigo_externo,
            barrio_id=barrio_id,
            ubicacion=_geom_wkt(coords),
            estado_id=estado_id,
            tecnologia_id=tecnologia_id,
            potencia_id=potencia_id,
            marca_id=marca_id,
            tipo_intervencion_id=tipo_intervencion_id,
            fecha_instalacion=fecha_instalacion,
            fecha_mision=fecha_mision,
            fecha_baja=fecha_baja,
            poste=poste,
            es_rural=es_rural,
            observaciones=observaciones,
            creado_por=actor_id,
            modificado_por=actor_id,
        )
        repositorio.crear_luminaria(db, lum)
        repositorio.crear_evento(
            db,
            EventoActivo(
                luminaria_id=lum.id,
                tipo="alta",
                estado_nuevo_id=estado_id,
                detalle={"origen": "migracion", "codigo": codigo_norm},
                creado_por=actor_id,
            ),
        )
        return lum.id, True

    existente.codigo_externo = codigo_externo or existente.codigo_externo
    existente.barrio_id = barrio_id if barrio_id is not None else existente.barrio_id
    if coords is not None:
        existente.ubicacion = _geom_wkt(coords)
    existente.estado_id = estado_id
    existente.tecnologia_id = tecnologia_id or existente.tecnologia_id
    existente.potencia_id = potencia_id or existente.potencia_id
    existente.marca_id = marca_id or existente.marca_id
    existente.tipo_intervencion_id = tipo_intervencion_id or existente.tipo_intervencion_id
    existente.fecha_instalacion = fecha_instalacion
    existente.fecha_mision = fecha_mision
    existente.fecha_baja = fecha_baja
    existente.poste = poste or existente.poste
    existente.es_rural = es_rural
    existente.modificado_por = actor_id
    db.flush()
    return existente.id, False


def sembrar_comodines_activos(db: Session) -> dict[str, int]:
    """Crea la luminaria comodín SIN-IDENTIFICAR (estado 110) en cada sede activa."""
    estado_110 = config_servicio.obtener_estado_por_id_o_codigo(db, "luminaria", codigo="110")
    if estado_110 is None:
        return {"comodines_creados": 0}
    creados = 0
    for sede in config_servicio.listar_sedes_activas_resumen(db):
        if repositorio.obtener_por_codigo(db, sede["id"], "SIN-IDENTIFICAR") is None:
            repositorio.crear_luminaria(
                db,
                Luminaria(
                    sede_id=sede["id"],
                    codigo="SIN-IDENTIFICAR",
                    estado_id=estado_110["id"],
                    es_comodin=True,
                    observaciones="Luminaria comodín para PQRS sin placa identificada (RN-016).",
                ),
            )
            creados += 1
    db.flush()
    return {"comodines_creados": creados}
