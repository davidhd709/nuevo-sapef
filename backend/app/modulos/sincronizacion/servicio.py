"""Servicio público de la sincronización de la app de campo (EP-07, §9.7).

- Bajada (`obtener_paquete`): órdenes abiertas asignadas, las que se retiraron desde el cursor,
  luminarias de la sede (todas o solo las que cambiaron), bodega, materiales y catálogos.
- Subida (`sincronizar`): cada operación se aplica en su propia transacción, con las mismas
  reglas del cierre web, y queda registrada por su uuid. Un reintento de una operación aplicada
  responde «ya_aplicada» sin tocar nada; una orden anulada o reasignada da «conflicto» sin
  afectar a las demás operaciones del lote.
"""

import logging
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.paginacion import Pagina
from app.modulos.activos import servicio as activos
from app.modulos.atencion import servicio as atencion
from app.modulos.configuracion import servicio as configuracion
from app.modulos.inventario import servicio as inventario
from app.modulos.seguridad.servicio import SedeResumen, UsuarioAutenticado
from app.modulos.sincronizacion import dominio, repositorio
from app.modulos.sincronizacion.esquemas import (
    BarrioCampo,
    CatalogosCampo,
    DestinoCampo,
    EstadoOperacion,
    LuminariaCampo,
    MapaBaseCampo,
    MaterialCampo,
    OperacionCampoSalida,
    OperacionEntrada,
    OrdenCampo,
    OrdenRetirada,
    PaqueteCampo,
    ResultadoOperacion,
    SedeCampo,
    SincronizarEntrada,
    SincronizarSalida,
    UsuarioCampo,
    ValorCampo,
)
from app.modulos.sincronizacion.modelos import OperacionCampo
from app.modulos.trabajos import servicio as trabajos

log = logging.getLogger("sapef.campo")


def _http(exc: dominio.ErrorDominioSincronizacion) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


# === Bajada ====================================================================================


def _valores(db: Session, clase: str) -> list[ValorCampo]:
    return [
        ValorCampo(id=v.id, codigo=v.codigo, nombre=v.nombre)
        for v in configuracion.listar_valores(db, clase, activo=True)
    ]


def _catalogos(db: Session, sede: SedeResumen) -> CatalogosCampo:
    base = trabajos.catalogos_campo()
    nombres = {e.codigo: e.nombre for e in configuracion.listar_estados(db, "luminaria")}
    return CatalogosCampo(
        barrios=[
            BarrioCampo(id=b.id, nombre=b.nombre, zona_id=b.zona_id, zona_nombre=b.zona_nombre)
            for b in configuracion.listar_barrios(db, sede, activo=True)
        ],
        tipos_expansion=_valores(db, "TIPO_EXPANSION"),
        tipos_modernizacion=_valores(db, "TIPO_MODERNIZACION"),
        marcas=_valores(db, "LUMINARIA_MARCA"),
        componentes=base["componentes"],
        destinos_desmontada=[
            DestinoCampo(codigo=c, nombre=nombres.get(c, c)) for c in base["destinos_desmontada"]
        ],
        tipos_evidencia=base["tipos_evidencia"],
    )


def obtener_paquete(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, desde: str | None
) -> PaqueteCampo:
    try:
        cursor_previo = dominio.decodificar_cursor(desde) if desde else None
    except dominio.ErrorDominioSincronizacion as exc:
        raise _http(exc) from exc
    # El cursor nuevo se toma antes de leer: lo que cambie mientras tanto vuelve en la próxima.
    ahora = datetime.now(UTC)
    cambios_desde = dominio.desde_con_solape(cursor_previo) if cursor_previo else None

    ordenes = trabajos.ordenes_para_campo(db, sede.id, actor.id)
    retiradas = (
        trabajos.ordenes_retiradas_campo(
            db, sede.id, actor.id, cambios_desde, [o["id"] for o in ordenes]
        )
        if cambios_desde is not None
        else []
    )
    return PaqueteCampo(
        cursor=dominio.codificar_cursor(ahora),
        generado_en=ahora,
        completo=cambios_desde is None,
        sede=SedeCampo(codigo=sede.codigo, nombre=sede.nombre),
        usuario=UsuarioCampo(id=actor.id, nombre_completo=actor.nombre_completo),
        ordenes_asignadas=[OrdenCampo.model_validate(o) for o in ordenes],
        ordenes_anuladas_o_reasignadas=[OrdenRetirada.model_validate(r) for r in retiradas],
        luminarias_zona=[
            LuminariaCampo.model_validate(lum)
            for lum in activos.luminarias_para_campo(db, sede.id, cambios_desde)
        ],
        luminarias_bodega=[
            LuminariaCampo.model_validate(lum)
            for lum in activos.luminarias_bodega_buena_para_campo(db, sede.id)
        ],
        materiales=[
            MaterialCampo.model_validate(m) for m in inventario.materiales_para_campo(db, sede.id)
        ],
        catalogos=_catalogos(db, sede),
        mapa_base=MapaBaseCampo(
            url=f"/api/v1/mapa/base/{sede.codigo}.pmtiles?v=20261125-ampliado"
        ),
    )


# === Subida ====================================================================================


