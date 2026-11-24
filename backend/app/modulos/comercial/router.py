"""Rutas HTTP del módulo comercial (EP-08).

Permisos (§4.3): `comercial.cargue.crear` y `.eliminar` para los cargues; `comercial.analisis.ver`
para los análisis agregados; `comercial.nominal.ver` para todo lo que muestra usuarios con nombre,
dirección o saldo (se audita); `comercial.entregable.generar` y `comercial.exportar` para los
documentos y descargas.
"""

from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.db import obtener_sesion
from app.modulos.comercial import servicio
from app.modulos.comercial.esquemas import (
    AnalisisCatalogo,
    CargueEncolado,
    CargueSalida,
    CorteSalida,
    EntregableEntrada,
    HallazgoEditarEntrada,
    HallazgoEntrada,
    HallazgoSalida,
    ImportacionOpainnEntrada,
    PaginaDatos,
    PeriodoEntrada,
    SabanaEntrada,
    TareaExportacion,
)
from app.modulos.seguridad.servicio import (
    SedeResumen,
    UsuarioAutenticado,
    requerir_algun_permiso,
    requerir_permiso,
    requerir_sede,
    verificar_permiso,
)

router = APIRouter(prefix="/comercial", tags=["comercial"])
router_migracion = APIRouter(prefix="/migracion/comercial", tags=["migracion"])

Db = Annotated[Session, Depends(obtener_sesion)]
SedeActiva = Annotated[SedeResumen, Depends(requerir_sede)]
Analiza = Annotated[
    UsuarioAutenticado,
    Depends(requerir_algun_permiso("comercial.analisis.ver", "comercial.cargue.crear")),
]
Carga = Annotated[UsuarioAutenticado, Depends(requerir_permiso("comercial.cargue.crear"))]
Elimina = Annotated[UsuarioAutenticado, Depends(requerir_permiso("comercial.cargue.eliminar"))]
Nominal = Annotated[UsuarioAutenticado, Depends(requerir_permiso("comercial.nominal.ver"))]
Genera = Annotated[UsuarioAutenticado, Depends(requerir_permiso("comercial.entregable.generar"))]
Exporta = Annotated[UsuarioAutenticado, Depends(requerir_permiso("comercial.exportar"))]
Periodo = Annotated[str, Query(pattern=r"^\d{4}(0[1-9]|1[0-2])$")]
Objeto = dict[str, Any]

TipoEntregable = Literal["requerimiento", "analisis", "anexo-nominal", "informe-gerencial"]


# --- Cargues -------------------------------------------------------------------------------------


@router.get("/cargues/{cargue_id}", response_model=CargueSalida, summary="Detalle de un cargue")
def obtener_cargue_general(cargue_id: int, sede: SedeActiva, _: Analiza, db: Db) -> CargueSalida:
    return servicio.obtener_cargue(db, sede, cargue_id)


@router.post(
    "/{comercializador}/cargues",
    response_model=CargueEncolado,
    status_code=202,
    responses={
        200: {"model": CargueEncolado, "description": "Reintento con el mismo Idempotency-Key"}
    },
    summary="Cargar los archivos de un corte (se procesan en segundo plano)",
)
async def cargar(
    comercializador: str,
    sede: SedeActiva,
    actor: Carga,
    db: Db,
    files: Annotated[list[UploadFile], File(description="Archivos del corte")],
    periodo: Annotated[str, Form(description="Periodo AAAAMM")],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    salida, creado = await servicio.recibir_cargue(
        db, actor, sede, comercializador, periodo, files, idempotency_key
    )
    return JSONResponse(status_code=202 if creado else 200, content=salida.model_dump())


@router.get(
    "/{comercializador}/cargues",
    response_model=list[CargueSalida],
    summary="Cargues recientes del comercializador en la sede",
)
def listar_cargues(
    comercializador: str, sede: SedeActiva, _: Analiza, db: Db
) -> list[CargueSalida]:
    return servicio.listar_cargues(db, sede, comercializador)


@router.get(
    "/{comercializador}/cargues/{cargue_id}",
    response_model=CargueSalida,
    summary="Detalle de un cargue (avance, avisos y errores)",
)
def obtener_cargue(
    comercializador: str, cargue_id: int, sede: SedeActiva, _: Analiza, db: Db
) -> CargueSalida:
    return servicio.obtener_cargue(db, sede, cargue_id, comercializador)


@router.delete(
    "/{comercializador}/cargues/{cargue_id}",
    status_code=204,
    response_class=Response,
    summary="Eliminar un cargue (y su corte si está publicado)",
)
def eliminar_cargue(
    comercializador: str, cargue_id: int, sede: SedeActiva, actor: Elimina, db: Db
) -> Response:
    servicio.eliminar_cargue(db, actor, sede, comercializador, cargue_id)
    return Response(status_code=204)


# --- Cortes y catálogo ---------------------------------------------------------------------------


@router.get(
    "/{comercializador}/cortes",
    response_model=list[CorteSalida],
    summary="Cortes publicados (uno por periodo)",
)
def listar_cortes(comercializador: str, sede: SedeActiva, _: Analiza, db: Db) -> list[CorteSalida]:
    return servicio.listar_cortes(db, sede, comercializador)


@router.get(
    "/{comercializador}/cortes/{periodo}/datos",
    response_model=PaginaDatos,
    summary="Filas normalizadas de una familia del corte (nominal, se audita)",
)
def datos_corte(
    comercializador: str,
    periodo: str,
    sede: SedeActiva,
    actor: Nominal,
    db: Db,
    familia: Annotated[str, Query(max_length=30)],
    buscar: Annotated[str | None, Query(max_length=80)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=500)] = 50,
) -> PaginaDatos:
    return servicio.datos_corte(
        db, actor, sede, comercializador, periodo, familia, page=page, size=size, buscar=buscar
    )


