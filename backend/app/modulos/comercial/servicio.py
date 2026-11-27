"""Servicio público del módulo comercial (EP-08).

Flujo de un cargue (§6.6): la API valida cantidad, tamaño, extensión y contenido, guarda los
originales con su SHA-256 y encola; el worker reconoce, valida y normaliza con el adaptador del
comercializador, escribe Parquet en un directorio provisional y publica el periodo completo de
forma atómica. Los análisis leen el almacén (con caché por corte) y aplican las reglas puras del
dominio. Las consultas nominales se auditan.
"""

import hashlib
import logging
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import HTTPException, UploadFile
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import obtener_configuracion
from app.core.tareas import app_tareas, encolar
from app.modulos.comercial import repositorio
from app.modulos.comercial.dominio import (
    afinia,
    afinia_ingesta,
    analisis,
    celsia,
    celsia_ingesta,
    entregables,
    vatia,
    vatia_ingesta,
)
from app.modulos.comercial.dominio import archivos as lectura
from app.modulos.comercial.dominio import catalogo as catalogo_dominio
from app.modulos.comercial.dominio.analisis import UsuarioCorte
from app.modulos.comercial.dominio.comun import (
    ErrorDominioComercial,
    d,
    div,
    q2,
    suma,
    sumar_meses,
    validar_periodo,
)
from app.modulos.comercial.esquemas import (
    AnalisisCatalogo,
    CargueEncolado,
    CargueSalida,
    CorteSalida,
    PaginaDatos,
)
from app.modulos.comercial.modelos import CargueComercial
from app.modulos.comercial.repositorio import almacen
from app.modulos.configuracion import servicio as configuracion
from app.modulos.seguridad import servicio as seguridad
from app.modulos.seguridad.servicio import SedeResumen, UsuarioAutenticado

log = logging.getLogger("sapef.comercial")

TAREA_PROCESAR = "comercial.procesar_cargue"
TAREA_SABANA = "comercial.exportar_sabana"
TAREA_IMPORTAR = "comercial.importar_opainn"


def _http(exc: ErrorDominioComercial) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def dominio_o_http[T](funcion: Callable[[], T]) -> T:
    try:
        return funcion()
    except ErrorDominioComercial as exc:
        raise _http(exc) from exc


# === Adaptadores y contexto ======================================================================


@dataclass(frozen=True)
class Adaptador:
    codigo: str
    ingesta: ModuleType
    busqueda: tuple[str, ...]
    identificador: str
    principal: str  # familia de la que salen los usuarios facturados

    @property
    def familias(self) -> tuple[str, ...]:
        return self.ingesta.FAMILIAS  # type: ignore[no-any-return]

    def esquemas(self) -> dict[str, dict[str, str]]:
        return {f: self.ingesta.esquema(f) for f in self.familias}


ADAPTADORES: dict[str, Adaptador] = {
    "afinia": Adaptador(
        "afinia",
        afinia_ingesta,
        ("nic", "sv", "concepto", "nombre", "barrio"),
        "nic",
        "facturacion",
    ),
    "celsia": Adaptador(
        "celsia", celsia_ingesta, ("cuenta", "factura", "nombre", "barrio"), "cuenta", "facturacion"
    ),
    "vatia": Adaptador(
        "vatia",
        vatia_ingesta,
        ("cliente_id", "factura", "cliente_nombre"),
        "cliente_id",
        "comercial",
    ),
}


@dataclass(frozen=True)
class Contexto:
    sede: SedeResumen
    codigo: str
    comercializador_id: int
    adaptador: Adaptador

    def ruta(self, periodo: str) -> Path:
        return almacen.ruta_corte(self.sede.codigo, self.codigo, periodo)


def contexto(db: Session, sede: SedeResumen, codigo: str) -> Contexto:
    """El comercializador debe existir y operar en la sede (RN-000c)."""
    adaptador = ADAPTADORES.get((codigo or "").lower())
    if adaptador is None:
        raise HTTPException(status_code=404, detail="Comercializador no reconocido.")
    if adaptador.codigo not in configuracion.listar_comercializadores_activos_sede(db, sede.id):
        raise HTTPException(
            status_code=404,
            detail=f"{adaptador.codigo.capitalize()} no opera en la sede {sede.nombre}.",
        )
    ids = {c.codigo: c.id for c in configuracion.listar_comercializadores(db)}
    return Contexto(sede, adaptador.codigo, ids[adaptador.codigo], adaptador)


def auditar_consulta(
    db: Session, actor: UsuarioAutenticado, ctx: Contexto, recurso: str, **parametros: Any
) -> None:
    """Consulta nominal (quién consultó qué usuario o listado; §11.13). Solo parámetros
    permitidos: nunca cuerpos ni datos personales."""
    seguridad.registrar_auditoria_consulta(
        db,
        usuario_id=actor.id,
        sede_id=ctx.sede.id,
        recurso=f"comercial.{ctx.codigo}.{recurso}",
        parametros_permitidos={k: v for k, v in parametros.items() if v is not None},
    )
    db.commit()


# === Cargues =====================================================================================


def _a_cargue(c: CargueComercial, codigo: str) -> CargueSalida:
    return CargueSalida(
        id=c.id,
        cargue_id=c.id,
        sede_id=c.sede_id,
        comercializador=codigo,
        periodo=c.periodo,
        estado=c.estado,
        origen=c.origen,
        completo=c.completo,
        publicable=c.publicable,
        version_adaptador=c.version_adaptador,
        archivos=[{k: v for k, v in a.items() if k != "ruta"} for a in c.archivos],
        familias=c.familias,
        advertencias=c.advertencias,
        errores=c.errores,
        creado_en=c.creado_en,
        procesado_en=c.procesado_en,
    )


def _codigo_de(db: Session, comercializador_id: int) -> str:
    return next(
        c.codigo for c in configuracion.listar_comercializadores(db) if c.id == comercializador_id
    )


async def recibir_cargue(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    codigo: str,
    periodo: str,
    archivos: list[UploadFile],
    idempotency_key: str | None,
) -> tuple[CargueEncolado, bool]:
    """Devuelve (respuesta, creado). Valida todo antes de procesar (§11.5 paso 1)."""
    ctx = contexto(db, sede, codigo)
    periodo = dominio_o_http(lambda: validar_periodo(periodo))
    config = obtener_configuracion()
    if not archivos:
        raise HTTPException(status_code=422, detail="Adjunte al menos un archivo.")
    if len(archivos) > config.comercial_max_archivos:
        raise HTTPException(
            status_code=413,
            detail=f"Máximo {config.comercial_max_archivos} archivos por cargue ({len(archivos)}).",
        )
    limite = config.comercial_max_archivo_mb * 1024 * 1024
    limite_total = config.comercial_max_total_mb * 1024 * 1024
    clave = (idempotency_key or "").strip()[:100] or None
    for archivo in archivos:
        nombre = archivo.filename or "archivo"
        if archivo.size is not None and archivo.size > limite:
            raise HTTPException(
                status_code=413,
                detail=f"«{nombre}» supera {config.comercial_max_archivo_mb} MiB.",
            )
        inicio = await archivo.read(8192)
        await archivo.seek(0)
        dominio_o_http(
            lambda n=nombre, i=inicio: lectura.validar_contenido(
                n, i, ctx.adaptador.ingesta.EXTENSIONES
            )
        )
    total = sum(a.size or 0 for a in archivos)
    if total > limite_total:
        raise HTTPException(
            status_code=413, detail=f"La carga supera {config.comercial_max_total_mb} MiB en total."
        )

    temporal = almacen.raiz_originales() / ".tmp" / uuid.uuid4().hex
    try:
        guardados = await run_in_threadpool(
            _copiar_originales, temporal, archivos, limite, limite_total
        )
    except almacen.ArchivoDemasiadoGrande as exc:
        shutil.rmtree(temporal, ignore_errors=True)
        raise HTTPException(
            status_code=413,
            detail=f"«{exc}» supera el tamaño máximo permitido; no se cargó nada.",
        ) from exc
    huella = hashlib.sha256(
        "|".join([ctx.codigo, periodo, *sorted(g["sha256"] for g in guardados)]).encode()
    ).hexdigest()

    if clave:
        existente = repositorio.obtener_por_idempotencia(db, sede.id, clave)
        if existente is not None:
            shutil.rmtree(temporal, ignore_errors=True)
            if existente.huella != huella or existente.comercializador_id != ctx.comercializador_id:
                raise HTTPException(
                    status_code=409,
                    detail="El Idempotency-Key ya se usó con otros archivos o periodo.",
                )
            return _encolado(existente, None), False

    cargue = CargueComercial(
        sede_id=sede.id,
        comercializador_id=ctx.comercializador_id,
        periodo=periodo,
        estado="recibido",
        idempotency_key=clave,
        huella=huella,
        archivos=[],
        creado_por=actor.id,
    )
    try:
        repositorio.agregar(db, cargue)
    except IntegrityError as exc:
        db.rollback()
        shutil.rmtree(temporal, ignore_errors=True)
        existente = repositorio.obtener_por_idempotencia(db, sede.id, clave or "")
        if existente is None or existente.huella != huella:
            raise HTTPException(
                status_code=409, detail="Cargue concurrente con la misma clave."
            ) from exc
        return _encolado(existente, None), False
    destino = almacen.raiz_originales() / str(cargue.id)
    shutil.rmtree(destino, ignore_errors=True)
    temporal.rename(destino)
    cargue.archivos = [{**g, "ruta": str(destino / Path(g["ruta"]).name)} for g in guardados]
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="cargar",
        entidad="cargue_comercial",
        entidad_id=str(cargue.id),
        despues={
            "comercializador": ctx.codigo,
            "periodo": periodo,
            "archivos": [{"nombre": g["nombre"], "sha256": g["sha256"]} for g in guardados],
        },
    )
    db.commit()
    tarea = await encolar(TAREA_PROCESAR, cargue_id=cargue.id)
    return _encolado(cargue, tarea), True


def _copiar_originales(
    temporal: Path, archivos: list[UploadFile], limite: int, limite_total: int
) -> list[dict[str, Any]]:
    temporal.mkdir(parents=True, exist_ok=True)
    guardados = []
    restante = limite_total
    for i, archivo in enumerate(archivos):
        nombre = archivo.filename or f"archivo_{i}"
        archivo.file.seek(0)
        ruta, sha, tamano = almacen.guardar_original(
            temporal, i, nombre, archivo.file, limite, restante
        )
        restante -= tamano
        guardados.append({"nombre": nombre, "sha256": sha, "tamano": tamano, "ruta": str(ruta)})
    return guardados


def _encolado(cargue: CargueComercial, tarea: int | None) -> CargueEncolado:
    return CargueEncolado(
        id=cargue.id,
        cargue_id=cargue.id,
        cargueId=cargue.id,
        tarea_id=tarea,
        tareaId=tarea,
        estado=cargue.estado if tarea is None else "encolada",
    )


def _corte_anterior(
    ctx: Contexto, db: Session, periodo: str
) -> Callable[[str], list[dict[str, Any]]]:
    previos = [
        c.periodo
        for c in repositorio.publicados(db, ctx.sede.id, ctx.comercializador_id)
        if c.periodo < periodo
    ]

    def leer(familia: str) -> list[dict[str, Any]]:
        return almacen.leer_familia(ctx.ruta(previos[-1]), familia) if previos else []

    return leer


