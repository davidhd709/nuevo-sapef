"""Tareas del sistema (no de un módulo de negocio)."""

import logging

from app.core.tareas import app_tareas

log = logging.getLogger("sapef.tareas")


@app_tareas.task(name="sistema.prueba", queue="sistema", retry=2)
def tarea_prueba(mensaje: str) -> str:
    """Tarea de humo: comprueba que la API encola y el worker ejecuta."""
    log.info("tarea de prueba ejecutada", extra={"estado": "ok"})
    return f"recibido: {mensaje}"
