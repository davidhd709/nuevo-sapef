"""Servicio público del módulo de atención (EP-04).

Para trabajos: `pqrs_para_orden`, `avanzar_por_orden`, `registrar_reparacion` (sin commit, en
la transacción del cierre de la orden) y `encolar_notificacion` (después del commit).
"""

import io
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.correo import enviar_correo
from app.core.paginacion import Pagina, TareaEncolada
from app.core.tareas import encolar
from app.modulos.activos import servicio as activos
from app.modulos.archivos import servicio as archivos
from app.modulos.atencion import dominio, repositorio
from app.modulos.atencion.esquemas import (
    CiudadanoCrearEntrada,
    CiudadanoEditarEntrada,
    CiudadanoSalida,
    PendienteSalida,
    PqrsAnularEntrada,
    PqrsCrearEntrada,
    PqrsEditarEntrada,
    PqrsExportarEntrada,
    PqrsLuminariaEntrada,
    PqrsLuminariaSalida,
    PqrsSalida,
)
from app.modulos.atencion.modelos import Ciudadano, Pqrs, PqrsLuminaria
from app.modulos.configuracion import servicio as configuracion
from app.modulos.seguridad import servicio as seguridad
from app.modulos.seguridad.servicio import SedeResumen, UsuarioAutenticado

PERMISO_DATOS_PERSONALES = "atencion.datos_personales.ver"
PLANTILLA_REGISTRO = "MAIL_PQRS"
PLANTILLA_ATENCION = "MAIL.MANTENIMIENTO_LUMINARIA"


def _http(exc: dominio.ErrorDominioAtencion) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _ve_datos_personales(actor: UsuarioAutenticado) -> bool:
    return PERMISO_DATOS_PERSONALES in actor.permisos


class _Catalogos:
    """Estados y canales cargados una vez por petición."""

    def __init__(self, db: Session) -> None:
        self.estados_pqrs = {e.codigo: e for e in configuracion.listar_estados(db, "pqrs")}
        self.estado_por_id = {e.id: e for e in self.estados_pqrs.values()}
        self.estados_luminaria = {
            e.id: e.codigo for e in configuracion.listar_estados(db, "luminaria")
        }
        self.canales = {v.id: v for v in configuracion.listar_valores(db, "CANAL_PQRS")}

    def id_estado(self, codigo: str) -> int:
        try:
            return self.estados_pqrs[codigo].id
        except KeyError as exc:
            raise HTTPException(status_code=500, detail="Faltan los estados de PQRS.") from exc

    def codigo(self, estado_id: int) -> str:
        return self.estado_por_id[estado_id].codigo

    def ids_abiertos(self) -> list[int]:
        return [self.estados_pqrs[c].id for c in dominio.ABIERTOS if c in self.estados_pqrs]


# === Ciudadanos =================================================================================


def _a_ciudadano(c: Ciudadano, ve_datos: bool) -> CiudadanoSalida:
    datos = {
        "id": c.id,
        "identificacion": c.identificacion,
        "nombre_completo": c.nombre_completo,
        "barrio_id": c.barrio_id,
        "sector": c.sector,
        "telefono": c.telefono,
        "celular": c.celular,
        "correo": c.correo,
    }
    return CiudadanoSalida(**(datos if ve_datos else dominio.enmascarar_ciudadano(datos)))


def buscar_ciudadanos(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    buscar: str | None,
    *,
    page: int,
    size: int,
) -> Pagina[CiudadanoSalida]:
    filas, total = repositorio.buscar_ciudadanos(db, sede.id, buscar, page=page, size=size)
    ve = _ve_datos_personales(actor)
    if ve and filas:
        # Consulta nominal: queda quién consultó y cuántos resultados vio (no el término buscado).
        seguridad.registrar_auditoria_consulta(
            db,
            usuario_id=actor.id,
            sede_id=sede.id,
            recurso="ciudadano.buscar",
            parametros_permitidos={"resultados": len(filas), "page": page},
        )
        db.commit()
    return Pagina[CiudadanoSalida](
        items=[_a_ciudadano(c, ve) for c in filas], total=total, page=page, size=size
    )


