"""Tareas de segundo plano del módulo de migración (Procrastinate)."""

import logging

from app.core.tareas import app_tareas

log = logging.getLogger("sapef.migracion.tareas")


@app_tareas.task(name="migracion.confirmar_ejecucion", queue="migracion", retry=2)
def tarea_confirmar_ejecucion(ejecucion_id: int) -> str:
    """Registra cierre de tarea asíncrona de migración usando solo ID primitivo."""
    log.info("migracion confirmada", extra={"ejecucion_id": ejecucion_id})
    return f"ejecucion:{ejecucion_id}"
