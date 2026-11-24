"""Rutas HTTP de la app de campo: paquete de bajada, lote de subida y seguimiento (§9.7)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import obtener_sesion
from app.core.paginacion import Pagina
from app.modulos.seguridad.servicio import (
    SedeResumen,
    UsuarioAutenticado,
    requerir_permiso,
    requerir_sede,
)
from app.modulos.sincronizacion import servicio
from app.modulos.sincronizacion.esquemas import (
    EstadoRegistro,
    OperacionCampoSalida,
    PaqueteCampo,
    SincronizarEntrada,
    SincronizarSalida,
)

router = APIRouter(prefix="/campo", tags=["campo"])

Db = Annotated[Session, Depends(obtener_sesion)]
SedeActiva = Annotated[SedeResumen, Depends(requerir_sede)]
UsaCampo = Annotated[UsuarioAutenticado, Depends(requerir_permiso("campo.app.usar"))]
VeOrdenes = Annotated[UsuarioAutenticado, Depends(requerir_permiso("trabajos.orden.ver"))]


@router.get(
    "/paquete",
    response_model=PaqueteCampo,
    summary="Paquete para trabajar sin señal (completo, o solo cambios con `desde`)",
)
def obtener_paquete(
    actor: UsaCampo,
    sede: SedeActiva,
    db: Db,
    desde: Annotated[str | None, Query(max_length=200, description="Cursor anterior")] = None,
) -> PaqueteCampo:
    return servicio.obtener_paquete(db, actor, sede, desde)


@router.post(
    "/sincronizar",
    response_model=SincronizarSalida,
    summary="Aplicar un lote de operaciones de campo (idempotente por uuid)",
)
async def sincronizar(
    entrada: SincronizarEntrada, actor: UsaCampo, sede: SedeActiva, db: Db
) -> SincronizarSalida:
    return await servicio.sincronizar(db, actor, sede, entrada)


@router.get(
    "/operaciones",
    response_model=Pagina[OperacionCampoSalida],
    summary="Operaciones recibidas de campo (para revisar conflictos en la oficina)",
)
def listar_operaciones(
    _: VeOrdenes,
    sede: SedeActiva,
    db: Db,
    estado: EstadoRegistro | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Pagina[OperacionCampoSalida]:
    return servicio.listar_operaciones(db, sede, estado=estado, page=page, size=size)
