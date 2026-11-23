"""Endpoint de salud: lo usan el monitoreo y el despliegue para saber si la API está lista."""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import __version__
from app.core.db import comprobar_base_de_datos

log = logging.getLogger("sapef.salud")
router = APIRouter(tags=["sistema"])


class Salud(BaseModel):
    estado: str
    version: str
    base_de_datos: str
    postgres: str | None = None
    postgis: str | None = None


@router.get(
    "/salud",
    response_model=Salud,
    responses={503: {"model": Salud, "description": "La API responde pero la base de datos no"}},
    summary="Estado de la API y de la base de datos",
)
def salud() -> Salud | JSONResponse:
    try:
        versiones = comprobar_base_de_datos()
    except Exception:  # noqa: BLE001 - se informa como "no disponible", sin exponer el error
        log.warning("La base de datos no responde", exc_info=True)
        cuerpo = Salud(estado="degradado", version=__version__, base_de_datos="no disponible")
        return JSONResponse(cuerpo.model_dump(), status_code=503)
    return Salud(estado="ok", version=__version__, base_de_datos="ok", **versiones)
