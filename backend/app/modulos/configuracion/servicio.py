"""Servicio público del módulo de configuración (EP-02).

Otros módulos usan solo este archivo: `obtener_valor_parametro`, `renderizar_plantilla`,
`obtener_vigencia_aprobada`, `listar_comercializadores_activos_sede`.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modulos.configuracion import datos_semilla, dominio, repositorio
from app.modulos.configuracion.esquemas import (
    AcuerdoCopiarEntrada,
    AcuerdoCrearEntrada,
    AcuerdoDetalle,
    AcuerdoEditarEntrada,
    AcuerdoResumen,
    BarrioCrearEntrada,
    BarrioEditarEntrada,
    BarrioSalida,
    CatalogoComercialCrearEntrada,
    CatalogoComercialEditarEntrada,
    CatalogoComercialSalida,
    ComercializadorSalida,
    EstadoEditarEntrada,
    EstadoSalida,
    ExcepcionEntrada,
    ExcepcionSalida,
    MaestroClaseSalida,
    MaestroValorCrearEntrada,
    MaestroValorEditarEntrada,
    MaestroValorSalida,
    ParametroEditarEntrada,
    ParametroSalida,
    PlantillaCorreoEditarEntrada,
    PlantillaCorreoSalida,
    SedeComercializadorEntrada,
    SedeComercializadorSalida,
    SedeCrearEntrada,
    SedeEditarEntrada,
    SedeSalida,
    TarifaEntrada,
    TarifaSalida,
    ZonaCrearEntrada,
    ZonaEditarEntrada,
    ZonaSalida,
)
from app.modulos.configuracion.modelos import (
    AcuerdoExcepcion,
    AcuerdoTarifa,
    AcuerdoVigencia,
    Barrio,
    Comercializador,
    ConceptoComercial,
    Estado,
    MaestroClase,
    MaestroValor,
    OperacionContable,
    Parametro,
    PlantillaCorreo,
    Sede,
    SedeComercializador,
    Zona,
)
from app.modulos.seguridad import servicio as seguridad
from app.modulos.seguridad.servicio import SedeResumen, UsuarioAutenticado

TipoCatalogo = Literal["conceptos", "operaciones"]
_MODELO_CATALOGO: dict[str, type[ConceptoComercial] | type[OperacionContable]] = {
    "conceptos": ConceptoComercial,
    "operaciones": OperacionContable,
}
PERMISO_ADMIN_SEDES = "configuracion.sede.administrar"
_BARRIO_DUPLICADO = "Ya existe un barrio con ese nombre en la zona."


def _http(exc: dominio.ErrorDominioConfiguracion) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _dominio[T](fn: Callable[[], T]) -> T:
    try:
        return fn()
    except dominio.ErrorDominioConfiguracion as exc:
        raise _http(exc) from exc


def _confirmar(db: Session, mensaje_conflicto: str) -> None:
    """Commit que traduce las violaciones de unicidad (carreras incluidas) a 409."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=mensaje_conflicto) from exc


def _auditar(
    db: Session,
    actor: UsuarioAutenticado,
    *,
    accion: str,
    entidad: str,
    entidad_id: Any,
    sede_id: int | None = None,
    antes: dict[str, Any] | None = None,
    despues: dict[str, Any] | None = None,
) -> None:
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede_id,
        accion=accion,
        entidad=entidad,
        entidad_id=str(entidad_id),
        antes=antes,
        despues=despues,
    )


def _aplicar(objeto: Any, cambios: dict[str, Any]) -> None:
    for campo, valor in cambios.items():
        setattr(objeto, campo, valor)


# === Sedes y comercializadores ==================================================================


def _a_sede(s: Sede) -> SedeSalida:
    return SedeSalida.model_validate(s, from_attributes=True)


def _a_comercializador(c: Comercializador) -> ComercializadorSalida:
    return ComercializadorSalida.model_validate(c, from_attributes=True)


def _a_asignacion(a: SedeComercializador) -> SedeComercializadorSalida:
    return SedeComercializadorSalida(
        comercializador_id=a.comercializador_id,
        comercializador_codigo=a.comercializador.codigo,
        comercializador_nombre=a.comercializador.nombre,
        activo=a.activo,
        desde=a.desde,
    )


def _ve_todas_las_sedes(usuario: UsuarioAutenticado) -> bool:
    return bool({PERMISO_ADMIN_SEDES, "seguridad.usuario.ver"} & set(usuario.permisos))


def listar_sedes(db: Session, usuario: UsuarioAutenticado) -> list[SedeSalida]:
    ids = None if _ve_todas_las_sedes(usuario) else {s.id for s in usuario.sedes}
    return [_a_sede(s) for s in repositorio.listar_sedes(db, ids)]


def crear_sede(db: Session, actor: UsuarioAutenticado, entrada: SedeCrearEntrada) -> SedeSalida:
    codigo = _dominio(lambda: dominio.normalizar_codigo_sede(entrada.codigo))
    if repositorio.obtener_sede_por_codigo(db, codigo) is not None:
        raise HTTPException(status_code=409, detail="Ya existe una sede con ese código.")
    sede = Sede(
        codigo=codigo,
        nombre=_dominio(lambda: dominio.normalizar_nombre(entrada.nombre)),
        municipio=_dominio(lambda: dominio.normalizar_nombre(entrada.municipio)),
        departamento=_dominio(lambda: dominio.normalizar_nombre(entrada.departamento)),
        activa=entrada.activa,
    )
    db.add(sede)
    db.flush()
    _sembrar_valores_por_sede(db, sede)
    # Quien crea la sede la configura: sin acceso, sus propias rutas de la sede darían 403.
    seguridad.asignar_sede_a_usuario(db, actor.id, sede.id)
    _auditar(
        db,
        actor,
        accion="crear",
        entidad="sede",
        entidad_id=sede.id,
        sede_id=sede.id,
        despues=_a_sede(sede).model_dump(mode="json"),
    )
    _confirmar(db, "Ya existe una sede con ese código.")
    db.refresh(sede)
    return _a_sede(sede)


def editar_sede(
    db: Session, actor: UsuarioAutenticado, sede_id: int, entrada: SedeEditarEntrada
) -> SedeSalida:
    sede = repositorio.obtener_sede(db, sede_id)
    if sede is None:
        raise HTTPException(status_code=404, detail="Sede no encontrada.")
    antes = _a_sede(sede).model_dump(mode="json")
    cambios = entrada.model_dump(exclude_unset=True)
    for campo in ("nombre", "municipio", "departamento"):
        if cambios.get(campo) is not None:
            cambios[campo] = _dominio(lambda c=campo: dominio.normalizar_nombre(cambios[c]))
        else:
            cambios.pop(campo, None)
    if cambios.get("activa") is None:
        cambios.pop("activa", None)
    _aplicar(sede, cambios)
    db.flush()
    _auditar(
        db,
        actor,
        accion="editar",
        entidad="sede",
        entidad_id=sede.id,
        sede_id=sede.id,
        antes=antes,
        despues=_a_sede(sede).model_dump(mode="json"),
    )
    _confirmar(db, "No se pudo editar la sede.")
    db.refresh(sede)
    return _a_sede(sede)


def listar_comercializadores(db: Session) -> list[ComercializadorSalida]:
    return [_a_comercializador(c) for c in repositorio.listar_comercializadores(db)]


