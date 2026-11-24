"""Punto de entrada de la API."""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app import __version__
from app.core import salud, sistema
from app.core.config import obtener_configuracion
from app.core.errores import registrar_manejadores
from app.core.logs import configurar_logs, id_peticion, sede_log, usuario_log
from app.core.tareas import app_tareas
from app.modulos.activos.router import router as activos_router
from app.modulos.archivos.router import router as archivos_router
from app.modulos.atencion.router import router as atencion_router
from app.modulos.comercial.router import router as comercial_router
from app.modulos.comercial.router import router_migracion as comercial_migracion_router
from app.modulos.configuracion.router import router as configuracion_router
from app.modulos.inventario.router import router as inventario_router
from app.modulos.migracion.router import router as migracion_router
from app.modulos.notificaciones.router import router as notificaciones_router
from app.modulos.seguridad.router import router as seguridad_router
from app.modulos.sincronizacion.router import router as sincronizacion_router
from app.modulos.trabajos.router import router as trabajos_router

log = logging.getLogger("sapef.http")


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
    # La conexión de la cola se abre de forma perezosa: si la base no está, la API arranca igual
    # y /salud lo informa; encolar fallará con un error controlado.
    async with app_tareas.open_async():
        yield


def crear_app() -> FastAPI:
    config = obtener_configuracion()
    configurar_logs(config.log_nivel)

    app = FastAPI(
        title="SAPEF API",
        version=__version__,
        lifespan=ciclo_de_vida,
        # La documentación interactiva no se publica en producción.
        docs_url=None if config.es_produccion else "/api/docs",
        redoc_url=None,
        openapi_url=None if config.es_produccion else "/api/openapi.json",
    )
    registrar_manejadores(app)

    @app.middleware("http")
    async def registrar_peticion(request: Request, call_next) -> Response:
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        token = id_peticion.set(rid)
        token_usuario = usuario_log.set(None)
        token_sede = sede_log.set(None)
        inicio = time.perf_counter()
        estado = 500
        try:
            respuesta = await call_next(request)
            estado = respuesta.status_code
            respuesta.headers["X-Request-Id"] = rid
            return respuesta
        finally:
            log.info(
                "petición",
                extra={
                    "metodo": request.method,
                    "ruta": request.url.path,  # sin query string: puede llevar datos personales
                    "estado": estado,
                    "duracion_ms": round((time.perf_counter() - inicio) * 1000, 1),
                },
            )
            sede_log.reset(token_sede)
            usuario_log.reset(token_usuario)
            id_peticion.reset(token)

    app.include_router(salud.router, prefix="/api/v1")
    app.include_router(seguridad_router, prefix="/api/v1")
    app.include_router(archivos_router, prefix="/api/v1")
    app.include_router(configuracion_router, prefix="/api/v1")
    app.include_router(activos_router, prefix="/api/v1")
    app.include_router(migracion_router, prefix="/api/v1")
    app.include_router(inventario_router, prefix="/api/v1")
    app.include_router(atencion_router, prefix="/api/v1")
    app.include_router(trabajos_router, prefix="/api/v1")
    app.include_router(notificaciones_router, prefix="/api/v1")
    app.include_router(sincronizacion_router, prefix="/api/v1")
    app.include_router(comercial_router, prefix="/api/v1")
    app.include_router(comercial_migracion_router, prefix="/api/v1")
    if not config.es_produccion:
        app.include_router(sistema.router, prefix="/api/v1")
    return app


app = crear_app()
