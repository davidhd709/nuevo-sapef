"""Esquemas Pydantic v2 (DTOs) del módulo de inventario."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Cantidad = Annotated[Decimal, Field(max_digits=14, decimal_places=3)]
CantidadNoNegativa = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MaterialSalida(BaseModel):
    id: int
    sede_id: int
    categoria: str
    codigo: str
    descripcion: str
    unidad: str
    existencias: Decimal
    existencias_minimas: Decimal
    bajo_minimo: bool
    responsable: str | None
    activo: bool
    modificado_en: datetime


class MaterialCrearEntrada(_Entrada):
    categoria: str = Field(min_length=1, max_length=60)
    codigo: str = Field(min_length=1, max_length=60)
    descripcion: str = Field(min_length=1, max_length=255)
    unidad: str = Field(min_length=1, max_length=20)
    existencias: CantidadNoNegativa = Decimal(0)
    existencias_minimas: CantidadNoNegativa = Decimal(0)
    responsable: str | None = Field(default=None, max_length=160)
    activo: bool = True


class MaterialEditarEntrada(_Entrada):
    """Las existencias no se editan aquí: solo cambian con un movimiento del kárdex."""

    categoria: str | None = Field(default=None, min_length=1, max_length=60)
    descripcion: str | None = Field(default=None, min_length=1, max_length=255)
    unidad: str | None = Field(default=None, min_length=1, max_length=20)
    existencias_minimas: CantidadNoNegativa | None = None
    responsable: str | None = Field(default=None, max_length=160)
    activo: bool | None = None


TipoMovimiento = Literal["entrada", "salida", "ajuste"]


class MovimientoEntrada(_Entrada):
    tipo: TipoMovimiento
    # Entrada y salida: positiva. Ajuste: con signo (p. ej., -2 tras un conteo físico).
    cantidad: Cantidad
    descripcion: str | None = Field(default=None, max_length=255)
    uuid_origen: UUID | None = None
    latitud: float | None = Field(default=None, ge=-90, le=90)
    longitud: float | None = Field(default=None, ge=-180, le=180)


class MovimientoSalida(BaseModel):
    id: int
    material_id: int
    material_codigo: str
    tipo: str
    cantidad: Decimal
    delta: Decimal
    existencias_resultantes: Decimal
    origen: str
    descripcion: str | None
    orden_id: int | None
    uuid_origen: UUID | None
    creado_en: datetime
    creado_por: int | None


class BodegaCambioEntrada(_Entrada):
    estado_id: int
    observacion: str | None = Field(default=None, max_length=500)


class CargueBodegaSalida(BaseModel):
    id: int
    estado: str
    filas: int
    errores: list[dict[str, Any]]
    creado_en: datetime
    procesado_en: datetime | None