def listar_comercializadores_sede(
    db: Session, usuario: UsuarioAutenticado, sede_id: int
) -> list[SedeComercializadorSalida]:
    if repositorio.obtener_sede(db, sede_id) is None:
        raise HTTPException(status_code=404, detail="Sede no encontrada.")
    if not _ve_todas_las_sedes(usuario) and sede_id not in {s.id for s in usuario.sedes}:
        raise HTTPException(status_code=403, detail="No tiene acceso a la sede solicitada.")
    return [_a_asignacion(a) for a in repositorio.listar_asignaciones_sede(db, sede_id)]


def reemplazar_comercializadores_sede(
    db: Session,
    actor: UsuarioAutenticado,
    sede_id: int,
    entradas: list[SedeComercializadorEntrada],
) -> list[SedeComercializadorSalida]:
    """Las asignaciones que no vienen en la lista quedan inactivas (se conserva el historial)."""
    if repositorio.obtener_sede(db, sede_id) is None:
        raise HTTPException(status_code=404, detail="Sede no encontrada.")
    codigos = _dominio(
        lambda: dominio.validar_asignaciones_unicas(e.comercializador_codigo for e in entradas)
    )
    actuales = {a.comercializador_id: a for a in repositorio.listar_asignaciones_sede(db, sede_id)}
    antes = [_a_asignacion(a).model_dump(mode="json") for a in actuales.values()]

    recibidos: set[int] = set()
    for codigo, entrada in zip(codigos, entradas, strict=True):
        com = repositorio.obtener_comercializador_por_codigo(db, codigo)
        if com is None:
            raise HTTPException(status_code=422, detail=f"El comercializador '{codigo}' no existe.")
        recibidos.add(com.id)
        asignacion = actuales.get(com.id)
        if asignacion is None:
            asignacion = SedeComercializador(sede_id=sede_id, comercializador_id=com.id)
            db.add(asignacion)
        asignacion.activo = entrada.activo
        asignacion.desde = entrada.desde
        asignacion.modificado_por = actor.id
    for com_id, asignacion in actuales.items():
        if com_id not in recibidos and asignacion.activo:
            asignacion.activo = False
            asignacion.modificado_por = actor.id
    db.flush()
    db.expire_all()
    despues = [
        _a_asignacion(a).model_dump(mode="json")
        for a in repositorio.listar_asignaciones_sede(db, sede_id)
    ]
    _auditar(
        db,
        actor,
        accion="editar",
        entidad="sede_comercializador",
        entidad_id=sede_id,
        sede_id=sede_id,
        antes={"asignaciones": antes},
        despues={"asignaciones": despues},
    )
    _confirmar(db, "No se pudieron guardar los comercializadores de la sede.")
    return [_a_asignacion(a) for a in repositorio.listar_asignaciones_sede(db, sede_id)]


def listar_comercializadores_activos_sede(db: Session, sede_id: int) -> list[str]:
    """Códigos de los comercializadores que operan hoy en la sede (para el módulo comercial)."""
    return [
        a.comercializador.codigo
        for a in repositorio.listar_asignaciones_sede(db, sede_id)
        if a.activo and a.comercializador.activo
    ]


# === Maestros ===================================================================================


def _obtener_clase(db: Session, clase_codigo: str) -> MaestroClase:
    clase = repositorio.obtener_clase_por_codigo(db, clase_codigo.strip().upper())
    if clase is None:
        raise HTTPException(status_code=404, detail="Clase de maestro no encontrada.")
    return clase


def _a_valor(v: MaestroValor, clase: MaestroClase) -> MaestroValorSalida:
    return MaestroValorSalida(
        id=v.id,
        clase_codigo=clase.codigo,
        codigo=v.codigo,
        nombre=v.nombre,
        orden=v.orden,
        activo=v.activo,
    )


def listar_clases(db: Session) -> list[MaestroClaseSalida]:
    return [
        MaestroClaseSalida(id=c.id, codigo=c.codigo, nombre=c.nombre, total_valores=n)
        for c, n in repositorio.listar_clases_con_conteo(db)
    ]


def listar_valores(
    db: Session, clase_codigo: str, *, activo: bool | None = None, buscar: str | None = None
) -> list[MaestroValorSalida]:
    clase = _obtener_clase(db, clase_codigo)
    return [
        _a_valor(v, clase)
        for v in repositorio.listar_valores(db, clase.id, activo=activo, buscar=buscar)
    ]


def crear_valor(
    db: Session, actor: UsuarioAutenticado, clase_codigo: str, entrada: MaestroValorCrearEntrada
) -> MaestroValorSalida:
    clase = _obtener_clase(db, clase_codigo)
    codigo = _dominio(lambda: dominio.normalizar_codigo_maestro(entrada.codigo))
    if repositorio.existe_valor_codigo(db, clase.id, codigo):
        raise HTTPException(status_code=409, detail="Ya existe un valor con ese código.")
    valor = MaestroValor(
        clase_id=clase.id,
        codigo=codigo,
        nombre=_dominio(lambda: dominio.normalizar_nombre(entrada.nombre)),
        orden=entrada.orden,
        activo=entrada.activo,
        creado_por=actor.id,
        modificado_por=actor.id,
    )
    db.add(valor)
    db.flush()
    _auditar(
        db,
        actor,
        accion="crear",
        entidad="maestro_valor",
        entidad_id=valor.id,
        despues=_a_valor(valor, clase).model_dump(mode="json"),
    )
    _confirmar(db, "Ya existe un valor con ese código.")
    return _a_valor(valor, clase)


def editar_valor(
    db: Session,
    actor: UsuarioAutenticado,
    clase_codigo: str,
    valor_id: int,
    entrada: MaestroValorEditarEntrada,
) -> MaestroValorSalida:
    clase = _obtener_clase(db, clase_codigo)
    valor = repositorio.obtener_valor(db, clase.id, valor_id)
    if valor is None:
        raise HTTPException(status_code=404, detail="Valor de maestro no encontrado.")
    antes = _a_valor(valor, clase).model_dump(mode="json")
    cambios = {k: v for k, v in entrada.model_dump(exclude_unset=True).items() if v is not None}
    if "nombre" in cambios:
        cambios["nombre"] = _dominio(lambda: dominio.normalizar_nombre(cambios["nombre"]))
    _aplicar(valor, cambios)
    valor.modificado_por = actor.id
    db.flush()
    _auditar(
        db,
        actor,
        accion="editar",
        entidad="maestro_valor",
        entidad_id=valor.id,
        antes=antes,
        despues=_a_valor(valor, clase).model_dump(mode="json"),
    )
    _confirmar(db, "No se pudo editar el valor.")
    return _a_valor(valor, clase)


# === Zonas y barrios ============================================================================


def _a_zona(z: Zona, total_barrios: int) -> ZonaSalida:
    return ZonaSalida(
        id=z.id, sede_id=z.sede_id, nombre=z.nombre, activa=z.activa, total_barrios=total_barrios
    )


def _a_barrio(b: Barrio, zona_nombre: str) -> BarrioSalida:
    return BarrioSalida(
        id=b.id,
        sede_id=b.sede_id,
        zona_id=b.zona_id,
        zona_nombre=zona_nombre,
        nombre=b.nombre,
        activo=b.activo,
    )


