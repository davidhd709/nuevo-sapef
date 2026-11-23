"""Esquemas Pydantic v2 (DTOs) del módulo de atención."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Ciudadanos ---------------------------------------------------------------------------------


class CiudadanoSalida(BaseModel):
    id: int
    identificacion: str
    nombre_completo: str
    barrio_id: int | None
    sector: str | None
    telefono: str | None
    celular: str | None
    correo: str | None
    # True cuando quien consulta no tiene atencion.datos_personales.ver.
    enmascarado: bool = False


class CiudadanoCrearEntrada(_Entrada):
    identificacion: str = Field(min_length=2, max_length=40)
    nombre_completo: str = Field(min_length=2, max_length=180)
    barrio_id: int | None = None
    sector: str | None = Field(default=None, max_length=120)
    telefono: str | None = Field(default=None, max_length=40)
    celular: str | None = Field(default=None, max_length=40)
    correo: str | None = Field(default=None, max_length=180, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CiudadanoEditarEntrada(_Entrada):
    nombre_completo: str | None = Field(default=None, min_length=2, max_length=180)
    barrio_id: int | None = None
    sector: str | None = Field(default=None, max_length=120)
    telefono: str | None = Field(default=None, max_length=40)
    celular: str | None = Field(default=None, max_length=40)
    correo: str | None = Field(default=None, max_length=180, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --- PQRS ---------------------------------------------------------------------------------------


class PqrsLuminariaEntrada(_Entrada):
    luminaria_id: int
    observacion_solicitante: str | None = Field(default=None, max_length=2000)


class PqrsCrearEntrada(_Entrada):
    canal_id: int
    ciudadano_id: int | None = None
    prioridad: int = Field(default=2, ge=0, le=3)
    fecha_solicitud: datetime | None = None
    observacion_solicitante: str | None = Field(default=None, max_length=4000)
    observacion_interna: str | None = Field(default=None, max_length=4000)
    notificar_cliente: bool = False
    luminarias: list[PqrsLuminariaEntrada] = Field(min_length=1, max_length=100)


class PqrsEditarEntrada(_Entrada):
    canal_id: int | None = None
    ciudadano_id: int | None = None
    prioridad: int | None = Field(default=None, ge=0, le=3)
    observacion_interna: str | None = Field(default=None, max_length=4000)
    calidad_servicio: str | None = Field(default=None, max_length=40)
    notificar_cliente: bool | None = None


class PqrsAnularEntrada(_Entrada):
    motivo: str = Field(min_length=3, max_length=500)


class PqrsLuminariaSalida(BaseModel):
    id: int
    luminaria_id: int
    luminaria_codigo: str
    es_comodin: bool
    estado_reportado_codigo: str | None
    observacion_solicitante: str | None
    observacion_tecnico: str | None
    reparada: bool
    fecha_reparacion: datetime | None
    orden_id: int | None


class PqrsSalida(BaseModel):
    id: int
    sede_id: int
    numero: int
    canal_id: int
    canal_nombre: str | None
    fecha_solicitud: datetime
    ciudadano: CiudadanoSalida | None
    observacion_solicitante: str | None
    observacion_interna: str | None
    prioridad: int
    prioridad_nombre: str
    estado_id: int
    estado_codigo: str
    estado_nombre: str
    calidad_servicio: str | None
    fecha_cierre: datetime | None
    notificar_cliente: bool
    motivo_anulacion: str | None
    luminarias: list[PqrsLuminariaSalida]
    total_luminarias: int
    reparadas: int
    creado_en: datetime


Semaforo = Literal["verde", "amarillo", "rojo"]


class PendienteSalida(BaseModel):
    """Una luminaria con PQRS abierta (RF-035)."""

    pqrs_id: int
    pqrs_numero: int
    luminaria_id: int
    luminaria_codigo: str
    barrio_nombre: str | None
    estado_reportado_codigo: str | None
    prioridad: int
    prioridad_nombre: str
    solicitante: str | None
    fecha_reporte: date
    dias_abierta: int
    semaforo: Semaforo
    latitud: float | None
    longitud: float | None


class PqrsExportarEntrada(_Entrada):
    estado_id: int | None = None
    prioridad: int | None = Field(default=None, ge=0, le=3)
    desde: date | None = None
    hasta: date | None = None