def _validar_barrio(db: Session, sede_id: int, barrio_id: int | None) -> None:
    if barrio_id is not None and configuracion.resolver_barrio_sede(db, sede_id, barrio_id) is None:
        raise HTTPException(status_code=404, detail="El barrio no pertenece a la sede activa.")


def crear_ciudadano(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, entrada: CiudadanoCrearEntrada
) -> CiudadanoSalida:
    identificacion = entrada.identificacion.strip()
    if repositorio.existe_identificacion(db, sede.id, identificacion):
        raise HTTPException(
            status_code=409, detail="Ya existe un ciudadano con esa identificación en la sede."
        )
    _validar_barrio(db, sede.id, entrada.barrio_id)
    ciudadano = Ciudadano(
        sede_id=sede.id,
        identificacion=identificacion,
        nombre_completo=" ".join(entrada.nombre_completo.split()),
        barrio_id=entrada.barrio_id,
        sector=entrada.sector,
        telefono=entrada.telefono,
        celular=entrada.celular,
        correo=entrada.correo.strip().lower() if entrada.correo else None,
        creado_por=actor.id,
        modificado_por=actor.id,
    )
    db.add(ciudadano)
    db.flush()
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="crear",
        entidad="ciudadano",
        entidad_id=str(ciudadano.id),
        despues={"id": ciudadano.id},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Ya existe un ciudadano con esa identificación en la sede."
        ) from exc
    return _a_ciudadano(ciudadano, _ve_datos_personales(actor))


def obtener_ciudadano(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, ciudadano_id: int
) -> CiudadanoSalida:
    ciudadano = repositorio.obtener_ciudadano(db, sede.id, ciudadano_id)
    if ciudadano is None:
        raise HTTPException(status_code=404, detail="Ciudadano no encontrado.")
    ve = _ve_datos_personales(actor)
    if ve:
        seguridad.registrar_auditoria_consulta(
            db,
            usuario_id=actor.id,
            sede_id=sede.id,
            recurso="ciudadano.detalle",
            parametros_permitidos={"ciudadano_id": ciudadano.id},
        )
        db.commit()
    return _a_ciudadano(ciudadano, ve)


def editar_ciudadano(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    ciudadano_id: int,
    entrada: CiudadanoEditarEntrada,
) -> CiudadanoSalida:
    ciudadano = repositorio.obtener_ciudadano(db, sede.id, ciudadano_id)
    if ciudadano is None:
        raise HTTPException(status_code=404, detail="Ciudadano no encontrado.")
    cambios = entrada.model_dump(exclude_unset=True)
    _validar_barrio(db, sede.id, cambios.get("barrio_id"))
    for campo, valor in cambios.items():
        if campo == "nombre_completo" and valor is None:
            continue
        if campo == "correo" and valor:
            valor = valor.strip().lower()
        setattr(ciudadano, campo, valor)
    ciudadano.modificado_por = actor.id
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="editar",
        entidad="ciudadano",
        entidad_id=str(ciudadano.id),
        despues={"campos": sorted(cambios)},
    )
    db.commit()
    return _a_ciudadano(ciudadano, _ve_datos_personales(actor))


# === PQRS =======================================================================================


