"""Esquemas Pydantic v2 (DTOs) de la sincronización de la app de campo (§9.7)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EstadoOperacion = Literal["aplicada", "ya_aplicada", "conflicto", "error"]
EstadoRegistro = Literal["aplicada", "conflicto", "error"]


# --- Subida -------------------------------------------------------------------------------------


class OperacionEntrada(BaseModel):
    """Una operación de la bandeja de salida del teléfono. Acepta `ordenId`/`creadaEn` (contrato
    de la app) o `orden_id`/`creada_en`."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    uuid: UUID
    tipo: str = Field(max_length=30)
    orden_id: int | None = Field(default=None, alias="ordenId")
    creada_en: datetime | None = Field(default=None, alias="creadaEn")
    payload: dict[str, Any] = Field(default_factory=dict)


class SincronizarEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operaciones: list[OperacionEntrada] = Field(max_length=50)


class ResultadoOperacion(BaseModel):
    uuid: UUID
    estado: EstadoOperacion
    motivo: str | None = None
    orden_id: int | None = None


class SincronizarSalida(BaseModel):
    resultados: list[ResultadoOperacion]
    procesado_en: datetime


class OperacionCampoSalida(BaseModel):
    uuid: UUID
    tipo: str
    orden_id: int | None
    orden_numero: int | None
    estado: EstadoRegistro
    motivo: str | None
    intentos: int
    usuario_id: int
    usuario_nombre: str
    creada_en: datetime | None
    recibida_en: datetime
    actualizada_en: datetime


# --- Bajada -------------------------------------------------------------------------------------


class LuminariaOrdenCampo(BaseModel):
    luminaria_id: int
    codigo: str
    rol: str
    estado_codigo: str | None
    barrio_id: int | None
    barrio_nombre: str | None
    poste: str | None
    latitud: float | None
    longitud: float | None


class OrdenCampo(BaseModel):
    id: int
    numero: int
    tipo: str
    estado_codigo: str
    estado_nombre: str
    prioridad: int
    pqrs_id: int | None
    fecha_programada: date | None
    asignada_en: datetime | None
    observaciones: str | None
    modificado_en: datetime
    luminarias: list[LuminariaOrdenCampo]


class OrdenRetirada(BaseModel):
    id: int
    numero: int
    motivo: Literal["anulada", "cerrada", "reasignada"]


class LuminariaCampo(BaseModel):
    id: int
    codigo: str
    estado_codigo: str
    barrio_id: int | None
    poste: str | None
    latitud: float | None
    longitud: float | None
    tecnologia: str | None
    potencia: str | None
    marca: str | None


class MaterialCampo(BaseModel):
    id: int
    codigo: str
    descripcion: str
    categoria: str
    unidad: str
    existencias: Decimal


class ValorCampo(BaseModel):
    id: int
    codigo: str
    nombre: str


class BarrioCampo(BaseModel):
    id: int
    nombre: str
    zona_id: int
    zona_nombre: str


class DestinoCampo(BaseModel):
    codigo: str
    nombre: str


class CatalogosCampo(BaseModel):
    barrios: list[BarrioCampo]
    tipos_expansion: list[ValorCampo]
    tipos_modernizacion: list[ValorCampo]
    marcas: list[ValorCampo]
    componentes: list[str]
    destinos_desmontada: list[DestinoCampo]
    tipos_evidencia: list[str]


class SedeCampo(BaseModel):
    codigo: str
    nombre: str


class UsuarioCampo(BaseModel):
    id: int
    nombre_completo: str


class MapaBaseCampo(BaseModel):
    url: str


class PaqueteCampo(BaseModel):
    cursor: str
    generado_en: datetime
    completo: bool = Field(description="True si trae todas las luminarias; False si es delta")
    sede: SedeCampo
    usuario: UsuarioCampo
    ordenes_asignadas: list[OrdenCampo]
    ordenes_anuladas_o_reasignadas: list[OrdenRetirada]
    luminarias_zona: list[LuminariaCampo]
    luminarias_bodega: list[LuminariaCampo]
    materiales: list[MaterialCampo]
    catalogos: CatalogosCampo
    mapa_base: MapaBaseCampo