def procesar_cargue(db: Session, cargue_id: int) -> str:
    """Tarea del worker: normaliza, valida y publica (o deja el detalle de errores)."""
    cargue = repositorio.obtener_cargue_por_id(db, cargue_id, bloquear=True)
    if cargue is None or cargue.estado not in ("recibido", "validando"):
        return "omitido"
    cargue.estado = "validando"
    db.commit()
    codigo = _codigo_de(db, cargue.comercializador_id)
    sede = next(
        s for s in configuracion.listar_sedes_activas_resumen(db) if s["id"] == cargue.sede_id
    )
    ctx = Contexto(
        SedeResumen(id=sede["id"], codigo=sede["codigo"], nombre=sede["nombre"]),
        codigo,
        cargue.comercializador_id,
        ADAPTADORES[codigo],
    )
    try:
        entradas = [
            lectura.ArchivoEntrada(a["nombre"], almacen.leer_original(a["ruta"]))
            for a in cargue.archivos
        ]
        resultado = ctx.adaptador.ingesta.procesar(
            entradas, cargue.periodo, corte_anterior=_corte_anterior(ctx, db, cargue.periodo)
        )
    except ErrorDominioComercial as exc:
        return _terminar(db, cargue, "con_errores", errores=[exc.detail])
    except Exception:
        log.exception("cargue %s: error inesperado al normalizar", cargue_id)
        return _terminar(
            db,
            cargue,
            "con_errores",
            errores=["Error inesperado al leer los archivos; revise el formato."],
        )

    por_nombre = {a["nombre"]: a for a in resultado.archivos}
    cargue.archivos = [{**a, **por_nombre.get(a["nombre"], {})} for a in cargue.archivos]
    cargue.familias = {f: len(v) for f, v in resultado.familias.items() if f in resultado.presentes}
    cargue.advertencias = resultado.advertencias
    cargue.completo = resultado.completo
    cargue.publicable = resultado.publicable
    cargue.version_adaptador = ctx.adaptador.ingesta.VERSION
    if resultado.errores:
        return _terminar(db, cargue, "con_errores", errores=resultado.errores[:200])
    if not resultado.publicable:
        return _terminar(
            db, cargue, "no_publicable", errores=[resultado.motivo_no_publicable or ""]
        )

    manifiesto = {
        "sede_codigo": ctx.sede.codigo,
        "comercializador_codigo": ctx.codigo,
        "periodo": cargue.periodo,
        "cargue_id": cargue.id,
        "version_adaptador": cargue.version_adaptador,
        "fecha_publicacion_iso": datetime.now(UTC).isoformat(),
        "usuario_id": cargue.creado_por,
        "completo": resultado.completo,
        "publicable": resultado.publicable,
        "presentes": sorted(resultado.presentes),
        "archivos": [
            {
                "nombre": a["nombre"],
                "sha256": a["sha256"],
                "tamano": a["tamano"],
                "familia": a.get("familia"),
            }
            for a in cargue.archivos
        ],
        "advertencias": resultado.advertencias,
    }
    return publicar(db, ctx, cargue, resultado.familias, manifiesto)


def publicar(
    db: Session,
    ctx: Contexto,
    cargue: CargueComercial,
    familias: dict[str, list[dict[str, Any]]],
    manifiesto: dict[str, Any],
) -> str:
    provisional = None
    try:
        provisional = almacen.escribir_provisional(familias, ctx.adaptador.esquemas(), manifiesto)
        repositorio.bloquear_corte(db, ctx.sede.id, ctx.comercializador_id, cargue.periodo)
        previo = repositorio.cargue_publicado(
            db, ctx.sede.id, ctx.comercializador_id, cargue.periodo, bloquear=True
        )
        almacen.publicar(provisional, ctx.ruta(cargue.periodo))
    except Exception:
        log.exception("cargue %s: no se pudo publicar", cargue.id)
        almacen.descartar(provisional)
        db.rollback()
        cargue = repositorio.obtener_cargue_por_id(db, cargue.id) or cargue
        return _terminar(
            db,
            cargue,
            "con_errores",
            errores=["No se pudo publicar el corte; el periodo anterior se conserva."],
        )
    if previo is not None and previo.id != cargue.id:
        previo.estado = "reemplazado"
        db.flush()
    return _terminar(db, cargue, "publicado")


def _terminar(
    db: Session, cargue: CargueComercial, estado: str, errores: list[str] | None = None
) -> str:
    cargue.estado = estado
    if errores is not None:
        cargue.errores = errores
    cargue.procesado_en = datetime.now(UTC)
    db.commit()
    log.info("cargue %s: %s", cargue.id, estado)
    if estado == "publicado":
        _avisar_tablero(cargue.sede_id)
    return estado


TAREA_TABLERO = "tablero.recalcular"


def _avisar_tablero(sede_id: int) -> None:
    """Tras publicar un corte se recalculan las tablas resumen del tablero (§9.8). Si la cola no
    responde, el recálculo nocturno lo cubre: nunca se pierde la publicación por esto."""
    try:
        app_tareas.configure_task(name=TAREA_TABLERO, queueing_lock=f"tablero-{sede_id}").defer(
            sede_ids=str(sede_id)
        )
    except AlreadyEnqueued:
        pass
    except Exception:  # noqa: BLE001 - el aviso es de mejor esfuerzo
        log.warning("no se pudo encolar el recálculo del tablero de la sede %s", sede_id)


def obtener_cargue(
    db: Session, sede: SedeResumen, cargue_id: int, codigo: str | None = None
) -> CargueSalida:
    cargue = repositorio.obtener_cargue(db, sede.id, cargue_id)
    if cargue is None:
        raise HTTPException(status_code=404, detail="Cargue no encontrado.")
    real = _codigo_de(db, cargue.comercializador_id)
    if codigo is not None and real != codigo:
        raise HTTPException(status_code=404, detail="Cargue no encontrado.")
    return _a_cargue(cargue, real)


def listar_cargues(db: Session, sede: SedeResumen, codigo: str) -> list[CargueSalida]:
    ctx = contexto(db, sede, codigo)
    return [
        _a_cargue(c, ctx.codigo)
        for c in repositorio.listar_cargues(db, sede.id, ctx.comercializador_id)
    ]


def eliminar_cargue(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, codigo: str, cargue_id: int
) -> None:
    ctx = contexto(db, sede, codigo)
    cargue = repositorio.obtener_cargue(db, sede.id, cargue_id)
    if cargue is None or cargue.comercializador_id != ctx.comercializador_id:
        raise HTTPException(status_code=404, detail="Cargue no encontrado.")
    if cargue.estado == "eliminado":
        return
    if cargue.estado in ("recibido", "validando"):
        raise HTTPException(status_code=409, detail="El cargue se está procesando; espere.")
    antes = {"estado": cargue.estado}
    if cargue.estado == "publicado":
        repositorio.bloquear_corte(db, sede.id, ctx.comercializador_id, cargue.periodo)
        almacen.eliminar_corte(ctx.ruta(cargue.periodo))
    cargue.estado = "eliminado"
    cargue.eliminado_en = datetime.now(UTC)
    cargue.eliminado_por = actor.id
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="eliminar",
        entidad="cargue_comercial",
        entidad_id=str(cargue.id),
        antes=antes,
        despues={"estado": "eliminado", "periodo": cargue.periodo},
    )
    db.commit()


# === Cortes y datos ==============================================================================


def cortes_publicados(db: Session, ctx: Contexto) -> list[CargueComercial]:
    return repositorio.publicados(db, ctx.sede.id, ctx.comercializador_id)


def listar_cortes(db: Session, sede: SedeResumen, codigo: str) -> list[CorteSalida]:
    ctx = contexto(db, sede, codigo)
    return [
        CorteSalida(
            periodo=c.periodo,
            cargue_id=c.id,
            completo=c.completo,
            publicable=c.publicable,
            familias={k: int(v) for k, v in c.familias.items()},
            advertencias=c.advertencias,
            version_adaptador=c.version_adaptador,
            publicado_en=c.procesado_en,
        )
        for c in cortes_publicados(db, ctx)
    ]


def exigir_corte(db: Session, ctx: Contexto, periodo: str) -> CargueComercial:
    periodo = dominio_o_http(lambda: validar_periodo(periodo))
    cargue = repositorio.cargue_publicado(db, ctx.sede.id, ctx.comercializador_id, periodo)
    if cargue is None or not ctx.ruta(periodo).is_dir():
        raise HTTPException(
            status_code=404, detail=f"No hay un corte publicado de {ctx.codigo} para {periodo}."
        )
    return cargue


def datos_corte(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    codigo: str,
    periodo: str,
    familia: str,
    *,
    page: int,
    size: int,
    buscar: str | None,
) -> PaginaDatos:
    ctx = contexto(db, sede, codigo)
    exigir_corte(db, ctx, periodo)
    if familia not in ctx.adaptador.familias:
        raise HTTPException(
            status_code=422,
            detail=f"Familia desconocida; use {', '.join(ctx.adaptador.familias)}.",
        )
    filas, total = almacen.leer_pagina(
        ctx.ruta(periodo),
        familia,
        page=page,
        size=size,
        buscar=buscar,
        campos_busqueda=ctx.adaptador.busqueda,
    )
    auditar_consulta(
        db, actor, ctx, "datos", periodo=periodo, familia=familia, page=page, buscar=bool(buscar)
    )
    columnas = list(ctx.adaptador.ingesta.esquema(familia))
    return PaginaDatos(
        familia=familia, columnas=columnas, items=filas, total=total, page=page, size=size
    )


def catalogo(db: Session, sede: SedeResumen, codigo: str) -> list[AnalisisCatalogo]:
    ctx = contexto(db, sede, codigo)
    return [AnalisisCatalogo.model_validate(a) for a in catalogo_dominio.catalogo(ctx.codigo)]


# === Lectura de cortes con caché =================================================================

_CACHE_CORTE: dict[tuple[str, str, int], Any] = {}


def _cacheado(ctx: Contexto, periodo: str, clave: str, calcular: Callable[[], Any]) -> Any:
    manifiesto = ctx.ruta(periodo) / "manifest.json"
    marca = manifiesto.stat().st_mtime_ns if manifiesto.is_file() else 0
    llave = (str(ctx.ruta(periodo)), clave, marca)
    if llave not in _CACHE_CORTE:
        if len(_CACHE_CORTE) > 400:
            _CACHE_CORTE.clear()
        _CACHE_CORTE[llave] = calcular()
    return _CACHE_CORTE[llave]


def familia(ctx: Contexto, periodo: str, nombre: str) -> list[dict[str, Any]]:
    return almacen.leer_familia(ctx.ruta(periodo), nombre)


def familias(ctx: Contexto, periodo: str) -> dict[str, list[dict[str, Any]]]:
    return {f: familia(ctx, periodo, f) for f in ctx.adaptador.familias}


def usuarios(ctx: Contexto, periodo: str) -> dict[str, UsuarioCorte]:
    modulo = {"afinia": afinia, "celsia": celsia, "vatia": vatia}[ctx.codigo]
    return _cacheado(
        ctx, periodo, "usuarios", lambda: modulo.usuarios_corte(familias(ctx, periodo))
    )  # type: ignore[attr-defined]


def facturados(ctx: Contexto, periodo: str) -> frozenset[str]:
    return _cacheado(
        ctx,
        periodo,
        "facturados",
        lambda: frozenset(k for k, u in usuarios(ctx, periodo).items() if u.facturado_presente),
    )


def pagaron(ctx: Contexto, periodo: str) -> frozenset[str]:
    return _cacheado(
        ctx,
        periodo,
        "pagaron",
        lambda: frozenset(k for k, u in usuarios(ctx, periodo).items() if u.pago),
    )


# === Utilidades de análisis ======================================================================


def periodos(db: Session, ctx: Contexto) -> list[str]:
    return [c.periodo for c in cortes_publicados(db, ctx)]


def _comparable(lista: list[str], periodo: str) -> str | None:
    previos = [p for p in lista if p < periodo]
    return previos[-1] if previos else None


def _presencia(ctx: Contexto, lista: list[str]) -> dict[str, set[str]]:
    presencia: dict[str, set[str]] = {}
    for p in lista:
        for usuario in facturados(ctx, p):
            presencia.setdefault(usuario, set()).add(p)
    return presencia


def _periodicidades(
    ctx: Contexto, lista: list[str], presencia: dict[str, set[str]]
) -> dict[str, tuple[str, str]]:
    """Celsia: ciclo de cada cuenta por los meses facturados (y el archivo o el sector si hay una
    sola factura). Afinia y Vatia: todos mensuales."""
    if ctx.codigo != "celsia":
        return {u: (analisis.MENSUAL, "comercializador") for u in presencia}
    declaradas: dict[str, tuple[str | None, str | None]] = {}
    for p in lista:
        for k, u in usuarios(ctx, p).items():
            if u.facturado_presente:
                declaradas[k] = (u.periodicidad, u.extra.get("sector"))
    return {
        u: analisis.deducir_periodicidad(meses, *declaradas.get(u, (None, None)))
        for u, meses in presencia.items()
    }


def _movimiento(db: Session, ctx: Contexto, periodo: str) -> analisis.Movimiento:
    lista = [p for p in periodos(db, ctx) if p <= periodo]
    presencia = _presencia(ctx, lista)
    ciclos = _periodicidades(ctx, lista, presencia)
    return analisis.movimiento(presencia, lista, periodo, {u: c[0] for u, c in ciclos.items()})


def _pares_afinia(ctx: Contexto, periodo: str) -> frozenset[tuple[str, str]]:
    return _cacheado(  # type: ignore[no-any-return]
        ctx,
        periodo,
        "pares",
        lambda: frozenset(
            (str(f["nic"]), str(f.get("tarifa") or ""))
            for f in familia(ctx, periodo, "facturacion")
        ),
    )