def _a_pqrs(
    db: Session, p: Pqrs, cat: _Catalogos, ve_datos: bool, ciudadano: Ciudadano | None
) -> PqrsSalida:
    codigos = activos.codigos_luminarias(db, [pl.luminaria_id for pl in p.luminarias])
    estado = cat.estado_por_id[p.estado_id]
    canal = cat.canales.get(p.canal_id)
    return PqrsSalida(
        id=p.id,
        sede_id=p.sede_id,
        numero=p.numero,
        canal_id=p.canal_id,
        canal_nombre=canal.nombre if canal else None,
        fecha_solicitud=p.fecha_solicitud,
        ciudadano=_a_ciudadano(ciudadano, ve_datos) if ciudadano else None,
        observacion_solicitante=p.observacion_solicitante,
        observacion_interna=p.observacion_interna,
        prioridad=p.prioridad,
        prioridad_nombre=dominio.PRIORIDADES[p.prioridad],
        estado_id=p.estado_id,
        estado_codigo=estado.codigo,
        estado_nombre=estado.nombre,
        calidad_servicio=p.calidad_servicio,
        fecha_cierre=p.fecha_cierre,
        notificar_cliente=p.notificar_cliente,
        motivo_anulacion=p.motivo_anulacion,
        luminarias=[
            PqrsLuminariaSalida(
                id=pl.id,
                luminaria_id=pl.luminaria_id,
                luminaria_codigo=codigos.get(pl.luminaria_id, ("?", False))[0],
                es_comodin=codigos.get(pl.luminaria_id, ("?", False))[1],
                estado_reportado_codigo=cat.estados_luminaria.get(pl.estado_reportado_id or -1),
                observacion_solicitante=pl.observacion_solicitante,
                observacion_tecnico=pl.observacion_tecnico,
                reparada=pl.reparada,
                fecha_reparacion=pl.fecha_reparacion,
                orden_id=pl.orden_id,
            )
            for pl in p.luminarias
        ],
        total_luminarias=len(p.luminarias),
        reparadas=sum(1 for pl in p.luminarias if pl.reparada),
        creado_en=p.creado_en,
    )


def _obtener_pqrs(db: Session, sede_id: int, pqrs_id: int, *, bloquear: bool = False) -> Pqrs:
    pqrs = repositorio.obtener_pqrs(db, sede_id, pqrs_id, bloquear=bloquear)
    if pqrs is None:
        raise HTTPException(status_code=404, detail="PQRS no encontrada.")
    return pqrs


def _reportar_luminaria(
    db: Session,
    *,
    sede_id: int,
    pqrs: Pqrs,
    entrada: PqrsLuminariaEntrada,
    actor_id: int,
) -> PqrsLuminaria:
    """Agrega la luminaria a la PQRS y la pasa a «Activo PQR» (RN-011); la comodín queda en 110."""
    resumen = activos.resumen_luminarias(db, sede_id, [entrada.luminaria_id]).get(
        entrada.luminaria_id
    )
    if resumen is None:
        # Una luminaria de otra sede responde igual que una inexistente.
        raise HTTPException(
            status_code=422, detail=f"La luminaria {entrada.luminaria_id} no existe en la sede."
        )
    try:
        dominio.validar_luminaria_reportable(resumen["codigo"], resumen["estado_codigo"])
    except dominio.ErrorDominioAtencion as exc:
        raise _http(exc) from exc
    if any(pl.luminaria_id == entrada.luminaria_id for pl in pqrs.luminarias):
        raise HTTPException(status_code=409, detail="La luminaria ya está en esta PQRS.")

    detalle = {
        "pqrs_numero": pqrs.numero,
        "observacion_solicitante": entrada.observacion_solicitante,
    }
    if resumen["estado_codigo"] == dominio.LUMINARIA_EN_OPERACION:
        activos.cambiar_estado_luminaria(
            db,
            sede_id=sede_id,
            luminaria_id=entrada.luminaria_id,
            estado_codigo=dominio.LUMINARIA_ACTIVO_PQR,
            tipo_evento="pqrs",
            actor_id=actor_id,
            origenes_permitidos=(dominio.LUMINARIA_EN_OPERACION,),
            pqrs_id=pqrs.id,
            detalle=detalle,
        )
    else:
        activos.registrar_evento_luminaria(
            db,
            sede_id=sede_id,
            luminaria_id=entrada.luminaria_id,
            tipo="pqrs",
            actor_id=actor_id,
            pqrs_id=pqrs.id,
            detalle=detalle,
        )
    fila = PqrsLuminaria(
        luminaria_id=entrada.luminaria_id,
        estado_reportado_id=resumen["estado_id"],
        observacion_solicitante=entrada.observacion_solicitante,
    )
    pqrs.luminarias.append(fila)
    db.flush()
    return fila