@router.post(
    "/{comercializador}/cortes/{periodo}/sabana",
    response_model=TareaExportacion,
    status_code=202,
    summary="Sábana completa de una familia (CSV o Excel, en segundo plano)",
)
async def sabana(
    comercializador: str,
    periodo: str,
    entrada: SabanaEntrada,
    sede: SedeActiva,
    actor: Exporta,
    db: Db,
) -> TareaExportacion:
    verificar_permiso(actor, "comercial.nominal.ver")
    tarea = await servicio.encolar_sabana(
        db, actor, sede, comercializador, periodo, entrada.familia, entrada.formato
    )
    return TareaExportacion(id=tarea, tarea_id=tarea, tareaId=tarea)


@router.get(
    "/{comercializador}/catalogo",
    response_model=list[AnalisisCatalogo],
    summary="Catálogo de los 29 análisis con su disponibilidad",
)
def catalogo(comercializador: str, sede: SedeActiva, _: Analiza, db: Db) -> list[AnalisisCatalogo]:
    return servicio.catalogo(db, sede, comercializador)


# --- Análisis: resumen y flujos ------------------------------------------------------------------

A = "/{comercializador}/analisis"


@router.get(
    f"{A}/indicadores/{{periodo}}",
    response_model=Objeto,
    summary="Indicadores del corte frente al comparable",
)
def indicadores(comercializador: str, periodo: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.indicadores(db, sede, comercializador, periodo)


@router.get(f"{A}/serie", response_model=Objeto, summary="Facturación y recaudo por periodo")
def serie(comercializador: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.serie(db, sede, comercializador)


@router.get(f"{A}/eficiencia/{{periodo}}", response_model=Objeto, summary="Eficiencia de recaudo")
def eficiencia(comercializador: str, periodo: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.eficiencia(db, sede, comercializador, periodo)


@router.get(
    f"{A}/detalle/{{periodo}}",
    response_model=Objeto,
    summary="Usuarios detrás de un indicador (nominal, se audita)",
)
def detalle(
    comercializador: str,
    periodo: str,
    sede: SedeActiva,
    actor: Nominal,
    db: Db,
    indicador: Annotated[str, Query(max_length=60)] = "facturacion",
    limite: Annotated[int, Query(ge=1, le=50000)] = 500,
) -> Objeto:
    return servicio.detalle_indicador(db, actor, sede, comercializador, periodo, indicador, limite)


@router.get(f"{A}/facturacion/{{periodo}}", response_model=Objeto, summary="Facturación del corte")
def facturacion(comercializador: str, periodo: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.flujo(db, sede, comercializador, periodo, "facturacion")


@router.get(
    f"{A}/recaudo/{{periodo}}", response_model=Objeto, summary="Recaudo corriente y de cartera"
)
def recaudo(comercializador: str, periodo: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.flujo(db, sede, comercializador, periodo, "recaudo")


@router.get(f"{A}/cartera/{{periodo}}", response_model=Objeto, summary="Cartera del corte")
def cartera(comercializador: str, periodo: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.flujo(db, sede, comercializador, periodo, "cartera")


@router.get(f"{A}/cartera-edades/{{periodo}}", response_model=Objeto, summary="Cartera por edades")
def cartera_edades(
    comercializador: str, periodo: str, sede: SedeActiva, _: Analiza, db: Db
) -> Objeto:
    return servicio.cartera_edades(db, sede, comercializador, periodo)


@router.get(
    f"{A}/concentracion/{{periodo}}",
    response_model=Objeto,
    summary="Concentración de la cartera (top 10, 21, 100 y 1.000)",
)
def concentracion(
    comercializador: str, periodo: str, sede: SedeActiva, _: Analiza, db: Db
) -> Objeto:
    return servicio.concentracion(db, sede, comercializador, periodo)


# --- Análisis: usuarios --------------------------------------------------------------------------


@router.get(
    f"{A}/movimientos/{{periodo}}",
    response_model=Objeto,
    summary="Nuevos, reintegrados y dejados de facturar",
)
def movimientos(comercializador: str, periodo: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.movimientos(db, sede, comercializador, periodo)


@router.get(
    f"{A}/ausencias/{{periodo}}",
    response_model=Objeto,
    summary="Usuarios con periodos esperados sin facturarse",
)
def ausencias(
    comercializador: str,
    periodo: str,
    sede: SedeActiva,
    _: Analiza,
    db: Db,
    limite: Annotated[int, Query(ge=1, le=50000)] = 1000,
) -> Objeto:
    return servicio.ausencias(db, sede, comercializador, periodo, limite)


@router.get(
    f"{A}/disminuciones/{{periodo}}",
    response_model=Objeto,
    summary="Usuarios que explican las caídas frente al corte anterior",
)
def disminuciones(
    comercializador: str,
    periodo: str,
    sede: SedeActiva,
    _: Analiza,
    db: Db,
    variable: str = "facturado",
    minimo_pct: Decimal | None = None,
    maximo_pct: Decimal | None = None,
    segmento: Annotated[str | None, Query(max_length=80)] = None,
    barrio: Annotated[str | None, Query(max_length=120)] = None,
    solo_comerciales: bool = False,
    limite: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> Objeto:
    return servicio.disminuciones(
        db,
        sede,
        comercializador,
        periodo,
        variable=variable,
        minimo=minimo_pct,
        maximo=maximo_pct,
        segmento=segmento,
        barrio=barrio,
        solo_comerciales=solo_comerciales,
        limite=limite,
    )


@router.get(
    f"{A}/periodicidad/{{periodo}}",
    response_model=Objeto,
    summary="Usuarios por periodicidad (ciclo deducido)",
)
def periodicidad(
    comercializador: str,
    periodo: str,
    sede: SedeActiva,
    _: Analiza,
    db: Db,
    limite: Annotated[int, Query(ge=1, le=50000)] = 1000,
) -> Objeto:
    return servicio.periodicidad(db, sede, comercializador, periodo, limite)


# --- Análisis: hallazgos -------------------------------------------------------------------------


@router.get(
    f"{A}/control-tarifario/{{periodo}}",
    response_model=Objeto,
    summary="Control tarifario del impuesto (nominal, se audita)",
)
def control_tarifario(
    comercializador: str,
    periodo: str,
    sede: SedeActiva,
    actor: Nominal,
    db: Db,
    grupo_consumo: Literal["todos", "minima", "variable", "especial", "revision"] = "todos",
    estado: Literal["CORRECTO", "POR_ENCIMA", "POR_DEBAJO", "NO_VALIDABLE", "REQUIERE_REVISION"]
    | None = None,
    buscar: Annotated[str | None, Query(max_length=40)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> Objeto:
    return servicio.control_tarifario(
        db,
        actor,
        sede,
        comercializador,
        periodo,
        grupo_consumo=grupo_consumo,
        estado=estado,
        buscar=buscar,
        page=page,
        size=size,
    )


@router.get(
    f"{A}/facturas-revision/{{periodo}}",
    response_model=Objeto,
    summary="Facturas irregulares (5 categorías)",
)
def facturas_revision(
    comercializador: str, periodo: str, sede: SedeActiva, _: Analiza, db: Db
) -> Objeto:
    return servicio.facturas_revision(db, sede, comercializador, periodo)


# --- Análisis: históricos y gestión --------------------------------------------------------------


@router.get(
    f"{A}/consolidado-anual",
    response_model=Objeto,
    summary="Consolidado del año con cobertura de meses",
)
def consolidado_anual(
    comercializador: str,
    sede: SedeActiva,
    _: Analiza,
    db: Db,
    anio: Annotated[int | None, Query(ge=2000, le=2200)] = None,
) -> Objeto:
    return servicio.consolidado_anual(db, sede, comercializador, anio)


@router.get(f"{A}/historico-facturacion", response_model=Objeto, summary="Histórico de facturación")
def historico_facturacion(comercializador: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.historico(db, sede, comercializador, "historico-facturacion")


@router.get(f"{A}/historico-cartera", response_model=Objeto, summary="Histórico de cartera")
def historico_cartera(comercializador: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.historico(db, sede, comercializador, "historico-cartera")


@router.get(
    f"{A}/historico-comerciales",
    response_model=Objeto,
    summary="Histórico de los usuarios comerciales",
)
def historico_comerciales(comercializador: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.historico(db, sede, comercializador, "historico-comerciales")


@router.get(
    f"{A}/comportamiento-pago",
    response_model=Objeto,
    summary="Paga siempre, a veces o nunca (nominal, se audita)",
)
def comportamiento_pago(
    comercializador: str,
    sede: SedeActiva,
    actor: Nominal,
    db: Db,
    limite: Annotated[int, Query(ge=1, le=50000)] = 1000,
) -> Objeto:
    return servicio.comportamiento_pago(db, actor, sede, comercializador, limite)


@router.get(
    f"{A}/maduracion/{{periodo}}",
    response_model=Objeto,
    summary="Maduración del recaudo y curva de cohortes",
)
def maduracion(comercializador: str, periodo: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.maduracion(db, sede, comercializador, periodo)


@router.get(f"{A}/convenios/{{periodo}}", response_model=Objeto, summary="Convenios del corte")
def convenios(comercializador: str, periodo: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.convenios(db, sede, comercializador, periodo)


@router.get(
    f"{A}/convenios-ajustes",
    response_model=Objeto,
    summary="Cohortes de convenios y ajustes negativos del recaudo",
)
def convenios_ajustes(comercializador: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.convenios_ajustes(db, sede, comercializador)


@router.get(
    f"{A}/rutas-campo/{{periodo}}",
    response_model=Objeto,
    summary="Rutas de cobro y controles de campo (nominal, se audita)",
)
def rutas_campo(
    comercializador: str,
    periodo: str,
    sede: SedeActiva,
    actor: Nominal,
    db: Db,
    grupo: Literal["NUNCA_PAGA", "INTERMITENTE", "PAGA_SIEMPRE"] = "NUNCA_PAGA",
    limite: Annotated[int, Query(ge=1, le=50000)] = 1000,
) -> Objeto:
    return servicio.rutas_campo(db, actor, sede, comercializador, periodo, grupo, limite)


# --- Análisis: herramientas ----------------------------------------------------------------------


@router.get(f"{A}/segmentacion/{{periodo}}", response_model=Objeto, summary="Reparto por segmento")
def segmentacion(
    comercializador: str,
    periodo: str,
    sede: SedeActiva,
    _: Analiza,
    db: Db,
    por: Literal["segmento", "estrato", "tarifa"] = "segmento",
) -> Objeto:
    return servicio.segmentacion(db, sede, comercializador, periodo, por)


@router.get(
    f"{A}/comparativo-segmentos/{{periodo}}",
    response_model=Objeto,
    summary="Cambio de cada segmento frente al corte anterior",
)
def comparativo_segmentos(
    comercializador: str,
    periodo: str,
    sede: SedeActiva,
    _: Analiza,
    db: Db,
    por: Literal["segmento", "estrato", "tarifa"] = "segmento",
) -> Objeto:
    return servicio.comparativo_segmentos(db, sede, comercializador, periodo, por)


@router.get(f"{A}/barrios/{{periodo}}", response_model=Objeto, summary="Reparto por barrio")
def barrios(comercializador: str, periodo: str, sede: SedeActiva, _: Analiza, db: Db) -> Objeto:
    return servicio.barrios(db, sede, comercializador, periodo)


@router.get(
    f"{A}/tabla-dinamica/{{periodo}}",
    response_model=Objeto,
    summary="Tabla dinámica del corte (Afinia: 12 tarifas + total, 45 columnas)",
)
def tabla_dinamica(
    comercializador: str, periodo: str, sede: SedeActiva, _: Analiza, db: Db
) -> Objeto:
    return servicio.tabla_dinamica(db, sede, comercializador, periodo)


@router.get(
    f"{A}/trazabilidad/{{identificador}}",
    response_model=Objeto,
    summary="Historia completa de un usuario (nominal, se audita)",
)
def trazabilidad(
    comercializador: str, identificador: str, sede: SedeActiva, actor: Nominal, db: Db
) -> Objeto:
    return servicio.trazabilidad(db, actor, sede, comercializador, identificador)


# --- Hallazgos revisados -------------------------------------------------------------------------


@router.get(
    "/{comercializador}/hallazgos",
    response_model=list[HallazgoSalida],
    summary="Bitácora de hallazgos (nominal)",
)
def listar_hallazgos(
    comercializador: str,
    sede: SedeActiva,
    actor: Nominal,
    db: Db,
    estado: Literal["ABIERTO", "EN_REVISION", "RESUELTO"] | None = None,
) -> list[Objeto]:
    return servicio.listar_hallazgos(db, actor, sede, comercializador, estado)


@router.post(
    "/{comercializador}/hallazgos",
    response_model=HallazgoSalida,
    status_code=201,
    summary="Registrar un hallazgo (responsable y decisión obligatorios)",
)
def crear_hallazgo(
    comercializador: str, entrada: HallazgoEntrada, sede: SedeActiva, actor: Nominal, db: Db
) -> Objeto:
    return servicio.crear_hallazgo(db, actor, sede, comercializador, entrada)


@router.patch(
    "/{comercializador}/hallazgos/{hallazgo_id}",
    response_model=HallazgoSalida,
    summary="Actualizar el estado o la decisión de un hallazgo",
)
def editar_hallazgo(
    comercializador: str,
    hallazgo_id: int,
    entrada: HallazgoEditarEntrada,
    sede: SedeActiva,
    actor: Nominal,
    db: Db,
) -> Objeto:
    return servicio.editar_hallazgo(db, actor, sede, comercializador, hallazgo_id, entrada)


# --- Entregables y exportaciones -----------------------------------------------------------------

_DESCARGA = {200: {"content": {"application/octet-stream": {}}}}


@router.post(
    "/{comercializador}/entregables/{tipo}",
    response_class=Response,
    responses=_DESCARGA,
    summary="Requerimiento (Word/PDF/HTML), análisis (HTML/PDF), anexo nominal (Excel) "
    "o informe gerencial (PDF)",
)
def entregable(
    comercializador: str,
    tipo: TipoEntregable,
    entrada: EntregableEntrada,
    sede: SedeActiva,
    actor: Genera,
    db: Db,
) -> Response:
    if tipo == "anexo-nominal":
        verificar_permiso(actor, "comercial.nominal.ver")
    contenido, mime, nombre = servicio.generar_entregable(
        db, actor, sede, comercializador, tipo, entrada.periodo, entrada.formato, entrada.max_filas
    )
    disposicion = "inline" if mime.startswith("text/html") else "attachment"
    return Response(
        content=contenido,
        media_type=mime,
        headers={"Content-Disposition": f'{disposicion}; filename="{nombre}"'},
    )


@router.post(
    "/{comercializador}/exportaciones/cartera",
    response_class=Response,
    responses=_DESCARGA,
    summary="Cartera en ZIP: resumen y detalle por cuenta (Celsia)",
)
def exportar_cartera(
    comercializador: str, entrada: PeriodoEntrada, sede: SedeActiva, actor: Exporta, db: Db
) -> Response:
    verificar_permiso(actor, "comercial.nominal.ver")
    contenido = servicio.exportar_cartera(db, actor, sede, comercializador, entrada.periodo)
    return Response(
        content=contenido,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="cartera_{comercializador}_{entrada.periodo}.zip"'
            )
        },
    )


@router.post(
    "/{comercializador}/exportaciones/promedios-ids",
    response_class=Response,
    responses=_DESCARGA,
    summary="Promedios de consumo por lista de IDs (.txt UTF-8, ≤ 1 MiB y 50.000 IDs)",
)
async def promedios_ids(
    comercializador: str,
    sede: SedeActiva,
    actor: Exporta,
    db: Db,
    archivo: Annotated[UploadFile, File(...)],
) -> Response:
    contenido = await servicio.promedios_por_ids(db, actor, sede, comercializador, archivo)
    return Response(
        content=contenido,
        media_type=servicio.XLSX,
        headers={"Content-Disposition": f'attachment; filename="promedios_{comercializador}.xlsx"'},
    )


# --- Migración del almacén de OPainn (HU-080) ----------------------------------------------------


@router_migracion.post(
    "/opainn",
    status_code=202,
    response_model=Objeto,
    summary="Importar periodos del almacén de OPainn (Parquet + manifiesto)",
)
async def importar_opainn(
    entrada: ImportacionOpainnEntrada, sede: SedeActiva, actor: Carga, db: Db
) -> Objeto:
    return await servicio.importar_opainn(
        db, actor, sede, entrada.ruta_almacen, entrada.comercializador_codigo, entrada.periodos
    )
