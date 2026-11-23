"""Rutas HTTP del módulo de activos y mapa (EP-03)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.core.db import obtener_sesion
from app.modulos.activos import servicio
from app.modulos.activos.esquemas import (
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
)
from app.modulos.seguridad.servicio import (
    SedeResumen,
    UsuarioAutenticado,
    requerir_permiso,
    requerir_sede,
)

router = APIRouter(tags=["activos"])

Db = Annotated[Session, Depends(obtener_sesion)]
SedeActiva = Annotated[SedeResumen, Depends(requerir_sede)]
VeLuminarias = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("activos.luminaria.ver"))
]
CreaLuminarias = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("activos.luminaria.crear"))
]
EditaLuminarias = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("activos.luminaria.editar"))
]
MueveLuminarias = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("activos.luminaria.mover"))
]
ExportaLuminarias = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("activos.luminaria.exportar"))
]
CreaLotes = Annotated[UsuarioAutenticado, Depends(requerir_permiso("activos.lote.crear"))]
VeMapa = Annotated[UsuarioAutenticado, Depends(requerir_permiso("activos.mapa.ver"))]


@router.get(
    "/luminarias",
    response_model=Pagina[LuminariaSalida],
    summary="Listar luminarias de la sede activa con filtros y paginación",
)
def listar_luminarias(
    sede: SedeActiva,
    _: VeLuminarias,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    texto: Annotated[str | None, Query(max_length=120)] = None,
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
    return servicio.listar_luminarias(
        db,
        sede,
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


@router.get(
    "/luminarias/buscar",
    response_model=list[LuminariaSalida],
    summary="Autocompletar luminarias en el servidor",
)
def buscar_luminarias(
    sede: SedeActiva,
    _: VeLuminarias,
    db: Db,
    q: Annotated[str, Query(min_length=2, max_length=80)],
) -> list[LuminariaSalida]:
    return servicio.buscar_luminarias(db, sede, q)


@router.post(
    "/luminarias",
    response_model=LuminariaSalida,
    status_code=201,
    summary="Registrar una nueva luminaria en la sede activa",
)
def crear_luminaria(
    entrada: LuminariaCrearEntrada,
    sede: SedeActiva,
    actor: CreaLuminarias,
    db: Db,
) -> LuminariaSalida:
    return servicio.crear_luminaria(db, actor, sede, entrada)


@router.post(
    "/luminarias/exportar",
    response_model=TareaExportacionSalida,
    status_code=202,
    summary="Encolar exportación de luminarias a Excel",
)
async def exportar_luminarias(
    sede: SedeActiva,
    actor: ExportaLuminarias,
    entrada: LuminariaExportarEntrada | None = None,
) -> TareaExportacionSalida:
    return await servicio.encolar_exportacion_luminarias(actor, sede, entrada)


@router.get(
    "/luminarias/{luminaria_id}",
    response_model=LuminariaSalida,
    summary="Consultar detalle de una luminaria de la sede activa",
)
def obtener_luminaria(
    luminaria_id: int,
    sede: SedeActiva,
    _: VeLuminarias,
    db: Db,
) -> LuminariaSalida:
    return servicio.obtener_luminaria(db, sede, luminaria_id)


@router.patch(
    "/luminarias/{luminaria_id}",
    response_model=LuminariaSalida,
    summary="Editar datos o estado de una luminaria",
)
def editar_luminaria(
    luminaria_id: int,
    entrada: LuminariaEditarEntrada,
    sede: SedeActiva,
    actor: EditaLuminarias,
    db: Db,
) -> LuminariaSalida:
    return servicio.editar_luminaria(db, actor, sede, luminaria_id, entrada)


@router.post(
    "/luminarias/{luminaria_id}/ubicacion",
    response_model=LuminariaSalida,
    summary="Actualizar ubicación geográfica registrando historial",
)
def mover_ubicacion(
    luminaria_id: int,
    entrada: LuminariaMoverEntrada,
    sede: SedeActiva,
    actor: MueveLuminarias,
    db: Db,
) -> LuminariaSalida:
    return servicio.mover_ubicacion_luminaria(db, actor, sede, luminaria_id, entrada)


@router.get(
    "/luminarias/{luminaria_id}/historial",
    response_model=HistorialLuminariaSalida,
    summary="Consultar ficha y hoja de vida completa de una luminaria",
)
def obtener_historial(
    luminaria_id: int,
    sede: SedeActiva,
    _: VeLuminarias,
    db: Db,
) -> HistorialLuminariaSalida:
    return servicio.obtener_historial_luminaria(db, sede, luminaria_id)


# --- Lotes ---------------------------------------------------------------------------------------


@router.get(
    "/lotes",
    response_model=Pagina[LoteSalida],
    summary="Listar lotes de marcación de la sede activa",
)
def listar_lotes(
    sede: SedeActiva,
    _: VeLuminarias,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Pagina[LoteSalida]:
    return servicio.listar_lotes(db, sede, page=page, size=size)


@router.post(
    "/lotes",
    response_model=LoteSalida,
    status_code=201,
    summary="Registrar lote por consecutivos creando luminarias en bodega (estado 124)",
)
def crear_lote(
    entrada: LoteCrearEntrada,
    sede: SedeActiva,
    actor: CreaLotes,
    db: Db,
) -> LoteSalida:
    return servicio.crear_lote(db, actor, sede, entrada)


# --- Mapa MVT y PMTiles --------------------------------------------------------------------------


@router.get(
    "/mapa/luminarias/{z}/{x}/{y}.mvt",
    summary="Tesela vectorial Mapbox (MVT) desde PostGIS con agrupación en zooms bajos",
)
def obtener_tesela_mvt(
    z: int,
    x: int,
    y: int,
    sede: SedeActiva,
    _: VeMapa,
    db: Db,
    estado_id: int | None = None,
    tecnologia_id: int | None = None,
    potencia_id: int | None = None,
    marca_id: int | None = None,
    zona_id: int | None = None,
    barrio_id: int | None = None,
    en_bodega: bool | None = None,
    validado: bool | None = None,
    en_transito: bool | None = None,
    texto: Annotated[str | None, Query(max_length=120)] = None,
) -> Response:
    mvt = servicio.generar_mvt_luminarias(
        db,
        sede,
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
    return Response(
        content=mvt,
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=60"},
    )


@router.get(
    "/mapa/base/{sede_codigo}.pmtiles",
    summary="Mapa base PMTiles de una sede con soporte de rangos HTTP (Range)",
)
def obtener_pmtiles(
    sede_codigo: str,
    usuario: VeMapa,
    db: Db,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    contenido, status_code, inicio, fin, total = servicio.obtener_pmtiles_sede(
        db, usuario, sede_codigo, range_header
    )
    cabeceras = {"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"}
    if status_code == 206:
        cabeceras["Content-Range"] = f"bytes {inicio}-{fin}/{total}"
    return Response(
        content=contenido,
        status_code=status_code,
        media_type="application/vnd.pmtiles",
        headers=cabeceras,
    )
