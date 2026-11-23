"""Esquemas Pydantic v2 (DTOs) del módulo de trabajos."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TipoOrden = Literal["mantenimiento", "modernizacion", "expansion", "reubicacion"]
TipoCargue = Literal["expansion", "modernizacion", "reubicacion"]
RolLuminaria = Literal["intervenida", "instalada", "desmontada"]
TipoEvidencia = Literal[
    "foto",
    "firma",  # firma sin rol indicado
    "firma_tecnico",
    "firma_oficial",
    "firma_quien_recibe",
    "firma_solicitante",
    "audio",
    "adjunto",
    "soporte",
]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Técnicos y cuadrillas ----------------------------------------------------------------------


class TecnicoSalida(BaseModel):
    id: int
    nombre_usuario: str
    nombre_completo: str
    activo: bool


class CuadrillaSalida(BaseModel):
    id: int
    nombre: str
    activa: bool
    tecnicos: list[TecnicoSalida]


class CuadrillaCrearEntrada(_Entrada):
    nombre: str = Field(min_length=2, max_length=120)
    tecnicos_ids: list[int] = Field(default_factory=list, max_length=50)
    activa: bool = True


class CuadrillaEditarEntrada(_Entrada):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    tecnicos_ids: list[int] | None = Field(default=None, max_length=50)
    activa: bool | None = None


# --- Órdenes ------------------------------------------------------------------------------------


class OrdenLuminariaEntrada(_Entrada):
    luminaria_id: int
    rol: RolLuminaria


class OrdenCrearEntrada(_Entrada):
    tipo: TipoOrden
    prioridad: int = Field(default=2, ge=0, le=3)
    pqrs_id: int | None = None
    observaciones: str | None = Field(default=None, max_length=4000)
    fecha_programada: date | None = None
    luminarias: list[OrdenLuminariaEntrada] = Field(min_length=1, max_length=50)


class OrdenEditarEntrada(_Entrada):
    prioridad: int | None = Field(default=None, ge=0, le=3)
    observaciones: str | None = Field(default=None, max_length=4000)
    fecha_programada: date | None = None


class OrdenAsignarEntrada(_Entrada):
    tecnico_id: int | None = None
    cuadrilla_id: int | None = None
    fecha_programada: date | None = None


class OrdenAnularEntrada(_Entrada):
    motivo: str = Field(min_length=3, max_length=500)


class MaterialUsoEntrada(_Entrada):
    material_id: int
    cantidad: Decimal = Field(gt=0, max_digits=14, decimal_places=3)


class EvidenciaEntrada(_Entrada):
    archivo_id: UUID
    tipo: TipoEvidencia


class OrdenCerrarEntrada(BaseModel):
    """Cierre de cualquier tipo de orden. Se validan los campos que exige el tipo; los demás se
    ignoran (un formulario genérico puede mandar campos de otro tipo)."""

    model_config = ConfigDict(extra="ignore")

    fecha_ejecucion: datetime | None = None
    observaciones: str | None = Field(default=None, max_length=4000)
    latitud: float | None = Field(default=None, ge=-90, le=90)
    longitud: float | None = Field(default=None, ge=-180, le=180)
    materiales: list[MaterialUsoEntrada] = Field(default_factory=list, max_length=50)
    evidencias: list[EvidenciaEntrada] = Field(default_factory=list, max_length=20)
    # Mantenimiento
    sitio_arreglo: str | None = Field(default=None, max_length=255)
    quien_recibe: str | None = Field(default=None, max_length=160)
    observacion_tecnica: str | None = Field(default=None, max_length=4000)
    requiere_desmonte: bool = False
    causal_desmonte: str | None = Field(default=None, max_length=255)
    luminaria_reemplazo_id: int | None = None
    componentes: dict[str, Any] | None = None
    # Expansión, modernización y reubicación
    tipo_expansion_id: int | None = None
    tipo_modernizacion_id: int | None = None
    barrio_id: int | None = None
    marca_id: int | None = None
    poste: str | None = Field(default=None, max_length=80)
    longitud_brazo: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    referencia: str | None = Field(default=None, max_length=255)
    novedades: str | None = Field(default=None, max_length=4000)
    comentario: str | None = Field(default=None, max_length=4000)
    destino_desmontada: str | None = Field(default=None, max_length=10)


class OrdenLuminariaSalida(BaseModel):
    luminaria_id: int
    luminaria_codigo: str
    rol: str


class MantenimientoSalida(BaseModel):
    sitio_arreglo: str | None
    quien_recibe: str | None
    observacion_tecnica: str | None
    requiere_desmonte: bool
    causal_desmonte: str | None
    luminaria_reemplazo_id: int | None
    destino_desmontada: str | None
    componentes: dict[str, bool]


class InstalacionSalida(BaseModel):
    tipo_valor_id: int | None
    barrio_id: int | None
    marca_id: int | None
    poste: str | None
    longitud_brazo: Decimal | None
    referencia: str | None
    novedades: str | None
    destino_desmontada: str | None
    comentario: str | None


class MaterialUsadoSalida(BaseModel):
    material_id: int
    material_codigo: str
    cantidad: Decimal


class EvidenciaOrdenSalida(BaseModel):
    archivo_id: UUID
    tipo: str
    creado_en: datetime


class OrdenSalida(BaseModel):
    id: int
    sede_id: int
    numero: int
    tipo: str
    estado_id: int
    estado_codigo: str
    estado_nombre: str
    prioridad: int
    pqrs_id: int | None
    tecnico_id: int | None
    tecnico_nombre: str | None
    cuadrilla_id: int | None
    cuadrilla_nombre: str | None
    fecha_programada: date | None
    asignada_en: datetime | None
    fecha_ejecucion: datetime | None
    latitud: float | None
    longitud: float | None
    observaciones: str | None
    motivo_anulacion: str | None
    origen: str
    luminarias: list[OrdenLuminariaSalida]
    mantenimiento: MantenimientoSalida | None
    instalacion: InstalacionSalida | None
    materiales: list[MaterialUsadoSalida]
    evidencias: list[EvidenciaOrdenSalida]
    creado_en: datetime


class CargueMasivoSalida(BaseModel):
    id: int
    tipo: str
    estado: str
    filas: int
    ordenes_creadas: int
    errores: list[dict[str, Any]]
    creado_en: datetime
    procesado_en: datetime | None
