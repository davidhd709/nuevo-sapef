"""Rutas HTTP del módulo de trabajos (EP-05)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.db import obtener_sesion
from app.core.paginacion import Pagina, TareaEncolada
from app.modulos.seguridad.servicio import (
    SedeResumen,
    UsuarioAutenticado,
    requerir_algun_permiso,
    requerir_permiso,
    requerir_sede,
)
from app.modulos.trabajos import servicio
from app.modulos.trabajos.esquemas import (
    CargueMasivoSalida,
    CuadrillaCrearEntrada,
    CuadrillaEditarEntrada,
    CuadrillaSalida,
    OrdenAnularEntrada,
    OrdenAsignarEntrada,
    OrdenCerrarEntrada,
    OrdenCrearEntrada,
    OrdenEditarEntrada,
    OrdenSalida,
    TecnicoSalida,
    TipoCargue,
    TipoOrden,
)

router = APIRouter(tags=["trabajos"])

Db = Annotated[Session, Depends(obtener_sesion)]
SedeActiva = Annotated[SedeResumen, Depends(requerir_sede)]
Ve = Annotated[
    UsuarioAutenticado,
    Depends(requerir_algun_permiso("trabajos.orden.ver", "trabajos.orden.ver_propias")),
]
Crea = Annotated[UsuarioAutenticado, Depends(requerir_permiso("trabajos.orden.crear"))]
Asigna = Annotated[UsuarioAutenticado, Depends(requerir_permiso("trabajos.orden.asignar"))]
VeEquipo = Annotated[
    UsuarioAutenticado,
    Depends(requerir_algun_permiso("trabajos.orden.asignar", "trabajos.orden.ver")),
]
Cierra = Annotated[
    UsuarioAutenticado,
    Depends(requerir_algun_permiso("trabajos.orden.cerrar", "trabajos.orden.ejecutar")),
]
Anula = Annotated[UsuarioAutenticado, Depends(requerir_permiso("trabajos.orden.anular"))]
Carga = Annotated[UsuarioAutenticado, Depends(requerir_permiso("trabajos.cargue_masivo.crear"))]

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# --- Técnicos y cuadrillas ----------------------------------------------------------------------


@router.get("/tecnicos", response_model=list[TecnicoSalida], summary="Técnicos de la sede")
def listar_tecnicos(sede: SedeActiva, _: VeEquipo, db: Db) -> list[TecnicoSalida]:
    return servicio.listar_tecnicos(db, sede)


@router.get("/cuadrillas", response_model=list[CuadrillaSalida], summary="Cuadrillas de la sede")
def listar_cuadrillas(
    sede: SedeActiva, _: VeEquipo, db: Db, activa: bool | None = None
) -> list[CuadrillaSalida]:
    return servicio.listar_cuadrillas(db, sede, activa)


@router.post(
    "/cuadrillas", response_model=CuadrillaSalida, status_code=201, summary="Crear una cuadrilla"
)
def crear_cuadrilla(
    entrada: CuadrillaCrearEntrada, sede: SedeActiva, actor: Asigna, db: Db
) -> CuadrillaSalida:
    return servicio.crear_cuadrilla(db, actor, sede, entrada)


@router.patch(
    "/cuadrillas/{cuadrilla_id}", response_model=CuadrillaSalida, summary="Editar una cuadrilla"
)
def editar_cuadrilla(
    cuadrilla_id: int, entrada: CuadrillaEditarEntrada, sede: SedeActiva, actor: Asigna, db: Db
) -> CuadrillaSalida:
    return servicio.editar_cuadrilla(db, actor, sede, cuadrilla_id, entrada)


# --- Cargue masivo (rutas fijas antes de /ordenes/{orden_id}) ---------------------------------


@router.get(
    "/ordenes/plantillas/{tipo}",
    summary="Plantilla Excel del cargue masivo",
    response_class=Response,
    responses={200: {"content": {_XLSX: {}}}},
)
def descargar_plantilla(tipo: TipoCargue, _sede: SedeActiva, _: Carga) -> Response:
    return Response(
        content=servicio.plantilla_cargue(tipo),
        media_type=_XLSX,
        headers={"Content-Disposition": f'attachment; filename="plantilla_{tipo}.xlsx"'},
    )


@router.post(
    "/ordenes/cargue-masivo/{tipo}",
    response_model=TareaEncolada,
    status_code=202,
    summary="Cargar órdenes ejecutadas desde Excel (todo o nada, en segundo plano)",
)
async def cargar_masivo(
    tipo: TipoCargue,
    archivo: Annotated[UploadFile, File(...)],
    sede: SedeActiva,
    actor: Carga,
    db: Db,
) -> TareaEncolada:
    return await servicio.recibir_cargue(db, actor, sede, tipo, archivo)


@router.get(
    "/ordenes/cargue-masivo/{cargue_id}",
    response_model=CargueMasivoSalida,
    summary="Resultado de un cargue masivo (errores por fila)",
)
def obtener_cargue(cargue_id: int, sede: SedeActiva, _: Carga, db: Db) -> CargueMasivoSalida:
    return servicio.obtener_cargue(db, sede, cargue_id)


# --- Órdenes ------------------------------------------------------------------------------------


@router.get(
    "/ordenes",
    response_model=Pagina[OrdenSalida],
    summary="Órdenes de la sede (por defecto, 2 meses; con ver_propias, solo las asignadas)",
)
def listar_ordenes(
    sede: SedeActiva,
    actor: Ve,
    db: Db,
    tipo: TipoOrden | None = None,
    estado_id: int | None = None,
    tecnico_id: int | None = None,
    pqrs_id: int | None = None,
    luminaria_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Pagina[OrdenSalida]:
    return servicio.listar_ordenes(
        db,
        actor,
        sede,
        page=page,
        size=size,
        tipo=tipo,
        estado_id=estado_id,
        tecnico_id=tecnico_id,
        pqrs_id=pqrs_id,
        luminaria_id=luminaria_id,
        desde=desde,
        hasta=hasta,
    )


@router.post(
    "/ordenes",
    response_model=OrdenSalida,
    status_code=201,
    summary="Crear una orden (desde una PQRS o directa)",
)
def crear_orden(entrada: OrdenCrearEntrada, sede: SedeActiva, actor: Crea, db: Db) -> OrdenSalida:
    return servicio.crear_orden(db, actor, sede, entrada)


@router.get("/ordenes/{orden_id}", response_model=OrdenSalida, summary="Detalle de una orden")
def obtener_orden(orden_id: int, sede: SedeActiva, actor: Ve, db: Db) -> OrdenSalida:
    return servicio.obtener_orden(db, actor, sede, orden_id)


@router.patch("/ordenes/{orden_id}", response_model=OrdenSalida, summary="Editar una orden abierta")
def editar_orden(
    orden_id: int, entrada: OrdenEditarEntrada, sede: SedeActiva, actor: Crea, db: Db
) -> OrdenSalida:
    return servicio.editar_orden(db, actor, sede, orden_id, entrada)


@router.post(
    "/ordenes/{orden_id}/asignar",
    response_model=OrdenSalida,
    summary="Asignar a un técnico o cuadrilla de la sede (con aviso push)",
)
async def asignar_orden(
    orden_id: int, entrada: OrdenAsignarEntrada, sede: SedeActiva, actor: Asigna, db: Db
) -> OrdenSalida:
    return await servicio.asignar_orden(db, actor, sede, orden_id, entrada)


@router.post(
    "/ordenes/{orden_id}/cerrar",
    response_model=OrdenSalida,
    summary="Cerrar la orden: luminarias, materiales y evidencias en una sola transacción",
)
async def cerrar_orden(
    orden_id: int, entrada: OrdenCerrarEntrada, sede: SedeActiva, actor: Cierra, db: Db
) -> OrdenSalida:
    return await servicio.cerrar_orden(db, actor, sede, orden_id, entrada)


@router.post("/ordenes/{orden_id}/anular", response_model=OrdenSalida, summary="Anular una orden")
def anular_orden(
    orden_id: int, entrada: OrdenAnularEntrada, sede: SedeActiva, actor: Anula, db: Db
) -> OrdenSalida:
    return servicio.anular_orden(db, actor, sede, orden_id, entrada)
