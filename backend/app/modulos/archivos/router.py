"""Rutas HTTP del módulo transversal de archivos (F3-1)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.db import obtener_sesion
from app.modulos.archivos import servicio
from app.modulos.archivos.esquemas import ArchivoSalida, CategoriaArchivo
from app.modulos.seguridad.servicio import (
    SedeResumen,
    UsuarioAutenticado,
    requerir_permiso_carga_archivo,
    requerir_sede,
)

router = APIRouter(prefix="/archivos", tags=["archivos"])


@router.post(
    "",
    response_model=ArchivoSalida,
    status_code=201,
    responses={200: {"model": ArchivoSalida, "description": "Replay idempotente"}},
    summary="Cargar un archivo validando magic bytes, tamaño, SHA-256 e idempotencia",
)
async def subir_archivo(
    archivo: Annotated[UploadFile, File(...)],
    sede: Annotated[SedeResumen, Depends(requerir_sede)],
    usuario: Annotated[UsuarioAutenticado, Depends(requerir_permiso_carga_archivo)],
    db: Annotated[Session, Depends(obtener_sesion)],
    categoria: Annotated[CategoriaArchivo, Form()] = "evidencia",
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    contenido = await servicio.leer_upload_con_limite(archivo, categoria)
    salida, creado = servicio.guardar_archivo(
        db,
        sede_id=sede.id,
        archivo_bytes=contenido,
        nombre=archivo.filename or "archivo",
        categoria=categoria,
        idempotency_key=idempotency_key,
        subido_por_id=usuario.id,
    )
    return JSONResponse(
        content=salida.model_dump(mode="json"),
        status_code=201 if creado else 200,
    )


@router.get(
    "/{archivo_id}",
    summary="Descargar un archivo verificado por sede",
)
def descargar_archivo(
    archivo_id: UUID,
    sede: Annotated[SedeResumen, Depends(requerir_sede)],
    db: Annotated[Session, Depends(obtener_sesion)],
    descargar: bool = Query(default=False),
) -> Response:
    meta, contenido = servicio.obtener_archivo_verificado(db, sede.id, archivo_id)
    cabeceras = servicio.construir_cabeceras_descarga(meta, descargar)
    return Response(content=contenido, media_type=meta.tipo_mime, headers=cabeceras)


@router.get(
    "/{archivo_id}/metadatos",
    response_model=ArchivoSalida,
    summary="Consultar metadatos de un archivo verificado por sede",
)
def obtener_metadatos(
    archivo_id: UUID,
    sede: Annotated[SedeResumen, Depends(requerir_sede)],
    db: Annotated[Session, Depends(obtener_sesion)],
) -> ArchivoSalida:
    return servicio.obtener_metadatos_archivo(db, sede.id, archivo_id)
