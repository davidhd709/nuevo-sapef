"""Tareas de segundo plano del módulo de trabajos (solo reciben ids)."""

import logging

from sqlalchemy.orm import Session

from app.core.db import obtener_motor
from app.core.tareas import app_tareas
from app.modulos.trabajos import servicio

log = logging.getLogger("sapef.trabajos.tareas")


@app_tareas.task(name="trabajos.procesar_cargue_masivo", queue="trabajos")
def tarea_procesar_cargue_masivo(cargue_id: int) -> str:
    with Session(obtener_motor()) as db:
        return servicio.procesar_cargue(db, cargue_id)


@app_tareas.task(name=servicio.TAREA_PUSH, queue="trabajos", retry=3)
def tarea_push_orden_asignada(orden_id: int) -> int:
    with Session(obtener_motor()) as db:
        entregados = servicio.procesar_push_asignacion(db, orden_id)
    log.info("aviso de orden asignada: %s dispositivo(s)", entregados)
    return entregados
