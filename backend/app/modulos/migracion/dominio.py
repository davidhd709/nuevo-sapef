"""Reglas puras de dominio para normalización y lectura de libros de migración."""

import csv
import datetime as dt
import io
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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
        momento = normalizar_fecha_hora_sapef(valor)
        return momento.date() if momento is not None else None
    if fecha.year <= 1900:
        return None
    return fecha


_HORA = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*([AaPp]\.?\s?[Mm]\.?)?$")


def normalizar_fecha_hora_sapef(valor: Any) -> dt.datetime | None:
    """Fecha (y hora, si viene) de SAPEF como datetime sin zona.

    SAPEF exporta tres formatos: `29/07/2024 14:51:14` (día/mes), `2/25/2019 5:38:52 AM`
    (mes/día, siempre con AM/PM) y ISO. `01/01/1900` significa «sin fecha» y da None.
    """
    if valor is None or valor == "":
        return None
    if isinstance(valor, dt.datetime):
        return None if valor.year <= 1900 else valor.replace(tzinfo=None)
    if isinstance(valor, dt.date):
        return None if valor.year <= 1900 else dt.datetime(valor.year, valor.month, valor.day)
    if isinstance(valor, (int, float)):
        fecha = normalizar_fecha_sapef(valor)
        return dt.datetime(fecha.year, fecha.month, fecha.day) if fecha else None
    txt = str(valor).strip()
    if not txt:
        return None
    if "T" in txt[:11] and txt[:4].isdigit():
        txt = txt.replace("T", " ", 1)
    partes = txt.split(" ", 1)
    fecha_txt, hora_txt = partes[0], (partes[1].strip() if len(partes) > 1 else "")
    con_am_pm = bool(re.search(r"[AaPp]\.?\s?[Mm]\.?$", hora_txt))
    formatos = ("%Y-%m-%d", "%Y/%m/%d") + (
        ("%m/%d/%Y", "%d/%m/%Y") if con_am_pm else ("%d/%m/%Y", "%m/%d/%Y")
    )
    fecha: dt.date | None = None
    for fmt in formatos:
        try:
            fecha = dt.datetime.strptime(fecha_txt, fmt).date()
            break
        except ValueError:
            continue
    if fecha is None:
        raise ErrorDominioMigracion(422, f"Formato de fecha inválido: {txt!r}.")
    if fecha.year <= 1900:
        return None
    hora, minuto, segundo = 0, 0, 0
    if hora_txt:
        m = _HORA.match(hora_txt.replace(" ", " "))
        if m is None:
            raise ErrorDominioMigracion(422, f"Formato de hora inválido: {txt!r}.")
        hora, minuto, segundo = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        sufijo = (m.group(4) or "").upper().replace(".", "").replace(" ", "")
        if sufijo == "PM" and hora < 12:
            hora += 12
        elif sufijo == "AM" and hora == 12:
            hora = 0
        if hora > 23 or minuto > 59 or segundo > 59:
            raise ErrorDominioMigracion(422, f"Formato de hora inválido: {txt!r}.")
    return dt.datetime(fecha.year, fecha.month, fecha.day, hora, minuto, segundo)


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
                encabezados.append(normalizar_encabezado(celda, idx))

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


# --- Lectura tabular: Excel (.xlsx) o CSV exportado por SAPEF --------------------------------

_HOJA_CSV = "csv"
_SEPARADORES = (";", "\t", ",", "|")


def normalizar_encabezado(celda: Any, idx: int) -> str:
    if celda is None or str(celda).strip() == "":
        return f"col_{idx}"
    limpio = _sin_tildes(str(celda)).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", limpio).strip("_") or f"col_{idx}"


def _decodificar(contenido: bytes) -> str:
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            return contenido.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return contenido.decode("latin-1")


def _es_formula(valor: str) -> bool:
    return len(valor) > 1 and valor[0] == "=" and not valor[1:].replace(".", "", 1).isdigit()


def leer_csv(contenido: bytes) -> list[dict[str, Any]]:
    """CSV de SAPEF: con o sin BOM, con línea `sep=;` opcional y separador `;`, tabulador o
    coma (lo detecta por el encabezado). Las celdas vacías llegan como None."""
    lineas = _decodificar(contenido).splitlines()
    separador: str | None = None
    if lineas and re.fullmatch(r"sep=.", lineas[0].strip(), flags=re.IGNORECASE):
        separador = lineas[0].strip()[4]
        lineas = lineas[1:]
    while lineas and not lineas[0].strip():
        lineas = lineas[1:]
    if not lineas:
        raise ErrorDominioMigracion(422, "El archivo CSV no tiene encabezado.")
    if separador is None:
        separador = max(_SEPARADORES, key=lambda s: lineas[0].count(s))
    lector = csv.reader(io.StringIO("\n".join(lineas)), delimiter=separador)
    columnas = [normalizar_encabezado(c, i) for i, c in enumerate(next(lector))]
    filas: list[dict[str, Any]] = []
    for valores in lector:
        if all(not v.strip() for v in valores):
            continue
        registro: dict[str, Any] = {}
        for i, col in enumerate(columnas):
            val = valores[i].strip() if i < len(valores) else ""
            if _es_formula(val):
                raise ErrorDominioMigracion(
                    422, f"La fila {len(filas) + 2} contiene fórmulas; no se importa."
                )
            registro[col] = val if val != "" else None
        filas.append(registro)
    return filas


def es_xlsx(contenido: bytes) -> bool:
    return contenido[:4] == b"PK\x03\x04"