def listar_zonas(db: Session, sede: SedeResumen, activa: bool | None = None) -> list[ZonaSalida]:
    return [_a_zona(z, n) for z, n in repositorio.listar_zonas_con_conteo(db, sede.id, activa)]


def crear_zona(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, entrada: ZonaCrearEntrada
) -> ZonaSalida:
    nombre = _dominio(lambda: dominio.normalizar_nombre(entrada.nombre))
    if repositorio.existe_zona_nombre(db, sede.id, nombre):
        raise HTTPException(status_code=409, detail="Ya existe una zona con ese nombre.")
    zona = Zona(
        sede_id=sede.id,
        nombre=nombre,
        activa=entrada.activa,
        creado_por=actor.id,
        modificado_por=actor.id,
    )
    db.add(zona)
    db.flush()
    _auditar(
        db,
        actor,
        accion="crear",
        entidad="zona",
        entidad_id=zona.id,
        sede_id=sede.id,
        despues=_a_zona(zona, 0).model_dump(mode="json"),
    )
    _confirmar(db, "Ya existe una zona con ese nombre.")
    return _a_zona(zona, 0)


def editar_zona(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    zona_id: int,
    entrada: ZonaEditarEntrada,
) -> ZonaSalida:
    zona = repositorio.obtener_zona(db, sede.id, zona_id)
    if zona is None:
        raise HTTPException(status_code=404, detail="Zona no encontrada.")
    total = repositorio.contar_barrios_zona(db, zona.id)
    antes = _a_zona(zona, total).model_dump(mode="json")
    cambios = {k: v for k, v in entrada.model_dump(exclude_unset=True).items() if v is not None}
    if "nombre" in cambios:
        cambios["nombre"] = _dominio(lambda: dominio.normalizar_nombre(cambios["nombre"]))
        if repositorio.existe_zona_nombre(db, sede.id, cambios["nombre"], excluir_id=zona.id):
            raise HTTPException(status_code=409, detail="Ya existe una zona con ese nombre.")
    _aplicar(zona, cambios)
    zona.modificado_por = actor.id
    db.flush()
    _auditar(
        db,
        actor,
        accion="editar",
        entidad="zona",
        entidad_id=zona.id,
        sede_id=sede.id,
        antes=antes,
        despues=_a_zona(zona, total).model_dump(mode="json"),
    )
    _confirmar(db, "Ya existe una zona con ese nombre.")
    return _a_zona(zona, total)


def listar_barrios(
    db: Session,
    sede: SedeResumen,
    *,
    zona_id: int | None = None,
    activo: bool | None = None,
    buscar: str | None = None,
) -> list[BarrioSalida]:
    return [
        _a_barrio(b, zn)
        for b, zn in repositorio.listar_barrios(
            db, sede.id, zona_id=zona_id, activo=activo, buscar=buscar
        )
    ]


def crear_barrio(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, entrada: BarrioCrearEntrada
) -> BarrioSalida:
    # Una zona de otra sede responde igual que una inexistente: no se filtra su existencia.
    zona = repositorio.obtener_zona(db, sede.id, entrada.zona_id)
    if zona is None:
        raise HTTPException(status_code=404, detail="Zona no encontrada.")
    nombre = _dominio(lambda: dominio.normalizar_nombre(entrada.nombre))
    if repositorio.existe_barrio_nombre(db, zona.id, nombre):
        raise HTTPException(status_code=409, detail=_BARRIO_DUPLICADO)
    barrio = Barrio(
        sede_id=sede.id,
        zona_id=zona.id,
        nombre=nombre,
        activo=entrada.activo,
        creado_por=actor.id,
        modificado_por=actor.id,
    )
    db.add(barrio)
    db.flush()
    _auditar(
        db,
        actor,
        accion="crear",
        entidad="barrio",
        entidad_id=barrio.id,
        sede_id=sede.id,
        despues=_a_barrio(barrio, zona.nombre).model_dump(mode="json"),
    )
    _confirmar(db, _BARRIO_DUPLICADO)
    return _a_barrio(barrio, zona.nombre)


def editar_barrio(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    barrio_id: int,
    entrada: BarrioEditarEntrada,
) -> BarrioSalida:
    encontrado = repositorio.obtener_barrio(db, sede.id, barrio_id)
    if encontrado is None:
        raise HTTPException(status_code=404, detail="Barrio no encontrado.")
    barrio, zona_nombre = encontrado
    antes = _a_barrio(barrio, zona_nombre).model_dump(mode="json")
    cambios = {k: v for k, v in entrada.model_dump(exclude_unset=True).items() if v is not None}
    if "zona_id" in cambios:
        zona = repositorio.obtener_zona(db, sede.id, cambios["zona_id"])
        if zona is None:
            raise HTTPException(status_code=404, detail="Zona no encontrada.")
        zona_nombre = zona.nombre
    if "nombre" in cambios:
        cambios["nombre"] = _dominio(lambda: dominio.normalizar_nombre(cambios["nombre"]))
    zona_destino = cambios.get("zona_id", barrio.zona_id)
    nombre_destino = cambios.get("nombre", barrio.nombre)
    if repositorio.existe_barrio_nombre(db, zona_destino, nombre_destino, excluir_id=barrio.id):
        raise HTTPException(status_code=409, detail=_BARRIO_DUPLICADO)
    _aplicar(barrio, cambios)
    barrio.modificado_por = actor.id
    db.flush()
    _auditar(
        db,
        actor,
        accion="editar",
        entidad="barrio",
        entidad_id=barrio.id,
        sede_id=sede.id,
        antes=antes,
        despues=_a_barrio(barrio, zona_nombre).model_dump(mode="json"),
    )
    _confirmar(db, _BARRIO_DUPLICADO)
    return _a_barrio(barrio, zona_nombre)


# === Estados ====================================================================================


def _a_estado(e: Estado) -> EstadoSalida:
    return EstadoSalida.model_validate(e, from_attributes=True)


def listar_estados(
    db: Session, proceso: str | None = None, vigente: bool | None = None
) -> list[EstadoSalida]:
    return [_a_estado(e) for e in repositorio.listar_estados(db, proceso, vigente)]


def editar_estado(
    db: Session, actor: UsuarioAutenticado, estado_id: int, entrada: EstadoEditarEntrada
) -> EstadoSalida:
    estado = repositorio.obtener_estado(db, estado_id)
    if estado is None:
        raise HTTPException(status_code=404, detail="Estado no encontrado.")
    antes = _a_estado(estado).model_dump(mode="json")
    cambios = {k: v for k, v in entrada.model_dump(exclude_unset=True).items() if v is not None}
    if "nombre" in cambios:
        cambios["nombre"] = _dominio(lambda: dominio.normalizar_nombre(cambios["nombre"]))
    _aplicar(estado, cambios)
    estado.modificado_por = actor.id
    db.flush()
    _auditar(
        db,
        actor,
        accion="editar",
        entidad="estado",
        entidad_id=estado.id,
        antes=antes,
        despues=_a_estado(estado).model_dump(mode="json"),
    )
    _confirmar(db, "No se pudo editar el estado.")
    return _a_estado(estado)


# === Parámetros =================================================================================