def _td_afinia(
    db: Session, ctx: Contexto, periodo: str, *, con_movimiento: bool = True
) -> dict[str, Any]:
    def calcular(
        anteriores: set[tuple[str, str]], historicos: set[tuple[str, str]]
    ) -> dict[str, Any]:
        fam = familias(ctx, periodo)
        return afinia.tabla_dinamica(
            periodo,
            facturacion=fam["facturacion"],
            recaudo=fam["recaudo"],
            catastro=fam["catastro"],
            refactura=fam["refactura"],
            convenio=fam["convenio"],
            pares_anteriores=anteriores,
            pares_historicos=historicos,
        )

    if not con_movimiento:
        return _cacheado(ctx, periodo, "td", lambda: calcular(set(), set()))  # type: ignore[no-any-return]
    lista = periodos(db, ctx)
    comparable = _comparable(lista, periodo)
    anteriores = set(_pares_afinia(ctx, comparable)) if comparable else set()
    historicos: set[tuple[str, str]] = set()
    for p in lista:
        if comparable and p < comparable:
            historicos |= _pares_afinia(ctx, p)
    return _cacheado(  # type: ignore[no-any-return]
        ctx, periodo, f"td:{comparable}:{len(historicos)}", lambda: calcular(anteriores, historicos)
    )


def totales_corte(
    db: Session, ctx: Contexto, periodo: str, *, con_movimiento: bool = False
) -> dict[str, Any]:
    """Cifras del corte para indicadores, serie, consolidado y entregables (una sola fuente)."""
    if ctx.codigo == "afinia":
        total = dict(_td_afinia(db, ctx, periodo, con_movimiento=con_movimiento)["total"])
        total.pop("estrato_uso", None)
        total.pop("estrato_uso_catastro", None)
        total["recaudo"] = total["recaudo_total"]
        total["cartera"] = total["cartera_acumulada"]
        total["n_facturados"] = total["n_factura"]
        total["eficiencia"] = total["eficiencia_con_cartera"]
        return total
    if ctx.codigo == "vatia":
        return vatia.resumen(familia(ctx, periodo, "comercial"))
    return analisis.totales(usuarios(ctx, periodo).values())


def _exigir(ctx: Contexto, analisis_id: str) -> None:
    dominio_o_http(lambda: catalogo_dominio.exigir_disponible(ctx.codigo, analisis_id))


def _ctx_corte(
    db: Session, sede: SedeResumen, codigo: str, periodo: str, analisis_id: str
) -> Contexto:
    ctx = contexto(db, sede, codigo)
    _exigir(ctx, analisis_id)
    exigir_corte(db, ctx, periodo)
    return ctx


def _movimiento_dict(mov: analisis.Movimiento) -> dict[str, Any]:
    return {
        "periodo": mov.periodo,
        "comparable": mov.comparable,
        "salto_corte_detectado": mov.salto_corte_detectado,
        "skipped_missing_cut": mov.salto_corte_detectado,
        "cortes_faltantes": mov.cortes_faltantes,
    }


# === Resumen =====================================================================================


def indicadores(db: Session, sede: SedeResumen, codigo: str, periodo: str) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "resumen-indicadores")
    actual = totales_corte(db, ctx, periodo, con_movimiento=True)
    mov = _movimiento(db, ctx, periodo)
    if ctx.codigo != "afinia":
        actual.update(
            nuevos_usuarios=len(mov.nuevos),
            usuarios_reintegrados=len(mov.reintegrados),
            usuarios_dejados_facturar=len(mov.dejados_facturar),
        )
    anterior = totales_corte(db, ctx, mov.comparable) if mov.comparable else None
    return {
        **actual,
        **_movimiento_dict(mov),
        "comercializador": ctx.codigo,
        "anterior": anterior,
        "variacion": analisis.variaciones(actual, anterior),
        "nota": catalogo_dominio.capacidad(ctx.codigo, "resumen-indicadores").nota,
    }


def serie(db: Session, sede: SedeResumen, codigo: str) -> dict[str, Any]:
    ctx = contexto(db, sede, codigo)
    puntos = []
    for p in periodos(db, ctx):
        t = totales_corte(db, ctx, p)
        puntos.append(
            {
                "periodo": p,
                "facturacion": t["facturacion"],
                "recaudo": t["recaudo"],
                "recaudo_corriente": t.get("recaudo_corriente"),
                "recaudo_cartera": t.get("recaudo_cartera"),
                "cartera": t["cartera"],
                "n_facturados": t["n_facturados"],
                "eficiencia": t.get("eficiencia"),
            }
        )
    return {"comercializador": ctx.codigo, "serie": puntos}


def eficiencia(db: Session, sede: SedeResumen, codigo: str, periodo: str) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "resumen-eficiencia")
    t = totales_corte(db, ctx, periodo)
    lista = usuarios(ctx, periodo).values()
    return {
        "periodo": periodo,
        "eficiencia_pesos": t.get("eficiencia"),
        "eficiencia_usuarios": analisis.totales(lista)["eficiencia_usuarios"],
        "facturacion": t["facturacion"],
        "recaudo": t["recaudo"],
        "nota": "La eficiencia en pesos puede superar 100 % cuando el recaudo incluye pagos de "
        "facturas anteriores; por usuarios, solo cuentan los facturados del corte.",
        **analisis.eficiencia_detalle(lista),
    }


ALIAS_INDICADOR: dict[str, str] = {
    "pct_n_factura": "n_factura",
    "tarifa_promedio": "facturacion",
    "total_facturacion": "facturacion",
    "pct_n_rec": "n_rec",
    "eficiencia_facturacion": "n_rec",
    "pct_recaudo_corriente": "recaudo_corriente",
    "factura_promedio_rec_corriente": "recaudo_corriente",
    "eficiencia_corriente": "recaudo_corriente",
    "pct_recaudo_total": "recaudo_total",
    "factura_promedio_rec_total": "recaudo_total",
    "eficiencia_con_cartera": "recaudo_total",
    "pct_recaudo_cartera": "recaudo_cartera",
    "factura_promedio_cartera": "recaudo_cartera",
    "cartera_recuperada": "recaudo_cartera",
    "n_usuarios_cartera_recuperada": "n_facturas_recaudo_cartera",
    "pct_n_usuarios_cartera": "n_usuarios_cartera_acumulada",
    "pct_cartera_valor": "cartera_acumulada",
    "facturado": "facturacion",
    "recaudo": "recaudo_total",
    "cartera": "cartera_acumulada",
    "consumo": "consumo_kwh",
}

_SELECTORES: dict[str, Callable[[UsuarioCorte], Any]] = {
    "n_factura": lambda u: u.facturado if u.facturado_presente else None,
    "facturacion": lambda u: u.facturado if u.facturado_presente else None,
    "promedio_consumo_kwh": lambda u: u.consumo if u.facturado_presente else None,
    "consumo_kwh": lambda u: u.consumo if u.facturado_presente else None,
    "n_rec": lambda u: u.recaudo if u.pago else None,
    "recaudo_total": lambda u: u.recaudo if u.pago else None,
    "recaudo_corriente": lambda u: u.recaudo_corriente or None,
    "recaudo_cartera": lambda u: u.recaudo_cartera or None,
    "n_facturas_recaudo_cartera": lambda u: u.recaudo_cartera or None,
    "cartera_acumulada": lambda u: u.cartera if u.cartera != 0 else None,
    "n_usuarios_cartera_acumulada": lambda u: u.cartera if u.cartera > 0 else None,
    "eficiencia_usuarios": lambda u: u.facturado if u.facturado_presente and not u.pago else None,
    "n_facturacion_cartera_ordinaria": (
        lambda u: u.facturado if u.facturado_presente and not u.pago else None
    ),
    "cartera_periodo": lambda u: (u.facturado - u.recaudo) if u.facturado_presente else None,
}


def detalle_indicador(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    codigo: str,
    periodo: str,
    indicador: str,
    limite: int,
) -> dict[str, Any]:
    """E.2: ¿qué usuarios hay detrás de cada cifra? Consulta nominal (se audita)."""
    ctx = _ctx_corte(db, sede, codigo, periodo, "detalle-indicador")
    base = ALIAS_INDICADOR.get(indicador, indicador)
    datos = usuarios(ctx, periodo)
    if base in ("usuarios_dejados_facturar", "nuevos_usuarios", "usuarios_reintegrados"):
        mov = _movimiento(db, ctx, periodo)
        ids = {
            "usuarios_dejados_facturar": mov.dejados_facturar,
            "nuevos_usuarios": mov.nuevos,
            "usuarios_reintegrados": mov.reintegrados,
        }[base]
        if mov.comparable:
            datos = {**usuarios(ctx, mov.comparable), **datos}
        filas = [(k, datos[k].facturado if k in datos else None) for k in ids]
    elif base in _SELECTORES:
        filas = [(k, _SELECTORES[base](u)) for k, u in datos.items()]
        filas = [(k, v) for k, v in filas if v is not None]
    else:
        raise HTTPException(status_code=422, detail=f"Indicador sin detalle: {indicador}.")
    filas.sort(key=lambda kv: (-abs(kv[1] or 0), kv[0]))
    auditar_consulta(db, actor, ctx, "detalle", periodo=periodo, indicador=indicador)

    def ficha(k: str, v: Any) -> dict[str, Any]:
        u = datos.get(k)
        return {
            "identificador": k,
            "valor": v,
            "nombre": u.nombre if u else None,
            "direccion": u.direccion if u else None,
            "barrio": u.barrio if u else None,
            "tarifa": u.tarifa if u else None,
            "estado_suministro": u.estado_suministro if u else None,
        }

    return {
        "periodo": periodo,
        "indicador": indicador,
        "indicador_base": base,
        "total": len(filas),
        "items": [ficha(k, v) for k, v in filas[:limite]],
    }


# === Flujos ======================================================================================


def flujo(
    db: Session, sede: SedeResumen, codigo: str, periodo: str, analisis_id: str
) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, analisis_id)
    lista = list(usuarios(ctx, periodo).values())
    t = totales_corte(db, ctx, periodo)
    por_segmento = analisis.agrupar(lista, "segmento")
    if analisis_id == "facturacion":
        campo = {"afinia": "sv", "celsia": "factura"}.get(ctx.codigo)
        facturas = (
            len({f.get(campo) for f in familia(ctx, periodo, "facturacion")})
            if campo
            else t.get("facturas", 0)
        )
        return {
            "periodo": periodo,
            "usuarios": t["n_facturados"],
            "facturas": facturas,
            "facturacion": t["facturacion"],
            "consumo": t.get("consumo_kwh", t.get("consumo", t.get("consumo_activa"))),
            "por_segmento": por_segmento,
        }
    if analisis_id == "recaudo":
        return {
            "periodo": periodo,
            "recaudo": t["recaudo"],
            "recaudo_corriente": t.get("recaudo_corriente"),
            "recaudo_cartera": t.get("recaudo_cartera"),
            "usuarios_pagaron": sum(1 for u in lista if u.pago),
            "nota": "Corriente o cartera según la antigüedad de la factura pagada "
            "(clasificación analítica, no certificada por el operador).",
            "por_segmento": por_segmento,
        }
    return {
        "periodo": periodo,
        "cartera": t["cartera"],
        "usuarios_con_saldo": sum(1 for u in lista if u.cartera > 0),
        "por_segmento": por_segmento,
    }


def cartera_edades(db: Session, sede: SedeResumen, codigo: str, periodo: str) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "cartera-edades")
    if ctx.codigo == "celsia":
        return {"periodo": periodo, **celsia.cartera_por_edades(familia(ctx, periodo, "cartera"))}
    return {"periodo": periodo, **vatia.cartera_por_edades(familia(ctx, periodo, "comercial"))}


def concentracion(db: Session, sede: SedeResumen, codigo: str, periodo: str) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "concentracion-cartera")
    deudas = {k: u.cartera for k, u in usuarios(ctx, periodo).items()}
    return {"periodo": periodo, **analisis.concentracion(deudas)}


# === Usuarios ====================================================================================


