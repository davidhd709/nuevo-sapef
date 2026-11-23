"""Reglas puras del módulo de inventario (sin BD, HTTP ni cola)."""

import io
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from openpyxl import load_workbook


class ErrorDominioInventario(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


TIPOS_MOVIMIENTO = ("entrada", "salida", "ajuste")
# Estados de luminaria que se gestionan en la bodega (RF-053); 126 es terminal.
ESTADOS_BODEGA = ("124", "123", "125", "112", "126")
ESTADO_TERMINAL = "126"


def normalizar_codigo_material(codigo: str) -> str:
    limpio = " ".join(codigo.split()).upper()
    if not limpio:
        raise ErrorDominioInventario(422, "El código del material es obligatorio.")
    return limpio


def calcular_delta(tipo: str, cantidad: Decimal) -> Decimal:
    """Entrada suma, salida resta; el ajuste lleva su signo (corrección de conteo físico)."""
    if tipo not in TIPOS_MOVIMIENTO:
        raise ErrorDominioInventario(422, f"Tipo de movimiento no válido: {tipo}.")
    if tipo == "ajuste":
        if cantidad == 0:
            raise ErrorDominioInventario(422, "Un ajuste no puede ser de cantidad cero.")
        return cantidad
    if cantidad <= 0:
        raise ErrorDominioInventario(422, "La cantidad debe ser mayor que cero.")
    return cantidad if tipo == "entrada" else -cantidad


def aplicar_delta(existencias: Decimal, delta: Decimal, codigo: str) -> Decimal:
    """RN-017: no se permiten existencias negativas (409 para que el cliente lo muestre)."""
    resultado = existencias + delta
    if resultado < 0:
        raise ErrorDominioInventario(
            409,
            f"Existencias insuficientes de {codigo}: hay {existencias.normalize():f} y se "
            f"necesitan {(-delta).normalize():f}.",
        )
    return resultado


def esta_bajo_minimo(existencias: Decimal, minimas: Decimal) -> bool:
    return existencias < minimas


def validar_transicion_bodega(actual: str, destino: str) -> None:
    if destino not in ESTADOS_BODEGA:
        raise ErrorDominioInventario(
            422, f"El estado {destino} no es de bodega ({', '.join(ESTADOS_BODEGA)})."
        )
    if actual not in ESTADOS_BODEGA:
        raise ErrorDominioInventario(
            422, f"La luminaria no está en bodega (estado {actual}); use una orden de trabajo."
        )
    if actual == ESTADO_TERMINAL:
        raise ErrorDominioInventario(422, "Una luminaria en disposición final no cambia de estado.")
    if actual == destino:
        raise ErrorDominioInventario(422, f"La luminaria ya está en el estado {destino}.")


# --- Cargue de bodega desde Excel -----------------------------------------------------------

COLUMNAS_CARGUE_BODEGA = ("luminaria_codigo", "estado_codigo", "observacion")
MAX_FILAS_CARGUE = 10_000


@dataclass(frozen=True)
class FilaBodega:
    fila: int
    luminaria_codigo: str
    estado_codigo: str
    observacion: str | None


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def leer_cargue_bodega(contenido: bytes) -> tuple[list[FilaBodega], list[dict[str, Any]]]:
    """Lee la primera hoja. Devuelve las filas y los errores de formato (con su fila de Excel)."""
    try:
        libro = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception as exc:  # archivo dañado o no es xlsx
        raise ErrorDominioInventario(422, "El archivo no es un Excel (.xlsx) válido.") from exc
    hoja = libro.worksheets[0]
    filas = hoja.iter_rows(values_only=True)
    encabezado = [_texto(c).lower() for c in next(filas, ())]
    faltan = [c for c in ("luminaria_codigo", "estado_codigo") if c not in encabezado]
    if faltan:
        raise ErrorDominioInventario(422, f"Faltan columnas: {', '.join(faltan)}.")
    idx = {c: encabezado.index(c) for c in COLUMNAS_CARGUE_BODEGA if c in encabezado}

    leidas: list[FilaBodega] = []
    errores: list[dict[str, Any]] = []
    for n, valores in enumerate(filas, start=2):
        if not any(v not in (None, "") for v in valores):
            continue
        if len(leidas) >= MAX_FILAS_CARGUE:
            raise ErrorDominioInventario(422, f"Máximo {MAX_FILAS_CARGUE} filas por cargue.")

        def celda(col: str, valores: tuple[Any, ...] = valores) -> str:
            i = idx.get(col)
            return _texto(valores[i]) if i is not None and i < len(valores) else ""

        codigo, estado = celda("luminaria_codigo"), celda("estado_codigo")
        if not codigo or not estado:
            errores.append(
                {"fila": n, "error": "luminaria_codigo y estado_codigo son obligatorios"}
            )
            continue
        leidas.append(FilaBodega(n, codigo, estado, celda("observacion") or None))
    return leidas, errores