def _a_parametro(p: Parametro) -> ParametroSalida:
    return ParametroSalida(
        id=p.id,
        sede_id=p.sede_id,
        alcance="global" if p.sede_id is None else "sede",
        codigo=p.codigo,
        nombre=p.nombre,
        valor=p.valor,
        editable=p.editable,
        modificado_en=p.modificado_en,
    )


def listar_parametros(db: Session, sede: SedeResumen) -> list[ParametroSalida]:
    return [_a_parametro(p) for p in repositorio.listar_parametros_visibles(db, sede.id)]


def editar_parametro(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    parametro_id: int,
    entrada: ParametroEditarEntrada,
) -> ParametroSalida:
    parametro = repositorio.obtener_parametro_visible(db, sede.id, parametro_id)
    if parametro is None:
        raise HTTPException(status_code=404, detail="Parámetro no encontrado.")
    if not parametro.editable:
        raise HTTPException(
            status_code=403,
            detail="Este parámetro lo fija la configuración del servidor y no se edita aquí.",
        )
    # Un parámetro global afecta a todas las sedes: solo quien administra sedes.
    if parametro.sede_id is None:
        seguridad.verificar_permiso(actor, PERMISO_ADMIN_SEDES)
    _dominio(lambda: dominio.validar_valor_parametro(parametro.codigo, entrada.valor))
    antes = _a_parametro(parametro).model_dump(mode="json")
    parametro.valor = entrada.valor
    parametro.modificado_por = actor.id
    db.flush()
    db.refresh(parametro)
    _auditar(
        db,
        actor,
        accion="editar",
        entidad="parametro",
        entidad_id=parametro.id,
        sede_id=parametro.sede_id,
        antes=antes,
        despues=_a_parametro(parametro).model_dump(mode="json"),
    )
    _confirmar(db, "No se pudo editar el parámetro.")
    return _a_parametro(parametro)


def obtener_valor_parametro(db: Session, codigo: str, sede_id: int) -> Any:
    """Valor vigente para la sede (el de la sede o, si no tiene, el global). None si no existe."""
    parametro = repositorio.obtener_parametro_por_codigo(db, codigo, sede_id)
    if parametro is None:
        parametro = repositorio.obtener_parametro_por_codigo(db, codigo, None)
    return parametro.valor if parametro is not None else None


# === Plantillas de correo =====================================================================


def _a_plantilla(p: PlantillaCorreo) -> PlantillaCorreoSalida:
    return PlantillaCorreoSalida.model_validate(p, from_attributes=True)


def listar_plantillas(db: Session, sede: SedeResumen) -> list[PlantillaCorreoSalida]:
    return [_a_plantilla(p) for p in repositorio.listar_plantillas(db, sede.id)]


def editar_plantilla(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    plantilla_id: int,
    entrada: PlantillaCorreoEditarEntrada,
) -> PlantillaCorreoSalida:
    plantilla = repositorio.obtener_plantilla(db, sede.id, plantilla_id)
    if plantilla is None:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada.")
    antes = _a_plantilla(plantilla).model_dump(mode="json")
    cambios = {k: v for k, v in entrada.model_dump(exclude_unset=True).items() if v is not None}
    asunto = cambios.get("asunto", plantilla.asunto).strip()
    cuerpo = cambios.get("cuerpo_html", plantilla.cuerpo_html)
    _dominio(lambda: dominio.validar_plantilla(asunto, cuerpo, plantilla.variables))
    if "asunto" in cambios:
        cambios["asunto"] = asunto
    _aplicar(plantilla, cambios)
    plantilla.modificado_por = actor.id
    db.flush()
    db.refresh(plantilla)
    _auditar(
        db,
        actor,
        accion="editar",
        entidad="plantilla_correo",
        entidad_id=plantilla.id,
        sede_id=sede.id,
        antes=antes,
        despues=_a_plantilla(plantilla).model_dump(mode="json"),
    )
    _confirmar(db, "No se pudo editar la plantilla.")
    return _a_plantilla(plantilla)


def renderizar_plantilla(
    db: Session, sede_id: int, codigo: str, contexto: dict[str, Any]
) -> tuple[str, str] | None:
    """(asunto, cuerpo_html) con las variables reemplazadas; los valores se escapan como HTML."""
    plantilla = repositorio.obtener_plantilla_por_codigo(db, sede_id, codigo)
    if plantilla is None or not plantilla.activa:
        return None
    permitidas = set(plantilla.variables)
    return (
        dominio.renderizar_texto(plantilla.asunto, permitidas, contexto, escapar_html=False),
        dominio.renderizar_texto(plantilla.cuerpo_html, permitidas, contexto, escapar_html=True),
    )


# === Acuerdos tarifarios ========================================================================


def _datos_acuerdo(
    uvt: Decimal | None,
    umbral_kwh: Decimal | None,
    tolerancia: Decimal | None,
    base: str | None,
    tarifas: list[Any],
    excepciones: list[Any],
) -> dominio.AcuerdoDatos:
    return dominio.AcuerdoDatos(
        uvt=uvt,
        umbral_kwh=umbral_kwh,
        tolerancia=tolerancia,
        base_costo_variable=base,
        tarifas=[
            dominio.TarifaDatos(
                tarifa=t.tarifa.strip(),
                tipo_regla=t.tipo_regla,
                factor_uvt_minimo=t.factor_uvt_minimo,
                porcentaje_costo_variable=t.porcentaje_costo_variable,
                valor_urbano=t.valor_urbano,
                valor_rural=t.valor_rural,
            )
            for t in tarifas
        ],
        excepciones=[
            dominio.ExcepcionDatos(
                identificador=e.identificador.strip(), factor_uvt=e.factor_uvt, regla=e.regla
            )
            for e in excepciones
        ],
    )


def _datos_de_modelo(a: AcuerdoVigencia) -> dominio.AcuerdoDatos:
    return _datos_acuerdo(
        a.uvt, a.umbral_kwh, a.tolerancia, a.base_costo_variable, a.tarifas, a.excepciones
    )


def _a_acuerdo_resumen(a: AcuerdoVigencia) -> AcuerdoResumen:
    return AcuerdoResumen(
        id=a.id,
        sede_id=a.sede_id,
        comercializador_codigo=a.comercializador.codigo,
        comercializador_nombre=a.comercializador.nombre,
        anio=a.anio,
        estado=a.estado,
        uvt=a.uvt,
        umbral_kwh=a.umbral_kwh,
        tolerancia=a.tolerancia,
        base_costo_variable=a.base_costo_variable,
        fuente=a.fuente,
        origen_id=a.origen_id,
        aprobado_por=a.aprobado_por,
        aprobado_en=a.aprobado_en,
        total_tarifas=len(a.tarifas),
        total_excepciones=len(a.excepciones),
        creado_en=a.creado_en,
        modificado_en=a.modificado_en,
    )


