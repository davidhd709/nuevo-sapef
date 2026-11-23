"""Tareas de segundo plano del módulo de activos (Procrastinate)."""

import logging

from sqlalchemy.orm import Session

from app.core.db import obtener_motor
from app.core.tareas import app_tareas
from app.modulos.activos import servicio

log = logging.getLogger("sapef.activos.tareas")


@app_tareas.task(name="activos.exportar_luminarias", queue="activos", retry=2)
def tarea_exportar_luminarias(
    sede_id: int, usuario_id: int, texto: str | None = None
) -> str:
    """Genera el Excel de luminarias de la sede usando solo IDs primitivos."""
    with Session(obtener_motor()) as db:
        archivo_id = servicio.procesar_exportacion_luminarias(
            db, sede_id=sede_id, usuario_id=usuario_id, texto=texto
        )
    log.info("exportacion de luminarias completada", extra={"archivo_id": archivo_id})
    return archivo_id
