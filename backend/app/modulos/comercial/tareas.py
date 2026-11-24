"""Tareas de segundo plano del módulo comercial (solo reciben ids y códigos, nunca datos)."""

from sqlalchemy.orm import Session

from app.core.db import obtener_motor
from app.core.tareas import app_tareas
from app.modulos.comercial import servicio


@app_tareas.task(name=servicio.TAREA_PROCESAR, queue="comercial")
def tarea_procesar_cargue(cargue_id: int) -> str:
    with Session(obtener_motor()) as db:
        return servicio.procesar_cargue(db, cargue_id)


@app_tareas.task(name=servicio.TAREA_SABANA, queue="comercial")
def tarea_exportar_sabana(
    sede_id: int, comercializador: str, periodo: str, familia: str, formato: str, usuario_id: int
) -> str:
    with Session(obtener_motor()) as db:
        return servicio.procesar_sabana(
            db,
            sede_id=sede_id,
            comercializador=comercializador,
            periodo=periodo,
            familia=familia,
            formato=formato,
            usuario_id=usuario_id,
        )


@app_tareas.task(name=servicio.TAREA_IMPORTAR, queue="comercial")
def tarea_importar_opainn(
    sede_id: int, comercializador: str, periodo: str, ruta: str, usuario_id: int
) -> str:
    with Session(obtener_motor()) as db:
        return servicio.procesar_importacion_opainn(
            db,
            sede_id=sede_id,
            comercializador=comercializador,
            periodo=periodo,
            ruta=ruta,
            usuario_id=usuario_id,
        )
