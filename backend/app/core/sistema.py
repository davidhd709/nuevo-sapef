"""Rutas de diagnóstico del sistema. Solo se registran fuera de producción."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.core.db import obtener_motor
from app.core.tareas_sistema import tarea_prueba

router = APIRouter(prefix="/sistema", tags=["sistema"])


class TareaEncolada(BaseModel):
    id: int


class EstadoTarea(BaseModel):
    id: int
    estado: str
    intentos: int


@router.post("/tareas/prueba", response_model=TareaEncolada, status_code=202,
             summary="Encola una tarea de prueba (diagnóstico)")
async def encolar_prueba() -> TareaEncolada:
    job_id = await tarea_prueba.defer_async(mensaje="hola desde la API")
    return TareaEncolada(id=job_id)


@router.get("/tareas/{job_id}", response_model=EstadoTarea, summary="Estado de una tarea")
def estado_tarea(job_id: int) -> EstadoTarea:
    with obtener_motor().connect() as conexion:
        fila = conexion.execute(
            text("SELECT id, status, attempts FROM procrastinate_jobs WHERE id = :id"),
            {"id": job_id},
        ).one_or_none()
    if fila is None:
        raise HTTPException(status_code=404, detail="La tarea no existe.")
    return EstadoTarea(id=fila.id, estado=str(fila.status), intentos=fila.attempts)
