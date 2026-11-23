"""Esquemas Pydantic v2 (DTOs) del módulo de migración."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class EjecucionMigracionSalida(BaseModel):
    id: int
    ejecucion_id: int
    ejecucionId: int
    tarea_id: int | None = None
    tareaId: int | None = None
    tipo: str
    estado: str
    conciliacion: dict[str, int]
    errores: list[dict[str, Any]]
    creado_en: datetime
