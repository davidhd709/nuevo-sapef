"""Tipos comunes de los adaptadores: resultado de normalizar un corte y esquemas de familias."""

from dataclasses import dataclass, field
from typing import Any, Literal

# Tipos de columna del almacén (el repositorio los traduce a tipos de Parquet).
TipoColumna = Literal["texto", "entero", "decimal", "fecha", "booleano"]


@dataclass
class ResultadoAdaptador:
    """Lo que entrega un adaptador al normalizar los archivos de un corte."""

    familias: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    presentes: set[str] = field(default_factory=set)
    advertencias: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    archivos: list[dict[str, Any]] = field(default_factory=list)
    completo: bool = False
    publicable: bool = False
    motivo_no_publicable: str | None = None


@dataclass(frozen=True)
class Capacidad:
    estado: Literal["disponible", "parcial", "pendiente", "no_aplica"]
    nota: str | None = None


def duplicados_exactos(filas: list[dict[str, Any]], ignorar: tuple[str, ...] = ()) -> int:
    """Filas repetidas en todas sus columnas (se cuentan las copias, no la primera)."""
    vistos: set[tuple[Any, ...]] = set()
    repetidas = 0
    for fila in filas:
        clave = tuple(v for k, v in fila.items() if k not in ignorar)
        if clave in vistos:
            repetidas += 1
        else:
            vistos.add(clave)
    return repetidas