def _liberar_luminaria(
    db: Session,
    cat: _Catalogos,
    *,
    sede_id: int,
    pqrs: Pqrs,
    fila: PqrsLuminaria,
    actor_id: int,
    motivo: str,
) -> None:
    """Si nadie más la reporta, la luminaria vuelve de «Activo PQR» a «Activo en operación»."""
    otras = repositorio.otras_pqrs_abiertas_con_luminaria(
        db, fila.luminaria_id, pqrs.id, cat.ids_abiertos()
    )
    resumen = activos.resumen_luminarias(db, sede_id, [fila.luminaria_id]).get(fila.luminaria_id)
    if otras == 0 and resumen and resumen["estado_codigo"] == dominio.LUMINARIA_ACTIVO_PQR:
        activos.cambiar_estado_luminaria(
            db,
            sede_id=sede_id,
            luminaria_id=fila.luminaria_id,
            estado_codigo=dominio.LUMINARIA_EN_OPERACION,
            tipo_evento=motivo,
            actor_id=actor_id,
            pqrs_id=pqrs.id,
            detalle={"pqrs_numero": pqrs.numero},
        )


def _crear_pqrs(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, entrada: PqrsCrearEntrada
) -> PqrsSalida:
    cat = _Catalogos(db)
    if entrada.canal_id not in cat.canales:
        raise HTTPException(status_code=422, detail="El canal no es un canal de PQRS válido.")
    ids = [lum.luminaria_id for lum in entrada.luminarias]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Hay luminarias repetidas en la PQRS.")
    ciudadano = None
    if entrada.ciudadano_id is not None:
        ciudadano = repositorio.obtener_ciudadano(db, sede.id, entrada.ciudadano_id)
        if ciudadano is None:
            raise HTTPException(status_code=422, detail="El solicitante no existe en la sede.")

    pqrs = Pqrs(
        sede_id=sede.id,
        numero=repositorio.siguiente_numero(db, sede.id),
        canal_id=entrada.canal_id,
        ciudadano_id=entrada.ciudadano_id,
        observacion_solicitante=entrada.observacion_solicitante,
        observacion_interna=entrada.observacion_interna,
        prioridad=entrada.prioridad,
        estado_id=cat.id_estado(dominio.EN_ELABORACION),
        notificar_cliente=entrada.notificar_cliente,
        creado_por=actor.id,
        modificado_por=actor.id,
    )
    if entrada.fecha_solicitud is not None:
        pqrs.fecha_solicitud = entrada.fecha_solicitud
    db.add(pqrs)
    db.flush()
    for lum in entrada.luminarias:
        _reportar_luminaria(db, sede_id=sede.id, pqrs=pqrs, entrada=lum, actor_id=actor.id)
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="crear",
        entidad="pqrs",
        entidad_id=str(pqrs.id),
        despues={"numero": pqrs.numero, "luminarias": ids, "prioridad": pqrs.prioridad},
    )
    db.commit()
    db.refresh(pqrs)
    return _a_pqrs(db, pqrs, cat, _ve_datos_personales(actor), ciudadano)


async def crear_pqrs(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, entrada: PqrsCrearEntrada
) -> PqrsSalida:
    salida = await run_in_threadpool(_crear_pqrs, db, actor, sede, entrada)
    if salida.notificar_cliente and salida.ciudadano is not None:
        await encolar_notificacion(salida.id, "registro")
    return salida


