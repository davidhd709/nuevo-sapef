"""Rutas HTTP del módulo de atención (EP-04)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.db import obtener_sesion
from app.core.paginacion import Pagina, TareaEncolada
from app.modulos.atencion import servicio
from app.modulos.atencion.esquemas import (
    CiudadanoCrearEntrada,
    CiudadanoEditarEntrada,
    CiudadanoSalida,
    PendienteSalida,
    PqrsAnularEntrada,
    PqrsCrearEntrada,
    PqrsEditarEntrada,
    PqrsExportarEntrada,
    PqrsLuminariaEntrada,
    PqrsSalida,
    Semaforo,
)
from app.modulos.seguridad.servicio import (
    SedeResumen,
    UsuarioAutenticado,
    requerir_algun_permiso,
    requerir_permiso,
    requerir_sede,
)

router = APIRouter(tags=["atencion"])

Db = Annotated[Session, Depends(obtener_sesion)]
SedeActiva = Annotated[SedeResumen, Depends(requerir_sede)]
Ve = Annotated[UsuarioAutenticado, Depends(requerir_permiso("atencion.pqrs.ver"))]
Crea = Annotated[UsuarioAutenticado, Depends(requerir_permiso("atencion.pqrs.crear"))]
Edita = Annotated[UsuarioAutenticado, Depends(requerir_permiso("atencion.pqrs.editar"))]
Anula = Annotated[UsuarioAutenticado, Depends(requerir_permiso("atencion.pqrs.anular"))]
Exporta = Annotated[UsuarioAutenticado, Depends(requerir_permiso("atencion.pqrs.exportar"))]
GestionaCiudadanos = Annotated[
    UsuarioAutenticado,
    Depends(requerir_algun_permiso("atencion.pqrs.crear", "atencion.pqrs.editar")),
]


# --- Ciudadanos ---------------------------------------------------------------------------------


@router.get(
    "/ciudadanos",
    response_model=Pagina[CiudadanoSalida],
    summary="Buscar solicitantes (sin tildes; enmascarados sin permiso de datos personales)",
)
def buscar_ciudadanos(
    sede: SedeActiva,
    actor: Ve,
    db: Db,
    buscar: Annotated[str | None, Query(max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Pagina[CiudadanoSalida]:
    return servicio.buscar_ciudadanos(db, actor, sede, buscar, page=page, size=size)


@router.post(
    "/ciudadanos", response_model=CiudadanoSalida, status_code=201, summary="Registrar solicitante"
)
def crear_ciudadano(
    entrada: CiudadanoCrearEntrada, sede: SedeActiva, actor: GestionaCiudadanos, db: Db
) -> CiudadanoSalida:
    return servicio.crear_ciudadano(db, actor, sede, entrada)


@router.get("/ciudadanos/{ciudadano_id}", response_model=CiudadanoSalida, summary="Un solicitante")
def obtener_ciudadano(ciudadano_id: int, sede: SedeActiva, actor: Ve, db: Db) -> CiudadanoSalida:
    return servicio.obtener_ciudadano(db, actor, sede, ciudadano_id)


@router.patch(
    "/ciudadanos/{ciudadano_id}", response_model=CiudadanoSalida, summary="Editar solicitante"
)
def editar_ciudadano(
    ciudadano_id: int,
    entrada: CiudadanoEditarEntrada,
    sede: SedeActiva,
    actor: GestionaCiudadanos,
    db: Db,
) -> CiudadanoSalida:
    return servicio.editar_ciudadano(db, actor, sede, ciudadano_id, entrada)


# --- PQRS ---------------------------------------------------------------------------------------


@router.get(
    "/pqrs/pendientes",
    response_model=Pagina[PendienteSalida],
    summary="Luminarias con PQRS abierta y su semáforo (umbrales de la sede)",
)
def listar_pendientes(
    sede: SedeActiva,
    actor: Ve,
    db: Db,
    semaforo: Semaforo | None = None,
    barrio_id: int | None = None,
    prioridad: Annotated[int | None, Query(ge=0, le=3)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Pagina[PendienteSalida]:
    return servicio.listar_pendientes(
        db,
        actor,
        sede,
        semaforo=semaforo,
        barrio_id=barrio_id,
        prioridad=prioridad,
        page=page,
        size=size,
    )


@router.post(
    "/pqrs/exportar",
    response_model=TareaEncolada,
    status_code=202,
    summary="Exportar PQRS a Excel (segundo plano)",
)
async def exportar_pqrs(
    sede: SedeActiva, actor: Exporta, entrada: PqrsExportarEntrada | None = None
) -> TareaEncolada:
    return await servicio.encolar_exportacion(actor, sede, entrada or PqrsExportarEntrada())


@router.get(
    "/pqrs", response_model=Pagina[PqrsSalida], summary="Listar PQRS (por defecto, 30 días)"
)
def listar_pqrs(
    sede: SedeActiva,
    actor: Ve,
    db: Db,
    desde: date | None = None,
    hasta: date | None = None,
    estado_id: int | None = None,
    prioridad: Annotated[int | None, Query(ge=0, le=3)] = None,
    barrio_id: int | None = None,
    numero: int | None = None,
    ciudadano_id: int | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Pagina[PqrsSalida]:
    return servicio.listar_pqrs(
        db,
        actor,
        sede,
        page=page,
        size=size,
        desde=desde,
        hasta=hasta,
        estado_id=estado_id,
        prioridad=prioridad,
        barrio_id=barrio_id,
        numero=numero,
        ciudadano_id=ciudadano_id,
    )


@router.post(
    "/pqrs",
    response_model=PqrsSalida,
    status_code=201,
    summary="Registrar una PQRS (canal obligatorio; una o varias luminarias)",
)
async def crear_pqrs(
    entrada: PqrsCrearEntrada, sede: SedeActiva, actor: Crea, db: Db
) -> PqrsSalida:
    return await servicio.crear_pqrs(db, actor, sede, entrada)


@router.get("/pqrs/{pqrs_id}", response_model=PqrsSalida, summary="Detalle de una PQRS")
def obtener_pqrs(pqrs_id: int, sede: SedeActiva, actor: Ve, db: Db) -> PqrsSalida:
    return servicio.obtener_pqrs(db, actor, sede, pqrs_id)


@router.patch("/pqrs/{pqrs_id}", response_model=PqrsSalida, summary="Editar una PQRS abierta")
def editar_pqrs(
    pqrs_id: int, entrada: PqrsEditarEntrada, sede: SedeActiva, actor: Edita, db: Db
) -> PqrsSalida:
    return servicio.editar_pqrs(db, actor, sede, pqrs_id, entrada)


@router.post("/pqrs/{pqrs_id}/anular", response_model=PqrsSalida, summary="Anular una PQRS")
def anular_pqrs(
    pqrs_id: int, entrada: PqrsAnularEntrada, sede: SedeActiva, actor: Anula, db: Db
) -> PqrsSalida:
    return servicio.anular_pqrs(db, actor, sede, pqrs_id, entrada)


@router.post(
    "/pqrs/{pqrs_id}/luminarias",
    response_model=PqrsSalida,
    status_code=201,
    summary="Agregar una luminaria a la PQRS",
)
def agregar_luminaria(
    pqrs_id: int, entrada: PqrsLuminariaEntrada, sede: SedeActiva, actor: Edita, db: Db
) -> PqrsSalida:
    return servicio.agregar_luminaria(db, actor, sede, pqrs_id, entrada)


@router.delete(
    "/pqrs/{pqrs_id}/luminarias/{luminaria_id}",
    status_code=204,
    summary="Quitar una luminaria no reparada (no la última)",
)
def quitar_luminaria(
    pqrs_id: int, luminaria_id: int, sede: SedeActiva, actor: Edita, db: Db
) -> Response:
    servicio.quitar_luminaria(db, actor, sede, pqrs_id, luminaria_id)
    return Response(status_code=204)
