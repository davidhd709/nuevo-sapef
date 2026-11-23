"""Rutas HTTP del módulo de inventario (EP-06)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.db import obtener_sesion
from app.core.paginacion import Pagina, TareaEncolada
from app.modulos.activos.servicio import LuminariaSalida
from app.modulos.activos.servicio import Pagina as PaginaActivos
from app.modulos.inventario import servicio
from app.modulos.inventario.esquemas import (
    BodegaCambioEntrada,
    CargueBodegaSalida,
    MaterialCrearEntrada,
    MaterialEditarEntrada,
    MaterialSalida,
    MovimientoEntrada,
    MovimientoSalida,
)
from app.modulos.seguridad.servicio import (
    SedeResumen,
    UsuarioAutenticado,
    requerir_algun_permiso,
    requerir_permiso,
    requerir_sede,
)

router = APIRouter(tags=["inventario"])

Db = Annotated[Session, Depends(obtener_sesion)]
SedeActiva = Annotated[SedeResumen, Depends(requerir_sede)]
VeMateriales = Annotated[UsuarioAutenticado, Depends(requerir_permiso("inventario.material.ver"))]
EditaMateriales = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("inventario.material.editar"))
]
Mueve = Annotated[
    UsuarioAutenticado,
    Depends(requerir_algun_permiso("inventario.movimiento.crear", "inventario.movimiento.ajustar")),
]
VeBodega = Annotated[UsuarioAutenticado, Depends(requerir_permiso("inventario.bodega.ver"))]
EditaBodega = Annotated[UsuarioAutenticado, Depends(requerir_permiso("inventario.bodega.editar"))]


@router.get("/materiales", response_model=Pagina[MaterialSalida], summary="Materiales de la sede")
def listar_materiales(
    sede: SedeActiva,
    _: VeMateriales,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 50,
    buscar: Annotated[str | None, Query(max_length=80)] = None,
    categoria: Annotated[str | None, Query(max_length=60)] = None,
    bajo_minimo: bool | None = None,
    activo: bool | None = None,
) -> Pagina[MaterialSalida]:
    return servicio.listar_materiales(
        db,
        sede,
        page=page,
        size=size,
        buscar=buscar,
        categoria=categoria,
        bajo_minimo=bajo_minimo,
        activo=activo,
    )


@router.post(
    "/materiales", response_model=MaterialSalida, status_code=201, summary="Crear un material"
)
def crear_material(
    entrada: MaterialCrearEntrada, sede: SedeActiva, actor: EditaMateriales, db: Db
) -> MaterialSalida:
    return servicio.crear_material(db, actor, sede, entrada)


@router.get("/materiales/{material_id}", response_model=MaterialSalida, summary="Un material")
def obtener_material(material_id: int, sede: SedeActiva, _: VeMateriales, db: Db) -> MaterialSalida:
    return servicio.obtener_material(db, sede, material_id)


@router.patch(
    "/materiales/{material_id}",
    response_model=MaterialSalida,
    summary="Editar un material (las existencias solo cambian con movimientos)",
)
def editar_material(
    material_id: int,
    entrada: MaterialEditarEntrada,
    sede: SedeActiva,
    actor: EditaMateriales,
    db: Db,
) -> MaterialSalida:
    return servicio.editar_material(db, actor, sede, material_id, entrada)


@router.get(
    "/materiales/{material_id}/movimientos",
    response_model=Pagina[MovimientoSalida],
    summary="Kárdex de un material",
)
def listar_movimientos(
    material_id: int,
    sede: SedeActiva,
    _: VeMateriales,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=500)] = 100,
    desde: datetime | None = None,
    hasta: datetime | None = None,
) -> Pagina[MovimientoSalida]:
    return servicio.listar_movimientos(
        db, sede, material_id, page=page, size=size, desde=desde, hasta=hasta
    )


@router.post(
    "/materiales/{material_id}/movimientos",
    response_model=MovimientoSalida,
    status_code=201,
    responses={200: {"model": MovimientoSalida, "description": "Ya aplicado (mismo uuid_origen)"}},
    summary="Registrar entrada, salida o ajuste (sin existencias negativas)",
)
def registrar_movimiento(
    material_id: int,
    entrada: MovimientoEntrada,
    sede: SedeActiva,
    actor: Mueve,
    db: Db,
) -> JSONResponse:
    movimiento, creado = servicio.registrar_movimiento(db, actor, sede, material_id, entrada)
    return JSONResponse(movimiento.model_dump(mode="json"), status_code=201 if creado else 200)


@router.get(
    "/bodega/luminarias",
    response_model=PaginaActivos[LuminariaSalida],
    summary="Luminarias en bodega (124, 123, 125, 112, 126)",
)
def listar_bodega(
    sede: SedeActiva,
    _: VeBodega,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 50,
    texto: Annotated[str | None, Query(max_length=80)] = None,
    estado_id: int | None = None,
) -> PaginaActivos[LuminariaSalida]:
    return servicio.listar_bodega(db, sede, page=page, size=size, texto=texto, estado_id=estado_id)


@router.patch(
    "/bodega/luminarias/{luminaria_id}",
    response_model=LuminariaSalida,
    summary="Cambiar el estado en bodega (126 es terminal)",
)
def cambiar_estado_bodega(
    luminaria_id: int,
    entrada: BodegaCambioEntrada,
    sede: SedeActiva,
    actor: EditaBodega,
    db: Db,
) -> LuminariaSalida:
    return servicio.cambiar_estado_bodega(db, actor, sede, luminaria_id, entrada)


@router.post(
    "/bodega/cargue",
    response_model=TareaEncolada,
    status_code=202,
    summary="Cargar estados de bodega desde Excel (todo o nada, en segundo plano)",
)
async def cargar_bodega(
    archivo: Annotated[UploadFile, File(...)],
    sede: SedeActiva,
    actor: EditaBodega,
    db: Db,
) -> TareaEncolada:
    return await servicio.recibir_cargue_bodega(db, actor, sede, archivo)


@router.get(
    "/bodega/cargue/{cargue_id}",
    response_model=CargueBodegaSalida,
    summary="Resultado de un cargue de bodega",
)
def obtener_cargue_bodega(
    cargue_id: int, sede: SedeActiva, _: VeBodega, db: Db
) -> CargueBodegaSalida:
    return servicio.obtener_cargue_bodega(db, sede, cargue_id)
