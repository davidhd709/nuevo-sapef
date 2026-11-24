"""DTO del tablero gerencial (EP-09)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SedeTablero(BaseModel):
    id: int
    codigo: str
    nombre: str


class ConteoTablero(BaseModel):
    etiqueta: str
    grupo: str | None = None
    cantidad: int


class MesTablero(BaseModel):
    mes: int
    cantidad: int
    acumulado: int


class ActivosTablero(BaseModel):
    total_luminarias: int
    en_servicio: int
    en_bodega: int
    instaladas_anio: int
    luminarias_instaladas_mes: list[MesTablero]
    por_tecnologia: list[ConteoTablero]
    por_potencia: list[ConteoTablero]
    por_zona: list[ConteoTablero]
    por_barrio: list[ConteoTablero]


class SemaforoTablero(BaseModel):
    verde: int
    amarillo: int
    rojo: int
    umbral_verde_dias: int | None = None
    umbral_amarillo_dias: int | None = None


class OperacionTablero(BaseModel):
    luminarias_por_estado: list[ConteoTablero]
    pqrs_abiertas: int
    pqrs_semaforo: SemaforoTablero
    pqrs_recibidas_mes: int
    pqrs_recibidas_mes_anterior: int
    variacion_pqrs_recibidas: float | None
    pqrs_atendidas_mes: int
    pqrs_atendidas_anio: int
    tiempo_promedio_atencion_horas: float | None
    pqrs_por_barrio: list[ConteoTablero]
    mantenimientos_mes: int
    mantenimientos_mes_anterior: int
    variacion_mantenimientos: float | None
    ordenes_abiertas: int
    materiales_bajo_minimo: int


class ComercializadorTablero(BaseModel):
    sede_codigo: str
    sede_nombre: str
    comercializador: str
    nombre: str
    periodo: str
    periodo_anterior: str | None
    actual: dict[str, Any]
    anterior: dict[str, Any] | None
    variacion: dict[str, float | None]
    participacion: list[dict[str, Any]]
    historico: list[dict[str, Any]]


class ComercialTablero(BaseModel):
    estado: str = Field(description="con_datos, sin_cortes_cargados o pendiente_de_calculo")
    comercializadores: list[ComercializadorTablero]


class SedeResumenTablero(BaseModel):
    sede: SedeTablero
    calculado_en: datetime | None
    total_luminarias: int
    en_servicio: int
    instaladas_anio: int
    pqrs_abiertas: int
    pqrs_rojo: int
    mantenimientos_mes: int


class ResumenTableroSalida(BaseModel):
    sede: str = Field(description="Código de la sede o «todas» para el consolidado")
    sedes_incluidas: list[SedeTablero]
    anio: int
    calculado_en: datetime | None
    activos: ActivosTablero
    operacion: OperacionTablero
    comercial: ComercialTablero
    por_sede: list[SedeResumenTablero]


class RecalcularEntrada(BaseModel):
    sede_id: int | None = None


class RecalculoEncolado(BaseModel):
    tarea_id: int
    tareaId: int  # noqa: N815 - alias que esperan los clientes
    sede_ids: list[int]