def listar_pqrs(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    *,
    page: int,
    size: int,
    desde: date | None = None,
    hasta: date | None = None,
    estado_id: int | None = None,
    prioridad: int | None = None,
    barrio_id: int | None = None,
    numero: int | None = None,
    ciudadano_id: int | None = None,
) -> Pagina[PqrsSalida]:
    # Por defecto, el último mes (RF-041). Los días son de la hora de Colombia.
    hoy = datetime.now(dominio.HORA_COLOMBIA).date()
    inicio = datetime.combine(desde or (hoy - timedelta(days=30)), time.min, dominio.HORA_COLOMBIA)
    fin = datetime.combine(hasta, time.max, dominio.HORA_COLOMBIA) if hasta else None
    filas, total = repositorio.listar_pqrs(
        db,
        sede.id,
        page=page,
        size=size,
        desde=inicio,
        hasta=fin,
        estado_id=estado_id,
        prioridad=prioridad,
        barrio_id=barrio_id,
        numero=numero,
        ciudadano_id=ciudadano_id,
    )
    cat = _Catalogos(db)
    ve = _ve_datos_personales(actor)
    ciudadanos = repositorio.ciudadanos_por_ids(
        db, [p.ciudadano_id for p in filas if p.ciudadano_id]
    )
    return Pagina[PqrsSalida](
        items=[_a_pqrs(db, p, cat, ve, ciudadanos.get(p.ciudadano_id or -1)) for p in filas],
        total=total,
        page=page,
        size=size,
    )


def obtener_pqrs(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, pqrs_id: int
) -> PqrsSalida:
    pqrs = _obtener_pqrs(db, sede.id, pqrs_id)
    ciudadano = (
        repositorio.obtener_ciudadano(db, sede.id, pqrs.ciudadano_id) if pqrs.ciudadano_id else None
    )
    ve = _ve_datos_personales(actor)
    if ve and ciudadano is not None:
        seguridad.registrar_auditoria_consulta(
            db,
            usuario_id=actor.id,
            sede_id=sede.id,
            recurso="pqrs.detalle",
            parametros_permitidos={"pqrs_id": pqrs.id},
        )
        db.commit()
    return _a_pqrs(db, pqrs, _Catalogos(db), ve, ciudadano)


def editar_pqrs(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    pqrs_id: int,
    entrada: PqrsEditarEntrada,
) -> PqrsSalida:
    cat = _Catalogos(db)
    pqrs = _obtener_pqrs(db, sede.id, pqrs_id, bloquear=True)
    try:
        dominio.validar_abierta(cat.codigo(pqrs.estado_id))
    except dominio.ErrorDominioAtencion as exc:
        raise _http(exc) from exc
    cambios = {k: v for k, v in entrada.model_dump(exclude_unset=True).items() if v is not None}
    if "canal_id" in cambios and cambios["canal_id"] not in cat.canales:
        raise HTTPException(status_code=422, detail="El canal no es un canal de PQRS válido.")
    if (
        "ciudadano_id" in cambios
        and repositorio.obtener_ciudadano(db, sede.id, cambios["ciudadano_id"]) is None
    ):
        raise HTTPException(status_code=422, detail="El solicitante no existe en la sede.")
    for campo, valor in cambios.items():
        setattr(pqrs, campo, valor)
    pqrs.modificado_por = actor.id
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="editar",
        entidad="pqrs",
        entidad_id=str(pqrs.id),
        despues={"campos": sorted(cambios)},
    )
    db.commit()
    return obtener_pqrs(db, actor, sede, pqrs.id)


def anular_pqrs(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    pqrs_id: int,
    entrada: PqrsAnularEntrada,
) -> PqrsSalida:
    cat = _Catalogos(db)
    pqrs = _obtener_pqrs(db, sede.id, pqrs_id, bloquear=True)
    try:
        dominio.validar_abierta(cat.codigo(pqrs.estado_id))
    except dominio.ErrorDominioAtencion as exc:
        raise _http(exc) from exc
    pqrs.estado_id = cat.id_estado(dominio.ANULADA)
    pqrs.motivo_anulacion = entrada.motivo.strip()
    pqrs.fecha_cierre = datetime.now(UTC)
    pqrs.modificado_por = actor.id
    db.flush()
    for fila in pqrs.luminarias:
        if not fila.reparada:
            _liberar_luminaria(
                db,
                cat,
                sede_id=sede.id,
                pqrs=pqrs,
                fila=fila,
                actor_id=actor.id,
                motivo="pqrs_anulada",
            )
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="anular",
        entidad="pqrs",
        entidad_id=str(pqrs.id),
        despues={"estado": dominio.ANULADA},
    )
    db.commit()
    return obtener_pqrs(db, actor, sede, pqrs.id)


