"""Reglas puras de dominio para normalización y lectura de libros de migración."""

import datetime as dt
import io
import unicodedata
from dataclasses import dataclass
from typing import Any

from openpyxl import load_workbook

_EXCEL_EPOCH = dt.date(1899, 12, 30)

_ALIAS_MARCA: dict[str, str] = {
    "KUNIX": "KUNIX",
    "KUN IX": "KUNIX",
    "SCHREDER": "SCHREDER",
    "SHREDER": "SCHREDER",
    "SILVANIA": "SYLVANIA",
    "SYLVANIA": "SYLVANIA",
}

_ALIAS_TECNOLOGIA: dict[str, str] = {
    "MH": "METAL_HALIDE",
    "METAL HALIDE": "METAL_HALIDE",
    "METAL_HALIDE": "METAL_HALIDE",
    "LED": "LED",
    "LED SOLAR": "LED_SOLAR",
    "LED_SOLAR": "LED_SOLAR",
    "INDUCCION": "INDUCCION",
    "SODIO": "SODIO",
    "MIXTA": "MIXTA",
    "AHORRADORA": "AHORRADORA",
}


@dataclass(frozen=True)
class ErrorDominioMigracion(Exception):
    status_code: int
    detail: str


def _sin_tildes(texto: str) -> str:
    nfd = unicodedata.normalize("NFD", texto)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def normalizar_codigo_marca(valor: Any) -> str | None:
    if valor is None:
        return None
    limpio = _sin_tildes(str(valor).strip()).upper()
    if not limpio:
        return None
    return _ALIAS_MARCA.get(limpio, limpio.replace(" ", "_"))


def normalizar_codigo_tecnologia(valor: Any) -> str | None:
    if valor is None:
        return None
    limpio = _sin_tildes(str(valor).strip()).upper()
    if not limpio:
        return None
    return _ALIAS_TECNOLOGIA.get(limpio, limpio.replace(" ", "_"))


def normalizar_codigo_potencia(valor: Any) -> str | None:
    if valor is None:
        return None
    txt = str(valor).strip().upper().removesuffix("W").strip()
    if not txt:
        return None
    try:
        return str(int(float(txt)))
    except ValueError:
        return txt


def normalizar_fecha_sapef(valor: Any) -> dt.date | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, dt.datetime):
        fecha = valor.date()
    elif isinstance(valor, dt.date):
        fecha = valor
    elif isinstance(valor, (int, float)):
        if valor <= 2:
            return None
        fecha = _EXCEL_EPOCH + dt.timedelta(days=int(valor))
    else:
        txt = str(valor).strip()
        if not txt or txt in {"01/01/1900", "1900-01-01", "1/01/1900", "1/1/1900"}:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                fecha = dt.datetime.strptime(txt[:10], fmt).date()
                break
            except ValueError:
                continue
        else:
            raise ErrorDominioMigracion(422, f"Formato de fecha inválido: {txt!r}.")
    if fecha.year <= 1900:
        return None
    return fecha


def normalizar_bool(valor: Any, default: bool = False) -> bool:
    if valor is None or valor == "":
        return default
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(valor)
    txt = _sin_tildes(str(valor).strip()).upper()
    if txt in {"1", "TRUE", "SI", "S", "YES", "Y"}:
        return True
    if txt in {"0", "FALSE", "NO", "N"}:
        return False
    return default


def leer_hojas_xlsx(archivo_bytes: bytes) -> dict[str, list[dict[str, Any]]]:
    """Lee un archivo .xlsx validando que no contenga fórmulas."""
    if not archivo_bytes:
        raise ErrorDominioMigracion(422, "El archivo Excel está vacío.")
    try:
        wb = load_workbook(io.BytesIO(archivo_bytes), data_only=False, read_only=True)
    except Exception as exc:
        raise ErrorDominioMigracion(422, "El archivo no es un libro .xlsx válido.") from exc

    resultado: dict[str, list[dict[str, Any]]] = {}
    try:
        for nombre_hoja in wb.sheetnames:
            ws = wb[nombre_hoja]
            filas_iter = ws.iter_rows(values_only=True)
            encabezado_raw = next(filas_iter, None)
            if encabezado_raw is None:
                resultado[nombre_hoja] = []
                continue
            encabezados: list[str] = []
            for idx, celda in enumerate(encabezado_raw):
                if isinstance(celda, str) and celda.startswith("="):
                    raise ErrorDominioMigracion(
                        422, f"La hoja {nombre_hoja} contiene una fórmula en el encabezado."
                    )
                nombre_col = (
                    _sin_tildes(str(celda)).strip().lower().replace(" ", "_")
                    if celda is not None
                    else f"col_{idx}"
                )
                encabezados.append(nombre_col)

            filas: list[dict[str, Any]] = []
            for n_fila, fila_raw in enumerate(filas_iter, start=2):
                if all(v is None or str(v).strip() == "" for v in fila_raw):
                    continue
                registro: dict[str, Any] = {}
                for col_idx, col_nombre in enumerate(encabezados):
                    val = fila_raw[col_idx] if col_idx < len(fila_raw) else None
                    if isinstance(val, str) and val.startswith("="):
                        raise ErrorDominioMigracion(
                            422,
                            f"La hoja '{nombre_hoja}' fila {n_fila} contiene fórmulas.",
                        )
                    registro[col_nombre] = val
                filas.append(registro)
            resultado[nombre_hoja] = filas
    finally:
        wb.close()
    return resultado
