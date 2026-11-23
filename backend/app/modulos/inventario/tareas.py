"""Tareas de segundo plano del módulo de inventario (solo reciben ids)."""

from sqlalchemy.orm import Session

from app.core.db import obtener_motor
from app.core.tareas import app_tareas
from app.modulos.inventario import servicio


@app_tareas.task(name="inventario.procesar_cargue_bodega", queue="inventario")
def tarea_procesar_cargue_bodega(cargue_id: int) -> str:
    with Session(obtener_motor()) as db:
        return servicio.procesar_cargue_bodega(db, cargue_id)