def movimientos(db: Session, sede: SedeResumen, codigo: str, periodo: str) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "movimiento-usuarios")
    mov = _movimiento(db, ctx, periodo)

    def ids(lista: list[str]) -> list[dict[str, str]]:
        return [{"identificador": i} for i in lista]

    return {
        **_movimiento_dict(mov),
        "conteos": {
            "facturados": len(mov.facturados),
            "nuevos": len(mov.nuevos),
            "reintegrados": len(mov.reintegrados),
            "dejados_facturar": len(mov.dejados_facturar),
            "no_evaluables": len(mov.no_evaluables),
        },
        "nuevos": ids(mov.nuevos),
        "reintegrados": ids(mov.reintegrados),
        "dejados_facturar": ids(mov.dejados_facturar),
        "nota": "Solo sobre quienes les correspondía facturar; los meses sin archivo no cuentan "
        "como ausencia y quien reaparece es reintegrado, no nuevo.",
    }


def ausencias(
    db: Session, sede: SedeResumen, codigo: str, periodo: str, limite: int
) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "usuarios-ausentes")
    mov = _movimiento(db, ctx, periodo)
    items = sorted(
        (
            {
                "identificador": k,
                "ultimo_periodo": mov.ultimo_periodo[k],
                "periodos_ausente": n,
                "tramo": analisis.tramo(n),
                "causa": "sin causa identificada",
            }
            for k, n in mov.ausentes.items()
        ),
        key=lambda r: (-r["periodos_ausente"], r["identificador"]),
    )
    return {
        **_movimiento_dict(mov),
        "tramos": analisis.tramos_ausencia(mov.ausentes),
        "total": len(items),
        "items": items[:limite],
        "nota": "Antigüedad en periodos esperados del usuario; los cortes no entregados no suman.",
    }


def disminuciones(
    db: Session,
    sede: SedeResumen,
    codigo: str,
    periodo: str,
    *,
    variable: str,
    minimo: Decimal | None,
    maximo: Decimal | None,
    segmento: str | None,
    barrio: str | None,
    solo_comerciales: bool,
    limite: int,
) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "disminuciones")
    if variable not in analisis.VARIABLES_DISMINUCION:
        raise HTTPException(
            status_code=422,
            detail=f"Variable desconocida; use {', '.join(analisis.VARIABLES_DISMINUCION)}.",
        )
    comparable = _comparable(periodos(db, ctx), periodo)
    actual = usuarios(ctx, periodo)
    if solo_comerciales:
        actual = {k: u for k, u in actual.items() if (u.segmento or "").lower() == "comercial"}
    resultado = analisis.disminuciones(
        actual,
        usuarios(ctx, comparable) if comparable else {},
        variable=variable,
        minimo_pct=minimo,
        maximo_pct=maximo,
        segmento=segmento,
        barrio=barrio,
        limite=limite,
    )
    return {"periodo": periodo, "comparable": comparable, **resultado}


def periodicidad(
    db: Session, sede: SedeResumen, codigo: str, periodo: str, limite: int
) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "usuarios-periodicidad")
    lista = [p for p in periodos(db, ctx) if p <= periodo]
    presencia = _presencia(ctx, lista)
    ciclos = _periodicidades(ctx, lista, presencia)
    conteos: dict[str, int] = {}
    for valor, _origen in ciclos.values():
        conteos[valor] = conteos.get(valor, 0) + 1
    items = [
        {
            "identificador": k,
            "periodicidad": v,
            "origen": o,
            "meses_facturados": sorted(presencia[k]),
        }
        for k, (v, o) in sorted(ciclos.items())
    ]
    return {
        "periodo": periodo,
        "cortes_considerados": lista,
        "conteos": conteos,
        "total": len(items),
        "items": items[:limite],
    }


# === Hallazgos: control tarifario e irregularidades ==============================================


def vigencia_afinia(db: Session, ctx: Contexto, anio: int) -> afinia.VigenciaAfinia | None:
    acuerdo = configuracion.obtener_vigencia_aprobada(db, ctx.sede.id, "afinia", anio)
    if acuerdo is None or None in (acuerdo.uvt, acuerdo.umbral_kwh, acuerdo.tolerancia):
        return None
    return afinia.VigenciaAfinia(
        anio=anio,
        uvt=acuerdo.uvt,  # type: ignore[arg-type]
        umbral_kwh=acuerdo.umbral_kwh,  # type: ignore[arg-type]
        tolerancia=acuerdo.tolerancia,  # type: ignore[arg-type]
        tarifas={
            t.tarifa: (t.factor_uvt_minimo, t.porcentaje_costo_variable)
            for t in acuerdo.tarifas
            if t.factor_uvt_minimo is not None and t.porcentaje_costo_variable is not None
        },
        excepciones={
            e.identificador: e.factor_uvt
            for e in acuerdo.excepciones
            if e.activo and e.factor_uvt is not None
        },
    )


def vigencia_celsia(db: Session, ctx: Contexto, anio: int) -> celsia.VigenciaCelsia | None:
    acuerdo = configuracion.obtener_vigencia_aprobada(db, ctx.sede.id, "celsia", anio)
    if acuerdo is None or acuerdo.tolerancia is None:
        return None
    return celsia.VigenciaCelsia(
        anio=anio,
        tolerancia=acuerdo.tolerancia,
        duplicar_bimestral=bool(acuerdo.reglas.get("topes_se_duplican_en_bimestral", True)),
        tarifas={
            t.tarifa: celsia.ReglaCelsia(
                t.tipo_regla or "fija", t.porcentaje_costo_variable, t.valor_urbano, t.valor_rural
            )
            for t in acuerdo.tarifas
        },
        excepciones={e.identificador: dict(e.regla or {}) for e in acuerdo.excepciones if e.activo},
    )


def filas_control(db: Session, ctx: Contexto, periodo: str) -> tuple[list[afinia.FilaControl], Any]:
    anio = int(periodo[:4])
    fact = familia(ctx, periodo, "facturacion")
    if ctx.codigo == "afinia":
        vigencia: Any = vigencia_afinia(db, ctx, anio)
        filas = afinia.control_tarifario(fact, periodo, vigencia)
    else:
        vigencia = vigencia_celsia(db, ctx, anio)
        filas = celsia.control_tarifario(fact, periodo, vigencia)
    datos = usuarios(ctx, periodo)
    for fila in filas:
        u = datos.get(fila.identificador)
        if u is not None:
            fila.extra.update(nombre=u.nombre, barrio=u.barrio, direccion=u.direccion)
    return filas, vigencia


ORDEN_ESTADO = {
    "POR_ENCIMA": 0,
    "POR_DEBAJO": 1,
    "REQUIERE_REVISION": 2,
    "NO_VALIDABLE": 3,
    "CORRECTO": 4,
}


def control_tarifario(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    codigo: str,
    periodo: str,
    *,
    grupo_consumo: str,
    estado: str | None,
    buscar: str | None,
    page: int,
    size: int,
) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "control-tarifario")
    filas, vigencia = filas_control(db, ctx, periodo)
    if grupo_consumo not in afinia.GRUPOS_CONSUMO:
        raise HTTPException(
            status_code=422, detail="grupo_consumo: todos, minima, variable, especial o revision."
        )
    if ctx.codigo == "afinia":
        filas = afinia.filtrar_grupo(filas, grupo_consumo)
    else:
        filas = celsia.filtrar_grupo(filas, grupo_consumo, vigencia)
    totales = afinia.resumir_control(filas)
    if estado:
        filas = [f for f in filas if f.estado == estado.upper()]
    if buscar:
        filas = [f for f in filas if buscar.strip() in f.identificador]
    filas.sort(key=lambda f: (ORDEN_ESTADO[f.estado], -abs(f.diferencia or 0), f.identificador))
    auditar_consulta(
        db,
        actor,
        ctx,
        "control_tarifario",
        periodo=periodo,
        grupo=grupo_consumo,
        estado=estado,
        page=page,
    )
    return {
        "periodo": periodo,
        "comercializador": ctx.codigo,
        "vigencia": (
            {
                "anio": vigencia.anio,
                "tolerancia": vigencia.tolerancia,
                **(
                    {"uvt": vigencia.uvt, "umbral_kwh": vigencia.umbral_kwh}
                    if isinstance(vigencia, afinia.VigenciaAfinia)
                    else {}
                ),
            }
            if vigencia is not None
            else None
        ),
        "grupo_consumo": grupo_consumo,
        "totales": totales,
        "total": len(filas),
        "page": page,
        "size": size,
        "items": [f.como_dict() for f in filas[(page - 1) * size : page * size]],
    }


def facturas_revision(db: Session, sede: SedeResumen, codigo: str, periodo: str) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "facturas-revision")
    fact = familia(ctx, periodo, "facturacion")
    categorias = (
        afinia.facturas_irregulares(fact)
        if ctx.codigo == "afinia"
        else celsia.facturas_irregulares(fact, periodo)
    )
    nota = None
    if ctx.codigo == "celsia" and periodo < "202605":
        nota = "Los cortes de Celsia anteriores a mayo de 2026 no desglosan el concepto."
    return {
        "periodo": periodo,
        "por_categoria": categorias,
        "conteos": {k: len(v) for k, v in categorias.items()},
        "nota": nota,
    }


# === Gestión ====================================================================================


def convenios(db: Session, sede: SedeResumen, codigo: str, periodo: str) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "convenios")
    if ctx.codigo == "afinia":
        return {"periodo": periodo, **afinia.auditoria_convenios(familia(ctx, periodo, "convenio"))}
    filas = [
        f for f in familia(ctx, periodo, "facturacion") if f.get("tipo_concepto") == "financiacion"
    ]
    usuarios_fin = {str(f["cuenta"]) for f in filas}
    return {
        "periodo": periodo,
        "resumen": {
            "usuarios": len(usuarios_fin),
            "valor": q2(suma(f.get("valor_facturado") for f in filas)),
        },
        "nota": catalogo_dominio.capacidad(ctx.codigo, "convenios").nota,
    }


def convenios_ajustes(db: Session, sede: SedeResumen, codigo: str) -> dict[str, Any]:
    ctx = contexto(db, sede, codigo)
    _exigir(ctx, "convenios-ajustes")
    lista = periodos(db, ctx)
    recaudo_por = {p: familia(ctx, p, "recaudo") for p in lista}
    conv_por = {p: familia(ctx, p, "convenio") for p in lista}
    cuotas: dict[str, dict[str, Decimal]] = {}
    pagos: dict[str, dict[str, Decimal]] = {}
    saldos: dict[str, dict[str, Decimal]] = {}
    for p in lista:
        cuota: dict[str, Decimal] = {}
        for f in familia(ctx, p, "facturacion"):
            if f.get("concepto") == afinia.CONCEPTO_CUOTA_CONVENIO:
                cuota[str(f["nic"])] = cuota.get(str(f["nic"]), Decimal(0)) + d(
                    f.get("importe_trans")
                )
        cuotas[p] = cuota
        pagos[p] = {k: u.recaudo for k, u in usuarios(ctx, p).items() if u.pago}
        saldos[p] = {k: u.cartera for k, u in usuarios(ctx, p).items() if u.cartera}
    return {
        "cohortes": afinia.cohortes_convenio(
            conv_por, {p: set(facturados(ctx, p)) for p in lista}, cuotas, pagos, saldos
        ),
        "ajustes_negativos": afinia.ajustes_negativos(recaudo_por),
        "nota": "Descriptivo: el recaudo no permite asignar un pago a una cuota, así que no "
        "prueba cumplimiento ni abandono de un convenio.",
    }


def maduracion(db: Session, sede: SedeResumen, codigo: str, periodo: str) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "maduracion-recaudo")
    lista = [p for p in periodos(db, ctx) if p <= periodo]
    if ctx.codigo == "afinia":
        recaudo = familia(ctx, periodo, "recaudo")
        cartera_sin_edad = q2(
            suma(f.get("deuda_corriente") for f in familia(ctx, periodo, "catastro"))
        )
        fact_todos = [f for p in lista for f in familia(ctx, p, "facturacion")]
        reca_todos = [f for p in lista for f in familia(ctx, p, "recaudo")]
    else:

        def como_afinia(
            filas: list[dict[str, Any]], valor: str, fecha: str
        ) -> list[dict[str, Any]]:
            return [
                {
                    "nic": f["cuenta"],
                    "importe_trans": f.get(valor),
                    "concepto": None,
                    "fecha_fact_lect": f.get(fecha),
                    "fecha_trans": f.get("fecha_pago"),
                }
                for f in filas
            ]

        recaudo = como_afinia(
            familia(ctx, periodo, "recaudo"), "valor_recaudado", "fecha_vencimiento"
        )
        cartera_sin_edad = None
        fact_todos = [
            r
            for p in lista
            for r in como_afinia(familia(ctx, p, "facturacion"), "valor_facturado", "fecha_factura")
        ]
        reca_todos = [
            r
            for p in lista
            for r in como_afinia(familia(ctx, p, "recaudo"), "valor_recaudado", "fecha_vencimiento")
        ]
    return {
        "periodo": periodo,
        "bandas": afinia.maduracion(recaudo, periodo),
        "cartera_sin_edad_observable": cartera_sin_edad,
        "cohortes": afinia.curva_cohortes(fact_todos, reca_todos, lista),
        "nota": "Afinia no entrega la fecha de origen del saldo: la cartera del catastro no tiene "
        "edad observable."
        if ctx.codigo == "afinia"
        else None,
    }


