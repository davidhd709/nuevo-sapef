"""Esquemas Pydantic v2 (DTOs) del módulo comercial.

Los análisis devuelven estructuras variadas (cada uno con sus columnas, como en OPainn): se
publican como objetos JSON con decimales en texto exacto, igual que el resto de la API.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

Comercializador = Literal["afinia", "celsia", "vatia"]
TipoHallazgo = Literal["RUTA", "ANOMALIA", "MOVIMIENTO"]
EstadoHallazgo = Literal["ABIERTO", "EN_REVISION", "RESUELTO"]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CargueEncolado(BaseModel):
    """202 de un cargue: `id`/`cargueId`/`cargue_id` = cargue; `tareaId`/`tarea_id` = trabajo."""

    id: int
    cargue_id: int
    cargueId: int  # noqa: N815 - contrato público
    tarea_id: int | None
    tareaId: int | None  # noqa: N815
    estado: str


class CargueSalida(BaseModel):
    id: int
    cargue_id: int
    sede_id: int
    comercializador: str
    periodo: str
    estado: str
    origen: str
    completo: bool
    publicable: bool
    version_adaptador: str | None
    archivos: list[dict[str, Any]]
    familias: dict[str, Any]
    advertencias: list[str]
    errores: list[str]
    creado_en: datetime
    procesado_en: datetime | None


class CorteSalida(BaseModel):
    periodo: str
    cargue_id: int
    completo: bool
    publicable: bool
    familias: dict[str, int]
    advertencias: list[str]
    version_adaptador: str | None
    publicado_en: datetime | None


class AnalisisCatalogo(BaseModel):
    id: str
    grupo: str
    nombre: str
    pregunta: str
    ruta: str
    por_periodo: bool
    estado: Literal["disponible", "parcial", "pendiente", "no_aplica"]
    nota: str | None


class PaginaDatos(BaseModel):
    familia: str
    columnas: list[str]
    items: list[dict[str, Any]]
    total: int
    page: int
    size: int


class SabanaEntrada(_Entrada):
    familia: str = Field(min_length=1, max_length=30)
    formato: Literal["csv", "xlsx"] = "xlsx"


class TareaExportacion(BaseModel):
    id: int
    tarea_id: int
    tareaId: int  # noqa: N815
    estado: str = "encolada"


class HallazgoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tipo: TipoHallazgo
    estado: EstadoHallazgo = "ABIERTO"
    responsable: str = Field(min_length=2, max_length=160)
    decision: str = Field(min_length=2, max_length=4000)
    identificador: str | None = Field(
        default=None, max_length=40, validation_alias=AliasChoices("identificador", "nic", "cuenta")
    )
    referencia: str | None = Field(default=None, max_length=200)
    periodo: str | None = Field(default=None, pattern=r"^\d{4}(0[1-9]|1[0-2])$")


class HallazgoEditarEntrada(_Entrada):
    estado: EstadoHallazgo | None = None
    responsable: str | None = Field(default=None, min_length=2, max_length=160)
    decision: str | None = Field(default=None, min_length=2, max_length=4000)
    referencia: str | None = Field(default=None, max_length=200)


class HallazgoSalida(BaseModel):
    id: int
    comercializador: str
    tipo: str
    estado: str
    responsable: str
    decision: str
    identificador: str | None
    nic: str | None
    referencia: str | None
    periodo: str | None
    creado_en: datetime
    modificado_en: datetime


class EntregableEntrada(_Entrada):
    periodo: str = Field(pattern=r"^\d{4}(0[1-9]|1[0-2])$")
    formato: Literal["docx", "pdf", "html", "xlsx"] | None = None
    max_filas: int | None = Field(default=None, ge=1, le=1_000_000)


class PeriodoEntrada(_Entrada):
    periodo: str = Field(pattern=r"^\d{4}(0[1-9]|1[0-2])$")


class ImportacionOpainnEntrada(_Entrada):
    ruta_almacen: str = Field(min_length=1, max_length=1000)
    comercializador_codigo: Comercializador
    periodos: list[str] = Field(default_factory=list, max_length=240)
