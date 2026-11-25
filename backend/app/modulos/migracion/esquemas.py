"""Esquemas Pydantic v2 (DTOs) del módulo de migración."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class EjecucionMigracionSalida(BaseModel):
    """Una corrida de importación. `estado`: pendiente → procesando → completado,
    con_errores (algunas filas no entraron; ver `errores`) o error (no se pudo leer)."""

    id: int
    ejecucion_id: int
    ejecucionId: int
    tarea_id: int | None = None
    tareaId: int | None = None
    tipo: str
    estado: str
    archivos: list[str] = []
    conciliacion: dict[str, int]
    errores: list[dict[str, Any]]
    advertencias: list[dict[str, Any]] = []
    creado_en: datetime
    procesado_en: datetime | None = None