def agregar_luminaria(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    pqrs_id: int,
    entrada: PqrsLuminariaEntrada,
) -> PqrsSalida:
    cat = _Catalogos(db)
    pqrs = _obtener_pqrs(db, sede.id, pqrs_id, bloquear=True)
    try:
        dominio.validar_abierta(cat.codigo(pqrs.estado_id))
    except dominio.ErrorDominioAtencion as exc:
        raise _http(exc) from exc
    _reportar_luminaria(db, sede_id=sede.id, pqrs=pqrs, entrada=entrada, actor_id=actor.id)
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="agregar_luminaria",
        entidad="pqrs",
        entidad_id=str(pqrs.id),
        despues={"luminaria_id": entrada.luminaria_id},
    )
    db.commit()
    return obtener_pqrs(db, actor, sede, pqrs.id)


def quitar_luminaria(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, pqrs_id: int, luminaria_id: int
) -> None:
    cat = _Catalogos(db)
    pqrs = _obtener_pqrs(db, sede.id, pqrs_id, bloquear=True)
    fila = next((pl for pl in pqrs.luminarias if pl.luminaria_id == luminaria_id), None)
    if fila is None:
        raise HTTPException(status_code=404, detail="La luminaria no está en esta PQRS.")
    try:
        dominio.validar_abierta(cat.codigo(pqrs.estado_id))
        dominio.validar_quitar_luminaria(len(pqrs.luminarias), fila.reparada)
    except dominio.ErrorDominioAtencion as exc:
        raise _http(exc) from exc
    pqrs.luminarias.remove(fila)
    db.flush()
    _liberar_luminaria(
        db, cat, sede_id=sede.id, pqrs=pqrs, fila=fila, actor_id=actor.id, motivo="pqrs_retirada"
    )
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="quitar_luminaria",
        entidad="pqrs",
        entidad_id=str(pqrs.id),
        antes={"luminaria_id": luminaria_id},
    )
    db.commit()


def umbrales_semaforo(db: Session, sede_id: int) -> tuple[int, int]:
    """(verde_max_dias, amarillo_max_dias) vigentes para la sede (RN-015). Lo usa el tablero."""
    return dominio.umbrales(
        configuracion.obtener_valor_parametro(db, "semaforo_pqrs_umbrales", sede_id)
    )


ESTADOS_PQRS_ABIERTOS: tuple[str, ...] = tuple(dominio.ABIERTOS)


def listar_pendientes(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    *,
    semaforo: str | None,
    barrio_id: int | None,
    prioridad: int | None,
    page: int,
    size: int,
) -> Pagina[PendienteSalida]:
    verde, amarillo = dominio.umbrales(
        configuracion.obtener_valor_parametro(db, "semaforo_pqrs_umbrales", sede.id)
    )
    filas, total = repositorio.listar_pendientes(
        db,
        sede.id,
        abiertos=list(dominio.ABIERTOS),
        verde_max=verde,
        amarillo_max=amarillo,
        semaforo=semaforo,
        barrio_id=barrio_id,
        prioridad=prioridad,
        page=page,
        size=size,
    )
    ve = _ve_datos_personales(actor)
    items = []
    for f in filas:
        dias = int(f["dias_abierta"])
        solicitante = f["solicitante"]
        if solicitante and not ve:
            solicitante = dominio.enmascarar_nombre(solicitante)
        items.append(
            PendienteSalida(
                **{**f, "dias_abierta": dias, "solicitante": solicitante},
                prioridad_nombre=dominio.PRIORIDADES[int(f["prioridad"])],
                semaforo=dominio.color_semaforo(dias, verde, amarillo),
            )
        )
    return Pagina[PendienteSalida](items=items, total=total, page=page, size=size)


