"""Tareas de segundo plano del módulo de atención (solo reciben ids, nunca datos personales)."""

from sqlalchemy.orm import Session

from app.core.db import obtener_motor
from app.core.tareas import app_tareas
from app.modulos.atencion import servicio


@app_tareas.task(name="atencion.notificar_pqrs", queue="atencion", retry=3)
def tarea_notificar_pqrs(pqrs_id: int, evento: str) -> bool:
    with Session(obtener_motor()) as db:
        return servicio.procesar_notificacion(db, pqrs_id, evento)


@app_tareas.task(name="atencion.exportar_pqrs", queue="atencion", retry=2)
def tarea_exportar_pqrs(
    sede_id: int,
    usuario_id: int,
    incluir_datos_personales: bool,
    estado_id: int | None = None,
    prioridad: int | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> str:
    with Session(obtener_motor()) as db:
        return servicio.procesar_exportacion(
            db,
            sede_id=sede_id,
            usuario_id=usuario_id,
            incluir_datos_personales=incluir_datos_personales,
            estado_id=estado_id,
            prioridad=prioridad,
            desde=desde,
            hasta=hasta,
        )
