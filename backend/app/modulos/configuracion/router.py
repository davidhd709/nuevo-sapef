"""Rutas HTTP del módulo de configuración (EP-02).

Lectura de catálogos (maestros, estados, zonas, barrios, parámetros, plantillas): cualquier
usuario con sesión (y con la sede, si el recurso es por sede), porque los usan todos los
formularios y la app de campo. Escritura: el permiso `configuracion.*` de §4.3.
"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import obtener_sesion
from app.modulos.configuracion import servicio
from app.modulos.configuracion.esquemas import (
    AcuerdoAprobarEntrada,
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
    EstadoAcuerdo,
    EstadoEditarEntrada,
    EstadoSalida,
    MaestroClaseSalida,
    MaestroValorCrearEntrada,
    MaestroValorEditarEntrada,
    MaestroValorSalida,
    ParametroEditarEntrada,
    ParametroSalida,
    PlantillaCorreoEditarEntrada,
    PlantillaCorreoSalida,
    Proceso,
    SedeComercializadorEntrada,
    SedeComercializadorSalida,
    SedeCrearEntrada,
    SedeEditarEntrada,
    SedeSalida,
    ZonaCrearEntrada,
    ZonaEditarEntrada,
    ZonaSalida,
)
from app.modulos.seguridad.servicio import (
    SedeResumen,
    UsuarioAutenticado,
    requerir_permiso,
    requerir_sede,
    requerir_usuario,
)

router = APIRouter(tags=["configuracion"])

Db = Annotated[Session, Depends(obtener_sesion)]
Usuario = Annotated[UsuarioAutenticado, Depends(requerir_usuario)]
SedeActiva = Annotated[SedeResumen, Depends(requerir_sede)]


AdminSedes = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("configuracion.sede.administrar"))
]
EditaMaestros = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("configuracion.maestro.editar"))
]
EditaBarrios = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("configuracion.barrio.editar"))
]
EditaEstados = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("configuracion.estado.editar"))
]
EditaParametros = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("configuracion.parametro.editar"))
]
EditaPlantillas = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("configuracion.plantilla.editar"))
]
VeAcuerdos = Annotated[UsuarioAutenticado, Depends(requerir_permiso("configuracion.acuerdo.ver"))]
EditaAcuerdos = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("configuracion.acuerdo.editar"))
]
ApruebaAcuerdos = Annotated[
    UsuarioAutenticado, Depends(requerir_permiso("configuracion.acuerdo.aprobar"))
]


# --- Sedes y comercializadores ---------------------------------------------------------------


@router.get("/sedes", response_model=list[SedeSalida], summary="Listar sedes")
def listar_sedes(usuario: Usuario, db: Db) -> list[SedeSalida]:
    """Todas las sedes para quien administra sedes o usuarios; si no, solo las propias."""
    return servicio.listar_sedes(db, usuario)


@router.post("/sedes", response_model=SedeSalida, status_code=201, summary="Crear una sede")
def crear_sede(entrada: SedeCrearEntrada, actor: AdminSedes, db: Db) -> SedeSalida:
    return servicio.crear_sede(db, actor, entrada)


@router.patch("/sedes/{sede_id}", response_model=SedeSalida, summary="Editar una sede")
def editar_sede(sede_id: int, entrada: SedeEditarEntrada, actor: AdminSedes, db: Db) -> SedeSalida:
    return servicio.editar_sede(db, actor, sede_id, entrada)


@router.get(
    "/sedes/{sede_id}/comercializadores",
    response_model=list[SedeComercializadorSalida],
    summary="Comercializadores asignados a una sede",
)
def listar_comercializadores_sede(
    sede_id: int, usuario: Usuario, db: Db
) -> list[SedeComercializadorSalida]:
    return servicio.listar_comercializadores_sede(db, usuario, sede_id)


@router.put(
    "/sedes/{sede_id}/comercializadores",
    response_model=list[SedeComercializadorSalida],
    summary="Reemplazar los comercializadores de una sede (los omitidos quedan inactivos)",
)
def reemplazar_comercializadores_sede(
    sede_id: int,
    entradas: Annotated[list[SedeComercializadorEntrada], Body(max_length=50)],
    actor: AdminSedes,
    db: Db,
) -> list[SedeComercializadorSalida]:
    return servicio.reemplazar_comercializadores_sede(db, actor, sede_id, entradas)


@router.get(
    "/comercializadores",
    response_model=list[ComercializadorSalida],
    summary="Catálogo de comercializadores",
)
def listar_comercializadores(_: Usuario, db: Db) -> list[ComercializadorSalida]:
    return servicio.listar_comercializadores(db)


# --- Maestros --------------------------------------------------------------------------------


@router.get(
    "/maestros/clases", response_model=list[MaestroClaseSalida], summary="Clases de maestros"
)
def listar_clases(_: Usuario, db: Db) -> list[MaestroClaseSalida]:
    return servicio.listar_clases(db)


@router.get(
    "/maestros/{clase}",
    response_model=list[MaestroValorSalida],
    summary="Valores de una clase de maestro",
)
def listar_valores(
    clase: str,
    _: Usuario,
    db: Db,
    activo: bool | None = None,
    buscar: Annotated[str | None, Query(max_length=80)] = None,
) -> list[MaestroValorSalida]:
    return servicio.listar_valores(db, clase, activo=activo, buscar=buscar)


@router.post(
    "/maestros/{clase}",
    response_model=MaestroValorSalida,
    status_code=201,
    summary="Crear un valor de maestro",
)
def crear_valor(
    clase: str, entrada: MaestroValorCrearEntrada, actor: EditaMaestros, db: Db
) -> MaestroValorSalida:
    return servicio.crear_valor(db, actor, clase, entrada)


@router.patch(
    "/maestros/{clase}/{valor_id}",
    response_model=MaestroValorSalida,
    summary="Editar o inactivar un valor de maestro",
)
def editar_valor(
    clase: str, valor_id: int, entrada: MaestroValorEditarEntrada, actor: EditaMaestros, db: Db
) -> MaestroValorSalida:
    return servicio.editar_valor(db, actor, clase, valor_id, entrada)


# --- Zonas y barrios (por sede) --------------------------------------------------------------


@router.get("/zonas", response_model=list[ZonaSalida], summary="Zonas de la sede activa")
def listar_zonas(sede: SedeActiva, db: Db, activa: bool | None = None) -> list[ZonaSalida]:
    return servicio.listar_zonas(db, sede, activa)


@router.post("/zonas", response_model=ZonaSalida, status_code=201, summary="Crear una zona")
def crear_zona(
    entrada: ZonaCrearEntrada, sede: SedeActiva, actor: EditaBarrios, db: Db
) -> ZonaSalida:
    return servicio.crear_zona(db, actor, sede, entrada)


@router.patch("/zonas/{zona_id}", response_model=ZonaSalida, summary="Editar una zona")
def editar_zona(
    zona_id: int, entrada: ZonaEditarEntrada, sede: SedeActiva, actor: EditaBarrios, db: Db
) -> ZonaSalida:
    return servicio.editar_zona(db, actor, sede, zona_id, entrada)


@router.get("/barrios", response_model=list[BarrioSalida], summary="Barrios de la sede activa")
def listar_barrios(
    sede: SedeActiva,
    db: Db,
    zona_id: int | None = None,
    activo: bool | None = None,
    buscar: Annotated[str | None, Query(max_length=80)] = None,
) -> list[BarrioSalida]:
    return servicio.listar_barrios(db, sede, zona_id=zona_id, activo=activo, buscar=buscar)


@router.post("/barrios", response_model=BarrioSalida, status_code=201, summary="Crear un barrio")
def crear_barrio(
    entrada: BarrioCrearEntrada, sede: SedeActiva, actor: EditaBarrios, db: Db
) -> BarrioSalida:
    return servicio.crear_barrio(db, actor, sede, entrada)


@router.patch("/barrios/{barrio_id}", response_model=BarrioSalida, summary="Editar un barrio")
def editar_barrio(
    barrio_id: int, entrada: BarrioEditarEntrada, sede: SedeActiva, actor: EditaBarrios, db: Db
) -> BarrioSalida:
    return servicio.editar_barrio(db, actor, sede, barrio_id, entrada)


# --- Estados ---------------------------------------------------------------------------------


@router.get("/estados", response_model=list[EstadoSalida], summary="Estados por proceso")
def listar_estados(
    _: Usuario, db: Db, proceso: Proceso | None = None, vigente: bool | None = None
) -> list[EstadoSalida]:
    return servicio.listar_estados(db, proceso, vigente)


@router.patch("/estados/{estado_id}", response_model=EstadoSalida, summary="Editar un estado")
def editar_estado(
    estado_id: int, entrada: EstadoEditarEntrada, actor: EditaEstados, db: Db
) -> EstadoSalida:
    return servicio.editar_estado(db, actor, estado_id, entrada)


# --- Parámetros y plantillas -----------------------------------------------------------------


@router.get(
    "/parametros",
    response_model=list[ParametroSalida],
    summary="Parámetros de la sede activa y globales (sin credenciales)",
)
def listar_parametros(sede: SedeActiva, db: Db) -> list[ParametroSalida]:
    return servicio.listar_parametros(db, sede)


@router.patch(
    "/parametros/{parametro_id}", response_model=ParametroSalida, summary="Editar un parámetro"
)
def editar_parametro(
    parametro_id: int,
    entrada: ParametroEditarEntrada,
    sede: SedeActiva,
    actor: EditaParametros,
    db: Db,
) -> ParametroSalida:
    return servicio.editar_parametro(db, actor, sede, parametro_id, entrada)


@router.get(
    "/plantillas-correo",
    response_model=list[PlantillaCorreoSalida],
    summary="Plantillas de correo de la sede activa",
)
def listar_plantillas(sede: SedeActiva, db: Db) -> list[PlantillaCorreoSalida]:
    return servicio.listar_plantillas(db, sede)


@router.patch(
    "/plantillas-correo/{plantilla_id}",
    response_model=PlantillaCorreoSalida,
    summary="Editar una plantilla de correo",
)
def editar_plantilla(
    plantilla_id: int,
    entrada: PlantillaCorreoEditarEntrada,
    sede: SedeActiva,
    actor: EditaPlantillas,
    db: Db,
) -> PlantillaCorreoSalida:
    return servicio.editar_plantilla(db, actor, sede, plantilla_id, entrada)


# --- Acuerdos tarifarios (por sede) ------------------------------------------------------------


@router.get(
    "/acuerdos",
    response_model=list[AcuerdoResumen],
    summary="Vigencias del acuerdo tarifario de la sede activa",
)
def listar_acuerdos(
    sede: SedeActiva,
    _: VeAcuerdos,
    db: Db,
    comercializador: Annotated[str | None, Query(max_length=40)] = None,
    anio: Annotated[int | None, Query(ge=2000, le=2200)] = None,
    estado: EstadoAcuerdo | None = None,
) -> list[AcuerdoResumen]:
    return servicio.listar_acuerdos(
        db, sede, comercializador=comercializador, anio=anio, estado=estado
    )


@router.post(
    "/acuerdos",
    response_model=AcuerdoDetalle,
    status_code=201,
    summary="Crear una vigencia en borrador",
)
def crear_acuerdo(
    entrada: AcuerdoCrearEntrada, sede: SedeActiva, actor: EditaAcuerdos, db: Db
) -> AcuerdoDetalle:
    return servicio.crear_acuerdo(db, actor, sede, entrada)


@router.get(
    "/acuerdos/{acuerdo_id}",
    response_model=AcuerdoDetalle,
    summary="Detalle de una vigencia con tarifas y excepciones",
)
def obtener_acuerdo(
    acuerdo_id: int, sede: SedeActiva, actor: VeAcuerdos, db: Db
) -> AcuerdoDetalle:
    return servicio.obtener_acuerdo(db, actor, sede, acuerdo_id)


@router.patch(
    "/acuerdos/{acuerdo_id}",
    response_model=AcuerdoDetalle,
    summary="Editar una vigencia en borrador (aprobada: 409)",
)
def editar_acuerdo(
    acuerdo_id: int,
    entrada: AcuerdoEditarEntrada,
    sede: SedeActiva,
    actor: EditaAcuerdos,
    db: Db,
) -> AcuerdoDetalle:
    return servicio.editar_acuerdo(db, actor, sede, acuerdo_id, entrada)


@router.post(
    "/acuerdos/{acuerdo_id}/copiar",
    response_model=AcuerdoDetalle,
    status_code=201,
    summary="Copiar una vigencia a un borrador de otro año",
)
def copiar_acuerdo(
    acuerdo_id: int,
    entrada: AcuerdoCopiarEntrada,
    sede: SedeActiva,
    actor: EditaAcuerdos,
    db: Db,
) -> AcuerdoDetalle:
    return servicio.copiar_acuerdo(db, actor, sede, acuerdo_id, entrada)


@router.post(
    "/acuerdos/{acuerdo_id}/aprobar",
    response_model=AcuerdoDetalle,
    summary="Aprobar un borrador (reemplaza la vigencia aprobada del mismo año)",
)
def aprobar_acuerdo(
    acuerdo_id: int,
    sede: SedeActiva,
    actor: ApruebaAcuerdos,
    db: Db,
    entrada: AcuerdoAprobarEntrada | None = None,
) -> AcuerdoDetalle:
    observacion = entrada.observacion if entrada else None
    return servicio.aprobar_acuerdo(db, actor, sede, acuerdo_id, observacion)


# --- Catálogos comerciales (conceptos CI y operaciones OC) -----------------------------------


@router.get(
    "/comercial/catalogos/{tipo}",
    response_model=list[CatalogoComercialSalida],
    summary="Conceptos u operaciones contables de los comercializadores",
)
def listar_catalogo(
    tipo: servicio.TipoCatalogo,
    _: Usuario,
    db: Db,
    comercializador: Annotated[str | None, Query(max_length=40)] = None,
    activo: bool | None = None,
) -> list[CatalogoComercialSalida]:
    return servicio.listar_catalogo(db, tipo, comercializador=comercializador, activo=activo)


@router.post(
    "/comercial/catalogos/{tipo}",
    response_model=CatalogoComercialSalida,
    status_code=201,
    summary="Agregar un concepto u operación contable",
)
def crear_item_catalogo(
    tipo: servicio.TipoCatalogo,
    entrada: CatalogoComercialCrearEntrada,
    actor: EditaMaestros,
    db: Db,
) -> CatalogoComercialSalida:
    return servicio.crear_item_catalogo(db, actor, tipo, entrada)


@router.patch(
    "/comercial/catalogos/{tipo}/{item_id}",
    response_model=CatalogoComercialSalida,
    summary="Editar un concepto u operación contable (p. ej., «entra al cálculo»)",
)
def editar_item_catalogo(
    tipo: servicio.TipoCatalogo,
    item_id: int,
    entrada: CatalogoComercialEditarEntrada,
    actor: EditaMaestros,
    db: Db,
) -> CatalogoComercialSalida:
    return servicio.editar_item_catalogo(db, actor, tipo, item_id, entrada)