def _registrar(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    op: OperacionEntrada,
    estado: str,
    motivo: str | None,
    previa: OperacionCampo | None,
    orden_id: int | None,
) -> None:
    """Deja constancia de la operación. `orden_id` solo si la orden existe (llave foránea)."""
    ahora = datetime.now(UTC)
    if previa is None:
        repositorio.guardar(
            db,
            OperacionCampo(
                uuid=op.uuid,
                sede_id=sede.id,
                usuario_id=actor.id,
                tipo=op.tipo[:30],
                orden_id=orden_id,
                estado=estado,
                motivo=motivo,
                creada_en=op.creada_en,
                recibida_en=ahora,
                actualizada_en=ahora,
            ),
        )
    else:
        previa.estado = estado
        previa.motivo = motivo
        previa.intentos += 1
        previa.actualizada_en = ahora
        previa.orden_id = orden_id
    db.commit()


def _resultado(
    op: OperacionEntrada, estado: str, motivo: str | None, orden_id: int | None
) -> ResultadoOperacion:
    return ResultadoOperacion(
        uuid=op.uuid, estado=cast(EstadoOperacion, estado), motivo=motivo, orden_id=orden_id
    )


def _aplicar(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    op: OperacionEntrada,
    ahora: datetime,
) -> tuple[ResultadoOperacion, int | None]:
    """Aplica una operación. Devuelve el resultado y, si corresponde, la PQRS a notificar."""
    previa = repositorio.obtener(db, op.uuid)
    if previa is not None and (previa.usuario_id != actor.id or previa.sede_id != sede.id):
        return (
            ResultadoOperacion(
                uuid=op.uuid,
                estado="error",
                motivo="El identificador de la operación ya fue usado por otra operación.",
            ),
            None,
        )
    if previa is not None and previa.estado == dominio.APLICADA:
        return ResultadoOperacion(
            uuid=op.uuid, estado="ya_aplicada", orden_id=previa.orden_id
        ), None

    # Recuperación: el cierre quedó confirmado pero el registro de la operación no.
    cerrada = trabajos.orden_cerrada_por_uuid(db, sede.id, op.uuid)
    if cerrada is not None:
        _registrar(db, actor, sede, op, dominio.APLICADA, None, previa, cerrada)
        return _resultado(op, dominio.YA_APLICADA, None, cerrada), None

    orden = (
        trabajos.estado_orden_campo(db, sede.id, op.orden_id, actor.id)
        if op.orden_id is not None
        else None
    )
    decision = dominio.evaluar_operacion(op.tipo, op.orden_id, orden)
    if decision is not None:
        estado, motivo = decision
        _registrar(db, actor, sede, op, estado, motivo, previa, orden["id"] if orden else None)
        return _resultado(op, estado, motivo, op.orden_id), None

    assert op.orden_id is not None
    try:
        salida, notificar = trabajos.cerrar_orden_desde_campo(
            db,
            actor,
            sede,
            op.orden_id,
            op.payload,
            uuid_origen=op.uuid,
            ejecutada_en=dominio.fecha_ejecucion(op.creada_en, ahora),
        )
    except HTTPException as exc:
        db.rollback()
        estado = dominio.estado_por_http(exc.status_code)
        motivo = dominio.recortar_motivo(exc.detail)
        _registrar(db, actor, sede, op, estado, motivo, previa, op.orden_id)
        return _resultado(op, estado, motivo, op.orden_id), None
    except IntegrityError:
        # Otro lote con el mismo uuid ganó la carrera: el índice único lo detuvo.
        db.rollback()
        if trabajos.orden_cerrada_por_uuid(db, sede.id, op.uuid) is not None:
            return _resultado(op, dominio.YA_APLICADA, None, op.orden_id), None
        raise
    _registrar(db, actor, sede, op, dominio.APLICADA, None, previa, salida.id)
    return (
        ResultadoOperacion(uuid=op.uuid, estado="aplicada", orden_id=salida.id),
        salida.pqrs_id if notificar else None,
    )


def _sincronizar(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, entrada: SincronizarEntrada
) -> tuple[SincronizarSalida, list[int]]:
    ahora = datetime.now(UTC)
    resultados: dict[UUID, ResultadoOperacion] = {}
    pqrs_a_notificar: list[int] = []
    for op in entrada.operaciones:
        if op.uuid in resultados:
            continue
        resultado, pqrs_id = _aplicar(db, actor, sede, op, ahora)
        resultados[op.uuid] = resultado
        if pqrs_id is not None:
            pqrs_a_notificar.append(pqrs_id)
    conteo: dict[str, int] = {}
    for r in resultados.values():
        conteo[r.estado] = conteo.get(r.estado, 0) + 1
    log.info("lote de campo: %s", conteo)
    # Una operación repetida dentro del lote aparece una sola vez en la respuesta.
    return SincronizarSalida(resultados=list(resultados.values()), procesado_en=ahora), (
        pqrs_a_notificar
    )


async def sincronizar(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, entrada: SincronizarEntrada
) -> SincronizarSalida:
    salida, pqrs_ids = await run_in_threadpool(_sincronizar, db, actor, sede, entrada)
    for pqrs_id in pqrs_ids:
        await atencion.encolar_notificacion(pqrs_id, "atencion")
    return salida


# === Seguimiento en la oficina =================================================================


def listar_operaciones(
    db: Session, sede: SedeResumen, *, estado: str | None, page: int, size: int
) -> Pagina[OperacionCampoSalida]:
    filas, total = repositorio.listar(db, sede.id, estado=estado, page=page, size=size)
    return Pagina[OperacionCampoSalida](
        items=[OperacionCampoSalida.model_validate(f) for f in filas],
        total=total,
        page=page,
        size=size,
    )
