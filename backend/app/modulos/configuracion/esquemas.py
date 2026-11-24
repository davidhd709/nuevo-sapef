"""Esquemas Pydantic v2 (DTOs) del módulo de configuración (EP-02).

Los importes y factores viajan como decimales (en JSON, como texto) para no perder
precisión. Los porcentajes son fracciones entre 0 y 1 (12 % = 0.12).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

Proceso = Literal["luminaria", "pqrs", "orden", "solicitud"]
EstadoAcuerdo = Literal["borrador", "aprobado", "reemplazado"]

Texto120 = Annotated[str, Field(min_length=1, max_length=120)]
Texto160 = Annotated[str, Field(min_length=1, max_length=160)]
NoNegativo = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=4)]
Fraccion = Annotated[Decimal, Field(ge=0, le=1, max_digits=10, decimal_places=6)]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Sedes y comercializadores ---------------------------------------------------------------


class SedeSalida(BaseModel):
    id: int
    codigo: str
    nombre: str
    municipio: str
    departamento: str
    activa: bool
    creado_en: datetime
    modificado_en: datetime


class SedeCrearEntrada(_Entrada):
    codigo: str = Field(min_length=2, max_length=40)
    nombre: Texto120
    municipio: Texto120
    departamento: Texto120
    activa: bool = True


class SedeEditarEntrada(_Entrada):
    nombre: Texto120 | None = None
    municipio: Texto120 | None = None
    departamento: Texto120 | None = None
    activa: bool | None = None


class ComercializadorSalida(BaseModel):
    id: int
    codigo: str
    nombre: str
    identificador_usuario: str
    regla_tarifaria: str | None
    periodicidad: str
    activo: bool


class SedeComercializadorSalida(BaseModel):
    comercializador_id: int
    comercializador_codigo: str
    comercializador_nombre: str
    activo: bool
    desde: date | None


class SedeComercializadorEntrada(_Entrada):
    comercializador_codigo: str = Field(min_length=1, max_length=40)
    activo: bool = True
    desde: date | None = None


# --- Maestros --------------------------------------------------------------------------------


class MaestroClaseSalida(BaseModel):
    id: int
    codigo: str
    nombre: str
    total_valores: int


class MaestroValorSalida(BaseModel):
    id: int
    clase_codigo: str
    codigo: str
    nombre: str
    orden: int
    activo: bool


class MaestroValorCrearEntrada(_Entrada):
    codigo: str = Field(min_length=1, max_length=60)
    nombre: Texto160
    orden: int = Field(default=0, ge=0, le=1_000_000)
    activo: bool = True


class MaestroValorEditarEntrada(_Entrada):
    nombre: Texto160 | None = None
    orden: int | None = Field(default=None, ge=0, le=1_000_000)
    activo: bool | None = None


# --- Zonas y barrios ---------------------------------------------------------------------------


class ZonaSalida(BaseModel):
    id: int
    sede_id: int
    nombre: str
    activa: bool
    total_barrios: int


class ZonaCrearEntrada(_Entrada):
    nombre: Texto120
    activa: bool = True


class ZonaEditarEntrada(_Entrada):
    nombre: Texto120 | None = None
    activa: bool | None = None


class BarrioSalida(BaseModel):
    id: int
    sede_id: int
    zona_id: int
    zona_nombre: str
    nombre: str
    activo: bool


class BarrioCrearEntrada(_Entrada):
    zona_id: int
    nombre: Texto160
    activo: bool = True


class BarrioEditarEntrada(_Entrada):
    zona_id: int | None = None
    nombre: Texto160 | None = None
    activo: bool | None = None


# --- Estados -----------------------------------------------------------------------------------


class EstadoSalida(BaseModel):
    id: int
    proceso: Proceso
    codigo: str
    nombre: str
    orden: int
    final: bool
    vigente: bool


class EstadoEditarEntrada(_Entrada):
    nombre: Texto120 | None = None
    orden: int | None = Field(default=None, ge=0, le=10_000)


# --- Parámetros y plantillas ------------------------------------------------------------------


class ParametroSalida(BaseModel):
    id: int
    sede_id: int | None
    alcance: Literal["sede", "global"]
    codigo: str
    nombre: str
    valor: Any
    editable: bool
    modificado_en: datetime


class ParametroEditarEntrada(_Entrada):
    valor: Any


class PlantillaCorreoSalida(BaseModel):
    id: int
    sede_id: int
    codigo: str
    nombre: str
    asunto: str
    cuerpo_html: str
    variables: list[str]
    activa: bool
    modificado_en: datetime


class PlantillaCorreoEditarEntrada(_Entrada):
    asunto: str | None = Field(default=None, min_length=1, max_length=255)
    cuerpo_html: str | None = Field(default=None, min_length=1, max_length=100_000)
    activa: bool | None = None


# --- Acuerdos tarifarios -------------------------------------------------------------------------


class TarifaEntrada(_Entrada):
    """Acepta también los nombres cortos de OPainn (`codigo`, `factor_uvt`, `porcentaje_variable`,
    `urbano`, `rural`); `nombre` es descriptivo y no se guarda."""

    tarifa: str = Field(
        min_length=1, max_length=80, validation_alias=AliasChoices("tarifa", "codigo")
    )
    nombre: str | None = Field(default=None, max_length=120)
    tipo_regla: str | None = Field(default=None, max_length=40)
    factor_uvt_minimo: NoNegativo | None = Field(
        default=None, validation_alias=AliasChoices("factor_uvt_minimo", "factor_uvt")
    )
    porcentaje_costo_variable: Fraccion | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "porcentaje_costo_variable", "porcentaje_variable", "porcentaje"
        ),
    )
    valor_urbano: NoNegativo | None = Field(
        default=None, validation_alias=AliasChoices("valor_urbano", "urbano")
    )
    valor_rural: NoNegativo | None = Field(
        default=None, validation_alias=AliasChoices("valor_rural", "rural")
    )


class TarifaSalida(BaseModel):
    id: int
    tarifa: str
    orden: int
    tipo_regla: str | None
    factor_uvt_minimo: Decimal | None
    porcentaje_costo_variable: Decimal | None
    valor_urbano: Decimal | None
    valor_rural: Decimal | None
    # UVT × factor, redondeado a centavos (solo cuando aplica).
    valor_minimo: Decimal | None


class ExcepcionEntrada(_Entrada):
    identificador: str = Field(min_length=1, max_length=40)
    nombre: str | None = Field(default=None, max_length=200)
    factor_uvt: NoNegativo | None = None
    regla: dict[str, Any] | None = None
    activo: bool = True


class ExcepcionSalida(BaseModel):
    id: int
    identificador: str
    nombre: str | None
    factor_uvt: Decimal | None
    regla: dict[str, Any] | None
    activo: bool


class AcuerdoCrearEntrada(_Entrada):
    comercializador_codigo: str = Field(min_length=1, max_length=40)
    anio: int = Field(ge=2000, le=2200)
    uvt: NoNegativo | None = None
    umbral_kwh: NoNegativo | None = None
    tolerancia: NoNegativo | None = None
    base_costo_variable: str | None = Field(default=None, max_length=60)
    reglas: dict[str, Any] = Field(default_factory=dict)
    fuente: str | None = Field(default=None, max_length=500)
    tarifas: list[TarifaEntrada] = Field(default_factory=list, max_length=200)
    excepciones: list[ExcepcionEntrada] = Field(default_factory=list, max_length=5000)


class AcuerdoEditarEntrada(_Entrada):
    """Solo en borrador. Si se envían `tarifas` o `excepciones`, reemplazan la lista completa."""

    uvt: NoNegativo | None = None
    umbral_kwh: NoNegativo | None = None
    tolerancia: NoNegativo | None = None
    base_costo_variable: str | None = Field(default=None, max_length=60)
    reglas: dict[str, Any] | None = None
    fuente: str | None = Field(default=None, max_length=500)
    tarifas: list[TarifaEntrada] | None = Field(default=None, max_length=200)
    excepciones: list[ExcepcionEntrada] | None = Field(default=None, max_length=5000)


class AcuerdoCopiarEntrada(_Entrada):
    anio_destino: int = Field(ge=2000, le=2200)


class AcuerdoAprobarEntrada(_Entrada):
    observacion: str | None = Field(default=None, max_length=500)


class AcuerdoResumen(BaseModel):
    id: int
    sede_id: int
    comercializador_codigo: str
    comercializador_nombre: str
    anio: int
    estado: EstadoAcuerdo
    uvt: Decimal | None
    umbral_kwh: Decimal | None
    tolerancia: Decimal | None
    base_costo_variable: str | None
    fuente: str | None
    origen_id: int | None
    aprobado_por: int | None
    aprobado_en: datetime | None
    total_tarifas: int
    total_excepciones: int
    creado_en: datetime
    modificado_en: datetime


class AcuerdoDetalle(AcuerdoResumen):
    reglas: dict[str, Any]
    tarifas: list[TarifaSalida]
    excepciones: list[ExcepcionSalida]


# --- Catálogos comerciales (conceptos CI y operaciones OC) ------------------------------------


class CatalogoComercialSalida(BaseModel):
    id: int
    comercializador_codigo: str
    codigo: str
    descripcion: str
    entra_al_calculo: bool
    activo: bool


class CatalogoComercialCrearEntrada(_Entrada):
    comercializador_codigo: str = Field(min_length=1, max_length=40)
    codigo: str = Field(min_length=1, max_length=20)
    descripcion: str = Field(min_length=1, max_length=200)
    entra_al_calculo: bool = False
    activo: bool = True


class CatalogoComercialEditarEntrada(_Entrada):
    descripcion: str | None = Field(default=None, min_length=1, max_length=200)
    entra_al_calculo: bool | None = None
    activo: bool | None = None
