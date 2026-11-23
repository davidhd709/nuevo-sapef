"""Errores en formato RFC 9457 (application/problem+json), sin trazas internas para el cliente."""

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logs import id_peticion

log = logging.getLogger("sapef.errores")
TIPO_PROBLEMA = "application/problem+json"


def _problema(estado: int, detalle: str | None = None, errores: list | None = None) -> JSONResponse:
    cuerpo: dict = {
        "type": "about:blank",
        "title": HTTPStatus(estado).phrase,
        "status": estado,
    }
    if detalle:
        cuerpo["detail"] = detalle
    if errores:
        cuerpo["errors"] = errores
    if (rid := id_peticion.get()) is not None:
        cuerpo["requestId"] = rid
    return JSONResponse(cuerpo, status_code=estado, media_type=TIPO_PROBLEMA)


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detalle = exc.detail if isinstance(exc.detail, str) else None
        return _problema(exc.status_code, detalle)

    @app.exception_handler(RequestValidationError)
    async def _validacion(_: Request, exc: RequestValidationError) -> JSONResponse:
        errores = [
            {"campo": ".".join(str(p) for p in e["loc"]), "mensaje": e["msg"]}
            for e in exc.errors()
        ]
        return _problema(422, "Los datos enviados no son válidos.", errores)

    @app.exception_handler(Exception)
    async def _inesperado(_: Request, exc: Exception) -> JSONResponse:
        # El detalle completo queda solo en el log del servidor.
        log.exception("Error no controlado", exc_info=exc)
        return _problema(500, "Ocurrió un error interno. Use el requestId para rastrearlo.")
