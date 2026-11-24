"""Tareas del tablero (solo reciben ids de sede como texto «1,2»; nunca datos)."""

from sqlalchemy.orm import Session

from app.core.db import obtener_motor
from app.core.tareas import app_tareas
from app.modulos.tablero import servicio


@app_tareas.task(name=servicio.TAREA_RECALCULAR, queue="tablero", retry=2)
def tarea_recalcular(sede_ids: str | None = None) -> str:
    with Session(obtener_motor()) as db:
        return servicio.procesar_recalculo(db, sede_ids)


# HU-094: las tablas resumen se recalculan cada noche (3:00 a. m. de Colombia = 08:00 UTC).
@app_tareas.periodic(cron="0 8 * * *", periodic_id="tablero-nocturno")
@app_tareas.task(name="tablero.recalcular_nocturno", queue="tablero")
def tarea_recalcular_nocturno(timestamp: int) -> str:
    with Session(obtener_motor()) as db:
        return servicio.procesar_recalculo(db, None)