def _a_acuerdo_detalle(a: AcuerdoVigencia) -> AcuerdoDetalle:
    return AcuerdoDetalle(
        **_a_acuerdo_resumen(a).model_dump(),
        reglas=a.reglas,
        tarifas=[
            TarifaSalida(
                id=t.id,
                tarifa=t.tarifa,
                orden=t.orden,
                tipo_regla=t.tipo_regla,
                factor_uvt_minimo=t.factor_uvt_minimo,
                porcentaje_costo_variable=t.porcentaje_costo_variable,
                valor_urbano=t.valor_urbano,
                valor_rural=t.valor_rural,
                valor_minimo=dominio.valor_minimo(a.uvt, t.factor_uvt_minimo),
            )
            for t in a.tarifas
        ],
        excepciones=[
            ExcepcionSalida.model_validate(e, from_attributes=True) for e in a.excepciones
        ],
    )


def _snapshot_acuerdo(a: AcuerdoVigencia) -> dict[str, Any]:
    datos = _a_acuerdo_detalle(a).model_dump(mode="json")
    # En la bitácora basta el identificador y el factor de cada contribuyente especial.
    datos["excepciones"] = [
        {"identificador": e["identificador"], "factor_uvt": e["factor_uvt"]}
        for e in datos["excepciones"]
    ]
    return datos


def _tarifas_modelo(tarifas: list[TarifaEntrada]) -> list[AcuerdoTarifa]:
    return [
        AcuerdoTarifa(
            tarifa=t.tarifa.strip(),
            orden=i,
            tipo_regla=t.tipo_regla,
            factor_uvt_minimo=t.factor_uvt_minimo,
            porcentaje_costo_variable=t.porcentaje_costo_variable,
            valor_urbano=t.valor_urbano,
            valor_rural=t.valor_rural,
        )
        for i, t in enumerate(tarifas)
    ]


def _excepciones_modelo(excepciones: list[ExcepcionEntrada]) -> list[AcuerdoExcepcion]:
    return [
        AcuerdoExcepcion(
            identificador=e.identificador.strip(),
            nombre=e.nombre.strip() if e.nombre else None,
            factor_uvt=e.factor_uvt,
            regla=e.regla,
            activo=e.activo,
        )
        for e in excepciones
    ]


def _comercializador_de_sede(db: Session, sede_id: int, codigo: str) -> Comercializador:
    com = repositorio.obtener_comercializador_por_codigo(db, codigo)
    asignacion = repositorio.obtener_asignacion(db, sede_id, com.id) if com else None
    if com is None or asignacion is None or not asignacion.activo:
        raise HTTPException(
            status_code=422, detail=f"El comercializador '{codigo}' no opera en esta sede."
        )
    return com


def _obtener_acuerdo(
    db: Session, sede: SedeResumen, acuerdo_id: int, *, bloquear: bool = False
) -> AcuerdoVigencia:
    acuerdo = repositorio.obtener_acuerdo(db, sede.id, acuerdo_id, bloquear=bloquear)
    if acuerdo is None:
        raise HTTPException(status_code=404, detail="Acuerdo no encontrado.")
    return acuerdo


def listar_acuerdos(
    db: Session,
    sede: SedeResumen,
    *,
    comercializador: str | None = None,
    anio: int | None = None,
    estado: str | None = None,
) -> list[AcuerdoResumen]:
    com_id = None
    if comercializador:
        com = repositorio.obtener_comercializador_por_codigo(db, comercializador)
        if com is None:
            return []
        com_id = com.id
    return [
        _a_acuerdo_resumen(a)
        for a in repositorio.listar_acuerdos(
            db, sede.id, comercializador_id=com_id, anio=anio, estado=estado
        )
    ]


def obtener_acuerdo(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, acuerdo_id: int
) -> AcuerdoDetalle:
    acuerdo = _obtener_acuerdo(db, sede, acuerdo_id)
    if acuerdo.excepciones:
        # Las excepciones identifican contribuyentes (NIC/cuenta): se audita quién las consultó.
        seguridad.registrar_auditoria_consulta(
            db,
            usuario_id=actor.id,
            sede_id=sede.id,
            recurso="acuerdo.detalle",
            parametros_permitidos={"acuerdo_id": acuerdo.id},
        )
        db.commit()
    return _a_acuerdo_detalle(acuerdo)


def crear_acuerdo(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, entrada: AcuerdoCrearEntrada
) -> AcuerdoDetalle:
    com = _comercializador_de_sede(db, sede.id, entrada.comercializador_codigo)
    regla = _dominio(lambda: dominio.validar_regla_admite_acuerdo(com.regla_tarifaria, com.codigo))
    datos = _datos_acuerdo(
        entrada.uvt,
        entrada.umbral_kwh,
        entrada.tolerancia,
        entrada.base_costo_variable,
        entrada.tarifas,
        entrada.excepciones,
    )
    _dominio(lambda: dominio.validar_estructura_acuerdo(regla, datos))
    if repositorio.obtener_acuerdo_en_estado(db, sede.id, com.id, entrada.anio, "borrador"):
        raise HTTPException(
            status_code=409, detail="Ya hay un borrador para ese comercializador y año."
        )
    acuerdo = AcuerdoVigencia(
        sede_id=sede.id,
        comercializador_id=com.id,
        anio=entrada.anio,
        estado="borrador",
        uvt=entrada.uvt,
        umbral_kwh=entrada.umbral_kwh,
        tolerancia=entrada.tolerancia,
        base_costo_variable=entrada.base_costo_variable,
        reglas=entrada.reglas,
        fuente=entrada.fuente,
        creado_por=actor.id,
        modificado_por=actor.id,
        tarifas=_tarifas_modelo(entrada.tarifas),
        excepciones=_excepciones_modelo(entrada.excepciones),
    )
    db.add(acuerdo)
    db.flush()
    db.refresh(acuerdo)
    _auditar(
        db,
        actor,
        accion="crear",
        entidad="acuerdo_vigencia",
        entidad_id=acuerdo.id,
        sede_id=sede.id,
        despues=_snapshot_acuerdo(acuerdo),
    )
    _confirmar(db, "Ya hay un borrador para ese comercializador y año.")
    return _a_acuerdo_detalle(acuerdo)


def editar_acuerdo(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    acuerdo_id: int,
    entrada: AcuerdoEditarEntrada,
) -> AcuerdoDetalle:
    acuerdo = _obtener_acuerdo(db, sede, acuerdo_id, bloquear=True)
    _dominio(lambda: dominio.validar_editable(acuerdo.estado))
    cambios = entrada.model_dump(exclude_unset=True)
    tarifas = entrada.tarifas if "tarifas" in cambios and entrada.tarifas is not None else None
    excepciones = (
        entrada.excepciones
        if "excepciones" in cambios and entrada.excepciones is not None
        else None
    )
    simples = {
        k: getattr(entrada, k)
        for k in ("uvt", "umbral_kwh", "tolerancia", "base_costo_variable", "fuente")
        if k in cambios
    }
    if "reglas" in cambios:
        simples["reglas"] = entrada.reglas or {}

    datos = _datos_acuerdo(
        simples.get("uvt", acuerdo.uvt),
        simples.get("umbral_kwh", acuerdo.umbral_kwh),
        simples.get("tolerancia", acuerdo.tolerancia),
        simples.get("base_costo_variable", acuerdo.base_costo_variable),
        tarifas if tarifas is not None else acuerdo.tarifas,
        excepciones if excepciones is not None else acuerdo.excepciones,
    )
    regla = acuerdo.comercializador.regla_tarifaria or ""
    _dominio(lambda: dominio.validar_estructura_acuerdo(regla, datos))

    antes = _snapshot_acuerdo(acuerdo)
    _aplicar(acuerdo, simples)
    if tarifas is not None:
        acuerdo.tarifas.clear()
        db.flush()
        acuerdo.tarifas.extend(_tarifas_modelo(tarifas))
    if excepciones is not None:
        acuerdo.excepciones.clear()
        db.flush()
        acuerdo.excepciones.extend(_excepciones_modelo(excepciones))
    acuerdo.modificado_por = actor.id
    db.flush()
    db.refresh(acuerdo)
    _auditar(
        db,
        actor,
        accion="editar",
        entidad="acuerdo_vigencia",
        entidad_id=acuerdo.id,
        sede_id=sede.id,
        antes=antes,
        despues=_snapshot_acuerdo(acuerdo),
    )
    _confirmar(db, "No se pudo editar el acuerdo.")
    return _a_acuerdo_detalle(acuerdo)