def comportamiento_pago(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, codigo: str, limite: int
) -> dict[str, Any]:
    ctx = contexto(db, sede, codigo)
    _exigir(ctx, "comportamiento-pago")
    lista = periodos(db, ctx)
    if not lista:
        return {"resumen": {}, "total": 0, "items": [], "cortes": []}
    resultado = analisis.comportamiento_pago(
        {p: set(facturados(ctx, p)) for p in lista},
        {p: set(pagaron(ctx, p)) for p in lista},
        usuarios(ctx, lista[-1]),
        limite,
    )
    auditar_consulta(db, actor, ctx, "comportamiento_pago", limite=limite)
    return {**resultado, "cortes": lista, "nota": "Señal operativa: no prueba mora jurídica."}


def rutas_campo(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    codigo: str,
    periodo: str,
    grupo: str,
    limite: int,
) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "rutas-campo")
    lista = [p for p in periodos(db, ctx) if p <= periodo]
    comportamiento = analisis.comportamiento_pago(
        {p: set(facturados(ctx, p)) for p in lista},
        {p: set(pagaron(ctx, p)) for p in lista},
        usuarios(ctx, periodo),
        limite=10**9,
    )
    candidatos = [
        r for r in comportamiento["items"] if r["comportamiento"] == grupo and r["cartera"] > 0
    ]
    por_barrio: dict[str, dict[str, Any]] = {}
    for r in candidatos:
        b = por_barrio.setdefault(
            r["barrio"] or "Sin barrio",
            {"barrio": r["barrio"] or "Sin barrio", "usuarios": 0, "cartera": Decimal(0)},
        )
        b["usuarios"] += 1
        b["cartera"] += r["cartera"]
    candidatos.sort(key=lambda r: (r["barrio"] or "", -r["cartera"], r["identificador"]))
    comparable = _comparable(lista, periodo)

    def consumo_factura(p: str) -> dict[str, tuple[Decimal, Decimal]]:
        return {
            k: (u.consumo or Decimal(0), u.facturado)
            for k, u in usuarios(ctx, p).items()
            if u.facturado_presente
        }

    anomalias = (
        afinia.anomalias_consumo(consumo_factura(periodo), consumo_factura(comparable))
        if comparable
        else []
    )
    presencia = _presencia(ctx, lista)
    repetidos = afinia.movimientos_repetidos(
        {k: [p in v for p in lista] for k, v in presencia.items()}
    )
    auditar_consulta(db, actor, ctx, "rutas_campo", periodo=periodo, grupo=grupo)
    return {
        "periodo": periodo,
        "grupo": grupo,
        "barrios": sorted(por_barrio.values(), key=lambda b: (-b["cartera"], b["barrio"])),
        "items": candidatos[:limite],
        "anomalias": anomalias[:limite],
        "movimientos_repetidos": repetidos[:limite],
        "comparable": comparable,
    }


# === Históricos ==================================================================================


def consolidado_anual(
    db: Session, sede: SedeResumen, codigo: str, anio: int | None
) -> dict[str, Any]:
    ctx = contexto(db, sede, codigo)
    lista = periodos(db, ctx)
    if anio is None:
        anio = int(lista[-1][:4]) if lista else datetime.now(UTC).year
    series = {p: totales_corte(db, ctx, p) for p in lista if p.startswith(str(anio))}
    return {"comercializador": ctx.codigo, **analisis.consolidado_anual(anio, series)}


def historico(db: Session, sede: SedeResumen, codigo: str, analisis_id: str) -> dict[str, Any]:
    """Serie por tarifa (Afinia) o por segmento/submercado (Celsia, Vatia)."""
    ctx = contexto(db, sede, codigo)
    _exigir(ctx, analisis_id)
    puntos = []
    for p in periodos(db, ctx):
        if ctx.codigo == "afinia":
            filas = _td_afinia(db, ctx, p, con_movimiento=False)["filas"]
            if analisis_id == "historico-comerciales":
                filas = [f for f in filas if f["estrato_uso"] in afinia.TARIFAS_COMERCIALES]
            grupos = [
                {
                    "grupo": f["estrato_uso"],
                    "usuarios": f["n_factura"],
                    "facturacion": f["facturacion"],
                    "recaudo_corriente": f["recaudo_corriente"],
                    "recaudo_cartera": f["recaudo_cartera"],
                    "recaudo_total": f["recaudo_total"],
                    "cartera": f["cartera_acumulada"],
                    "consumo_kwh": f["consumo_kwh"],
                }
                for f in filas
            ]
        else:
            lista_u = list(usuarios(ctx, p).values())
            if analisis_id == "historico-comerciales":
                lista_u = [u for u in lista_u if "comercial" in (u.segmento or "").lower()]
            grupos = [
                {
                    "grupo": g["segmento"],
                    "usuarios": g["usuarios"],
                    "facturacion": g["facturacion"],
                    "recaudo_total": g["recaudo"],
                    "cartera": g["cartera"],
                    "consumo_kwh": g["consumo"],
                }
                for g in analisis.agrupar(lista_u, "segmento")
            ]
        total = totales_corte(db, ctx, p)
        puntos.append(
            {
                "periodo": p,
                "facturacion": total["facturacion"],
                "cartera": total["cartera"],
                "grupos": grupos,
            }
        )
    for anterior, actual in zip(puntos, puntos[1:], strict=False):
        for campo in ("facturacion", "cartera"):
            actual[f"{campo}_variacion_pct"] = div(
                actual[campo] - anterior[campo], anterior[campo], nulo=True
            )
    return {"comercializador": ctx.codigo, "analisis": analisis_id, "serie": puntos}


# === Herramientas ================================================================================


def segmentacion(
    db: Session, sede: SedeResumen, codigo: str, periodo: str, por: str
) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "segmentacion")
    if por not in ("segmento", "estrato", "tarifa"):
        raise HTTPException(status_code=422, detail="por: segmento, estrato o tarifa.")
    return {
        "periodo": periodo,
        "por": por,
        "grupos": analisis.agrupar(usuarios(ctx, periodo).values(), por),
    }


def comparativo_segmentos(
    db: Session, sede: SedeResumen, codigo: str, periodo: str, por: str
) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "comparativo-segmentos")
    if por not in ("segmento", "estrato", "tarifa"):
        raise HTTPException(status_code=422, detail="por: segmento, estrato o tarifa.")
    comparable = _comparable(periodos(db, ctx), periodo)
    actual = analisis.agrupar(usuarios(ctx, periodo).values(), por)
    anterior = analisis.agrupar(usuarios(ctx, comparable).values(), por) if comparable else []
    return {
        "periodo": periodo,
        "comparable": comparable,
        "por": por,
        "grupos": analisis.comparar_grupos(actual, anterior, por),
    }


def barrios(db: Session, sede: SedeResumen, codigo: str, periodo: str) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "barrios")
    return {
        "periodo": periodo,
        "grupos": analisis.agrupar(usuarios(ctx, periodo).values(), "barrio"),
        "nota": catalogo_dominio.capacidad(ctx.codigo, "barrios").nota,
    }


def tabla_dinamica(db: Session, sede: SedeResumen, codigo: str, periodo: str) -> dict[str, Any]:
    ctx = _ctx_corte(db, sede, codigo, periodo, "tabla-dinamica")
    if ctx.codigo == "afinia":
        td = _td_afinia(db, ctx, periodo)
        mov = _movimiento(db, ctx, periodo)
        return {
            "periodo": periodo,
            **_movimiento_dict(mov),
            "columnas": list(afinia.COLUMNAS_TD),
            "filas": td["filas"],
            "total": td["total"],
        }
    if ctx.codigo == "vatia":
        return {"periodo": periodo, **vatia.tabla_dinamica(familia(ctx, periodo, "comercial"))}
    return {"periodo": periodo, **_td_celsia(db, ctx, periodo)}


def _clasificaciones_celsia(ctx: Contexto, periodo: str) -> dict[str, set[str]]:
    """cuenta → clasificaciones de la TD en el corte (una cuenta puede tener dos)."""

    def calcular() -> dict[str, set[str]]:
        mapa: dict[str, set[str]] = {}
        for f in familia(ctx, periodo, "facturacion"):
            mapa.setdefault(str(f.get("cuenta")), set()).add(celsia.clasificacion_td(f))
        return mapa

    return _cacheado(ctx, periodo, "clasificaciones_td", calcular)  # type: ignore[no-any-return]


def _cortes_celsia(db: Session, ctx: Contexto) -> dict[str, list[tuple[str, Any, Any]]]:
    """periodo → [(cuenta, periodicidad, sector)] de la facturación de cada corte publicado."""
    return {
        p: _cacheado(  # type: ignore[misc]
            ctx,
            p,
            "perfil_celsia",
            lambda p=p: list(
                dict.fromkeys(
                    (str(f.get("cuenta")), f.get("periodicidad"), f.get("sector"))
                    for f in familia(ctx, p, "facturacion")
                )
            ),
        )
        for p in periodos(db, ctx)
    }


def _td_celsia(db: Session, ctx: Contexto, periodo: str) -> dict[str, Any]:
    """TD de Celsia por clasificación, con la misma definición de OPainn (`td_celsia`)."""
    mov = celsia.clasificar_movimientos(_cortes_celsia(db, ctx), periodo)
    # Cada baja se cuenta en la clasificación de su propio corte comparable.
    dejados = {
        cuenta: _clasificaciones_celsia(ctx, mov.evaluables[cuenta]).get(cuenta, set())
        for cuenta in mov.dejados
    }
    # Variación contra el mismo ciclo de facturación: el corte de dos meses atrás.
    comparable = sumar_meses(periodo, -2)
    previo: dict[str, dict[str, Decimal]] | None = None
    if comparable in periodos(db, ctx):
        anterior = celsia.tabla_dinamica(
            comparable,
            facturacion=familia(ctx, comparable, "facturacion"),
            recaudo=familia(ctx, comparable, "recaudo"),
            cartera=None,
        )
        previo = {
            f["clasificacion"]: {"facturacion": f["facturacion"], "recaudo": f["recaudo_total"]}
            for f in anterior["filas"]
        }
    evaluable = bool(mov.evaluables)
    td = celsia.tabla_dinamica(
        periodo,
        facturacion=familia(ctx, periodo, "facturacion"),
        recaudo=familia(ctx, periodo, "recaudo"),
        cartera=familia(ctx, periodo, "cartera"),
        nuevos=mov.nuevos if evaluable else None,
        reintegrados=mov.reintegrados if evaluable else None,
        dejados=dejados if evaluable else None,
        previo=previo,
    )
    return {
        "periodo": periodo,
        "por": "clasificacion",
        "comparado_con": comparable if previo is not None else None,
        "cartera_disponible": td["cartera_disponible"],
        "filas": td["filas"],
        "total": td["totales"],
    }


def trazabilidad(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, codigo: str, identificador: str
) -> dict[str, Any]:
    """Historia completa de un usuario en todos los cortes. Consulta nominal (se audita)."""
    ctx = contexto(db, sede, codigo)
    _exigir(ctx, "trazabilidad")
    clave = identificador.strip()
    campo = ctx.adaptador.identificador
    historia = []
    ficha: dict[str, Any] = {}
    for p in periodos(db, ctx):
        u = usuarios(ctx, p).get(clave)
        lineas = {
            f: [r for r in familia(ctx, p, f) if str(r.get(campo)) == clave][:100]
            for f in ctx.adaptador.familias
        }
        if u is None and not any(lineas.values()):
            historia.append({"periodo": p, "presente": False})
            continue
        if u is not None:
            ficha = {
                "nombre": u.nombre,
                "direccion": u.direccion,
                "barrio": u.barrio,
                "tarifa": u.tarifa,
                "segmento": u.segmento,
                "estado_suministro": u.estado_suministro,
            }
        historia.append(
            {
                "periodo": p,
                "presente": bool(u and u.facturado_presente),
                "facturado": u.facturado if u else None,
                "recaudo": u.recaudo if u else None,
                "cartera": u.cartera if u else None,
                "consumo": u.consumo if u else None,
                "tarifa": u.tarifa if u else None,
                "lineas": lineas,
            }
        )
    auditar_consulta(db, actor, ctx, "trazabilidad", identificador=clave)
    if not any(h["presente"] or h.get("lineas") for h in historia):
        raise HTTPException(status_code=404, detail="El usuario no aparece en los cortes cargados.")
    presentes = [h["periodo"] for h in historia if h["presente"]]
    return {
        "identificador": clave,
        "comercializador": ctx.codigo,
        "ficha": ficha,
        "primer_periodo": presentes[0] if presentes else None,
        "ultimo_periodo": presentes[-1] if presentes else None,
        "cortes_ausente": [h["periodo"] for h in historia if not h["presente"]],
        "historia": historia,
    }


