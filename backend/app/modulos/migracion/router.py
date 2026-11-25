"""Rutas HTTP del módulo de migración (RF-110 a RF-112).

Todas las importaciones responden 202 con la ejecución «pendiente»: el worker procesa el
archivo y el resultado se consulta en `GET /migracion/ejecuciones/{id}`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.db import obtener_sesion
from app.modulos.migracion import servicio
from app.modulos.migracion.esquemas import EjecucionMigracionSalida
from app.modulos.seguridad.servicio import (
    SedeResumen,
    UsuarioAutenticado,
    requerir_algun_permiso,
    requerir_permiso,
    requerir_sede,
)

router = APIRouter(prefix="/migracion", tags=["migracion"])

Db = Annotated[Session, Depends(obtener_sesion)]
SedeActiva = Annotated[SedeResumen, Depends(requerir_sede)]
Archivo = Annotated[UploadFile, File(...)]
ArchivoOpcional = Annotated[UploadFile | None, File()]


def _actor(tipo: str) -> object:
    """Usuario autenticado con el permiso del importador (`servicio.PERMISOS`)."""
    return Annotated[UsuarioAutenticado, Depends(requerir_permiso(servicio.PERMISOS[tipo]))]


@router.post(
    "/luminarias",
    response_model=EjecucionMigracionSalida,
    status_code=202,
    summary="Importar luminarias (plantilla o LUMINARIAS_LIST_DESCARGA de SAPEF; .xlsx o .csv)",
)
async def importar_luminarias(
    archivo: Archivo, sede: SedeActiva, actor: _actor("luminarias"), db: Db
) -> EjecucionMigracionSalida:
    return await servicio.recibir(db, actor, sede, "luminarias", [("archivo", archivo)])


@router.post(
    "/base",
    response_model=EjecucionMigracionSalida,
    status_code=202,
    summary="Importar zonas, barrios y usuarios sin contraseña (IMP-6)",
)
async def importar_base(
    archivo: Archivo, sede: SedeActiva, actor: _actor("base"), db: Db
) -> EjecucionMigracionSalida:
    return await servicio.recibir(db, actor, sede, "base", [("archivo", archivo)])


@router.post(
    "/pqrs",
    response_model=EjecucionMigracionSalida,
    status_code=202,
    summary="Importar PQRS históricas (plantilla o LUMINARIAS_REPARAR de SAPEF)",
)
async def importar_pqrs(
    archivo: Archivo, sede: SedeActiva, actor: _actor("pqrs"), db: Db
) -> EjecucionMigracionSalida:
    return await servicio.recibir(db, actor, sede, "pqrs", [("archivo", archivo)])


@router.post(
    "/ordenes",
    response_model=EjecucionMigracionSalida,
    status_code=202,
    summary="Importar mantenimientos, expansiones, modernizaciones y reubicaciones de SAPEF",
)
async def importar_ordenes(
    sede: SedeActiva,
    actor: _actor("ordenes"),
    db: Db,
    mantenimientos: ArchivoOpcional = None,
    expansiones: ArchivoOpcional = None,
    modernizaciones: ArchivoOpcional = None,
    reubicaciones: ArchivoOpcional = None,
) -> EjecucionMigracionSalida:
    recibidos = {
        "mantenimientos": mantenimientos,
        "expansiones": expansiones,
        "modernizaciones": modernizaciones,
        "reubicaciones": reubicaciones,
    }
    adjuntos = [(campo, a) for campo, a in recibidos.items() if a is not None]
    if not adjuntos:
        raise HTTPException(
            status_code=422,
            detail="Adjunte al menos uno: mantenimientos, expansiones, modernizaciones o "
            "reubicaciones.",
        )
    return await servicio.recibir(db, actor, sede, "ordenes", adjuntos)


@router.post(
    "/inventario",
    response_model=EjecucionMigracionSalida,
    status_code=202,
    summary="Importar materiales, kárdex inicial y luminarias en bodega (con conciliación)",
)
async def importar_inventario(
    archivo: Archivo, sede: SedeActiva, actor: _actor("inventario"), db: Db
) -> EjecucionMigracionSalida:
    return await servicio.recibir(db, actor, sede, "inventario", [("archivo", archivo)])


@router.get(
    "/ejecuciones",
    response_model=list[EjecucionMigracionSalida],
    summary="Últimas ejecuciones de migración de la sede",
)
def listar_ejecuciones(
    sede: SedeActiva,
    actor: Annotated[
        UsuarioAutenticado, Depends(requerir_algun_permiso(*servicio.PERMISOS.values()))
    ],
    db: Db,
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[EjecucionMigracionSalida]:
    return servicio.listar_ejecuciones(db, actor, sede, limite)


@router.get(
    "/ejecuciones/{ejecucion_id}",
    response_model=EjecucionMigracionSalida,
    summary="Resultado y conciliación de una ejecución de migración",
)
def obtener_ejecucion(
    ejecucion_id: int,
    sede: SedeActiva,
    actor: Annotated[
        UsuarioAutenticado, Depends(requerir_algun_permiso(*servicio.PERMISOS.values()))
    ],
    db: Db,
) -> EjecucionMigracionSalida:
    return servicio.obtener_ejecucion(db, actor, sede, ejecucion_id)
