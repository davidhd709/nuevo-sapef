"""Servicio del tablero gerencial (EP-09, RF-090, ADR-009).

- `recalcular_sede` agrega las tablas operativas y el informe gerencial comercial y reemplaza
  las tablas resumen de la sede. Corre en el worker: de noche, tras cada corte comercial
  publicado y a pedido (`POST /tablero/recalcular`).
- `obtener_resumen` solo lee las tablas resumen (respuesta < 2 s, RNF-011). Si una sede nunca se
  calculó, calcula en el acto la parte operativa y deja encolado el cálculo comercial.
"""

import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.tareas import encolar
from app.modulos.atencion import servicio as atencion
from app.modulos.comercial import servicio as comercial
from app.modulos.seguridad import servicio as seguridad
from app.modulos.seguridad.servicio import SedeResumen, UsuarioAutenticado
from app.modulos.tablero import dominio, repositorio
from app.modulos.tablero.esquemas import (
    ActivosTablero,
    ComercializadorTablero,
    ComercialTablero,
    ConteoTablero,
    MesTablero,
    OperacionTablero,
    RecalculoEncolado,
    ResumenTableroSalida,
    SedeResumenTablero,
    SedeTablero,
    SemaforoTablero,
)

log = logging.getLogger("sapef.tablero")

TAREA_RECALCULAR = "tablero.recalcular"
ZONA = ZoneInfo("America/Bogota")


def hoy_local() -> date:
    return datetime.now(ZONA).date()


# --- Recálculo ----------------------------------------------------------------------------------


def recalcular_sede(db: Session, sede_id: int, *, con_comercial: bool = True) -> None:
    """Reemplaza el resumen de la sede. El comercial se calcula aparte de lo operativo: un
    archivo comercial dañado no deja al gerente sin los indicadores de la operación."""
    hoy = hoy_local()
    verde, amarillo = atencion.umbrales_semaforo(db, sede_id)
    operacion = repositorio.operacion(
        db,
        sede_id,
        hoy=hoy,
        abiertos=atencion.ESTADOS_PQRS_ABIERTOS,
        verde_max=verde,
        amarillo_max=amarillo,
    )
    dimensiones = repositorio.dimensiones_luminaria(db, sede_id)
    dimensiones += repositorio.pqrs_por_barrio(db, sede_id, inicio_anio=hoy.replace(month=1, day=1))
    filas_comercial: list[dict[str, Any]] = []
    if con_comercial:
        try:
            filas_comercial = comercial.resumen_tablero(db, sede_id)
        except Exception:  # noqa: BLE001 - se registra y el resto del tablero sigue
            log.exception("tablero: no se pudo calcular el comercial de la sede %s", sede_id)
            operacion["comercial_con_error"] = True
    else:
        operacion["comercial_pendiente"] = True
    repositorio.reemplazar_resumen(
        db,
        sede_id,
        meses=repositorio.luminarias_por_mes(db, sede_id),
        dimensiones=dimensiones,
        operacion_datos=operacion,
        comercial=filas_comercial,
    )
    db.commit()
    log.info("tablero recalculado", extra={"sede_id": sede_id})


def recalcular_sedes(db: Session, sede_ids: list[int] | None) -> int:
    ids = sede_ids or repositorio.ids_sedes_activas(db)
    for sede_id in ids:
        recalcular_sede(db, sede_id)
    return len(ids)


def _ids_desde_texto(sede_ids: str | None) -> list[int] | None:
    if not sede_ids:
        return None
    return [int(x) for x in sede_ids.split(",") if x.strip()]


def procesar_recalculo(db: Session, sede_ids: str | None) -> str:
    return f"sedes:{recalcular_sedes(db, _ids_desde_texto(sede_ids))}"


async def encolar_recalculo(
    db: Session,
    actor: UsuarioAutenticado,
    *,
    sede_id: int | None,
    x_sede: str | None,
) -> RecalculoEncolado:
    """Con `sede_id` o `X-Sede`, esa sede (debe estar asignada). Sin ninguno, todas las sedes del
    usuario, lo que exige ver el consolidado."""
    if sede_id is not None:
        asignadas = {s.id for s in actor.sedes}
        if sede_id not in asignadas:
            raise HTTPException(status_code=403, detail="No tiene acceso a la sede solicitada.")
        ids = [sede_id]
    elif x_sede:
        ids = [seguridad.validar_acceso_sede(db, actor, x_sede).id]
    else:
        seguridad.verificar_permiso(actor, "tablero.consolidado.ver")
        ids = sorted(s.id for s in actor.sedes)
    tarea = await encolar(TAREA_RECALCULAR, sede_ids=",".join(str(i) for i in ids))
    return RecalculoEncolado(tarea_id=int(tarea), tareaId=int(tarea), sede_ids=ids)


# --- Lectura ------------------------------------------------------------------------------------


def _conteos(filas: list[dict[str, Any]], limite: int | None = None) -> list[ConteoTablero]:
    lista = [ConteoTablero(**f) for f in filas]
    return lista[:limite] if limite else lista