# --- Exportación (segundo plano) ---------------------------------------------------------------


async def encolar_exportacion(
    actor: UsuarioAutenticado, sede: SedeResumen, entrada: PqrsExportarEntrada
) -> TareaEncolada:
    tarea_id = await encolar(
        "atencion.exportar_pqrs",
        sede_id=sede.id,
        usuario_id=actor.id,
        incluir_datos_personales=_ve_datos_personales(actor),
        estado_id=entrada.estado_id,
        prioridad=entrada.prioridad,
        desde=entrada.desde.isoformat() if entrada.desde else None,
        hasta=entrada.hasta.isoformat() if entrada.hasta else None,
    )
    return TareaEncolada(id=tarea_id, tareaId=tarea_id)


def procesar_exportacion(
    db: Session,
    *,
    sede_id: int,
    usuario_id: int,
    incluir_datos_personales: bool,
    estado_id: int | None,
    prioridad: int | None,
    desde: str | None,
    hasta: str | None,
) -> str:
    filas = repositorio.filas_exportacion(
        db,
        sede_id,
        estado_id=estado_id,
        prioridad=prioridad,
        desde=date.fromisoformat(desde) if desde else None,
        hasta=date.fromisoformat(hasta) if hasta else None,
    )
    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = "PQRS"
    hoja.append(
        [
            "Número",
            "Fecha",
            "Canal",
            "Prioridad",
            "Estado",
            "Identificación",
            "Solicitante",
            "Teléfono",
            "Celular",
            "Correo",
            "Luminaria",
            "Barrio",
            "Reparada",
            "Fecha reparación",
            "Observación",
            "Fecha cierre",
        ]
    )
    for f in filas:
        persona = {
            k: f[k] for k in ("identificacion", "nombre_completo", "telefono", "celular", "correo")
        }
        if not incluir_datos_personales and persona["nombre_completo"]:
            persona = dominio.enmascarar_ciudadano(persona)
        hoja.append(
            [
                f["numero"],
                f["fecha_solicitud"].replace(tzinfo=None),
                f["canal"],
                dominio.PRIORIDADES[int(f["prioridad"])],
                f["estado"],
                persona["identificacion"],
                persona["nombre_completo"],
                persona["telefono"],
                persona["celular"],
                persona["correo"],
                f["luminaria"],
                f["barrio"],
                "Sí" if f["reparada"] else "No",
                f["fecha_reparacion"].replace(tzinfo=None) if f["fecha_reparacion"] else None,
                f["observacion_solicitante"],
                f["fecha_cierre"].replace(tzinfo=None) if f["fecha_cierre"] else None,
            ]
        )
    buf = io.BytesIO()
    libro.save(buf)
    meta, _ = archivos.guardar_archivo(
        db,
        sede_id=sede_id,
        archivo_bytes=buf.getvalue(),
        nombre=f"pqrs_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.xlsx",
        categoria="cargue",
        subido_por_id=usuario_id,
    )
    return str(meta.id)


# === Operaciones para trabajos ==================================================================


def pqrs_para_orden(db: Session, sede_id: int, pqrs_id: int) -> dict[str, Any]:
    """Datos de la PQRS que necesita una orden. 404 si no es de la sede; 409 si está cerrada."""
    cat = _Catalogos(db)
    pqrs = repositorio.obtener_pqrs(db, sede_id, pqrs_id)
    if pqrs is None:
        raise HTTPException(status_code=422, detail="La PQRS no existe en la sede.")
    try:
        dominio.validar_abierta(cat.codigo(pqrs.estado_id))
    except dominio.ErrorDominioAtencion as exc:
        raise _http(exc) from exc
    return {
        "id": pqrs.id,
        "numero": pqrs.numero,
        "luminaria_ids": [pl.luminaria_id for pl in pqrs.luminarias if not pl.reparada],
    }