# === Hallazgos revisados (E.5) ===================================================================


def _a_hallazgo(h: Any, codigo: str) -> dict[str, Any]:
    return {
        "id": h.id,
        "comercializador": codigo,
        "tipo": h.tipo,
        "estado": h.estado,
        "responsable": h.responsable,
        "decision": h.decision,
        "identificador": h.identificador,
        "nic": h.identificador,
        "referencia": h.referencia,
        "periodo": h.periodo,
        "creado_en": h.creado_en,
        "modificado_en": h.modificado_en,
    }


def listar_hallazgos(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, codigo: str, estado: str | None
) -> list[dict[str, Any]]:
    ctx = contexto(db, sede, codigo)
    auditar_consulta(db, actor, ctx, "hallazgos", estado=estado)
    return [
        _a_hallazgo(h, ctx.codigo)
        for h in repositorio.listar_hallazgos(db, sede.id, ctx.comercializador_id, estado)
    ]


def crear_hallazgo(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, codigo: str, entrada: Any
) -> dict[str, Any]:
    from app.modulos.comercial.modelos import HallazgoComercial

    ctx = contexto(db, sede, codigo)
    hallazgo = HallazgoComercial(
        sede_id=sede.id,
        comercializador_id=ctx.comercializador_id,
        tipo=entrada.tipo,
        estado=entrada.estado,
        responsable=entrada.responsable.strip(),
        decision=entrada.decision.strip(),
        identificador=entrada.identificador,
        referencia=entrada.referencia,
        periodo=entrada.periodo,
        creado_por=actor.id,
        modificado_por=actor.id,
    )
    repositorio.agregar(db, hallazgo)
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="crear",
        entidad="hallazgo_comercial",
        entidad_id=str(hallazgo.id),
        despues={"tipo": hallazgo.tipo, "estado": hallazgo.estado, "periodo": hallazgo.periodo},
    )
    db.commit()
    db.refresh(hallazgo)
    return _a_hallazgo(hallazgo, ctx.codigo)


def editar_hallazgo(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    codigo: str,
    hallazgo_id: int,
    entrada: Any,
) -> dict[str, Any]:
    ctx = contexto(db, sede, codigo)
    hallazgo = repositorio.obtener_hallazgo(db, sede.id, ctx.comercializador_id, hallazgo_id)
    if hallazgo is None:
        raise HTTPException(status_code=404, detail="Hallazgo no encontrado.")
    cambios = entrada.model_dump(exclude_unset=True, exclude_none=True)
    antes = {k: getattr(hallazgo, k) for k in cambios}
    for campo, valor in cambios.items():
        setattr(hallazgo, campo, valor.strip() if isinstance(valor, str) else valor)
    hallazgo.modificado_por = actor.id
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="editar",
        entidad="hallazgo_comercial",
        entidad_id=str(hallazgo.id),
        antes=antes,
        despues=cambios,
    )
    db.commit()
    db.refresh(hallazgo)
    return _a_hallazgo(hallazgo, ctx.codigo)


# === Entregables (§11.12) ========================================================================

NOMBRES = {"afinia": "Afinia", "celsia": "Celsia", "vatia": "Vatia"}


def _subtitulo(ctx: Contexto, periodo: str) -> str:
    from app.modulos.comercial.dominio.comun import nombre_periodo

    return (
        f"{NOMBRES[ctx.codigo]} · Sede {ctx.sede.nombre} · Corte {nombre_periodo(periodo)} "
        f"({periodo}) · Generado el {datetime.now(UTC):%Y-%m-%d %H:%M} UTC"
    )


def _control_disponible(ctx: Contexto) -> bool:
    return catalogo_dominio.capacidad(ctx.codigo, "control-tarifario").estado != "no_aplica"


def _secciones_hallazgos(
    db: Session, ctx: Contexto, periodo: str, cargue: CargueComercial
) -> list[entregables.Seccion]:
    secciones: list[entregables.Seccion] = []
    if _control_disponible(ctx):
        filas, vigencia = filas_control(db, ctx, periodo)
        totales = afinia.resumir_control(filas)
        encima = sorted(
            (f for f in filas if f.estado == "POR_ENCIMA"),
            key=lambda f: (-f.valor_por_encima, f.identificador),
        )
        debajo = sorted(
            (f for f in filas if f.estado == "POR_DEBAJO"),
            key=lambda f: (-f.valor_por_debajo, f.identificador),
        )
        estados = totales["por_estado"]
        parrafos = [
            "Se comparó lo facturado por concepto del impuesto de alumbrado público con lo que "
            "corresponde según el acuerdo municipal vigente"
            + (
                f" (tolerancia de ${vigencia.tolerancia})."
                if vigencia
                else "; el periodo no tiene parámetros aprobados, por lo que no se pudo validar."
            ),
            f"Usuarios cobrados por encima: {estados['POR_ENCIMA']} por un total de "
            f"${entregables.formato(totales['valor_por_encima'])}. Usuarios cobrados por debajo: "
            f"{estados['POR_DEBAJO']} por un total de "
            f"${entregables.formato(totales['valor_por_debajo'])}. Estos valores se informan por "
            "separado; no se compensan entre sí.",
            f"Correctos: {estados['CORRECTO']} · No validables: {estados['NO_VALIDABLE']} · "
            f"Requieren revisión: {estados['REQUIERE_REVISION']}.",
        ]
        secciones.append(
            entregables.Seccion(
                "Cobros del impuesto frente a la tarifa vigente",
                parrafos,
                entregables.Tabla(
                    [
                        "Usuario",
                        "Tarifa",
                        "Regla",
                        "Facturado",
                        "Esperado",
                        "Por encima",
                        "Por debajo",
                    ],
                    [
                        [
                            f.identificador,
                            f.tarifa,
                            f.regla_aplicada,
                            f.facturado_real,
                            f.esperado,
                            f.valor_por_encima,
                            f.valor_por_debajo,
                        ]
                        for f in (encima[:40] + debajo[:40])
                    ],
                ),
            )
        )
    mov = _movimiento(db, ctx, periodo)
    datos = usuarios(ctx, periodo)
    parrafos = [
        f"Comparado con el corte {mov.comparable or 'anterior (no hay)'}: "
        f"{len(mov.dejados_facturar)} usuario(s) dejaron de facturarse, {len(mov.nuevos)} nuevos y "
        f"{len(mov.reintegrados)} reintegrados."
    ]
    if mov.salto_corte_detectado:
        parrafos.append(
            f"Atención: no se cargaron los cortes {', '.join(mov.cortes_faltantes)}; "
            "la comparación "
            "se hizo contra el último corte disponible."
        )
    if ctx.codigo == "afinia" and mov.dejados_facturar:
        en_catastro = [k for k in mov.dejados_facturar if k in datos]
        parrafos.append(
            f"Evidencia: {len(en_catastro)} de los usuarios que dejaron de facturarse siguen en el "
            "catastro de este corte."
        )
    secciones.append(
        entregables.Seccion(
            "Usuarios que dejaron de facturarse",
            parrafos,
            entregables.Tabla(
                ["Usuario", "Sigue en el catastro", "Estado del suministro"],
                [
                    [k, k in datos, datos[k].estado_suministro if k in datos else None]
                    for k in mov.dejados_facturar[:200]
                ],
            ),
        )
    )
    if catalogo_dominio.capacidad(ctx.codigo, "facturas-revision").estado != "no_aplica":
        categorias = (
            afinia.facturas_irregulares(familia(ctx, periodo, "facturacion"))
            if ctx.codigo == "afinia"
            else celsia.facturas_irregulares(familia(ctx, periodo, "facturacion"), periodo)
        )
        secciones.append(
            entregables.Seccion(
                "Facturas irregulares",
                ["Solo se consideran las líneas del impuesto de alumbrado."],
                entregables.Tabla(
                    ["Categoría", "Usuarios"],
                    [[k.replace("_", " ").capitalize(), len(v)] for k, v in categorias.items()],
                ),
            )
        )
    if ctx.codigo == "afinia" and mov.comparable:
        actual = q2(suma(u.cartera for u in datos.values()))
        anterior = q2(suma(u.cartera for u in usuarios(ctx, mov.comparable).values()))
        variacion = div(actual - anterior, anterior, nulo=True)
        if variacion is not None and abs(variacion) >= Decimal("0.30"):
            secciones.append(
                entregables.Seccion(
                    "Salto de cartera",
                    [
                        "La deuda corriente del catastro pasó de "
                        f"${entregables.formato(anterior)} a ${entregables.formato(actual)} "
                        f"({entregables.formato(variacion * 100)} %). "
                        "Solicitamos aclarar la variación (descontando lo trasladado a convenios)."
                    ],
                )
            )
    repetidos = [a for a in cargue.advertencias if "duplic" in a.lower()]
    if repetidos:
        secciones.append(
            entregables.Seccion(
                "Filas repetidas en los archivos",
                [*repetidos, "Se conservaron porque no se distinguen de pagos reales repetidos."],
            )
        )
    return secciones


def generar_entregable(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    codigo: str,
    tipo: str,
    periodo: str,
    formato: str | None,
    max_filas: int | None = None,
) -> tuple[bytes, str, str]:
    """Devuelve (contenido, tipo MIME, nombre de archivo)."""
    ctx = contexto(db, sede, codigo)
    cargue = exigir_corte(db, ctx, periodo)
    base = f"{tipo}_{ctx.codigo}_{ctx.sede.codigo}_{periodo}"
    if tipo == "anexo-nominal":
        return _anexo_nominal(db, actor, ctx, periodo, max_filas), XLSX, f"{base}.xlsx"
    if tipo == "requerimiento":
        doc = entregables.Documento(
            f"Requerimiento al operador {NOMBRES[ctx.codigo]}",
            _subtitulo(ctx, periodo),
            [
                entregables.Seccion(
                    "Objeto",
                    [
                        f"Con base en los archivos entregados por {NOMBRES[ctx.codigo]} para el "
                        f"corte {periodo}, el municipio solicita aclarar o corregir los hallazgos "
                        "que siguen. "
                        "El anexo nominal sustenta cada cifra."
                    ],
                ),
                *_secciones_hallazgos(db, ctx, periodo, cargue),
            ],
        )
        formato = formato or "docx"
    elif tipo == "analisis":
        total = totales_corte(db, ctx, periodo, con_movimiento=True)
        doc = entregables.Documento(
            f"Análisis del corte {periodo} · {NOMBRES[ctx.codigo]}",
            _subtitulo(ctx, periodo),
            [
                entregables.Seccion(
                    "Indicadores del corte",
                    [],
                    entregables.Tabla(
                        ["Indicador", "Valor"],
                        [
                            [k, v]
                            for k, v in total.items()
                            if isinstance(v, (int, Decimal)) and not isinstance(v, bool)
                        ],
                    ),
                ),
                *_secciones_hallazgos(db, ctx, periodo, cargue),
                entregables.Seccion("Avisos del cargue", cargue.advertencias or ["Sin avisos."]),
            ],
        )
        formato = formato or "html"
    elif tipo == "informe-gerencial":
        doc = _informe_gerencial(db, ctx, periodo)
        formato = formato or "pdf"
    else:
        raise HTTPException(status_code=404, detail="Entregable desconocido.")
    if formato == "docx":
        return entregables.a_docx(doc), DOCX, f"{base}.docx"
    if formato == "html":
        return entregables.a_html(doc).encode("utf-8"), "text/html; charset=utf-8", f"{base}.html"
    if formato == "pdf":
        return entregables.a_pdf(doc), "application/pdf", f"{base}.pdf"
    raise HTTPException(status_code=422, detail=f"Formato no disponible para {tipo}: {formato}.")


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _cifras_gerenciales(
    db: Session, ctx: Contexto, periodo: str
) -> tuple[dict[str, Any], dict[str, Any], analisis.Movimiento]:
    """Cifras del informe gerencial: el corte y su comparable. Una sola fuente para el informe
    y el tablero (coherencia obligatoria, §11.12)."""
    actual = totales_corte(db, ctx, periodo, con_movimiento=True)
    mov = _movimiento(db, ctx, periodo)
    if ctx.codigo != "afinia":
        actual.update(
            nuevos_usuarios=len(mov.nuevos),
            usuarios_reintegrados=len(mov.reintegrados),
            usuarios_dejados_facturar=len(mov.dejados_facturar),
        )
    anterior = totales_corte(db, ctx, mov.comparable) if mov.comparable else {}
    return actual, anterior, mov


