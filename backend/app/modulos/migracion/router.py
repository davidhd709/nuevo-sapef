"""Rutas HTTP del módulo de migración (IMP-1, IMP-6)."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.db import obtener_sesion
from app.modulos.migracion import servicio
from app.modulos.migracion.esquemas import EjecucionMigracionSalida
from app.modulos.seguridad.servicio import (
    SedeResumen,
    UsuarioAutenticado,
    requerir_permiso,
    requerir_sede,
)

router = APIRouter(prefix="/migracion", tags=["migracion"])

Db = Annotated[Session, Depends(obtener_sesion)]
SedeActiva = Annotated[SedeResumen, Depends(requerir_sede)]


@router.post(
    "/luminarias",
    response_model=EjecucionMigracionSalida,
    status_code=202,
    summary="Importar luminarias desde Excel de SAPEF (idempotente)",
)
async def importar_luminarias(
    archivo: Annotated[UploadFile, File(...)],
    sede: SedeActiva,
    actor: Annotated[
        UsuarioAutenticado, Depends(requerir_permiso("activos.luminaria.crear"))
    ],
    db: Db,
) -> EjecucionMigracionSalida:
    contenido = await archivo.read()
    return await servicio.importar_luminarias_excel(db, actor, sede, contenido)


@router.post(
    "/base",
    response_model=EjecucionMigracionSalida,
    status_code=202,
    summary="Importar zonas, barrios y usuarios sin contraseña (IMP-6)",
)
async def importar_base(
    archivo: Annotated[UploadFile, File(...)],
    sede: SedeActiva,
    actor: Annotated[
        UsuarioAutenticado, Depends(requerir_permiso("seguridad.usuario.crear"))
    ],
    db: Db,
) -> EjecucionMigracionSalida:
    contenido = await archivo.read()
    return await servicio.importar_base_config_excel(db, actor, sede, contenido)


@router.get(
    "/ejecuciones/{ejecucion_id}",
    response_model=EjecucionMigracionSalida,
    summary="Consultar resultado y conciliación de una ejecución de migración",
)
def obtener_ejecucion(
    ejecucion_id: int,
    sede: SedeActiva,
    _: Annotated[UsuarioAutenticado, Depends(requerir_permiso("activos.luminaria.ver"))],
    db: Db,
) -> EjecucionMigracionSalida:
    return servicio.obtener_ejecucion(db, sede, ejecucion_id)