def copiar_acuerdo(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    acuerdo_id: int,
    entrada: AcuerdoCopiarEntrada,
) -> AcuerdoDetalle:
    """Nueva vigencia en borrador a partir de otra (p. ej., la del año anterior)."""
    origen = _obtener_acuerdo(db, sede, acuerdo_id)
    if repositorio.obtener_acuerdo_en_estado(
        db, sede.id, origen.comercializador_id, entrada.anio_destino, "borrador"
    ):
        raise HTTPException(
            status_code=409, detail="Ya hay un borrador para ese comercializador y año."
        )
    copia = AcuerdoVigencia(
        sede_id=sede.id,
        comercializador_id=origen.comercializador_id,
        anio=entrada.anio_destino,
        estado="borrador",
        uvt=origen.uvt,
        umbral_kwh=origen.umbral_kwh,
        tolerancia=origen.tolerancia,
        base_costo_variable=origen.base_costo_variable,
        reglas=dict(origen.reglas),
        fuente=origen.fuente,
        origen_id=origen.id,
        creado_por=actor.id,
        modificado_por=actor.id,
        tarifas=[
            AcuerdoTarifa(
                tarifa=t.tarifa,
                orden=t.orden,
                tipo_regla=t.tipo_regla,
                factor_uvt_minimo=t.factor_uvt_minimo,
                porcentaje_costo_variable=t.porcentaje_costo_variable,
                valor_urbano=t.valor_urbano,
                valor_rural=t.valor_rural,
            )
            for t in origen.tarifas
        ],
        excepciones=[
            AcuerdoExcepcion(
                identificador=e.identificador,
                nombre=e.nombre,
                factor_uvt=e.factor_uvt,
                regla=e.regla,
                activo=e.activo,
            )
            for e in origen.excepciones
        ],
    )
    db.add(copia)
    db.flush()
    db.refresh(copia)
    _auditar(
        db,
        actor,
        accion="copiar",
        entidad="acuerdo_vigencia",
        entidad_id=copia.id,
        sede_id=sede.id,
        despues={**_snapshot_acuerdo(copia), "copiado_de": origen.id},
    )
    _confirmar(db, "Ya hay un borrador para ese comercializador y año.")
    return _a_acuerdo_detalle(copia)


def aprobar_acuerdo(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    acuerdo_id: int,
    observacion: str | None = None,
) -> AcuerdoDetalle:
    """Borrador -> aprobado. Si ya había una vigencia aprobada del mismo año, queda reemplazada."""
    acuerdo = _obtener_acuerdo(db, sede, acuerdo_id, bloquear=True)
    regla = acuerdo.comercializador.regla_tarifaria or ""
    _dominio(lambda: dominio.validar_aprobable(acuerdo.estado, regla, _datos_de_modelo(acuerdo)))

    anterior = repositorio.obtener_acuerdo_en_estado(
        db, sede.id, acuerdo.comercializador_id, acuerdo.anio, "aprobado"
    )
    if anterior is not None:
        anterior.estado = "reemplazado"
        anterior.modificado_por = actor.id
        db.flush()
        _auditar(
            db,
            actor,
            accion="reemplazar",
            entidad="acuerdo_vigencia",
            entidad_id=anterior.id,
            sede_id=sede.id,
            antes={"estado": "aprobado"},
            despues={"estado": "reemplazado", "reemplazado_por": acuerdo.id},
        )

    acuerdo.estado = "aprobado"
    acuerdo.aprobado_por = actor.id
    acuerdo.aprobado_en = datetime.now(UTC)
    acuerdo.modificado_por = actor.id
    db.flush()
    db.refresh(acuerdo)
    _auditar(
        db,
        actor,
        accion="aprobar",
        entidad="acuerdo_vigencia",
        entidad_id=acuerdo.id,
        sede_id=sede.id,
        antes={"estado": "borrador"},
        despues={**_snapshot_acuerdo(acuerdo), "observacion": observacion},
    )
    _confirmar(db, "Otra aprobación del mismo año se registró al mismo tiempo; recargue.")
    return _a_acuerdo_detalle(acuerdo)


def obtener_vigencia_aprobada(
    db: Session, sede_id: int, comercializador_codigo: str, anio: int
) -> AcuerdoDetalle | None:
    """Vigencia con la que se calcula un periodo de ese año (RN-005). None si no hay."""
    com = repositorio.obtener_comercializador_por_codigo(db, comercializador_codigo)
    if com is None:
        return None
    acuerdo = repositorio.obtener_acuerdo_en_estado(db, sede_id, com.id, anio, "aprobado")
    return _a_acuerdo_detalle(acuerdo) if acuerdo is not None else None


# === Catálogos comerciales =====================================================================


def _a_item_catalogo(item: ConceptoComercial | OperacionContable) -> CatalogoComercialSalida:
    return CatalogoComercialSalida(
        id=item.id,
        comercializador_codigo=item.comercializador.codigo,
        codigo=item.codigo,
        descripcion=item.descripcion,
        entra_al_calculo=item.entra_al_calculo,
        activo=item.activo,
    )


def listar_catalogo(
    db: Session,
    tipo: TipoCatalogo,
    *,
    comercializador: str | None = None,
    activo: bool | None = None,
) -> list[CatalogoComercialSalida]:
    com_id = None
    if comercializador:
        com = repositorio.obtener_comercializador_por_codigo(db, comercializador)
        if com is None:
            return []
        com_id = com.id
    return [
        _a_item_catalogo(i)
        for i in repositorio.listar_catalogo(
            db, _MODELO_CATALOGO[tipo], comercializador_id=com_id, activo=activo
        )
    ]


def crear_item_catalogo(
    db: Session,
    actor: UsuarioAutenticado,
    tipo: TipoCatalogo,
    entrada: CatalogoComercialCrearEntrada,
) -> CatalogoComercialSalida:
    modelo = _MODELO_CATALOGO[tipo]
    com = repositorio.obtener_comercializador_por_codigo(db, entrada.comercializador_codigo)
    if com is None:
        raise HTTPException(status_code=422, detail="El comercializador no existe.")
    codigo = _dominio(lambda: dominio.normalizar_codigo_comercial(entrada.codigo))
    if repositorio.existe_item_catalogo(db, modelo, com.id, codigo):
        raise HTTPException(status_code=409, detail="Ya existe ese código para el comercializador.")
    item = modelo(
        comercializador_id=com.id,
        codigo=codigo,
        descripcion=entrada.descripcion.strip(),
        entra_al_calculo=entrada.entra_al_calculo,
        activo=entrada.activo,
        modificado_por=actor.id,
    )
    db.add(item)
    db.flush()
    db.refresh(item)
    _auditar(
        db,
        actor,
        accion="crear",
        entidad=modelo.__tablename__,
        entidad_id=item.id,
        despues=_a_item_catalogo(item).model_dump(mode="json"),
    )
    _confirmar(db, "Ya existe ese código para el comercializador.")
    return _a_item_catalogo(item)


