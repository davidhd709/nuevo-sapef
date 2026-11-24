"""Reglas puras del tablero: series mensuales, consolidado de varias sedes y variaciones."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

SIN_CORTES = "sin_cortes_cargados"
PENDIENTE = "pendiente_de_calculo"
CON_DATOS = "con_datos"

# Indicadores escalares de la operación que se suman entre sedes en el consolidado.
OPERACION_SUMABLE = (
    "total_luminarias",
    "en_servicio",
    "en_bodega",
    "pqrs_abiertas",
    "pqrs_verde",
    "pqrs_amarillo",
    "pqrs_rojo",
    "pqrs_recibidas_mes",
    "pqrs_recibidas_mes_anterior",
    "pqrs_atendidas_mes",
    "mantenimientos_mes",
    "mantenimientos_mes_anterior",
    "ordenes_abiertas",
    "materiales_bajo_minimo",
)


@dataclass(frozen=True)
class FilaDimension:
    dimension: str
    clave: str
    etiqueta: str
    grupo: str | None
    cantidad: int


def serie_mensual(filas: Iterable[tuple[int, int, int]], anio: int) -> list[dict[str, int]]:
    """Doce meses del año con la cantidad del mes y el acumulado (meses sin dato valen 0)."""
    por_mes = defaultdict(int)
    for a, mes, cantidad in filas:
        if a == anio:
            por_mes[mes] += cantidad
    salida, acumulado = [], 0
    for mes in range(1, 13):
        acumulado += por_mes[mes]
        salida.append({"mes": mes, "cantidad": por_mes[mes], "acumulado": acumulado})
    return salida


def consolidar_dimensiones(
    filas_por_sede: Mapping[str, Iterable[FilaDimension]],
) -> dict[str, list[dict[str, Any]]]:
    """Agrupa por dimensión. Con una sola sede se conserva la clave; con varias, tecnología,
    potencia y estado se suman por etiqueta, y zona y barrio se rotulan con la sede (los barrios
    de dos municipios distintos nunca se mezclan)."""
    varias = len(filas_por_sede) > 1
    acumulado: dict[str, dict[tuple[str, str | None], int]] = defaultdict(lambda: defaultdict(int))
    for sede_nombre, filas in filas_por_sede.items():
        for f in filas:
            etiqueta, grupo = f.etiqueta, f.grupo
            if varias and f.dimension in ("zona", "barrio", "pqrs_barrio"):
                grupo = f"{sede_nombre} · {grupo}" if grupo else sede_nombre
            acumulado[f.dimension][(etiqueta, grupo)] += f.cantidad
    salida: dict[str, list[dict[str, Any]]] = {}
    for dimension, conteos in acumulado.items():
        salida[dimension] = sorted(
            (
                {"etiqueta": etiqueta, "grupo": grupo, "cantidad": cantidad}
                for (etiqueta, grupo), cantidad in conteos.items()
            ),
            key=lambda d: (-d["cantidad"], d["etiqueta"]),
        )
    return salida


def sumar_operacion(por_sede: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Suma los indicadores escalares; el tiempo promedio de atención se pondera por PQRS
    atendidas (un promedio de promedios engañaría)."""
    lista = list(por_sede)
    total: dict[str, Any] = {k: sum(int(o.get(k) or 0) for o in lista) for k in OPERACION_SUMABLE}
    peso = sum(int(o.get("pqrs_atendidas_anio") or 0) for o in lista)
    horas = sum(
        float(o.get("tiempo_promedio_atencion_horas") or 0) * int(o.get("pqrs_atendidas_anio") or 0)
        for o in lista
    )
    total["pqrs_atendidas_anio"] = peso
    total["tiempo_promedio_atencion_horas"] = round(horas / peso, 1) if peso else None
    return total


def variacion(actual: float | int | None, anterior: float | int | None) -> float | None:
    """Variación porcentual; None si no hay base de comparación."""
    if actual is None or anterior in (None, 0):
        return None
    return round((float(actual) - float(anterior)) / abs(float(anterior)) * 100, 1)


def estado_comercial(con_cortes: bool, filas: list[dict[str, Any]]) -> str:
    if filas:
        return CON_DATOS
    return PENDIENTE if con_cortes else SIN_CORTES