def _participacion(db: Session, ctx: Contexto, periodo: str) -> list[dict[str, Any]]:
    """Participación por tarifa (Afinia) o por segmento (Celsia y Vatia), como el informe."""
    if ctx.codigo == "afinia":
        return [
            {
                "grupo": f["estrato_uso"],
                "usuarios": f["n_factura"],
                "facturacion": f["facturacion"],
                "recaudo": f["recaudo_total"],
                "consumo": f["consumo_kwh"],
            }
            for f in _td_afinia(db, ctx, periodo)["filas"]
        ]
    return [
        {
            "grupo": g["segmento"],
            "usuarios": g["usuarios"],
            "facturacion": g["facturacion"],
            "recaudo": g["recaudo"],
            "consumo": g["consumo"],
        }
        for g in analisis.agrupar(usuarios(ctx, periodo).values(), "segmento")
    ]


CLAVES_TABLERO = (
    "n_facturados",
    "facturacion",
    "recaudo_corriente",
    "recaudo_cartera",
    "recaudo",
    "cartera",
    "eficiencia",
    "n_usuarios_convenios",
    "valor_convenios_periodo",
    "nuevos_usuarios",
    "usuarios_dejados_facturar",
    "usuarios_reintegrados",
    "consumo",
)


def _a_json(valor: Any) -> Any:
    if isinstance(valor, bool) or valor is None:
        return valor
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (int, float, str)):
        return valor
    return str(valor)


def _cifras_tablero(cifras: dict[str, Any], codigo: str) -> dict[str, Any]:
    datos = dict(cifras)
    if codigo == "afinia" and "consumo" not in datos:
        datos["consumo"] = datos.get("consumo_kwh")
    return {clave: _a_json(datos.get(clave)) for clave in CLAVES_TABLERO}


def resumen_tablero(db: Session, sede_id: int) -> list[dict[str, Any]]:
    """Indicadores del informe gerencial (RF-066) del último corte publicado de cada
    comercializador de la sede, para las tablas resumen del tablero (HU-092)."""
    sede_dict = next(
        (s for s in configuracion.listar_sedes_activas_resumen(db) if s["id"] == sede_id), None
    )
    if sede_dict is None:
        return []
    sede = SedeResumen(**sede_dict)
    salida: list[dict[str, Any]] = []
    for codigo in configuracion.listar_comercializadores_activos_sede(db, sede_id):
        if codigo not in ADAPTADORES:
            continue
        ctx = contexto(db, sede, codigo)
        lista = periodos(db, ctx)
        if not lista:
            continue
        periodo = lista[-1]
        actual, anterior, mov = _cifras_gerenciales(db, ctx, periodo)
        historico = []
        for p in lista[-12:]:
            t = totales_corte(db, ctx, p)
            historico.append(
                {
                    "periodo": p,
                    "facturacion": _a_json(t["facturacion"]),
                    "recaudo": _a_json(t["recaudo"]),
                    "cartera": _a_json(t["cartera"]),
                    "n_facturados": _a_json(t["n_facturados"]),
                }
            )
        salida.append(
            {
                "comercializador": codigo,
                "nombre": NOMBRES[codigo],
                "periodo": periodo,
                "periodo_anterior": mov.comparable,
                "actual": _cifras_tablero(actual, codigo),
                "anterior": _cifras_tablero(anterior, codigo) if anterior else None,
                "participacion": [
                    {k: _a_json(v) for k, v in fila.items()}
                    for fila in _participacion(db, ctx, periodo)
                ],
                "historico": historico,
            }
        )
    return salida


def _informe_gerencial(db: Session, ctx: Contexto, periodo: str) -> entregables.Documento:
    """Informe gerencial (secciones del PDF de SAPEF): actual frente al corte anterior."""
    actual, anterior, mov = _cifras_gerenciales(db, ctx, periodo)

    def comparar(claves: list[tuple[str, str]]) -> entregables.Tabla:
        filas = []
        for clave, nombre in claves:
            a, b = actual.get(clave), anterior.get(clave)
            variacion = (
                div(Decimal(a) - Decimal(b), b, nulo=True)
                if isinstance(a, (int, Decimal))
                and isinstance(b, (int, Decimal))
                and not isinstance(a, bool)
                else None
            )
            filas.append([nombre, a, b, variacion * 100 if variacion is not None else None])
        return entregables.Tabla(
            ["Indicador", periodo, mov.comparable or "Anterior", "Variación %"], filas
        )

    recaudo_claves = [
        ("recaudo_corriente", "Recaudo corriente"),
        ("recaudo_cartera", "Recaudo de cartera"),
        ("recaudo", "Recaudo total"),
    ]
    secciones = [
        entregables.Seccion(
            "Resumen del mes",
            [
                f"Usuarios facturados: {entregables.formato(actual['n_facturados'])}. Facturado: "
                f"${entregables.formato(actual['facturacion'])}. Recaudo total: "
                f"${entregables.formato(actual['recaudo'])}. Cartera: "
                f"${entregables.formato(actual['cartera'])}.",
            ],
            comparar(
                [
                    ("n_facturados", "Usuarios facturados"),
                    ("facturacion", "Facturado"),
                    ("recaudo", "Recaudo total"),
                    ("cartera", "Cartera"),
                ]
            ),
        ),
        entregables.Seccion("Usuarios facturados", [], comparar([("n_facturados", "Usuarios")])),
        entregables.Seccion("Valor facturado", [], comparar([("facturacion", "Facturado")])),
        entregables.Seccion("Recaudo", [], comparar(recaudo_claves)),
        entregables.Seccion(
            "Convenios de pago",
            [],
            comparar(
                [
                    ("n_usuarios_convenios", "Usuarios en convenio"),
                    ("valor_convenios_periodo", "Valor de convenios"),
                ]
            ),
        ),
        entregables.Seccion(
            "Movimiento de usuarios",
            [],
            comparar(
                [
                    ("nuevos_usuarios", "Nuevos"),
                    ("usuarios_dejados_facturar", "Dejaron de facturar"),
                    ("usuarios_reintegrados", "Reintegrados"),
                ]
            ),
        ),
        entregables.Seccion(
            "Consumo de energía",
            [],
            comparar([("consumo_kwh" if ctx.codigo == "afinia" else "consumo", "Consumo kWh")]),
        ),
    ]
    if ctx.codigo == "afinia":
        filas = _td_afinia(db, ctx, periodo)["filas"]
        for titulo, campo in (
            ("Consumo por tarifa", "consumo_kwh"),
            ("Facturación por tarifa", "facturacion"),
            ("Recaudo por tarifa", "recaudo_total"),
        ):
            secciones.append(
                entregables.Seccion(
                    titulo,
                    [],
                    entregables.Tabla(
                        ["Tarifa", "Usuarios", titulo.split(" por ")[0]],
                        [[f["estrato_uso"], f["n_factura"], f[campo]] for f in filas],
                    ),
                )
            )
    else:
        grupos = analisis.agrupar(usuarios(ctx, periodo).values(), "segmento")
        for titulo, campo in (
            ("Consumo por segmento", "consumo"),
            ("Facturación por segmento", "facturacion"),
            ("Recaudo por segmento", "recaudo"),
        ):
            secciones.append(
                entregables.Seccion(
                    titulo,
                    [],
                    entregables.Tabla(
                        ["Segmento", "Usuarios", titulo.split(" por ")[0]],
                        [[g["segmento"], g["usuarios"], g[campo]] for g in grupos],
                    ),
                )
            )
    return entregables.Documento(
        f"Informe gerencial · {NOMBRES[ctx.codigo]}", _subtitulo(ctx, periodo), secciones
    )


def _limite_anexo(db: Session, ctx: Contexto, max_filas: int | None) -> int:
    if max_filas is not None:
        return max_filas
    valor = configuracion.obtener_valor_parametro(db, "comercial_anexo_max_filas", ctx.sede.id)
    try:
        return int(valor) if valor is not None else 50000
    except (TypeError, ValueError):
        return 50000


def _anexo_nominal(
    db: Session, actor: UsuarioAutenticado, ctx: Contexto, periodo: str, max_filas: int | None
) -> bytes:
    """Listado nominal que sustenta el oficio. Si una hoja pasa del tope, la descarga se detiene
    (409): un anexo recortado no concilia con las cifras del oficio."""
    hojas: dict[str, entregables.Tabla] = {}
    datos = usuarios(ctx, periodo)

    def ficha(k: str) -> list[Any]:
        u = datos.get(k)
        return [u.nombre if u else None, u.direccion if u else None, u.barrio if u else None]

    if _control_disponible(ctx):
        filas, _ = filas_control(db, ctx, periodo)
        # Hoja completa: sustenta los conteos por estado del oficio (incluidos los correctos).
        hojas["Control tarifario"] = entregables.Tabla(
            [
                "Usuario",
                "Nombre",
                "Dirección",
                "Barrio",
                "Tarifa",
                "Regla",
                "Estado",
                "Motivo",
                "Consumo kWh",
                "Facturado",
                "Esperado",
                "Diferencia",
                "Por encima",
                "Por debajo",
                "Señal CI401",
                "Señal CI851",
            ],
            [
                [
                    f.identificador,
                    *ficha(f.identificador),
                    f.tarifa,
                    f.regla_aplicada,
                    f.estado,
                    f.motivo_revision,
                    f.consumo_kwh,
                    f.facturado_real,
                    f.esperado,
                    f.diferencia,
                    f.valor_por_encima,
                    f.valor_por_debajo,
                    f.senal_ci401,
                    f.senal_ci851,
                ]
                for f in filas
            ],
        )
        hojas["Cobros por encima"] = entregables.Tabla(
            [
                "Usuario",
                "Nombre",
                "Dirección",
                "Barrio",
                "Tarifa",
                "Regla",
                "Facturado",
                "Esperado",
                "Por encima",
            ],
            [
                [
                    f.identificador,
                    *ficha(f.identificador),
                    f.tarifa,
                    f.regla_aplicada,
                    f.facturado_real,
                    f.esperado,
                    f.valor_por_encima,
                ]
                for f in filas
                if f.estado == "POR_ENCIMA"
            ],
        )
        hojas["Cobros por debajo"] = entregables.Tabla(
            [
                "Usuario",
                "Nombre",
                "Dirección",
                "Barrio",
                "Tarifa",
                "Regla",
                "Facturado",
                "Esperado",
                "Por debajo",
            ],
            [
                [
                    f.identificador,
                    *ficha(f.identificador),
                    f.tarifa,
                    f.regla_aplicada,
                    f.facturado_real,
                    f.esperado,
                    f.valor_por_debajo,
                ]
                for f in filas
                if f.estado == "POR_DEBAJO"
            ],
        )
        hojas["Requieren revisión"] = entregables.Tabla(
            ["Usuario", "Tarifa", "Estado", "Motivo", "Facturado"],
            [
                [f.identificador, f.tarifa, f.estado, f.motivo_revision, f.facturado_real]
                for f in filas
                if f.estado in ("REQUIERE_REVISION", "NO_VALIDABLE")
            ],
        )
    mov = _movimiento(db, ctx, periodo)
    hojas["Dejaron de facturar"] = entregables.Tabla(
        ["Usuario", "Nombre", "Dirección", "Barrio"], [[k, *ficha(k)] for k in mov.dejados_facturar]
    )
    hojas["Ausentes"] = entregables.Tabla(
        ["Usuario", "Último periodo", "Periodos ausente", "Tramo"],
        [[k, mov.ultimo_periodo[k], n, analisis.tramo(n)] for k, n in sorted(mov.ausentes.items())],
    )
    limite = _limite_anexo(db, ctx, max_filas)
    excedidas = {n: len(t.filas) for n, t in hojas.items() if len(t.filas) > limite}
    if excedidas:
        detalle = ", ".join(f"{n} ({c} filas)" for n, c in excedidas.items())
        raise HTTPException(
            status_code=409,
            detail=f"El anexo supera el tope de {limite} filas por hoja en: {detalle}. Se detiene "
            "la descarga para no entregar un anexo recortado; ajuste el parámetro "
            "comercial_anexo_max_filas.",
        )
    auditar_consulta(db, actor, ctx, "anexo_nominal", periodo=periodo)
    return entregables.a_xlsx(hojas)


