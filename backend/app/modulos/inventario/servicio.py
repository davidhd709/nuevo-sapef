"""Servicio público del módulo de inventario (EP-06).

Para otros módulos: `descontar_materiales` (cierre de órdenes, en la transacción de quien
llama) y `listar_movimientos_orden`.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.paginacion import Pagina, TareaEncolada
from app.core.tareas import encolar
from app.modulos.activos import servicio as activos
from app.modulos.archivos import servicio as archivos
from app.modulos.configuracion import servicio as configuracion
from app.modulos.inventario import dominio, repositorio
from app.modulos.inventario.esquemas import (
    BodegaCambioEntrada,
    CargueBodegaSalida,
    MaterialCrearEntrada,
    MaterialEditarEntrada,
    MaterialSalida,
    MovimientoEntrada,
    MovimientoSalida,
)
from app.modulos.inventario.modelos import CargueBodega, Material, MovimientoMaterial
from app.modulos.seguridad import servicio as seguridad
from app.modulos.seguridad.servicio import SedeResumen, UsuarioAutenticado

PERMISO_AJUSTE = "inventario.movimiento.ajustar"
PERMISO_MOVIMIENTO = "inventario.movimiento.crear"


def _http(exc: dominio.ErrorDominioInventario) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _a_material(m: Material) -> MaterialSalida:
    return MaterialSalida(
        id=m.id,
        sede_id=m.sede_id,
        categoria=m.categoria,
        codigo=m.codigo,
        descripcion=m.descripcion,
        unidad=m.unidad,
        existencias=m.existencias,
        existencias_minimas=m.existencias_minimas,
        bajo_minimo=dominio.esta_bajo_minimo(m.existencias, m.existencias_minimas),
        responsable=m.responsable,
        activo=m.activo,
        modificado_en=m.modificado_en,
    )


def _a_movimiento(m: MovimientoMaterial, codigo: str) -> MovimientoSalida:
    return MovimientoSalida(
        id=m.id,
        material_id=m.material_id,
        material_codigo=codigo,
        tipo=m.tipo,
        cantidad=m.cantidad,
        delta=m.delta,
        existencias_resultantes=m.existencias_resultantes,
        origen=m.origen,
        descripcion=m.descripcion,
        orden_id=m.orden_id,
        uuid_origen=m.uuid_origen,
        creado_en=m.creado_en,
        creado_por=m.creado_por,
    )


def _obtener(db: Session, sede_id: int, material_id: int, *, bloquear: bool = False) -> Material:
    material = repositorio.obtener_material(db, sede_id, material_id, bloquear=bloquear)
    if material is None:
        raise HTTPException(status_code=404, detail="Material no encontrado.")
    return material


def _snapshot(m: Material) -> dict[str, Any]:
    return _a_material(m).model_dump(mode="json", exclude={"modificado_en"})


# === Materiales ================================================================================


def listar_materiales(
    db: Session,
    sede: SedeResumen,
    *,
    page: int,
    size: int,
    buscar: str | None = None,
    categoria: str | None = None,
    bajo_minimo: bool | None = None,
    activo: bool | None = None,
) -> Pagina[MaterialSalida]:
    filas, total = repositorio.listar_materiales(
        db,
        sede.id,
        page=page,
        size=size,
        buscar=buscar,
        categoria=categoria,
        bajo_minimo=bajo_minimo,
        activo=activo,
    )
    return Pagina[MaterialSalida](
        items=[_a_material(m) for m in filas], total=total, page=page, size=size
    )


def obtener_material(db: Session, sede: SedeResumen, material_id: int) -> MaterialSalida:
    return _a_material(_obtener(db, sede.id, material_id))


def crear_material(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, entrada: MaterialCrearEntrada
) -> MaterialSalida:
    try:
        codigo = dominio.normalizar_codigo_material(entrada.codigo)
    except dominio.ErrorDominioInventario as exc:
        raise _http(exc) from exc
    if repositorio.existe_codigo(db, sede.id, codigo):
        raise HTTPException(status_code=409, detail="Ya existe un material con ese código.")
    material = Material(
        sede_id=sede.id,
        categoria=entrada.categoria.strip().upper(),
        codigo=codigo,
        descripcion=entrada.descripcion.strip(),
        unidad=entrada.unidad.strip().upper(),
        existencias=entrada.existencias,
        existencias_minimas=entrada.existencias_minimas,
        responsable=entrada.responsable.strip() if entrada.responsable else None,
        activo=entrada.activo,
        creado_por=actor.id,
        modificado_por=actor.id,
    )
    db.add(material)
    db.flush()
    if entrada.existencias > 0:
        # El saldo inicial también queda en el kárdex.
        db.add(
            MovimientoMaterial(
                sede_id=sede.id,
                material_id=material.id,
                tipo="entrada",
                cantidad=entrada.existencias,
                delta=entrada.existencias,
                existencias_resultantes=entrada.existencias,
                origen="inicial",
                descripcion="Saldo inicial",
                creado_por=actor.id,
            )
        )
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="crear",
        entidad="material",
        entidad_id=str(material.id),
        despues=_snapshot(material),
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Ya existe un material con ese código."
        ) from exc
    db.refresh(material)
    return _a_material(material)


def editar_material(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    material_id: int,
    entrada: MaterialEditarEntrada,
) -> MaterialSalida:
    material = _obtener(db, sede.id, material_id, bloquear=True)
    antes = _snapshot(material)
    for campo, valor in entrada.model_dump(exclude_unset=True).items():
        if valor is None and campo != "responsable":
            continue
        if isinstance(valor, str):
            valor = valor.strip() or None
            if campo in ("categoria", "unidad") and valor:
                valor = valor.upper()
        setattr(material, campo, valor)
    material.modificado_por = actor.id
    db.flush()
    db.refresh(material)
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="editar",
        entidad="material",
        entidad_id=str(material.id),
        antes=antes,
        despues=_snapshot(material),
    )
    db.commit()
    db.refresh(material)
    return _a_material(material)


# === Kárdex ====================================================================================


def _aplicar(
    db: Session,
    material: Material,
    *,
    tipo: str,
    cantidad: Decimal,
    origen: str,
    actor_id: int | None,
    descripcion: str | None = None,
    orden_id: int | None = None,
    uuid_origen: UUID | None = None,
    latitud: float | None = None,
    longitud: float | None = None,
) -> MovimientoMaterial:
    """Aplica un movimiento sobre un material ya bloqueado. No hace commit."""
    try:
        delta = dominio.calcular_delta(tipo, cantidad)
        resultado = dominio.aplicar_delta(material.existencias, delta, material.codigo)
    except dominio.ErrorDominioInventario as exc:
        raise _http(exc) from exc
    material.existencias = resultado
    material.modificado_por = actor_id
    geom = (
        f"SRID=4326;POINT({longitud} {latitud})"
        if latitud is not None and longitud is not None
        else None
    )
    movimiento = MovimientoMaterial(
        sede_id=material.sede_id,
        material_id=material.id,
        tipo=tipo,
        cantidad=cantidad,
        delta=delta,
        existencias_resultantes=resultado,
        origen=origen,
        descripcion=descripcion.strip() if descripcion else None,
        orden_id=orden_id,
        uuid_origen=uuid_origen,
        ubicacion=geom,
        creado_por=actor_id,
    )
    db.add(movimiento)
    db.flush()
    return movimiento


def registrar_movimiento(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    material_id: int,
    entrada: MovimientoEntrada,
) -> tuple[MovimientoSalida, bool]:
    """Devuelve (movimiento, creado). Repetir el mismo `uuid_origen` no vuelve a aplicarlo."""
    seguridad.verificar_permiso(
        actor, PERMISO_AJUSTE if entrada.tipo == "ajuste" else PERMISO_MOVIMIENTO
    )
    material = _obtener(db, sede.id, material_id, bloquear=True)
    if entrada.uuid_origen is not None:
        previo = repositorio.obtener_movimiento_por_uuid(db, sede.id, entrada.uuid_origen)
        if previo is not None:
            if previo.material_id != material.id:
                raise HTTPException(
                    status_code=409, detail="Ese uuid_origen ya se usó en otro material."
                )
            return _a_movimiento(previo, material.codigo), False
    if (entrada.latitud is None) != (entrada.longitud is None):
        raise HTTPException(status_code=422, detail="Envíe latitud y longitud juntas.")
    movimiento = _aplicar(
        db,
        material,
        tipo=entrada.tipo,
        cantidad=entrada.cantidad,
        origen="ajuste" if entrada.tipo == "ajuste" else "manual",
        actor_id=actor.id,
        descripcion=entrada.descripcion,
        uuid_origen=entrada.uuid_origen,
        latitud=entrada.latitud,
        longitud=entrada.longitud,
    )
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion=f"movimiento_{entrada.tipo}",
        entidad="material",
        entidad_id=str(material.id),
        despues={"delta": str(movimiento.delta), "existencias": str(material.existencias)},
    )
    try:
        db.commit()
    except IntegrityError:  # dos peticiones simultáneas con el mismo uuid_origen
        db.rollback()
        previo = repositorio.obtener_movimiento_por_uuid(db, sede.id, entrada.uuid_origen)
        if previo is None:
            raise
        return _a_movimiento(previo, material.codigo), False
    db.refresh(movimiento)
    return _a_movimiento(movimiento, material.codigo), True


def listar_movimientos(
    db: Session,
    sede: SedeResumen,
    material_id: int,
    *,
    page: int,
    size: int,
    desde: datetime | None = None,
    hasta: datetime | None = None,
) -> Pagina[MovimientoSalida]:
    _obtener(db, sede.id, material_id)
    filas, total = repositorio.listar_movimientos(
        db, sede.id, material_id=material_id, desde=desde, hasta=hasta, page=page, size=size
    )
    return Pagina[MovimientoSalida](
        items=[_a_movimiento(m, c) for m, c in filas], total=total, page=page, size=size
    )


def descontar_materiales(
    db: Session,
    *,
    sede_id: int,
    items: list[tuple[int, Decimal]],
    orden_id: int,
    actor_id: int | None,
    descripcion: str | None = None,
    latitud: float | None = None,
    longitud: float | None = None,
) -> list[MovimientoSalida]:
    """Salidas de material de una orden (RF-052), en la transacción de quien llama.

    Si un material no alcanza, lanza 409 y quien llama debe deshacer todo (rollback).
    Bloquea los materiales en orden de id para evitar interbloqueos entre cierres simultáneos.
    """
    por_material: dict[int, Decimal] = {}
    for material_id, cantidad in items:
        if cantidad <= 0:
            raise HTTPException(status_code=422, detail="La cantidad de material debe ser > 0.")
        por_material[material_id] = por_material.get(material_id, Decimal(0)) + cantidad
    salidas: list[MovimientoSalida] = []
    for material_id in sorted(por_material):
        material = repositorio.obtener_material(db, sede_id, material_id, bloquear=True)
        if material is None:
            raise HTTPException(
                status_code=422, detail=f"El material {material_id} no existe en la sede."
            )
        mov = _aplicar(
            db,
            material,
            tipo="salida",
            cantidad=por_material[material_id],
            origen="orden",
            actor_id=actor_id,
            descripcion=descripcion,
            orden_id=orden_id,
            latitud=latitud,
            longitud=longitud,
        )
        salidas.append(_a_movimiento(mov, material.codigo))
    return salidas


def listar_movimientos_orden(db: Session, sede_id: int, orden_id: int) -> list[MovimientoSalida]:
    filas, _ = repositorio.listar_movimientos(db, sede_id, orden_id=orden_id, size=500)
    return [_a_movimiento(m, c) for m, c in filas]


# === Bodega de luminarias (RF-053) =============================================================


def listar_bodega(
    db: Session,
    sede: SedeResumen,
    *,
    page: int,
    size: int,
    texto: str | None = None,
    estado_id: int | None = None,
) -> activos.Pagina[activos.LuminariaSalida]:
    return activos.listar_luminarias_bodega(
        db, sede, page=page, size=size, texto=texto, estado_id=estado_id
    )


def _cambiar_estado_bodega(
    db: Session,
    *,
    sede_id: int,
    luminaria_id: int,
    destino_codigo: str,
    observacion: str | None,
    actor_id: int | None,
    origen: str,
) -> None:
    resumen = activos.resumen_luminarias(db, sede_id, [luminaria_id]).get(luminaria_id)
    if resumen is None:
        raise HTTPException(status_code=404, detail="Luminaria no encontrada.")
    try:
        dominio.validar_transicion_bodega(resumen["estado_codigo"] or "", destino_codigo)
    except dominio.ErrorDominioInventario as exc:
        raise _http(exc) from exc
    activos.cambiar_estado_luminaria(
        db,
        sede_id=sede_id,
        luminaria_id=luminaria_id,
        estado_codigo=destino_codigo,
        tipo_evento="cambio_estado",
        actor_id=actor_id,
        origenes_permitidos=dominio.ESTADOS_BODEGA,
        detalle={"origen": origen, "observacion": observacion},
    )


def cambiar_estado_bodega(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    luminaria_id: int,
    entrada: BodegaCambioEntrada,
) -> activos.LuminariaSalida:
    destino = configuracion.obtener_estado_por_id_o_codigo(
        db, "luminaria", estado_id=entrada.estado_id
    )
    if destino is None:
        raise HTTPException(status_code=422, detail="El estado indicado no existe.")
    _cambiar_estado_bodega(
        db,
        sede_id=sede.id,
        luminaria_id=luminaria_id,
        destino_codigo=destino["codigo"],
        observacion=entrada.observacion,
        actor_id=actor.id,
        origen="bodega",
    )
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="cambio_estado_bodega",
        entidad="luminaria",
        entidad_id=str(luminaria_id),
        despues={"estado": destino["codigo"]},
    )
    db.commit()
    return activos.obtener_luminaria(db, sede, luminaria_id)


async def recibir_cargue_bodega(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, archivo: UploadFile
) -> TareaEncolada:
    contenido = await archivos.leer_upload_con_limite(archivo, "cargue")
    meta, _ = archivos.guardar_archivo(
        db,
        sede_id=sede.id,
        archivo_bytes=contenido,
        nombre=archivo.filename or "bodega.xlsx",
        categoria="cargue",
        subido_por_id=actor.id,
    )
    cargue = CargueBodega(sede_id=sede.id, archivo_id=meta.id, creado_por=actor.id)
    db.add(cargue)
    db.commit()
    tarea_id = await encolar("inventario.procesar_cargue_bodega", cargue_id=cargue.id)
    return TareaEncolada(id=cargue.id, cargueId=cargue.id, tareaId=tarea_id)


def obtener_cargue_bodega(db: Session, sede: SedeResumen, cargue_id: int) -> CargueBodegaSalida:
    cargue = repositorio.obtener_cargue(db, sede.id, cargue_id)
    if cargue is None:
        raise HTTPException(status_code=404, detail="Cargue no encontrado.")
    return CargueBodegaSalida.model_validate(cargue, from_attributes=True)


def procesar_cargue_bodega(db: Session, cargue_id: int) -> str:
    """Tarea del worker: valida todas las filas y, solo si ninguna falla, aplica todas."""
    cargue = repositorio.obtener_cargue_por_id(db, cargue_id)
    if cargue is None or cargue.estado != "pendiente":
        return "omitido"
    _, contenido = archivos.obtener_archivo_verificado(db, cargue.sede_id, cargue.archivo_id)
    errores: list[dict[str, Any]] = []
    try:
        filas, errores = dominio.leer_cargue_bodega(contenido)
    except dominio.ErrorDominioInventario as exc:
        filas, errores = [], [{"fila": 1, "error": exc.detail}]

    for fila in filas:
        if errores and len(errores) > 200:
            break
        lum = activos.obtener_luminaria_por_codigo(db, cargue.sede_id, fila.luminaria_codigo)
        if lum is None:
            errores.append(
                {"fila": fila.fila, "error": f"No existe la luminaria {fila.luminaria_codigo}"}
            )
            continue
        try:
            dominio.validar_transicion_bodega(lum["estado_codigo"] or "", fila.estado_codigo)
        except dominio.ErrorDominioInventario as exc:
            errores.append({"fila": fila.fila, "error": exc.detail})

    cargue.filas = len(filas)
    cargue.procesado_en = datetime.now(UTC)
    if errores or not filas:
        cargue.estado = "con_errores"
        cargue.errores = errores or [{"fila": 1, "error": "El archivo no tiene filas."}]
        db.commit()
        return "con_errores"
    try:
        for fila in filas:
            lum = activos.obtener_luminaria_por_codigo(db, cargue.sede_id, fila.luminaria_codigo)
            assert lum is not None
            _cambiar_estado_bodega(
                db,
                sede_id=cargue.sede_id,
                luminaria_id=lum["id"],
                destino_codigo=fila.estado_codigo,
                observacion=fila.observacion,
                actor_id=cargue.creado_por,
                origen=f"cargue_bodega:{cargue.id}",
            )
    except HTTPException as exc:  # p. ej., la misma luminaria dos veces en el archivo
        db.rollback()
        cargue = repositorio.obtener_cargue_por_id(db, cargue_id)
        assert cargue is not None
        cargue.estado, cargue.procesado_en = "con_errores", datetime.now(UTC)
        cargue.errores = [{"fila": None, "error": str(exc.detail)}]
        db.commit()
        return "con_errores"
    cargue.estado = "completado"
    db.commit()
    return "completado"