def avanzar_por_orden(db: Session, sede_id: int, pqrs_id: int, evento: str, actor_id: int) -> None:
    """La PQRS sigue a su orden: creada → «En proceso»; asignada → «En mantenimiento»."""
    cat = _Catalogos(db)
    pqrs = repositorio.obtener_pqrs(db, sede_id, pqrs_id, bloquear=True)
    if pqrs is None:
        return
    siguiente = dominio.siguiente_estado_por_orden(cat.codigo(pqrs.estado_id), evento)
    if siguiente is not None:
        pqrs.estado_id = cat.id_estado(siguiente)
        pqrs.modificado_por = actor_id
        db.flush()


def registrar_reparacion(
    db: Session,
    *,
    sede_id: int,
    pqrs_id: int,
    luminaria_ids: list[int],
    orden_id: int,
    observacion_tecnico: str | None,
    actor_id: int,
) -> bool:
    """Marca reparadas las luminarias de la orden; si ya no queda ninguna, la PQRS pasa a
    «Atendida» (RN-010). Devuelve True si hay que avisar al ciudadano. No hace commit."""
    cat = _Catalogos(db)
    pqrs = repositorio.obtener_pqrs(db, sede_id, pqrs_id, bloquear=True)
    if pqrs is None:
        return False
    ahora = datetime.now(UTC)
    pendientes = [pl for pl in pqrs.luminarias if not pl.reparada]
    marcadas = [pl for pl in pendientes if pl.luminaria_id in luminaria_ids]
    if not marcadas:
        # La PQRS se reportó con la comodín: la orden repara la luminaria encontrada en sitio.
        codigos = activos.codigos_luminarias(db, [pl.luminaria_id for pl in pendientes])
        marcadas = [pl for pl in pendientes if codigos.get(pl.luminaria_id, ("", False))[1]][:1]
    for pl in marcadas:
        pl.reparada, pl.fecha_reparacion, pl.orden_id = True, ahora, orden_id
        pl.observacion_tecnico = observacion_tecnico
    db.flush()
    if pqrs.luminarias and all(pl.reparada for pl in pqrs.luminarias):
        pqrs.estado_id = cat.id_estado(dominio.ATENDIDA)
        pqrs.fecha_cierre = ahora
        pqrs.modificado_por = actor_id
        db.flush()
        return pqrs.notificar_cliente and pqrs.ciudadano_id is not None
    return False


async def encolar_notificacion(pqrs_id: int, evento: str) -> int:
    """Correo al ciudadano (registro o atención). Solo viajan ids: el correo se lee en el worker."""
    return await encolar("atencion.notificar_pqrs", pqrs_id=pqrs_id, evento=evento)


def procesar_notificacion(db: Session, pqrs_id: int, evento: str) -> bool:
    pqrs = db.get(Pqrs, pqrs_id)
    if pqrs is None or pqrs.ciudadano_id is None or not pqrs.notificar_cliente:
        return False
    ciudadano = db.get(Ciudadano, pqrs.ciudadano_id)
    if ciudadano is None or not ciudadano.correo:
        return False
    cat = _Catalogos(db)
    codigos = activos.codigos_luminarias(db, [pl.luminaria_id for pl in pqrs.luminarias])
    contexto = {
        "nombre": ciudadano.nombre_completo,
        "numero": pqrs.numero,
        "fecha": (pqrs.fecha_cierre or pqrs.fecha_solicitud).strftime("%d/%m/%Y"),
        "estado": cat.estado_por_id[pqrs.estado_id].nombre,
        "luminaria": ", ".join(c for c, _ in codigos.values()),
    }
    plantilla = PLANTILLA_ATENCION if evento == "atencion" else PLANTILLA_REGISTRO
    correo = configuracion.renderizar_plantilla(db, pqrs.sede_id, plantilla, contexto)
    if correo is None:
        return False
    asunto, cuerpo = correo
    return enviar_correo(ciudadano.correo, asunto, cuerpo)
