"""Utilidades puras del módulo comercial: decimales exactos, periodos y textos.

Reglas generales del Anexo E: sumas monetarias en decimal exacto (DECIMAL(20,4)), división por
cero = 0 salvo donde se indica `null`, y redondeo ROUND_HALF_UP.
"""

import datetime as dt
import re
import unicodedata
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CERO = Decimal(0)
UNO = Decimal(1)
_Q2 = Decimal("0.01")
_Q4 = Decimal("0.0001")

MESES_ES: dict[str, int] = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "SETIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}
MESES_ABREVIADOS: dict[str, int] = {
    "ENE": 1,
    "FEB": 2,
    "MAR": 3,
    "ABR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SEP": 9,
    "SET": 9,
    "OCT": 10,
    "NOV": 11,
    "DIC": 12,
}
NOMBRE_MES = {v: k.capitalize() for k, v in MESES_ES.items() if k != "SETIEMBRE"}


class ErrorDominioComercial(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


# --- Decimales --------------------------------------------------------------------------------


def dec(valor: Any) -> Decimal | None:
    """Convierte a Decimal exacto. Vacío → None. Lanza ValueError si no es numérico."""
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, bool):
        raise ValueError("booleano")
    if isinstance(valor, int):
        return Decimal(valor)
    if isinstance(valor, float):
        return Decimal(repr(valor))
    texto = str(valor).strip()
    if not texto:
        return None
    texto = texto.replace("$", "").replace(" ", "")
    # Miles con punto y decimales con coma (1.234,56) o el formato inglés (1,234.56).
    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation as exc:
        raise ValueError(texto) from exc


def d(valor: Any) -> Decimal:
    """Decimal para sumar: None → 0."""
    convertido = dec(valor) if not isinstance(valor, Decimal) else valor
    return convertido if convertido is not None else CERO


def q2(valor: Any) -> Decimal:
    return d(valor).quantize(_Q2, rounding=ROUND_HALF_UP)


def q4(valor: Any) -> Decimal:
    return d(valor).quantize(_Q4, rounding=ROUND_HALF_UP)


def div(num: Any, den: Any, *, nulo: bool = False) -> Decimal | None:
    """num ÷ den a 4 decimales; división por cero → 0 (o None si `nulo`)."""
    n, m = d(num), d(den)
    if m == CERO:
        return None if nulo else CERO
    return q4(n / m)


_Q10 = Decimal("0.0000000001")


def div_precisa(num: Any, den: Any) -> Decimal:
    """num ÷ den a 10 decimales (razones y porcentajes que se comparan con OPainn, que no los
    redondea); división por cero → 0."""
    n, m = d(num), d(den)
    if m == CERO:
        return CERO
    return (n / m).quantize(_Q10, rounding=ROUND_HALF_UP)


def suma(valores: Iterable[Any]) -> Decimal:
    total = CERO
    for v in valores:
        total += d(v)
    return total


# --- Periodos ---------------------------------------------------------------------------------

_PERIODO = re.compile(r"^(\d{4})(0[1-9]|1[0-2])$")


def validar_periodo(periodo: str) -> str:
    valor = (periodo or "").strip()
    if not _PERIODO.match(valor):
        raise ErrorDominioComercial(
            422, "El periodo debe tener el formato AAAAMM (p. ej., 202607)."
        )
    return valor


def periodo_de(fecha: dt.date) -> str:
    return f"{fecha.year:04d}{fecha.month:02d}"


def indice_mes(periodo: str) -> int:
    return int(periodo[:4]) * 12 + int(periodo[4:6]) - 1


def periodo_desde_indice(indice: int) -> str:
    anio, mes = divmod(indice, 12)
    return f"{anio:04d}{mes + 1:02d}"


def sumar_meses(periodo: str, meses: int) -> str:
    return periodo_desde_indice(indice_mes(periodo) + meses)


def primer_dia(periodo: str) -> dt.date:
    return dt.date(int(periodo[:4]), int(periodo[4:6]), 1)


def desplazar(dia: dt.date, meses: int) -> dt.date:
    """Primer día del mes desplazado `meses` desde el mes de `dia`."""
    indice = dia.year * 12 + dia.month - 1 + meses
    anio, mes = divmod(indice, 12)
    return dt.date(anio, mes + 1, 1)


def meses_entre(a: str, b: str) -> int:
    return indice_mes(b) - indice_mes(a)


def faltantes_entre(a: str, b: str) -> list[str]:
    """Meses estrictamente entre dos cortes (los que no se cargaron)."""
    return [periodo_desde_indice(i) for i in range(indice_mes(a) + 1, indice_mes(b))]


def nombre_periodo(periodo: str) -> str:
    return f"{NOMBRE_MES[int(periodo[4:6])]} de {periodo[:4]}"


def como_fecha(valor: Any) -> dt.date | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    texto = str(valor).strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y%m%d"):
        try:
            return dt.datetime.strptime(texto[:10] if "-" in texto[:10] else texto, formato).date()
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(texto).date()
    except ValueError as exc:
        raise ValueError(texto) from exc


# --- Textos -----------------------------------------------------------------------------------


def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def normalizar_encabezado(texto: Any) -> str:
    """Regla de Celsia/Vatia (E.9): sin tildes, minúsculas, lo no alfanumérico → `_`."""
    base = sin_tildes(str(texto or "")).lower()
    base = re.sub(r"[^a-z0-9]+", "_", base)
    return base.strip("_")


def texto(valor: Any) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    resultado = str(valor).strip()
    return resultado or None


def entero(valor: Any) -> int | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        raise ValueError("booleano")
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float):
        if not valor.is_integer():
            raise ValueError(str(valor))
        return int(valor)
    texto_ = str(valor).strip()
    if not texto_:
        return None
    numero = Decimal(texto_)
    if numero != numero.to_integral_value():
        raise ValueError(texto_)
    return int(numero)


def identificador(valor: Any) -> str | None:
    """Cuenta o cliente como texto sin `.0` de Excel."""
    return texto(valor)
