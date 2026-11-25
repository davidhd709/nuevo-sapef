"""Tareas de segundo plano del módulo de migración (Procrastinate; solo reciben ids)."""

from sqlalchemy.orm import Session

from app.core.db import obtener_motor
from app.core.tareas import app_tareas
from app.modulos.migracion import servicio


@app_tareas.task(name=servicio.TAREA_PROCESAR, queue="migracion")
def tarea_procesar_ejecucion(ejecucion_id: int) -> str:
    """Procesa una ejecución pendiente. Sin reintento automático: el importador es repetible y
    una ejecución interrumpida se vuelve a lanzar subiendo el mismo archivo."""
    with Session(obtener_motor()) as db:
        return servicio.procesar_ejecucion(db, ejecucion_id)