def editar_item_catalogo(
    db: Session,
    actor: UsuarioAutenticado,
    tipo: TipoCatalogo,
    item_id: int,
    entrada: CatalogoComercialEditarEntrada,
) -> CatalogoComercialSalida:
    modelo = _MODELO_CATALOGO[tipo]
    item = repositorio.obtener_item_catalogo(db, modelo, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Elemento del catálogo no encontrado.")
    antes = _a_item_catalogo(item).model_dump(mode="json")
    cambios = {k: v for k, v in entrada.model_dump(exclude_unset=True).items() if v is not None}
    if "descripcion" in cambios:
        cambios["descripcion"] = cambios["descripcion"].strip()
    _aplicar(item, cambios)
    item.modificado_por = actor.id
    db.flush()
    _auditar(
        db,
        actor,
        accion="editar",
        entidad=modelo.__tablename__,
        entidad_id=item.id,
        antes=antes,
        despues=_a_item_catalogo(item).model_dump(mode="json"),
    )
    _confirmar(db, "No se pudo editar el elemento del catálogo.")
    return _a_item_catalogo(item)


# === Semilla (python -m app.semillas) ==========================================================


def _sembrar_valores_por_sede(db: Session, sede: Sede) -> int:
    """Parámetros y plantillas por defecto de una sede (también al crear una sede nueva)."""
    creados = 0
    for codigo, (nombre, valor, editable) in datos_semilla.PARAMETROS_POR_SEDE.items():
        if repositorio.obtener_parametro_por_codigo(db, codigo, sede.id) is None:
            db.add(
                Parametro(
                    sede_id=sede.id, codigo=codigo, nombre=nombre, valor=valor, editable=editable
                )
            )
            creados += 1
    for codigo, (nombre, asunto, cuerpo, variables) in datos_semilla.PLANTILLAS_CORREO.items():
        if repositorio.obtener_plantilla_por_codigo(db, sede.id, codigo) is None:
            db.add(
                PlantillaCorreo(
                    sede_id=sede.id,
                    codigo=codigo,
                    nombre=nombre,
                    asunto=asunto,
                    cuerpo_html=cuerpo,
                    variables=list(variables),
                )
            )
            creados += 1
    db.flush()
    return creados


def sembrar_catalogos(db: Session, *, archivo_max_evidencia_mb: int) -> dict[str, int]:
    """Idempotente: crea lo que falte por su llave natural; no modifica lo existente.

    Excepción: los parámetros de sistema (no editables) toman el valor actual del servidor.
    No hace commit: lo decide quien la llama.
    """
    n: dict[str, int] = dict.fromkeys(
        (
            "sedes",
            "comercializadores",
            "asignaciones",
            "clases",
            "valores",
            "estados",
            "zonas",
            "barrios",
            "por_sede",
            "acuerdos",
            "conceptos",
            "operaciones",
        ),
        0,
    )

    sedes: dict[str, Sede] = {}
    for datos in datos_semilla.SEDES:
        sede = repositorio.obtener_sede_por_codigo(db, datos["codigo"])
        if sede is None:
            sede = Sede(**datos, activa=True)
            db.add(sede)
            n["sedes"] += 1
        sedes[sede.codigo] = sede
    db.flush()

    coms: dict[str, Comercializador] = {}
    for codigo, (nombre, ident, regla, periodicidad) in datos_semilla.COMERCIALIZADORES.items():
        com = repositorio.obtener_comercializador_por_codigo(db, codigo)
        if com is None:
            com = Comercializador(
                codigo=codigo,
                nombre=nombre,
                identificador_usuario=ident,
                regla_tarifaria=regla,
                periodicidad=periodicidad,
            )
            db.add(com)
            n["comercializadores"] += 1
        coms[codigo] = com
    db.flush()

    for sede_codigo, com_codigos in datos_semilla.SEDE_COMERCIALIZADORES.items():
        for com_codigo in com_codigos:
            sede, com = sedes[sede_codigo], coms[com_codigo]
            if repositorio.obtener_asignacion(db, sede.id, com.id) is None:
                db.add(SedeComercializador(sede_id=sede.id, comercializador_id=com.id))
                n["asignaciones"] += 1

    for clase_codigo, (clase_nombre, valores) in datos_semilla.MAESTROS.items():
        clase = repositorio.obtener_clase_por_codigo(db, clase_codigo)
        if clase is None:
            clase = MaestroClase(codigo=clase_codigo, nombre=clase_nombre)
            db.add(clase)
            db.flush()
            n["clases"] += 1
        presentes = {v.codigo for v in repositorio.listar_valores(db, clase.id)}
        for orden, (codigo, nombre) in enumerate(valores):
            if codigo not in presentes:
                db.add(MaestroValor(clase_id=clase.id, codigo=codigo, nombre=nombre, orden=orden))
                n["valores"] += 1

    existentes = {(e.proceso, e.codigo) for e in repositorio.listar_estados(db)}
    for proceso, estados in datos_semilla.ESTADOS.items():
        for orden, (codigo, nombre, final, vigente) in enumerate(estados):
            if (proceso, codigo) not in existentes:
                db.add(
                    Estado(
                        proceso=proceso,
                        codigo=codigo,
                        nombre=nombre,
                        orden=orden,
                        final=final,
                        vigente=vigente,
                    )
                )
                n["estados"] += 1
    db.flush()

    for sede_codigo, zonas in datos_semilla.ZONAS_BARRIOS.items():
        sede = sedes[sede_codigo]
        actuales = {
            z.nombre.lower(): z for z, _ in repositorio.listar_zonas_con_conteo(db, sede.id)
        }
        for zona_nombre, barrios in zonas.items():
            zona = actuales.get(zona_nombre.lower())
            if zona is None:
                zona = Zona(sede_id=sede.id, nombre=zona_nombre)
                db.add(zona)
                db.flush()
                n["zonas"] += 1
            en_zona = repositorio.listar_barrios(db, sede.id, zona_id=zona.id)
            presentes = {b.nombre.lower() for b, _ in en_zona}
            for barrio_nombre in barrios:
                if barrio_nombre.lower() not in presentes:
                    db.add(Barrio(sede_id=sede.id, zona_id=zona.id, nombre=barrio_nombre))
                    n["barrios"] += 1
        db.flush()

    for sede in repositorio.listar_sedes(db):
        n["por_sede"] += _sembrar_valores_por_sede(db, sede)

    for codigo, nombre in datos_semilla.PARAMETROS_SISTEMA.items():
        parametro = repositorio.obtener_parametro_por_codigo(db, codigo, None)
        valor = {"valor": archivo_max_evidencia_mb}
        if parametro is None:
            db.add(
                Parametro(sede_id=None, codigo=codigo, nombre=nombre, valor=valor, editable=False)
            )
        else:
            parametro.valor, parametro.editable = valor, False
    db.flush()

    ahora = datetime.now(UTC)
    for datos in datos_semilla.ACUERDOS_2026:
        sede, com = sedes[str(datos["sede"])], coms[str(datos["comercializador"])]
        anio = int(str(datos["anio"]))
        if repositorio.existe_acuerdo(db, sede.id, com.id, anio):
            continue
        tarifas = [TarifaEntrada(**t) for t in datos["tarifas"]]
        db.add(
            AcuerdoVigencia(
                sede_id=sede.id,
                comercializador_id=com.id,
                anio=anio,
                estado="aprobado",
                uvt=datos["uvt"],
                umbral_kwh=datos["umbral_kwh"],
                tolerancia=datos["tolerancia"],
                base_costo_variable=datos["base_costo_variable"],
                reglas=datos["reglas"],
                fuente=datos["fuente"],
                aprobado_en=ahora,
                tarifas=_tarifas_modelo(tarifas),
            )
        )
        n["acuerdos"] += 1
    db.flush()

    afinia = coms["afinia"]
    for clave, modelo, catalogo, en_calculo in (
        (
            "conceptos",
            ConceptoComercial,
            datos_semilla.CONCEPTOS_AFINIA,
            datos_semilla.CONCEPTOS_AFINIA_EN_CALCULO,
        ),
        ("operaciones", OperacionContable, datos_semilla.OPERACIONES_AFINIA, frozenset()),
    ):
        presentes = {
            i.codigo for i in repositorio.listar_catalogo(db, modelo, comercializador_id=afinia.id)
        }
        for codigo, descripcion in catalogo.items():
            if codigo not in presentes:
                db.add(
                    modelo(
                        comercializador_id=afinia.id,
                        codigo=codigo,
                        descripcion=descripcion,
                        entra_al_calculo=codigo in en_calculo,
                    )
                )
                n[clave] += 1
    db.flush()
    return n


# === Helpers públicos para otros módulos (frontera por servicio) ================================


def listar_sedes_activas_resumen(db: Session) -> list[dict[str, Any]]:
    return [
        {"id": s.id, "codigo": s.codigo, "nombre": s.nombre}
        for s in repositorio.listar_sedes(db)
        if s.activa
    ]


def obtener_sede_por_codigo_publico(db: Session, codigo: str) -> dict[str, Any] | None:
    s = repositorio.obtener_sede_por_codigo(db, codigo.strip().lower())
    if s is None:
        return None
    return {"id": s.id, "codigo": s.codigo, "nombre": s.nombre, "activa": s.activa}


def resolver_barrio_sede(db: Session, sede_id: int, barrio_id: int) -> dict[str, Any] | None:
    encontrado = repositorio.obtener_barrio(db, sede_id, barrio_id)
    if encontrado is None:
        return None
    barrio, zona_nombre = encontrado
    return {
        "id": barrio.id,
        "nombre": barrio.nombre,
        "zona_id": barrio.zona_id,
        "zona_nombre": zona_nombre,
    }


def resolver_barrio_por_nombre(db: Session, sede_id: int, nombre: str) -> dict[str, Any] | None:
    objetivo = nombre.strip().lower()
    for barrio, zona_nombre in repositorio.listar_barrios(db, sede_id):
        if barrio.nombre.strip().lower() == objetivo:
            return {
                "id": barrio.id,
                "nombre": barrio.nombre,
                "zona_id": barrio.zona_id,
                "zona_nombre": zona_nombre,
            }
    return None


def asegurar_zona_y_barrio(
    db: Session,
    sede_id: int,
    zona_nombre: str,
    barrio_nombre: str,
    *,
    actor_id: int | None = None,
) -> dict[str, Any]:
    zona_limpia = dominio.normalizar_nombre(zona_nombre)
    barrio_limpio = dominio.normalizar_nombre(barrio_nombre)
    zona = next(
        (
            z
            for z, _ in repositorio.listar_zonas_con_conteo(db, sede_id)
            if z.nombre.lower() == zona_limpia.lower()
        ),
        None,
    )
    if zona is None:
        zona = Zona(
            sede_id=sede_id,
            nombre=zona_limpia,
            activa=True,
            creado_por=actor_id,
            modificado_por=actor_id,
        )
        db.add(zona)
        db.flush()
    barrio = next(
        (
            b
            for b, _ in repositorio.listar_barrios(db, sede_id, zona_id=zona.id)
            if b.nombre.lower() == barrio_limpio.lower()
        ),
        None,
    )
    if barrio is None:
        barrio = Barrio(
            sede_id=sede_id,
            zona_id=zona.id,
            nombre=barrio_limpio,
            activo=True,
            creado_por=actor_id,
            modificado_por=actor_id,
        )
        db.add(barrio)
        db.flush()
    return {
        "id": barrio.id,
        "nombre": barrio.nombre,
        "zona_id": zona.id,
        "zona_nombre": zona.nombre,
    }


def obtener_estado_por_id_o_codigo(
    db: Session,
    proceso: str,
    *,
    estado_id: int | None = None,
    codigo: str | None = None,
) -> dict[str, Any] | None:
    estados = repositorio.listar_estados(db, proceso=proceso)
    for e in estados:
        if estado_id is not None and e.id == estado_id:
            return {"id": e.id, "codigo": e.codigo, "nombre": e.nombre, "final": e.final}
        if codigo is not None and e.codigo.strip().upper() == codigo.strip().upper():
            return {"id": e.id, "codigo": e.codigo, "nombre": e.nombre, "final": e.final}
    return None


def obtener_valor_maestro(
    db: Session,
    clase_codigo: str,
    *,
    valor_id: int | None = None,
    codigo: str | None = None,
) -> dict[str, Any] | None:
    clase = repositorio.obtener_clase_por_codigo(db, clase_codigo.strip().upper())
    if clase is None:
        return None
    valores = repositorio.listar_valores(db, clase.id)
    for v in valores:
        if valor_id is not None and v.id == valor_id:
            return {"id": v.id, "codigo": v.codigo, "nombre": v.nombre}
        if codigo is not None and v.codigo.strip().upper() == codigo.strip().upper():
            return {"id": v.id, "codigo": v.codigo, "nombre": v.nombre}
    return None


def asegurar_valor_maestro(
    db: Session,
    clase_codigo: str,
    codigo: str,
    nombre: str,
    *,
    actor_id: int | None = None,
) -> dict[str, Any]:
    clase = _obtener_clase(db, clase_codigo)
    codigo_norm = dominio.normalizar_codigo_maestro(codigo)
    for v in repositorio.listar_valores(db, clase.id):
        if v.codigo == codigo_norm or v.nombre.strip().lower() == nombre.strip().lower():
            return {"id": v.id, "codigo": v.codigo, "nombre": v.nombre}
    nuevo = MaestroValor(
        clase_id=clase.id,
        codigo=codigo_norm,
        nombre=dominio.normalizar_nombre(nombre),
        orden=900,
        activo=True,
        creado_por=actor_id,
        modificado_por=actor_id,
    )
    db.add(nuevo)
    db.flush()
    return {"id": nuevo.id, "codigo": nuevo.codigo, "nombre": nuevo.nombre}