def leer_tabla(contenido: bytes) -> dict[str, list[dict[str, Any]]]:
    """Hojas del archivo: un .xlsx da una entrada por hoja; un CSV, una sola («csv»)."""
    if not contenido:
        raise ErrorDominioMigracion(422, "El archivo está vacío.")
    if es_xlsx(contenido):
        return leer_hojas_xlsx(contenido)
    if b"\x00" in contenido[:4096]:
        raise ErrorDominioMigracion(422, "El archivo no es un Excel (.xlsx) ni un CSV de texto.")
    return {_HOJA_CSV: leer_csv(contenido)}


def hoja(hojas: Mapping[str, list[dict[str, Any]]], *nombres: str) -> list[dict[str, Any]]:
    """La hoja con alguno de esos nombres (sin importar mayúsculas), o la única del archivo."""
    por_nombre = {normalizar_encabezado(k, 0): v for k, v in hojas.items()}
    for nombre in nombres:
        encontrada = por_nombre.get(normalizar_encabezado(nombre, 0))
        if encontrada is not None:
            return encontrada
    if len(hojas) == 1:
        return next(iter(hojas.values()))
    return []


def campo(fila: Mapping[str, Any], *alias: str) -> Any:
    """Primer valor no vacío entre los alias de columna (plantilla nueva o exportación de SAPEF)."""
    for nombre in alias:
        val = fila.get(nombre)
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        return val
    return None


def texto(fila: Mapping[str, Any], *alias: str) -> str | None:
    val = campo(fila, *alias)
    if val is None:
        return None
    if isinstance(val, float) and val.is_integer():
        val = int(val)
    limpio = str(val).strip()
    return limpio or None


def numero(valor: Any) -> float | None:
    """Número de SAPEF; acepta coma decimal (`7,95`)."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        raise ErrorDominioMigracion(422, f"Número inválido: {valor!r}.")
    if isinstance(valor, (int, float)):
        return float(valor)
    txt = str(valor).strip().replace(" ", "")
    if "," in txt and "." not in txt:
        txt = txt.replace(",", ".")
    try:
        return float(txt)
    except ValueError as exc:
        raise ErrorDominioMigracion(422, f"Número inválido: {valor!r}.") from exc


def decimal_no_negativo(valor: Any, nombre: str) -> Decimal:
    num = numero(valor)
    if num is None:
        raise ErrorDominioMigracion(422, f"Falta {nombre}.")
    try:
        dec = Decimal(str(num))
    except InvalidOperation as exc:
        raise ErrorDominioMigracion(422, f"{nombre} inválido: {valor!r}.") from exc
    if dec < 0:
        raise ErrorDominioMigracion(422, f"{nombre} no puede ser negativo.")
    return dec


def coordenadas_colombia(
    latitud: Any, longitud: Any
) -> tuple[float | None, float | None, str | None]:
    """(lat, lng, advertencia). Colombia está al occidente: algunas exportaciones de SAPEF
    (mantenimientos) traen la longitud sin signo y se corrige. `0` se toma como «sin dato»."""
    lat, lng = numero(latitud), numero(longitud)
    if not lat or not lng:
        return None, None, None
    aviso = None
    if lng > 0:
        lng = -lng
        aviso = "Longitud sin signo negativo; se corrigió."
    if not (-5 <= lat <= 14 and -82 <= lng <= -66):
        raise ErrorDominioMigracion(422, f"Coordenadas fuera de Colombia: {lat}, {lng}.")
    return lat, lng, aviso


_PRIORIDADES = {"URGENTE": 0, "ALTA": 1, "MEDIA": 2, "BAJA": 3}


def normalizar_prioridad(valor: Any) -> int:
    if valor is None or valor == "":
        return 2
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        prioridad = int(valor)
    else:
        txt = _sin_tildes(str(valor).strip()).upper()
        if txt in _PRIORIDADES:
            return _PRIORIDADES[txt]
        try:
            prioridad = int(float(txt))
        except ValueError as exc:
            raise ErrorDominioMigracion(422, f"Prioridad desconocida: {valor!r}.") from exc
    if not 0 <= prioridad <= 3:
        raise ErrorDominioMigracion(422, f"Prioridad fuera de rango (0 a 3): {valor!r}.")
    return prioridad


def normalizar_identificacion(valor: Any) -> str | None:
    """Cédula sin puntos ni espacios (SAPEF la guarda a veces como `50.929.069`)."""
    txt = texto({"v": valor}, "v")
    if txt is None:
        return None
    return re.sub(r"[\s.]", "", txt) or None


def clave_texto(valor: Any) -> str:
    """Texto comparable: sin tildes, mayúsculas y espacios simples."""
    return re.sub(r"\s+", " ", _sin_tildes(str(valor or "")).strip().upper())


POTENCIA_ATIPICA_W = 1000


def potencia_atipica(codigo_potencia: str | None) -> bool:
    if codigo_potencia is None:
        return False
    try:
        return float(codigo_potencia) > POTENCIA_ATIPICA_W
    except ValueError:
        return False


COLUMNAS_CLAVE = frozenset(
    {"clave", "password", "contrasena", "hash_clave", "hash", "pass", "pwd", "clave_hash"}
)


def columnas_clave(filas: Iterable[Mapping[str, Any]]) -> list[str]:
    """Columnas de contraseña presentes en las filas (se ignoran: nunca se importan)."""
    vistas: set[str] = set()
    for fila in filas:
        vistas.update(k for k in fila if k in COLUMNAS_CLAVE)
    return sorted(vistas)


def es_si(valor: Any) -> bool:
    return normalizar_bool(valor, False)
