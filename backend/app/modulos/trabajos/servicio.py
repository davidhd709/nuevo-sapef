"""Servicio público del módulo de trabajos (EP-05).

El cierre de una orden es atómico: luminarias, kárdex, evidencias y PQRS se confirman juntos o
no se confirma nada (RF-052, RN-017). Los avisos (push, correo) se encolan después del commit.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.paginacion import Pagina, TareaEncolada
from app.core.tareas import encolar
from app.modulos.activos import servicio as activos
from app.modulos.archivos import servicio as archivos
from app.modulos.atencion import servicio as atencion
from app.modulos.configuracion import servicio as configuracion
from app.modulos.inventario import servicio as inventario
from app.modulos.notificaciones import servicio as notificaciones
from app.modulos.seguridad import servicio as seguridad
from app.modulos.seguridad.servicio import SedeResumen, UsuarioAutenticado
from app.modulos.trabajos import dominio, repositorio
from app.modulos.trabajos.esquemas import (
    CargueMasivoSalida,
    CuadrillaCrearEntrada,
    CuadrillaEditarEntrada,
    CuadrillaSalida,
    EvidenciaOrdenSalida,
    InstalacionSalida,
    MantenimientoSalida,
    MaterialUsadoSalida,
    OrdenAnularEntrada,
    OrdenAsignarEntrada,
    OrdenCerrarEntrada,
    OrdenCrearEntrada,
    OrdenEditarEntrada,
    OrdenLuminariaSalida,
    OrdenSalida,
    TecnicoSalida,
)
from app.modulos.trabajos.modelos import (
    CargueMasivo,
    Cuadrilla,
    CuadrillaTecnico,
    OrdenAsignacion,
    OrdenInstalacion,
    OrdenLuminaria,
    OrdenMantenimiento,
    OrdenTrabajo,
)

PERMISO_VER = "trabajos.orden.ver"
PERMISO_CERRAR = "trabajos.orden.cerrar"
TAREA_PUSH = "trabajos.push_orden_asignada"


def _http(exc: dominio.ErrorDominioTrabajos) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


class _Estados:
    def __init__(self, db: Session) -> None:
        self.por_codigo = {e.codigo: e for e in configuracion.listar_estados(db, "orden")}
        self.por_id = {e.id: e for e in self.por_codigo.values()}

    def id(self, codigo: str) -> int:
        return self.por_codigo[codigo].id

    def codigo(self, estado_id: int) -> str:
        return self.por_id[estado_id].codigo


def _tecnicos(db: Session, sede_id: int) -> dict[int, TecnicoSalida]:
    return {
        u.id: TecnicoSalida(
            id=u.id,
            nombre_usuario=u.nombre_usuario,
            nombre_completo=u.nombre_completo,
            activo=u.activo,
        )
        for u in seguridad.listar_tecnicos_sede(db, sede_id)
    }


def _es_mia(db: Session, orden: OrdenTrabajo, usuario_id: int) -> bool:
    if orden.tecnico_id == usuario_id:
        return True
    return (
        orden.cuadrilla_id is not None
        and orden.cuadrilla_id in repositorio.cuadrillas_de_usuario(db, usuario_id)
    )


# === Técnicos y cuadrillas ====================================================================


def listar_tecnicos(db: Session, sede: SedeResumen) -> list[TecnicoSalida]:
    return list(_tecnicos(db, sede.id).values())


def _a_cuadrilla(c: Cuadrilla, tecnicos: dict[int, TecnicoSalida]) -> CuadrillaSalida:
    return CuadrillaSalida(
        id=c.id,
        nombre=c.nombre,
        activa=c.activa,
        tecnicos=[tecnicos[t.usuario_id] for t in c.tecnicos if t.usuario_id in tecnicos],
    )


def listar_cuadrillas(db: Session, sede: SedeResumen, activa: bool | None) -> list[CuadrillaSalida]:
    tecnicos = _tecnicos(db, sede.id)
    return [_a_cuadrilla(c, tecnicos) for c in repositorio.listar_cuadrillas(db, sede.id, activa)]


def _validar_tecnicos(ids: list[int], tecnicos: dict[int, TecnicoSalida]) -> list[int]:
    unicos = list(dict.fromkeys(ids))
    ajenos = [i for i in unicos if i not in tecnicos]
    if ajenos:
        raise HTTPException(
            status_code=422,
            detail=f"No son técnicos activos de esta sede: {', '.join(map(str, ajenos))}.",
        )
    return unicos


def crear_cuadrilla(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, entrada: CuadrillaCrearEntrada
) -> CuadrillaSalida:
    nombre = " ".join(entrada.nombre.split())
    if repositorio.existe_cuadrilla(db, sede.id, nombre):
        raise HTTPException(status_code=409, detail="Ya existe una cuadrilla con ese nombre.")
    tecnicos = _tecnicos(db, sede.id)
    ids = _validar_tecnicos(entrada.tecnicos_ids, tecnicos)
    cuadrilla = Cuadrilla(
        sede_id=sede.id, nombre=nombre, activa=entrada.activa, modificado_por=actor.id
    )
    cuadrilla.tecnicos = [CuadrillaTecnico(usuario_id=i) for i in ids]
    db.add(cuadrilla)
    db.flush()
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="crear",
        entidad="cuadrilla",
        entidad_id=str(cuadrilla.id),
        despues={"nombre": nombre, "tecnicos": ids},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Ya existe una cuadrilla con ese nombre."
        ) from exc
    return _a_cuadrilla(cuadrilla, tecnicos)


def editar_cuadrilla(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    cuadrilla_id: int,
    entrada: CuadrillaEditarEntrada,
) -> CuadrillaSalida:
    cuadrilla = repositorio.obtener_cuadrilla(db, sede.id, cuadrilla_id)
    if cuadrilla is None:
        raise HTTPException(status_code=404, detail="Cuadrilla no encontrada.")
    tecnicos = _tecnicos(db, sede.id)
    if entrada.nombre is not None:
        nombre = " ".join(entrada.nombre.split())
        if repositorio.existe_cuadrilla(db, sede.id, nombre, excluir_id=cuadrilla.id):
            raise HTTPException(status_code=409, detail="Ya existe una cuadrilla con ese nombre.")
        cuadrilla.nombre = nombre
    if entrada.tecnicos_ids is not None:
        ids = _validar_tecnicos(entrada.tecnicos_ids, tecnicos)
        cuadrilla.tecnicos.clear()
        db.flush()
        cuadrilla.tecnicos.extend(CuadrillaTecnico(usuario_id=i) for i in ids)
    if entrada.activa is not None:
        cuadrilla.activa = entrada.activa
    cuadrilla.modificado_por = actor.id
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="editar",
        entidad="cuadrilla",
        entidad_id=str(cuadrilla.id),
        despues={"nombre": cuadrilla.nombre, "activa": cuadrilla.activa},
    )
    db.commit()
    return _a_cuadrilla(cuadrilla, tecnicos)


# === Órdenes: consulta ==========================================================================


def _a_orden(db: Session, o: OrdenTrabajo, est: _Estados) -> OrdenSalida:
    estado = est.por_id[o.estado_id]
    codigos = activos.codigos_luminarias(db, [ol.luminaria_id for ol in o.luminarias])
    tecnicos = _tecnicos(db, o.sede_id) if o.tecnico_id else {}
    cuadrilla = (
        repositorio.obtener_cuadrilla(db, o.sede_id, o.cuadrilla_id) if o.cuadrilla_id else None
    )
    lat, lng = repositorio.coordenadas_orden(db, o.id) if o.ubicacion is not None else (None, None)
    m, i = o.mantenimiento, o.instalacion
    return OrdenSalida(
        id=o.id,
        sede_id=o.sede_id,
        numero=o.numero,
        tipo=o.tipo,
        estado_id=o.estado_id,
        estado_codigo=estado.codigo,
        estado_nombre=estado.nombre,
        prioridad=o.prioridad,
        pqrs_id=o.pqrs_id,
        tecnico_id=o.tecnico_id,
        tecnico_nombre=tecnicos[o.tecnico_id].nombre_completo if o.tecnico_id in tecnicos else None,
        cuadrilla_id=o.cuadrilla_id,
        cuadrilla_nombre=cuadrilla.nombre if cuadrilla else None,
        fecha_programada=o.fecha_programada,
        asignada_en=o.asignada_en,
        fecha_ejecucion=o.fecha_ejecucion,
        latitud=lat,
        longitud=lng,
        observaciones=o.observaciones,
        motivo_anulacion=o.motivo_anulacion,
        origen=o.origen,
        luminarias=[
            OrdenLuminariaSalida(
                luminaria_id=ol.luminaria_id,
                luminaria_codigo=codigos.get(ol.luminaria_id, ("?", False))[0],
                rol=ol.rol,
            )
            for ol in o.luminarias
        ],
        mantenimiento=MantenimientoSalida.model_validate(m, from_attributes=True) if m else None,
        instalacion=InstalacionSalida.model_validate(i, from_attributes=True) if i else None,
        materiales=[
            MaterialUsadoSalida(
                material_id=mv.material_id,
                material_codigo=mv.material_codigo,
                cantidad=mv.cantidad,
            )
            for mv in inventario.listar_movimientos_orden(db, o.sede_id, o.id)
        ],
        evidencias=[
            EvidenciaOrdenSalida(archivo_id=e.archivo_id, tipo=e.tipo, creado_en=e.creado_en)
            for e in archivos.listar_evidencias(db, o.sede_id, "orden", str(o.id))
        ],
        creado_en=o.creado_en,
    )


def _obtener(db: Session, sede_id: int, orden_id: int, *, bloquear: bool = False) -> OrdenTrabajo:
    orden = repositorio.obtener_orden(db, sede_id, orden_id, bloquear=bloquear)
    if orden is None:
        raise HTTPException(status_code=404, detail="Orden no encontrada.")
    return orden


def listar_ordenes(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    *,
    page: int,
    size: int,
    tipo: str | None = None,
    estado_id: int | None = None,
    tecnico_id: int | None = None,
    pqrs_id: int | None = None,
    luminaria_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
) -> Pagina[OrdenSalida]:
    solo_mias = None if PERMISO_VER in actor.permisos else actor.id
    if desde is None and pqrs_id is None and luminaria_id is None:
        desde = date.today() - timedelta(days=62)  # por defecto, los últimos 2 meses (RF-030)
    filas, total = repositorio.listar_ordenes(
        db,
        sede.id,
        page=page,
        size=size,
        tipo=tipo,
        estado_id=estado_id,
        tecnico_id=tecnico_id,
        pqrs_id=pqrs_id,
        luminaria_id=luminaria_id,
        desde=datetime.combine(desde, datetime.min.time(), UTC) if desde else None,
        hasta=datetime.combine(hasta, datetime.max.time(), UTC) if hasta else None,
        solo_de_usuario=solo_mias,
    )
    est = _Estados(db)
    return Pagina[OrdenSalida](
        items=[_a_orden(db, o, est) for o in filas], total=total, page=page, size=size
    )


def obtener_orden(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, orden_id: int
) -> OrdenSalida:
    orden = _obtener(db, sede.id, orden_id)
    if PERMISO_VER not in actor.permisos and not _es_mia(db, orden, actor.id):
        raise HTTPException(status_code=403, detail="La orden no está asignada a usted.")
    return _a_orden(db, orden, _Estados(db))


# === Órdenes: creación y ciclo de vida ========================================================


def crear_orden(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, entrada: OrdenCrearEntrada
) -> OrdenSalida:
    roles = [lum.rol for lum in entrada.luminarias]
    try:
        dominio.validar_luminarias(entrada.tipo, roles)
    except dominio.ErrorDominioTrabajos as exc:
        raise _http(exc) from exc
    ids = [lum.luminaria_id for lum in entrada.luminarias]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Una luminaria no puede repetirse en la orden.")
    resumen = activos.resumen_luminarias(db, sede.id, ids)
    for lum in entrada.luminarias:
        datos = resumen.get(lum.luminaria_id)
        if datos is None:
            raise HTTPException(
                status_code=422, detail=f"La luminaria {lum.luminaria_id} no existe en la sede."
            )
        if datos["es_comodin"]:
            raise HTTPException(
                status_code=422, detail="Identifique la luminaria real antes de crear la orden."
            )
        esperado = dominio.LUM_EN_SITIO if lum.rol != "instalada" else (dominio.LUM_BODEGA_BUENA,)
        if datos["estado_codigo"] not in esperado:
            raise HTTPException(
                status_code=422,
                detail=f"La luminaria {datos['codigo']} ({lum.rol}) está en estado "
                f"{datos['estado_codigo']}; se esperaba {' o '.join(esperado)}.",
            )

    if entrada.pqrs_id is not None:
        pqrs = atencion.pqrs_para_orden(db, sede.id, entrada.pqrs_id)
        intervenidas = [lum.luminaria_id for lum in entrada.luminarias if lum.rol == "intervenida"]
        comodin_pendiente = any(
            es for _, es in activos.codigos_luminarias(db, pqrs["luminaria_ids"]).values()
        )
        if (
            intervenidas
            and not comodin_pendiente
            and not (set(intervenidas) & set(pqrs["luminaria_ids"]))
        ):
            raise HTTPException(
                status_code=422, detail="Las luminarias de la orden no están pendientes en la PQRS."
            )

    est = _Estados(db)
    orden = OrdenTrabajo(
        sede_id=sede.id,
        numero=repositorio.siguiente_numero(db, sede.id),
        tipo=entrada.tipo,
        estado_id=est.id(dominio.CREADA),
        prioridad=entrada.prioridad,
        pqrs_id=entrada.pqrs_id,
        fecha_programada=entrada.fecha_programada,
        observaciones=entrada.observaciones,
        creado_por=actor.id,
        modificado_por=actor.id,
        luminarias=[
            OrdenLuminaria(luminaria_id=lum.luminaria_id, rol=lum.rol) for lum in entrada.luminarias
        ],
    )
    db.add(orden)
    db.flush()
    if orden.pqrs_id is not None:
        atencion.avanzar_por_orden(db, sede.id, orden.pqrs_id, "orden_creada", actor.id)
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="crear",
        entidad="orden_trabajo",
        entidad_id=str(orden.id),
        despues={
            "numero": orden.numero,
            "tipo": orden.tipo,
            "luminarias": ids,
            "pqrs_id": orden.pqrs_id,
        },
    )
    db.commit()
    db.refresh(orden)
    return _a_orden(db, orden, est)


def _validar_abierta(orden: OrdenTrabajo, est: _Estados) -> None:
    try:
        dominio.validar_abierta(est.codigo(orden.estado_id))
    except dominio.ErrorDominioTrabajos as exc:
        raise _http(exc) from exc


def editar_orden(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    orden_id: int,
    entrada: OrdenEditarEntrada,
) -> OrdenSalida:
    est = _Estados(db)
    orden = _obtener(db, sede.id, orden_id, bloquear=True)
    _validar_abierta(orden, est)
    cambios = entrada.model_dump(exclude_unset=True)
    for campo, valor in cambios.items():
        if valor is not None or campo != "prioridad":
            setattr(orden, campo, valor)
    orden.modificado_por = actor.id
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="editar",
        entidad="orden_trabajo",
        entidad_id=str(orden.id),
        despues={"campos": sorted(cambios)},
    )
    db.commit()
    return _a_orden(db, orden, est)


def _asignar(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    orden_id: int,
    entrada: OrdenAsignarEntrada,
) -> OrdenSalida:
    if entrada.tecnico_id is None and entrada.cuadrilla_id is None:
        raise HTTPException(status_code=422, detail="Indique el técnico, la cuadrilla o ambos.")
    est = _Estados(db)
    orden = _obtener(db, sede.id, orden_id, bloquear=True)
    _validar_abierta(orden, est)
    if entrada.tecnico_id is not None and entrada.tecnico_id not in _tecnicos(db, sede.id):
        raise HTTPException(
            status_code=422, detail="El técnico no es un técnico activo de la sede."
        )
    if entrada.cuadrilla_id is not None:
        cuadrilla = repositorio.obtener_cuadrilla(db, sede.id, entrada.cuadrilla_id)
        if cuadrilla is None or not cuadrilla.activa:
            raise HTTPException(
                status_code=422, detail="La cuadrilla no es una cuadrilla activa de la sede."
            )
    orden.tecnico_id = entrada.tecnico_id
    orden.cuadrilla_id = entrada.cuadrilla_id
    orden.asignada_en = datetime.now(UTC)
    if entrada.fecha_programada is not None:
        orden.fecha_programada = entrada.fecha_programada
    if est.codigo(orden.estado_id) == dominio.CREADA:
        orden.estado_id = est.id(dominio.ASIGNADA)
    orden.modificado_por = actor.id
    orden.modificado_en = datetime.now(UTC)
    repositorio.registrar_asignacion(
        db,
        OrdenAsignacion(
            orden_id=orden.id,
            tecnico_id=orden.tecnico_id,
            cuadrilla_id=orden.cuadrilla_id,
            asignada_por=actor.id,
        ),
    )
    if orden.pqrs_id is not None:
        atencion.avanzar_por_orden(db, sede.id, orden.pqrs_id, "orden_asignada", actor.id)
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="asignar",
        entidad="orden_trabajo",
        entidad_id=str(orden.id),
        despues={"tecnico_id": orden.tecnico_id, "cuadrilla_id": orden.cuadrilla_id},
    )
    db.commit()
    return _a_orden(db, orden, est)


async def asignar_orden(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    orden_id: int,
    entrada: OrdenAsignarEntrada,
) -> OrdenSalida:
    salida = await run_in_threadpool(_asignar, db, actor, sede, orden_id, entrada)
    # Aviso push al técnico (RF-105): la tarea solo recibe el id de la orden.
    await encolar(TAREA_PUSH, orden_id=salida.id)
    return salida


def anular_orden(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    orden_id: int,
    entrada: OrdenAnularEntrada,
) -> OrdenSalida:
    est = _Estados(db)
    orden = _obtener(db, sede.id, orden_id, bloquear=True)
    _validar_abierta(orden, est)
    orden.estado_id = est.id(dominio.ANULADA)
    orden.motivo_anulacion = entrada.motivo.strip()
    orden.modificado_por = actor.id
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="anular",
        entidad="orden_trabajo",
        entidad_id=str(orden.id),
        despues={"motivo": orden.motivo_anulacion},
    )
    db.commit()
    return _a_orden(db, orden, est)


# === Cierre (RF-030 a RF-034) ===================================================================


@dataclass
class _Instalacion:
    tipo_valor_id: int | None
    barrio_id: int | None
    marca_id: int | None
    poste: str | None
    longitud_brazo: Decimal | None
    referencia: str | None
    novedades: str | None
    comentario: str | None
    destino: str
    latitud: float | None
    longitud: float | None
    fecha: date


def _detalle_evento(orden: OrdenTrabajo, **extra: Any) -> dict[str, Any]:
    return {"orden_numero": orden.numero, "orden_tipo": orden.tipo, **extra}


def _validar_tipo_valor(db: Session, clase: str, valor_id: int | None, obligatorio: bool) -> None:
    if valor_id is None:
        if obligatorio:
            raise HTTPException(status_code=422, detail=f"Falta el valor de {clase}.")
        return
    if configuracion.obtener_valor_maestro(db, clase, valor_id=valor_id) is None:
        raise HTTPException(status_code=422, detail=f"Valor inválido para {clase}.")


def _aplicar_instalacion(
    db: Session, orden: OrdenTrabajo, datos: _Instalacion, actor_id: int | None
) -> None:
    """Expansión, modernización o reubicación: desmonta (si aplica) e instala desde bodega."""
    instaladas = [ol.luminaria_id for ol in orden.luminarias if ol.rol == "instalada"]
    desmontadas = [ol.luminaria_id for ol in orden.luminarias if ol.rol == "desmontada"]
    intervencion = dominio.INTERVENCION_POR_TIPO[orden.tipo]
    resumen = activos.resumen_luminarias(db, orden.sede_id, desmontadas)
    pares = (
        list(zip(instaladas, desmontadas, strict=False))
        if desmontadas
        else [(i, None) for i in instaladas]
    )
    for instalada_id, desmontada_id in pares:
        lat, lng, barrio_id, poste = datos.latitud, datos.longitud, datos.barrio_id, datos.poste
        if desmontada_id is not None:
            sitio = resumen[desmontada_id]
            lat = lat if lat is not None else sitio["latitud"]
            lng = lng if lng is not None else sitio["longitud"]
            barrio_id = barrio_id or sitio["barrio_id"]
            poste = poste or sitio["poste"]
            activos.cambiar_estado_luminaria(
                db,
                sede_id=orden.sede_id,
                luminaria_id=desmontada_id,
                estado_codigo=datos.destino,
                tipo_evento=f"{orden.tipo}_desmontada",
                actor_id=actor_id,
                origenes_permitidos=dominio.LUM_EN_SITIO,
                orden_id=orden.id,
                detalle=_detalle_evento(orden, reemplazada_por=instalada_id),
            )
        if lat is None or lng is None:
            raise HTTPException(
                status_code=422, detail="Faltan las coordenadas donde quedó instalada la luminaria."
            )
        activos.instalar_luminaria(
            db,
            sede_id=orden.sede_id,
            luminaria_id=instalada_id,
            actor_id=actor_id,
            orden_id=orden.id,
            tipo_evento=f"{orden.tipo}_instalada",
            latitud=lat,
            longitud=lng,
            barrio_id=barrio_id,
            poste=poste,
            marca_id=datos.marca_id,
            longitud_brazo=datos.longitud_brazo,
            fecha=datos.fecha,
            tipo_intervencion_codigo=intervencion,
            reemplaza_a_id=desmontada_id if orden.tipo == "modernizacion" else None,
            detalle=_detalle_evento(orden),
        )
    orden.instalacion = OrdenInstalacion(
        tipo_valor_id=datos.tipo_valor_id,
        barrio_id=datos.barrio_id,
        marca_id=datos.marca_id,
        poste=datos.poste,
        longitud_brazo=datos.longitud_brazo,
        referencia=datos.referencia,
        novedades=datos.novedades,
        destino_desmontada=datos.destino if desmontadas else None,
        comentario=datos.comentario,
    )


def _cerrar_mantenimiento(
    db: Session, orden: OrdenTrabajo, entrada: OrdenCerrarEntrada, actor_id: int, fecha: date
) -> list[int]:
    try:
        componentes = dominio.validar_componentes(entrada.componentes)
        dominio.validar_mantenimiento(
            entrada.requiere_desmonte, entrada.causal_desmonte, entrada.luminaria_reemplazo_id
        )
        destino = dominio.validar_destino(entrada.destino_desmontada)
    except dominio.ErrorDominioTrabajos as exc:
        raise _http(exc) from exc
    intervenidas = [ol.luminaria_id for ol in orden.luminarias if ol.rol == "intervenida"]
    reemplazo = entrada.luminaria_reemplazo_id
    if reemplazo is not None and len(intervenidas) != 1:
        raise HTTPException(status_code=422, detail="El reemplazo aplica a una sola luminaria.")
    resumen = activos.resumen_luminarias(db, orden.sede_id, intervenidas)
    for luminaria_id in intervenidas:
        actual = resumen[luminaria_id]
        if entrada.requiere_desmonte:
            activos.cambiar_estado_luminaria(
                db,
                sede_id=orden.sede_id,
                luminaria_id=luminaria_id,
                estado_codigo=destino,
                tipo_evento="mantenimiento_desmonte",
                actor_id=actor_id,
                origenes_permitidos=dominio.LUM_EN_SITIO,
                orden_id=orden.id,
                detalle=_detalle_evento(
                    orden, causal=entrada.causal_desmonte, reemplazada_por=reemplazo
                ),
            )
            if reemplazo is not None:
                lat = entrada.latitud if entrada.latitud is not None else actual["latitud"]
                lng = entrada.longitud if entrada.longitud is not None else actual["longitud"]
                if lat is None or lng is None:
                    raise HTTPException(
                        status_code=422, detail="Faltan las coordenadas de la luminaria nueva."
                    )
                activos.instalar_luminaria(
                    db,
                    sede_id=orden.sede_id,
                    luminaria_id=reemplazo,
                    actor_id=actor_id,
                    orden_id=orden.id,
                    tipo_evento="mantenimiento_reemplazo",
                    latitud=lat,
                    longitud=lng,
                    barrio_id=actual["barrio_id"],
                    poste=actual["poste"],
                    fecha=fecha,
                    reemplaza_a_id=luminaria_id,
                    detalle=_detalle_evento(orden),
                )
                orden.luminarias.append(OrdenLuminaria(luminaria_id=reemplazo, rol="instalada"))
        elif actual["estado_codigo"] == dominio.LUM_ACTIVO_PQR:
            activos.cambiar_estado_luminaria(
                db,
                sede_id=orden.sede_id,
                luminaria_id=luminaria_id,
                estado_codigo=dominio.LUM_OPERACION,
                tipo_evento="mantenimiento",
                actor_id=actor_id,
                origenes_permitidos=(dominio.LUM_ACTIVO_PQR,),
                orden_id=orden.id,
                detalle=_detalle_evento(orden),
            )
        elif actual["estado_codigo"] == dominio.LUM_OPERACION:
            activos.registrar_evento_luminaria(
                db,
                sede_id=orden.sede_id,
                luminaria_id=luminaria_id,
                tipo="mantenimiento",
                actor_id=actor_id,
                orden_id=orden.id,
                detalle=_detalle_evento(orden),
            )
        else:
            raise HTTPException(
                status_code=409,
                detail=f"La luminaria {actual['codigo']} no está en sitio "
                f"(estado {actual['estado_codigo']}).",
            )
    orden.mantenimiento = OrdenMantenimiento(
        sitio_arreglo=entrada.sitio_arreglo,
        quien_recibe=entrada.quien_recibe,
        observacion_tecnica=entrada.observacion_tecnica,
        requiere_desmonte=entrada.requiere_desmonte,
        causal_desmonte=entrada.causal_desmonte,
        luminaria_reemplazo_id=reemplazo,
        destino_desmontada=destino if entrada.requiere_desmonte else None,
        componentes=componentes,
    )
    return intervenidas


def _cerrar(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    orden_id: int,
    entrada: OrdenCerrarEntrada,
    *,
    uuid_origen: UUID | None = None,
) -> tuple[OrdenSalida, bool]:
    est = _Estados(db)
    orden = _obtener(db, sede.id, orden_id, bloquear=True)
    _validar_abierta(orden, est)
    if PERMISO_CERRAR not in actor.permisos and not _es_mia(db, orden, actor.id):
        raise HTTPException(status_code=403, detail="Solo puede cerrar órdenes asignadas a usted.")
    if (entrada.latitud is None) != (entrada.longitud is None):
        raise HTTPException(status_code=422, detail="Envíe latitud y longitud juntas.")
    ejecutada = entrada.fecha_ejecucion or datetime.now(UTC)
    notificar = False
    try:
        if orden.tipo == "mantenimiento":
            intervenidas = _cerrar_mantenimiento(db, orden, entrada, actor.id, ejecutada.date())
            if orden.pqrs_id is not None:
                notificar = atencion.registrar_reparacion(
                    db,
                    sede_id=sede.id,
                    pqrs_id=orden.pqrs_id,
                    luminaria_ids=intervenidas,
                    orden_id=orden.id,
                    observacion_tecnico=entrada.observacion_tecnica,
                    actor_id=actor.id,
                )
        else:
            clase = {"expansion": "TIPO_EXPANSION", "modernizacion": "TIPO_MODERNIZACION"}.get(
                orden.tipo, "TIPO_MODERNIZACION"
            )
            tipo_valor = (
                entrada.tipo_expansion_id
                if orden.tipo == "expansion"
                else entrada.tipo_modernizacion_id
            )
            _validar_tipo_valor(db, clase, tipo_valor, obligatorio=orden.tipo != "reubicacion")
            try:
                destino = dominio.validar_destino(entrada.destino_desmontada)
            except dominio.ErrorDominioTrabajos as exc:
                raise _http(exc) from exc
            if orden.tipo == "expansion" and entrada.barrio_id is None:
                raise HTTPException(status_code=422, detail="Indique el barrio de la expansión.")
            _aplicar_instalacion(
                db,
                orden,
                _Instalacion(
                    tipo_valor_id=tipo_valor,
                    barrio_id=entrada.barrio_id,
                    marca_id=entrada.marca_id,
                    poste=entrada.poste,
                    longitud_brazo=entrada.longitud_brazo,
                    referencia=entrada.referencia,
                    novedades=entrada.novedades,
                    comentario=entrada.comentario,
                    destino=destino,
                    latitud=entrada.latitud,
                    longitud=entrada.longitud,
                    fecha=ejecutada.date(),
                ),
                actor.id,
            )
        inventario.descontar_materiales(
            db,
            sede_id=sede.id,
            items=[(m.material_id, m.cantidad) for m in entrada.materiales],
            orden_id=orden.id,
            actor_id=actor.id,
            descripcion=f"Orden {orden.numero} ({orden.tipo})",
            latitud=entrada.latitud,
            longitud=entrada.longitud,
        )
        for evidencia in entrada.evidencias:
            archivos.registrar_evidencia(
                db,
                sede_id=sede.id,
                entidad="orden",
                entidad_id=str(orden.id),
                tipo=evidencia.tipo,
                archivo_id=evidencia.archivo_id,
                creado_por=actor.id,
                latitud=entrada.latitud,
                longitud=entrada.longitud,
                confirmar=False,
            )
        orden.estado_id = est.id(dominio.CERRADA)
        orden.fecha_ejecucion = ejecutada
        if entrada.observaciones:
            orden.observaciones = entrada.observaciones
        if entrada.latitud is not None and entrada.longitud is not None:
            orden.ubicacion = f"SRID=4326;POINT({entrada.longitud} {entrada.latitud})"
        if uuid_origen is not None:
            # Idempotencia de la app de campo: el índice único (sede, uuid_origen) impide que la
            # misma operación cierre dos veces aunque lleguen dos lotes a la vez.
            orden.uuid_origen = uuid_origen
        orden.modificado_por = actor.id
        seguridad.registrar_auditoria(
            db,
            usuario_id=actor.id,
            sede_id=sede.id,
            accion="cerrar",
            entidad="orden_trabajo",
            entidad_id=str(orden.id),
            despues={
                "materiales": [[m.material_id, str(m.cantidad)] for m in entrada.materiales],
                "evidencias": len(entrada.evidencias),
            },
        )
        db.commit()
    except Exception:
        db.rollback()  # nada del cierre queda a medias (RN-017)
        raise
    db.refresh(orden)
    return _a_orden(db, orden, est), notificar


async def cerrar_orden(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    orden_id: int,
    entrada: OrdenCerrarEntrada,
) -> OrdenSalida:
    salida, notificar = await run_in_threadpool(_cerrar, db, actor, sede, orden_id, entrada)
    if notificar and salida.pqrs_id is not None:
        await atencion.encolar_notificacion(salida.pqrs_id, "atencion")
    return salida


def procesar_push_asignacion(db: Session, orden_id: int) -> int:
    """Tarea del worker (RF-105, HU-064): avisa por Web Push al técnico y a su cuadrilla. El
    mensaje lleva el número y el tipo de la orden, nunca datos personales. Devuelve cuántos
    avisos aceptó el servicio push."""
    orden = db.get(OrdenTrabajo, orden_id)
    if orden is None:
        return 0
    if _Estados(db).codigo(orden.estado_id) not in dominio.ABIERTOS:
        return 0  # se anuló o se cerró antes de que el worker la tomara
    destinatarios = {orden.tecnico_id} if orden.tecnico_id else set()
    if orden.cuadrilla_id is not None:
        cuadrilla = db.get(Cuadrilla, orden.cuadrilla_id)
        destinatarios |= {t.usuario_id for t in cuadrilla.tecnicos} if cuadrilla else set()
    if not destinatarios:
        return 0
    mensaje = dominio.mensaje_orden_asignada(orden.id, orden.numero, orden.tipo)
    return notificaciones.enviar_a_usuarios(db, sorted(destinatarios), mensaje)


# === App de campo (Fase 3, EP-07) ==============================================================


def _resumen_validacion(exc: ValidationError) -> str:
    partes = []
    for error in exc.errors()[:5]:
        campo = ".".join(str(p) for p in error["loc"]) or "payload"
        partes.append(f"{campo}: {error['msg']}")
    return "Datos inválidos: " + "; ".join(partes)


def ordenes_para_campo(db: Session, sede_id: int, usuario_id: int) -> list[dict[str, Any]]:
    """Órdenes abiertas asignadas a la persona (o a su cuadrilla), con lo que el técnico
    necesita para trabajar sin señal: luminarias con estado, barrio, poste y coordenadas."""
    est = _Estados(db)
    ordenes = repositorio.ordenes_abiertas_de_usuario(
        db, sede_id, usuario_id, [est.id(c) for c in dominio.ABIERTOS]
    )
    resumen = activos.resumen_luminarias(
        db, sede_id, [ol.luminaria_id for o in ordenes for ol in o.luminarias]
    )
    salida = []
    for o in ordenes:
        estado = est.por_id[o.estado_id]
        luminarias = []
        for ol in o.luminarias:
            datos = resumen.get(ol.luminaria_id, {})
            luminarias.append(
                {
                    "luminaria_id": ol.luminaria_id,
                    "codigo": datos.get("codigo", "?"),
                    "rol": ol.rol,
                    "estado_codigo": datos.get("estado_codigo"),
                    "barrio_id": datos.get("barrio_id"),
                    "barrio_nombre": datos.get("barrio_nombre"),
                    "poste": datos.get("poste"),
                    "latitud": datos.get("latitud"),
                    "longitud": datos.get("longitud"),
                }
            )
        salida.append(
            {
                "id": o.id,
                "numero": o.numero,
                "tipo": o.tipo,
                "estado_codigo": estado.codigo,
                "estado_nombre": estado.nombre,
                "prioridad": o.prioridad,
                "pqrs_id": o.pqrs_id,
                "fecha_programada": o.fecha_programada,
                "asignada_en": o.asignada_en,
                "observaciones": o.observaciones,
                "modificado_en": o.modificado_en,
                "luminarias": luminarias,
            }
        )
    return salida


def ordenes_retiradas_campo(
    db: Session, sede_id: int, usuario_id: int, desde: datetime, vigentes: list[int]
) -> list[dict[str, Any]]:
    """Órdenes que el técnico tuvo y que cambiaron desde `desde`: anuladas, cerradas o
    reasignadas a otra persona. La app las retira de su bandeja y avisa."""
    est = _Estados(db)
    salida = []
    for o in repositorio.ordenes_retiradas_desde(db, sede_id, usuario_id, desde, vigentes):
        codigo = est.codigo(o.estado_id)
        motivo = {dominio.ANULADA: "anulada", dominio.CERRADA: "cerrada"}.get(codigo, "reasignada")
        salida.append({"id": o.id, "numero": o.numero, "motivo": motivo})
    return salida


def estado_orden_campo(
    db: Session, sede_id: int, orden_id: int, usuario_id: int
) -> dict[str, Any] | None:
    """Lo mínimo para decidir si una operación de campo aplica o es un conflicto."""
    orden = repositorio.obtener_orden(db, sede_id, orden_id)
    if orden is None:
        return None
    return {
        "id": orden.id,
        "numero": orden.numero,
        "tipo": orden.tipo,
        "estado_codigo": _Estados(db).codigo(orden.estado_id),
        "es_mia": _es_mia(db, orden, usuario_id),
        "uuid_origen": orden.uuid_origen,
    }


def orden_cerrada_por_uuid(db: Session, sede_id: int, uuid_origen: UUID) -> int | None:
    return repositorio.orden_por_uuid_origen(db, sede_id, uuid_origen)


def cerrar_orden_desde_campo(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    orden_id: int,
    payload: dict[str, Any],
    *,
    uuid_origen: UUID,
    ejecutada_en: datetime | None,
) -> tuple[OrdenSalida, bool]:
    """Cierre que llega en un lote de la app de campo: mismas reglas y misma transacción que el
    cierre web, marcado con el uuid de la operación. Lanza HTTPException si no se puede."""
    try:
        entrada = OrdenCerrarEntrada.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_resumen_validacion(exc)) from exc
    if entrada.fecha_ejecucion is None:
        entrada.fecha_ejecucion = ejecutada_en
    return _cerrar(db, actor, sede, orden_id, entrada, uuid_origen=uuid_origen)


def catalogos_campo() -> dict[str, Any]:
    return {
        "componentes": list(dominio.COMPONENTES),
        "destinos_desmontada": list(dominio.DESTINOS_DESMONTADA),
        "tipos_evidencia": list(dominio.TIPOS_EVIDENCIA_CAMPO),
        "abiertos": list(dominio.ABIERTOS),
    }


# === Cargue masivo (RF-032 a RF-034) ===========================================================


def plantilla_cargue(tipo: str) -> bytes:
    try:
        return dominio.generar_plantilla(tipo)
    except dominio.ErrorDominioTrabajos as exc:
        raise _http(exc) from exc


async def recibir_cargue(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, tipo: str, archivo: UploadFile
) -> TareaEncolada:
    contenido = await archivos.leer_upload_con_limite(archivo, "cargue")
    meta, _ = archivos.guardar_archivo(
        db,
        sede_id=sede.id,
        archivo_bytes=contenido,
        nombre=archivo.filename or f"{tipo}.xlsx",
        categoria="cargue",
        subido_por_id=actor.id,
    )
    cargue = CargueMasivo(sede_id=sede.id, tipo=tipo, archivo_id=meta.id, creado_por=actor.id)
    db.add(cargue)
    db.commit()
    tarea_id = await encolar("trabajos.procesar_cargue_masivo", cargue_id=cargue.id)
    return TareaEncolada(id=cargue.id, cargueId=cargue.id, tareaId=tarea_id)


def obtener_cargue(db: Session, sede: SedeResumen, cargue_id: int) -> CargueMasivoSalida:
    cargue = repositorio.obtener_cargue(db, sede.id, cargue_id)
    if cargue is None:
        raise HTTPException(status_code=404, detail="Cargue no encontrado.")
    return CargueMasivoSalida.model_validate(cargue, from_attributes=True)


def _validar_fila(
    db: Session, sede_id: int, tipo: str, datos: dict[str, str], vistas: set[str]
) -> tuple[list[str], dict[str, Any]]:
    """Errores de una fila y, si no hay, lo necesario para aplicarla."""
    errores: list[str] = []
    plan: dict[str, Any] = {}
    barrio = configuracion.resolver_barrio_por_nombre(db, sede_id, datos.get("barrio", ""))
    if barrio is None:
        errores.append(f"El barrio «{datos.get('barrio')}» no existe en la sede")
    else:
        plan["barrio_id"] = barrio["id"]
    clase = "TIPO_EXPANSION" if tipo == "expansion" else "TIPO_MODERNIZACION"
    codigo_tipo = (datos.get("tipo_expansion") if tipo == "expansion" else datos.get("tipo")) or ""
    plan["tipo_valor_id"] = None
    if codigo_tipo:
        valor = configuracion.obtener_valor_maestro(db, clase, codigo=codigo_tipo.upper())
        if valor is None and tipo != "reubicacion":
            errores.append(f"Tipo «{codigo_tipo}» no existe en {clase}")
        plan["tipo_valor_id"] = valor["id"] if valor else None
    elif tipo != "reubicacion":
        errores.append("Falta el tipo")

    def luminaria(campo: str, esperado: tuple[str, ...]) -> int | None:
        codigo = datos.get(campo, "")
        if codigo.lower() in vistas:
            errores.append(f"La luminaria {codigo} se repite en el archivo")
            return None
        vistas.add(codigo.lower())
        lum = activos.obtener_luminaria_por_codigo(db, sede_id, codigo)
        if lum is None:
            errores.append(f"No existe la luminaria {codigo}")
            return None
        if lum["estado_codigo"] not in esperado:
            errores.append(
                f"La luminaria {codigo} está en {lum['estado_codigo']}, no en "
                f"{' o '.join(esperado)}"
            )
            return None
        return int(lum["id"])

    if tipo == "expansion":
        plan["instalada"] = luminaria("luminaria_codigo", (dominio.LUM_BODEGA_BUENA,))
        try:
            plan["latitud"], plan["longitud"] = dominio.coordenadas_de_fila(datos)
            if not (-90 <= plan["latitud"] <= 90 and -180 <= plan["longitud"] <= 180):
                errores.append("Coordenadas fuera de rango")
        except dominio.ErrorDominioTrabajos as exc:
            errores.append(exc.detail)
        plan["destino"] = dominio.LUM_DESMONTADA
    else:
        plan["instalada"] = luminaria("luminaria_instalada_codigo", (dominio.LUM_BODEGA_BUENA,))
        plan["desmontada"] = luminaria("luminaria_desmontada_codigo", dominio.LUM_EN_SITIO)
        try:
            plan["destino"] = dominio.validar_destino(datos.get("destino_desmontada") or None)
        except dominio.ErrorDominioTrabajos as exc:
            errores.append(exc.detail)
        plan["latitud"] = plan["longitud"] = None
    plan["poste"] = datos.get("poste") or None
    return errores, plan


def procesar_cargue(db: Session, cargue_id: int) -> str:
    """Tarea del worker: valida todas las filas; solo si ninguna falla, crea todas las órdenes
    (ya cerradas, con sus luminarias) en una sola transacción."""
    cargue = repositorio.obtener_cargue_por_id(db, cargue_id)
    if cargue is None or cargue.estado != "pendiente":
        return "omitido"
    _, contenido = archivos.obtener_archivo_verificado(db, cargue.sede_id, cargue.archivo_id)
    try:
        filas, errores = dominio.leer_cargue(cargue.tipo, contenido)
    except dominio.ErrorDominioTrabajos as exc:
        filas, errores = [], [{"fila": 1, "error": exc.detail}]
    planes: list[tuple[int, dict[str, Any]]] = []
    vistas: set[str] = set()
    for fila in filas:
        problemas, plan = _validar_fila(db, cargue.sede_id, cargue.tipo, fila.datos, vistas)
        if problemas:
            errores.append(
                {
                    "fila": fila.fila,
                    "registro": fila.fila - 1,
                    "errores": problemas,
                    "valores": fila.datos,
                }
            )
        else:
            planes.append((fila.fila, plan))

    cargue.filas = len(filas)
    cargue.procesado_en = datetime.now(UTC)
    if errores or not planes:
        cargue.estado = "con_errores"
        cargue.errores = errores or [{"fila": 1, "error": "El archivo no tiene filas."}]
        db.commit()
        return "con_errores"

    est = _Estados(db)
    try:
        for _numero_fila, plan in planes:
            luminarias = [OrdenLuminaria(luminaria_id=plan["instalada"], rol="instalada")]
            if plan.get("desmontada"):
                luminarias.append(OrdenLuminaria(luminaria_id=plan["desmontada"], rol="desmontada"))
            orden = OrdenTrabajo(
                sede_id=cargue.sede_id,
                numero=repositorio.siguiente_numero(db, cargue.sede_id),
                tipo=cargue.tipo,
                estado_id=est.id(dominio.CERRADA),
                origen="cargue",
                cargue_id=cargue.id,
                fecha_ejecucion=datetime.now(UTC),
                creado_por=cargue.creado_por,
                modificado_por=cargue.creado_por,
                luminarias=luminarias,
            )
            db.add(orden)
            db.flush()
            _aplicar_instalacion(
                db,
                orden,
                _Instalacion(
                    tipo_valor_id=plan["tipo_valor_id"],
                    barrio_id=plan.get("barrio_id"),
                    marca_id=None,
                    poste=plan["poste"],
                    longitud_brazo=None,
                    referencia=None,
                    novedades=None,
                    comentario=f"Cargue masivo {cargue.id}",
                    destino=plan["destino"],
                    latitud=plan["latitud"],
                    longitud=plan["longitud"],
                    fecha=date.today(),
                ),
                cargue.creado_por,
            )
        cargue.estado = "completado"
        cargue.ordenes_creadas = len(planes)
        db.commit()
    except HTTPException as exc:
        db.rollback()
        cargue = repositorio.obtener_cargue_por_id(db, cargue_id)
        assert cargue is not None
        cargue.estado, cargue.procesado_en = "con_errores", datetime.now(UTC)
        cargue.errores = [{"fila": None, "error": str(exc.detail)}]
        db.commit()
        return "con_errores"
    return "completado"