# === Exportaciones ===============================================================================

MAX_IDS_BYTES = 1024 * 1024
MAX_IDS = 50_000


def exportar_cartera(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, codigo: str, periodo: str
) -> bytes:
    """Celsia: ZIP con el resumen y el detalle de la cartera por cuenta."""
    import io
    import zipfile

    ctx = _ctx_corte(db, sede, codigo, periodo, "cartera")
    if ctx.codigo != "celsia":
        raise HTTPException(status_code=404, detail="Exportación disponible solo para Celsia.")
    cartera = familia(ctx, periodo, "cartera")
    resumen = celsia.cartera_por_edades(cartera)
    campos = [
        "cuenta",
        "nombre",
        "direccion",
        "segmento",
        "estrato",
        "grupo_cartera",
        *celsia_ingesta.EDADES,
        "cartera_total",
    ]
    libro_resumen = entregables.a_xlsx(
        {
            "Resumen": entregables.Tabla(
                ["Edad", "Usuarios", "Valor", "%"],
                [[b["edad"], b["usuarios"], b["valor"], b["pct"]] for b in resumen["bandas"]],
            )
        }
    )
    libro_detalle = entregables.a_xlsx(
        {
            "Detalle por cuenta": entregables.Tabla(
                campos, [[f.get(c) for c in campos] for f in cartera]
            )
        }
    )
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as zipf:
        zipf.writestr(f"cartera_resumen_{periodo}.xlsx", libro_resumen)
        zipf.writestr(f"cartera_detalle_{periodo}.xlsx", libro_detalle)
    auditar_consulta(db, actor, ctx, "exportar_cartera", periodo=periodo)
    return salida.getvalue()


async def promedios_por_ids(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, codigo: str, archivo: UploadFile
) -> bytes:
    """Promedios de consumo y facturación por lista de IDs (.txt UTF-8, un ID por línea,
    hasta 1 MiB y 50.000 IDs)."""
    ctx = contexto(db, sede, codigo)
    contenido = await archivo.read(MAX_IDS_BYTES + 1)
    if len(contenido) > MAX_IDS_BYTES:
        raise HTTPException(status_code=413, detail="La lista de IDs supera 1 MiB.")
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="La lista debe estar en UTF-8.") from exc
    ids = list(dict.fromkeys(linea.strip() for linea in texto.splitlines() if linea.strip()))
    if len(ids) > MAX_IDS:
        raise HTTPException(
            status_code=422, detail=f"La lista tiene {len(ids)} IDs; el máximo es {MAX_IDS}."
        )
    if not ids:
        raise HTTPException(status_code=422, detail="La lista de IDs está vacía.")
    lista = periodos(db, ctx)
    filas = []
    for clave in ids:
        presentes = [
            usuarios(ctx, p)[clave]
            for p in lista
            if clave in usuarios(ctx, p) and usuarios(ctx, p)[clave].facturado_presente
        ]
        consumos = [u.consumo for u in presentes if u.consumo is not None]
        filas.append(
            [
                clave,
                len(presentes),
                div(suma(consumos), len(consumos), nulo=True),
                div(suma(u.facturado for u in presentes), len(presentes), nulo=True),
                presentes[-1].nombre if presentes else None,
            ]
        )
    auditar_consulta(db, actor, ctx, "promedios_ids", cantidad=len(ids))
    return entregables.a_xlsx(
        {
            "Promedios": entregables.Tabla(
                ["ID", "Cortes con factura", "Consumo promedio", "Facturado promedio", "Nombre"],
                filas,
            )
        }
    )


async def encolar_sabana(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    codigo: str,
    periodo: str,
    familia_nombre: str,
    formato: str,
) -> int:
    ctx = contexto(db, sede, codigo)
    exigir_corte(db, ctx, periodo)
    if familia_nombre not in ctx.adaptador.familias:
        raise HTTPException(status_code=422, detail="Familia desconocida para la sábana.")
    auditar_consulta(db, actor, ctx, "sabana", periodo=periodo, familia=familia_nombre)
    return await encolar(
        TAREA_SABANA,
        sede_id=sede.id,
        comercializador=ctx.codigo,
        periodo=periodo,
        familia=familia_nombre,
        formato=formato,
        usuario_id=actor.id,
    )


def procesar_sabana(
    db: Session,
    *,
    sede_id: int,
    comercializador: str,
    periodo: str,
    familia: str,
    formato: str,
    usuario_id: int,
) -> str:
    """Tarea del worker: la sábana completa de una familia (CSV o Excel) al almacén de archivos;
    devuelve el id del archivo para descargarlo por /archivos."""
    import csv
    import io

    from app.modulos.archivos import servicio as archivos

    sede = next(s for s in configuracion.listar_sedes_activas_resumen(db) if s["id"] == sede_id)
    ruta = almacen.ruta_corte(sede["codigo"], comercializador, periodo)
    filas = almacen.leer_familia(ruta, familia)
    columnas = list(ADAPTADORES[comercializador].ingesta.esquema(familia))
    nombre = f"sabana_{comercializador}_{familia}_{periodo}"
    if formato == "csv":
        texto = io.StringIO()
        escritor = csv.writer(texto)
        escritor.writerow(columnas)
        for fila in filas:
            escritor.writerow(["" if fila.get(c) is None else fila.get(c) for c in columnas])
        contenido, nombre = texto.getvalue().encode("utf-8-sig"), f"{nombre}.csv"
    else:
        contenido = entregables.a_xlsx(
            {familia: entregables.Tabla(columnas, [[f.get(c) for c in columnas] for f in filas])}
        )
        nombre = f"{nombre}.xlsx"
    meta, _ = archivos.guardar_archivo(
        db,
        sede_id=sede_id,
        archivo_bytes=contenido,
        nombre=nombre,
        categoria="cargue",
        subido_por_id=usuario_id,
    )
    return str(meta.id)


# === Importación del almacén de OPainn (HU-080) ==================================================


def resolver_ruta_importacion(ruta: str) -> Path:
    """Solo se lee dentro del directorio de importación configurado (nunca rutas arbitrarias)."""
    config = obtener_configuracion()
    base = config.comercial_importacion_dir.resolve()
    alias = (config.comercial_importacion_alias or "").replace("\\", "/").rstrip("/")
    normalizada = ruta.replace("\\", "/")
    if alias and normalizada.lower().startswith(alias.lower() + "/"):
        ruta = str(base / normalizada[len(alias) + 1 :])
    candidata = Path(ruta)
    candidata = (candidata if candidata.is_absolute() else base / candidata).resolve()
    if candidata != base and base not in candidata.parents:
        raise HTTPException(
            status_code=422,
            detail="La ruta debe estar dentro del directorio de importación del servidor "
            "(SAPEF_COMERCIAL_IMPORTACION_DIR).",
        )
    if not candidata.is_dir():
        raise HTTPException(status_code=422, detail="La ruta de importación no existe.")
    return candidata


async def importar_opainn(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    ruta: str,
    codigo: str,
    lista: list[str],
) -> dict[str, Any]:
    ctx = contexto(db, sede, codigo)
    carpeta = resolver_ruta_importacion(ruta)

    # Un periodo es una carpeta con manifest.json o, en los cortes viejos de OPainn que no lo
    # tienen, con algún Parquet de una familia conocida.
    def es_paquete(p: Path) -> bool:
        return (p / "manifest.json").is_file() or any(
            (p / f"{f}.parquet").is_file() for f in ctx.adaptador.esquemas()
        )

    candidatas = (
        [carpeta]
        if es_paquete(carpeta)
        else sorted(p for p in carpeta.iterdir() if p.is_dir() and es_paquete(p))
    )
    por_periodo = {p.name: p for p in candidatas} if carpeta not in candidatas else {}
    if carpeta in candidatas:
        manifiesto = almacen.leer_manifiesto(carpeta) or {}
        por_periodo = {str(manifiesto.get("periodo") or carpeta.name): carpeta}
    elegidos = [p for p in (lista or sorted(por_periodo)) if p in por_periodo]
    if not elegidos:
        raise HTTPException(status_code=422, detail="No hay paquetes de OPainn para esos periodos.")
    tareas = []
    for periodo in elegidos:
        dominio_o_http(lambda p=periodo: validar_periodo(p))
        errores = await run_in_threadpool(
            almacen.verificar_paquete, por_periodo[periodo], ctx.adaptador.esquemas()
        )
        if errores:
            raise HTTPException(
                status_code=422,
                detail=f"Paquete de OPainn {periodo} rechazado: {' '.join(errores)}",
            )
        tareas.append(
            await encolar(
                TAREA_IMPORTAR,
                sede_id=sede.id,
                comercializador=ctx.codigo,
                periodo=periodo,
                ruta=str(por_periodo[periodo]),
                usuario_id=actor.id,
            )
        )
    return {
        "estado": "encolada",
        "comercializador": ctx.codigo,
        "periodos": elegidos,
        "tareas": tareas,
        "tarea_id": tareas[0],
        "tareaId": tareas[0],
    }


def procesar_importacion_opainn(
    db: Session, *, sede_id: int, comercializador: str, periodo: str, ruta: str, usuario_id: int
) -> str:
    """Valida los SHA-256 del manifiesto y el esquema de cada Parquet; publica como un cargue
    con origen «opainn». Si algo no cuadra, no se publica nada."""
    sede = next(s for s in configuracion.listar_sedes_activas_resumen(db) if s["id"] == sede_id)
    ids = {c.codigo: c.id for c in configuracion.listar_comercializadores(db)}
    adaptador = ADAPTADORES[comercializador]
    ctx = Contexto(
        SedeResumen(id=sede["id"], codigo=sede["codigo"], nombre=sede["nombre"]),
        comercializador,
        ids[comercializador],
        adaptador,
    )
    carpeta = resolver_ruta_importacion(ruta)
    paquete, errores = almacen.leer_paquete(carpeta, adaptador.esquemas())
    cargue = CargueComercial(
        sede_id=sede_id,
        comercializador_id=ctx.comercializador_id,
        periodo=periodo,
        estado="validando",
        huella=hashlib.sha256(f"opainn|{ruta}|{periodo}".encode()).hexdigest(),
        archivos=[{"nombre": f, "familia": f} for f in paquete],
        origen="opainn",
        creado_por=usuario_id,
        version_adaptador="opainn",
    )
    repositorio.agregar(db, cargue)
    db.commit()
    if errores:
        return _terminar(db, cargue, "con_errores", errores=errores)
    principal = adaptador.principal
    if not paquete.get(principal):
        return _terminar(
            db, cargue, "no_publicable", errores=[f"El paquete no trae la familia {principal}."]
        )
    cargue.familias = {f: len(v) for f, v in paquete.items()}
    cargue.completo = all(f in paquete for f in adaptador.familias)
    cargue.publicable = True
    aviso = almacen.aviso_manifiesto(carpeta)
    avisos = [aviso] if aviso else []
    cargue.advertencias = avisos
    manifiesto = {
        "sede_codigo": ctx.sede.codigo,
        "comercializador_codigo": comercializador,
        "periodo": periodo,
        "cargue_id": cargue.id,
        "version_adaptador": "opainn",
        "fecha_publicacion_iso": datetime.now(UTC).isoformat(),
        "usuario_id": usuario_id,
        "completo": cargue.completo,
        "publicable": True,
        "presentes": sorted(paquete),
        "origen": "opainn",
        "advertencias": avisos,
    }
    for filas in paquete.values():
        for fila in filas:
            fila["periodo"] = fila.get("periodo") or periodo
    if comercializador == "afinia":
        # Columnas derivadas que el almacén de OPainn puede no traer.
        for fila in paquete.get("recaudo", []):
            fila["tipo_recaudo"] = fila.get("tipo_recaudo") or afinia.tipo_recaudo(fila, periodo)
        for fila in paquete.get("catastro", []):
            if not fila.get("tarifa") and fila.get("desc_tar"):
                fila["tarifa"] = str(fila["desc_tar"]).replace(" ", "_")
    return publicar(db, ctx, cargue, paquete, manifiesto)
