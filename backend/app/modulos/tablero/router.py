"""Rutas del tablero gerencial (EP-09). `?sede=todas` es el consolidado y exige
`tablero.consolidado.ver`; nunca incluye sedes que el usuario no tenga asignadas."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.core.db import obtener_sesion
from app.modulos.seguridad.servicio import (
    SedeResumen,
    UsuarioAutenticado,
    requerir_permiso,
    requerir_tablero_alcance,
)
from app.modulos.tablero import servicio
from app.modulos.tablero.esquemas import RecalcularEntrada, RecalculoEncolado, ResumenTableroSalida

router = APIRouter(prefix="/tablero", tags=["tablero"])

Db = Annotated[Session, Depends(obtener_sesion)]
VeTablero = Annotated[UsuarioAutenticado, Depends(requerir_permiso("tablero.ver"))]


@router.get(
    "/resumen",
    response_model=ResumenTableroSalida,
    summary="Tablero gerencial de la sede o consolidado (?sede=todas)",
)
async def resumen(
    _: VeTablero,
    sedes: Annotated[list[SedeResumen], Depends(requerir_tablero_alcance)],
    db: Db,
    sede: Annotated[str | None, Query(max_length=40)] = None,
    anio: Annotated[int | None, Query(ge=2000, le=2100)] = None,
) -> ResumenTableroSalida:
    return await servicio.obtener_resumen(db, sedes, anio=anio, consolidado=sede == "todas")


@router.post(
    "/recalcular",
    response_model=RecalculoEncolado,
    status_code=202,
    summary="Encolar el recálculo de las tablas resumen",
)
async def recalcular(
    actor: VeTablero,
    db: Db,
    entrada: RecalcularEntrada | None = None,
    x_sede: Annotated[str | None, Header(alias="X-Sede")] = None,
) -> RecalculoEncolado:
    return await servicio.encolar_recalculo(
        db, actor, sede_id=(entrada.sede_id if entrada else None), x_sede=x_sede
    )
