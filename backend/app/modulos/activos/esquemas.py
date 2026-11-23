"""Esquemas Pydantic v2 (DTOs) del módulo de activos y mapa (EP-03)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class Pagina[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int


class LuminariaCrearEntrada(BaseModel):
    codigo: str = Field(min_length=1, max_length=80)
    codigo_externo: str | None = Field(default=None, max_length=120)
    barrio_id: int | None = None
    latitud: float | None = None
    longitud: float | None = None
    estado_id: int
    tecnologia_id: int | None = None
    potencia_id: int | None = None
    marca_id: int | None = None
    tipo_intervencion_id: int | None = None
    accion_operativa_id: int | None = None
    mision_objetivo_id: int | None = None
    fecha_instalacion: date | None = None
    fecha_mision: date | None = None
    fecha_baja: date | None = None
    fecha_disposicion_final: date | None = None
    mac: str | None = Field(default=None, max_length=80)
    poste: str | None = Field(default=None, max_length=80)
    longitud_brazo: Decimal | None = None
    es_rural: bool = False
    subnormal: bool = False
    tiene_medida: bool = False
    en_transito: bool = False
    validado: bool = False
    responsable: str | None = Field(default=None, max_length=160)
    observaciones: str | None = None
    luminaria_reemplazada_id: int | None = None


class LuminariaEditarEntrada(BaseModel):
    codigo_externo: str | None = Field(default=None, max_length=120)
    barrio_id: int | None = None
    estado_id: int | None = None
    tecnologia_id: int | None = None
    potencia_id: int | None = None
    marca_id: int | None = None
    tipo_intervencion_id: int | None = None
    accion_operativa_id: int | None = None
    mision_objetivo_id: int | None = None
    fecha_instalacion: date | None = None
    fecha_mision: date | None = None
    fecha_baja: date | None = None
    fecha_disposicion_final: date | None = None
    mac: str | None = Field(default=None, max_length=80)
    poste: str | None = Field(default=None, max_length=80)
    longitud_brazo: Decimal | None = None
    es_rural: bool | None = None
    subnormal: bool | None = None
    tiene_medida: bool | None = None
    en_transito: bool | None = None
    validado: bool | None = None
    responsable: str | None = Field(default=None, max_length=160)
    observaciones: str | None = None


class LuminariaMoverEntrada(BaseModel):
    latitud: float
    longitud: float
    origen: str = Field(default="web", min_length=2, max_length=30)


class LuminariaSalida(BaseModel):
    id: int
    sede_id: int
    codigo: str
    codigo_externo: str | None
    barrio_id: int | None
    barrio_nombre: str | None
    zona_id: int | None
    zona_nombre: str | None
    latitud: float | None
    longitud: float | None
    google_maps_url: str | None
    estado_id: int
    estado_codigo: str | None
    estado_nombre: str | None
    tecnologia_id: int | None
    tecnologia_codigo: str | None
    tecnologia_nombre: str | None
    potencia_id: int | None
    potencia_codigo: str | None
    potencia_nombre: str | None
    marca_id: int | None
    marca_codigo: str | None
    marca_nombre: str | None
    tipo_intervencion_id: int | None
    accion_operativa_id: int | None
    mision_objetivo_id: int | None
    lote_id: int | None
    luminaria_reemplazada_id: int | None
    fecha_instalacion: date | None
    fecha_mision: date | None
    fecha_baja: date | None
    fecha_disposicion_final: date | None
    mac: str | None
    poste: str | None
    longitud_brazo: Decimal | None
    es_rural: bool
    subnormal: bool
    tiene_medida: bool
    en_transito: bool
    validado: bool
    es_comodin: bool
    responsable: str | None
    observaciones: str | None
    creado_en: datetime
    modificado_en: datetime


class EventoActivoSalida(BaseModel):
    id: int
    luminaria_id: int
    tipo: str
    fecha: datetime
    orden_id: int | None
    pqrs_id: int | None
    estado_anterior_id: int | None
    estado_nuevo_id: int | None
    detalle: dict[str, Any]
    creado_por: int | None


class UbicacionHistorialSalida(BaseModel):
    id: int
    luminaria_id: int
    latitud_anterior: float | None
    longitud_anterior: float | None
    latitud_nueva: float
    longitud_nueva: float
    origen: str
    cambiado_en: datetime
    cambiado_por: int | None


class HistorialLuminariaSalida(BaseModel):
    luminaria: LuminariaSalida
    eventos: list[EventoActivoSalida]
    ubicaciones: list[UbicacionHistorialSalida]
    pqrs: list[dict[str, Any]]
    ordenes: list[dict[str, Any]]


class LuminariaExportarEntrada(BaseModel):
    texto: str | None = Field(default=None, max_length=120)
    estado_id: int | None = None
    zona_id: int | None = None
    barrio_id: int | None = None
    tecnologia_id: int | None = None
    potencia_id: int | None = None
    marca_id: int | None = None


class TareaExportacionSalida(BaseModel):
    id: int
    tarea_id: int
    tareaId: int
    estado: str


class LoteCrearEntrada(BaseModel):
    consecutivo_inicial: int = Field(ge=1)
    consecutivo_final: int = Field(ge=1)
    cantidad: int = Field(ge=1, le=5000)
    tecnologia_id: int
    potencia_id: int
    marca_id: int | None = None
    es_rural: bool = False
    orden_compra: str | None = Field(default=None, max_length=120)
    fecha_orden_compra: date | None = None
    entrada_almacen: str | None = Field(default=None, max_length=120)
    fecha_entrada_almacen: date | None = None


class LoteSalida(BaseModel):
    id: int
    sede_id: int
    consecutivo_inicial: int
    consecutivo_final: int
    cantidad: int
    tecnologia_id: int
    potencia_id: int
    marca_id: int | None
    es_rural: bool
    orden_compra: str | None
    fecha_orden_compra: date | None
    entrada_almacen: str | None
    fecha_entrada_almacen: date | None
    creado_en: datetime
