"""Rutas HTTP del módulo de notificaciones (Web Push de la app de campo)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.core.db import obtener_sesion
from app.modulos.notificaciones import servicio
from app.modulos.notificaciones.esquemas import (
    ClavePublicaSalida,
    SuscripcionBorrarEntrada,
    SuscripcionEntrada,
    SuscripcionSalida,
)
from app.modulos.seguridad.servicio import UsuarioAutenticado, requerir_permiso

router = APIRouter(prefix="/notificaciones/push", tags=["notificaciones"])

Db = Annotated[Session, Depends(obtener_sesion)]
UsaCampo = Annotated[UsuarioAutenticado, Depends(requerir_permiso("campo.app.usar"))]


@router.get(
    "/clave-publica",
    response_model=ClavePublicaSalida,
    summary="Clave pública VAPID para suscribirse (applicationServerKey)",
)
def clave_publica(_: UsaCampo) -> ClavePublicaSalida:
    return servicio.obtener_clave_publica()


@router.post(
    "/suscripciones",
    response_model=SuscripcionSalida,
    status_code=201,
    responses={200: {"model": SuscripcionSalida, "description": "Ya existía; se actualizó"}},
    summary="Registrar la suscripción Web Push de este dispositivo",
)
def suscribir(
    entrada: SuscripcionEntrada,
    actor: UsaCampo,
    db: Db,
    response: Response,
    user_agent: Annotated[str | None, Header(alias="User-Agent")] = None,
) -> SuscripcionSalida:
    salida, creada = servicio.suscribir(db, actor, entrada, user_agent)
    if not creada:
        response.status_code = 200
    return salida


@router.delete(
    "/suscripciones",
    status_code=204,
    response_class=Response,
    summary="Quitar la suscripción Web Push de este dispositivo",
)
def desuscribir(entrada: SuscripcionBorrarEntrada, actor: UsaCampo, db: Db) -> Response:
    servicio.desuscribir(db, actor, entrada)
    return Response(status_code=204)