async def obtener_resumen(
    db: Session, sedes: list[SedeResumen], *, anio: int | None, consolidado: bool
) -> ResumenTableroSalida:
    ids = [s.id for s in sedes]
    calculos = repositorio.leer_calculos(db, ids)
    sin_calculo = [i for i in ids if i not in calculos]
    con_cortes = repositorio.tiene_cortes_publicados(db, ids)
    for sede_id in sin_calculo:
        # Primera consulta de una sede: lo operativo se calcula ya (es SQL agregado, rápido);
        # el comercial lee Parquet y puede tardar: se encola.
        recalcular_sede(db, sede_id, con_comercial=False)
    pendientes = [i for i in sin_calculo if i in con_cortes]
    if pendientes:
        try:
            await encolar(TAREA_RECALCULAR, sede_ids=",".join(str(i) for i in pendientes))
        except Exception:  # noqa: BLE001 - el recálculo nocturno lo cubre
            log.warning("tablero: no se pudo encolar el recálculo de %s", pendientes)
    if sin_calculo:
        calculos = repositorio.leer_calculos(db, ids)

    anio = anio or hoy_local().year
    meses = repositorio.leer_meses(db, ids)
    dims = repositorio.leer_dimensiones(db, ids)
    com = repositorio.leer_comercial(db, ids)
    nombres = {s.id: s.nombre for s in sedes}

    agrupadas = dominio.consolidar_dimensiones(
        {nombres[i]: [dominio.FilaDimension(*d) for d in dims[i]] for i in ids}
    )
    operaciones = {i: dict(calculos[i].operacion) for i in ids}
    op = dominio.sumar_operacion(operaciones.values())
    serie = dominio.serie_mensual([m for i in ids for m in meses[i]], anio)

    filas_com: list[ComercializadorTablero] = []
    for s in sedes:
        for c in com[s.id]:
            actual, anterior = c.get("actual") or {}, c.get("anterior")
            filas_com.append(
                ComercializadorTablero(
                    sede_codigo=s.codigo,
                    sede_nombre=s.nombre,
                    comercializador=c["comercializador"],
                    nombre=c.get("nombre", c["comercializador"]),
                    periodo=c["periodo"],
                    periodo_anterior=c.get("periodo_anterior"),
                    actual=actual,
                    anterior=anterior,
                    variacion={
                        k: dominio.variacion(v, (anterior or {}).get(k))
                        for k, v in actual.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)
                    },
                    participacion=c.get("participacion") or [],
                    historico=c.get("historico") or [],
                )
            )
    raw_filas = [c for i in ids for c in com[i]]
    estado_com = dominio.estado_comercial(bool(con_cortes), raw_filas)

    por_sede = []
    for s in sedes:
        o = operaciones[s.id]
        por_sede.append(
            SedeResumenTablero(
                sede=SedeTablero(id=s.id, codigo=s.codigo, nombre=s.nombre),
                calculado_en=calculos[s.id].calculado_en,
                total_luminarias=int(o.get("total_luminarias") or 0),
                en_servicio=int(o.get("en_servicio") or 0),
                instaladas_anio=sum(c for a, _m, c in meses[s.id] if a == anio),
                pqrs_abiertas=int(o.get("pqrs_abiertas") or 0),
                pqrs_rojo=int(o.get("pqrs_rojo") or 0),
                mantenimientos_mes=int(o.get("mantenimientos_mes") or 0),
            )
        )

    umbral = next(iter(operaciones.values()), {}) if len(ids) == 1 else {}
    fechas = [c.calculado_en for c in calculos.values()]
    return ResumenTableroSalida(
        sede="todas" if consolidado else sedes[0].codigo,
        sedes_incluidas=[SedeTablero(id=s.id, codigo=s.codigo, nombre=s.nombre) for s in sedes],
        anio=anio,
        calculado_en=min(fechas) if fechas else None,
        activos=ActivosTablero(
            total_luminarias=op["total_luminarias"],
            en_servicio=op["en_servicio"],
            en_bodega=op["en_bodega"],
            instaladas_anio=serie[-1]["acumulado"],
            luminarias_instaladas_mes=[MesTablero(**m) for m in serie],
            por_tecnologia=_conteos(agrupadas.get("tecnologia", [])),
            por_potencia=_conteos(agrupadas.get("potencia", [])),
            por_zona=_conteos(agrupadas.get("zona", [])),
            por_barrio=_conteos(agrupadas.get("barrio", []), 30),
        ),
        operacion=OperacionTablero(
            luminarias_por_estado=_conteos(agrupadas.get("estado", [])),
            pqrs_abiertas=op["pqrs_abiertas"],
            pqrs_semaforo=SemaforoTablero(
                verde=op["pqrs_verde"],
                amarillo=op["pqrs_amarillo"],
                rojo=op["pqrs_rojo"],
                umbral_verde_dias=umbral.get("umbral_verde_dias"),
                umbral_amarillo_dias=umbral.get("umbral_amarillo_dias"),
            ),
            pqrs_recibidas_mes=op["pqrs_recibidas_mes"],
            pqrs_recibidas_mes_anterior=op["pqrs_recibidas_mes_anterior"],
            variacion_pqrs_recibidas=dominio.variacion(
                op["pqrs_recibidas_mes"], op["pqrs_recibidas_mes_anterior"]
            ),
            pqrs_atendidas_mes=op["pqrs_atendidas_mes"],
            pqrs_atendidas_anio=op["pqrs_atendidas_anio"],
            tiempo_promedio_atencion_horas=op["tiempo_promedio_atencion_horas"],
            pqrs_por_barrio=_conteos(agrupadas.get("pqrs_barrio", []), 20),
            mantenimientos_mes=op["mantenimientos_mes"],
            mantenimientos_mes_anterior=op["mantenimientos_mes_anterior"],
            variacion_mantenimientos=dominio.variacion(
                op["mantenimientos_mes"], op["mantenimientos_mes_anterior"]
            ),
            ordenes_abiertas=op["ordenes_abiertas"],
            materiales_bajo_minimo=op["materiales_bajo_minimo"],
        ),
        comercial=ComercialTablero(estado=estado_com, comercializadores=filas_com),
        por_sede=por_sede,
    )
