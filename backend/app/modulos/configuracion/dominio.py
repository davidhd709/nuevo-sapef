"""Reglas puras del módulo de configuración (sin BD, HTTP ni cola)."""

import html
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


class ErrorDominioConfiguracion(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


# --- Códigos y nombres -----------------------------------------------------------------------

_RE_CODIGO_SEDE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
_RE_CODIGO_MAESTRO = re.compile(r"^[A-Z0-9][A-Z0-9_]{0,59}$")
_RE_CODIGO_COMERCIAL = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{0,19}$")


def quitar_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def normalizar_nombre(nombre: str) -> str:
    limpio = re.sub(r"\s+", " ", nombre).strip()
    if not limpio:
        raise ErrorDominioConfiguracion(422, "El nombre no puede estar vacío.")
    return limpio


def normalizar_codigo_sede(codigo: str) -> str:
    limpio = codigo.strip().lower()
    if not _RE_CODIGO_SEDE.match(limpio):
        raise ErrorDominioConfiguracion(
            422,
            "El código de sede debe tener de 2 a 40 caracteres: minúsculas, números, '_' o '-'.",
        )
    return limpio


def normalizar_codigo_maestro(codigo: str) -> str:
    """Código en mayúsculas sin tildes; espacios y guiones pasan a '_' (KÜNIX -> KUNIX)."""
    limpio = re.sub(r"[\s-]+", "_", quitar_tildes(codigo.strip()).upper())
    if not _RE_CODIGO_MAESTRO.match(limpio):
        raise ErrorDominioConfiguracion(
            422, "El código debe tener letras, números o '_' (máximo 60 caracteres)."
        )
    return limpio


def normalizar_codigo_comercial(codigo: str) -> str:
    limpio = codigo.strip().upper()
    if not _RE_CODIGO_COMERCIAL.match(limpio):
        raise ErrorDominioConfiguracion(
            422, "El código debe tener letras, números, '_', '.' o '-' (máximo 20 caracteres)."
        )
    return limpio


def validar_asignaciones_unicas(codigos: Iterable[str]) -> list[str]:
    vistos: list[str] = []
    for codigo in codigos:
        c = codigo.strip().lower()
        if c in vistos:
            raise ErrorDominioConfiguracion(422, f"El comercializador '{c}' está repetido.")
        vistos.append(c)
    return vistos


# --- Parámetros (RF-013) ---------------------------------------------------------------------


def _validar_semaforo(valor: Any) -> None:
    if not isinstance(valor, dict) or set(valor) != {"verde_max_dias", "amarillo_max_dias"}:
        raise ErrorDominioConfiguracion(
            422, "El semáforo requiere exactamente 'verde_max_dias' y 'amarillo_max_dias'."
        )
    verde, amarillo = valor["verde_max_dias"], valor["amarillo_max_dias"]
    for v in (verde, amarillo):
        if isinstance(v, bool) or not isinstance(v, int):
            raise ErrorDominioConfiguracion(422, "Los umbrales del semáforo deben ser enteros.")
    if verde < 0 or amarillo <= verde or amarillo > 365:
        raise ErrorDominioConfiguracion(
            422, "Debe cumplirse 0 ≤ verde_max_dias < amarillo_max_dias ≤ 365."
        )


_VALIDADORES_PARAMETRO = {"semaforo_pqrs_umbrales": _validar_semaforo}


def validar_valor_parametro(codigo: str, valor: Any) -> None:
    if valor is None:
        raise ErrorDominioConfiguracion(422, "El valor del parámetro es obligatorio.")
    validador = _VALIDADORES_PARAMETRO.get(codigo)
    if validador is not None:
        validador(valor)


# --- Plantillas de correo (RF-014) -----------------------------------------------------------

_RE_VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
# El cuerpo se envía por correo y se previsualiza en la web: sin scripts ni manejadores.
_RE_HTML_PELIGROSO = re.compile(
    r"<\s*(script|iframe|object|embed|form|meta|link|style|base)\b|\bon[a-z]+\s*=|javascript\s*:",
    re.IGNORECASE,
)


def extraer_variables(texto: str) -> set[str]:
    return set(_RE_VARIABLE.findall(texto))


def renderizar_texto(
    texto: str, permitidas: set[str], contexto: dict[str, Any], *, escapar_html: bool
) -> str:
    """Reemplaza {{variable}}; las no permitidas quedan vacías; escapa los valores en HTML."""

    def valor(m: re.Match[str]) -> str:
        nombre = m.group(1)
        crudo = str(contexto.get(nombre, "")) if nombre in permitidas else ""
        return html.escape(crudo) if escapar_html else crudo

    return _RE_VARIABLE.sub(valor, texto)


def validar_plantilla(asunto: str, cuerpo_html: str, variables_permitidas: Iterable[str]) -> None:
    if not asunto.strip():
        raise ErrorDominioConfiguracion(422, "El asunto no puede estar vacío.")
    if "\n" in asunto or "\r" in asunto:
        raise ErrorDominioConfiguracion(422, "El asunto no puede tener saltos de línea.")
    if not cuerpo_html.strip():
        raise ErrorDominioConfiguracion(422, "El cuerpo no puede estar vacío.")
    if _RE_HTML_PELIGROSO.search(cuerpo_html):
        raise ErrorDominioConfiguracion(
            422, "El cuerpo no puede contener scripts, formularios ni manejadores de eventos."
        )
    desconocidas = (extraer_variables(asunto) | extraer_variables(cuerpo_html)) - set(
        variables_permitidas
    )
    if desconocidas:
        raise ErrorDominioConfiguracion(
            422, f"Variables no disponibles en esta plantilla: {', '.join(sorted(desconocidas))}."
        )


# --- Acuerdo tarifario (RF-015, RN-001 a RN-006) -------------------------------------------------

REGLA_AFINIA = "afinia_ci400"
REGLA_CELSIA = "celsia_impuesto"
TIPOS_REGLA_CELSIA = frozenset({"fija", "mayor_porcentaje_minimo", "porcentaje"})
CENTAVO = Decimal("0.01")


@dataclass(frozen=True)
class TarifaDatos:
    tarifa: str
    tipo_regla: str | None = None
    factor_uvt_minimo: Decimal | None = None
    porcentaje_costo_variable: Decimal | None = None
    valor_urbano: Decimal | None = None
    valor_rural: Decimal | None = None


@dataclass(frozen=True)
class ExcepcionDatos:
    identificador: str
    factor_uvt: Decimal | None = None
    regla: dict[str, Any] | None = None


@dataclass(frozen=True)
class AcuerdoDatos:
    uvt: Decimal | None
    umbral_kwh: Decimal | None
    tolerancia: Decimal | None
    base_costo_variable: str | None
    tarifas: list[TarifaDatos] = field(default_factory=list)
    excepciones: list[ExcepcionDatos] = field(default_factory=list)


def valor_minimo(uvt: Decimal | None, factor: Decimal | None) -> Decimal | None:
    """UVT × factor redondeando solo el resultado a centavos (ROUND_HALF_UP, §11.6)."""
    if uvt is None or factor is None:
        return None
    return (uvt * factor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def validar_regla_admite_acuerdo(regla_tarifaria: str | None, comercializador: str) -> str:
    if regla_tarifaria not in (REGLA_AFINIA, REGLA_CELSIA):
        raise ErrorDominioConfiguracion(
            422, f"El comercializador '{comercializador}' no tiene control tarifario."
        )
    return regla_tarifaria


def validar_estructura_acuerdo(regla: str, datos: AcuerdoDatos) -> None:
    """Validaciones que aplican también al borrador (puede estar incompleto, no inconsistente)."""
    tarifas = [t.tarifa for t in datos.tarifas]
    if len(tarifas) != len(set(tarifas)):
        raise ErrorDominioConfiguracion(422, "Hay tarifas repetidas en el acuerdo.")
    ids = [e.identificador for e in datos.excepciones]
    if len(ids) != len(set(ids)):
        raise ErrorDominioConfiguracion(422, "Hay excepciones repetidas (mismo NIC o cuenta).")
    if regla == REGLA_CELSIA:
        for t in datos.tarifas:
            if t.tipo_regla is not None and t.tipo_regla not in TIPOS_REGLA_CELSIA:
                raise ErrorDominioConfiguracion(
                    422,
                    f"Tipo de regla no válido en '{t.tarifa}': use "
                    f"{', '.join(sorted(TIPOS_REGLA_CELSIA))}.",
                )
    elif any(t.tipo_regla is not None for t in datos.tarifas):
        raise ErrorDominioConfiguracion(422, "Las tarifas de Afinia no llevan tipo de regla.")


def faltantes_para_aprobar(regla: str, datos: AcuerdoDatos) -> list[str]:
    faltan: list[str] = []
    if datos.tolerancia is None:
        faltan.append("tolerancia")
    if not datos.base_costo_variable:
        faltan.append("base_costo_variable")
    if not datos.tarifas:
        faltan.append("tarifas (al menos una)")

    if regla == REGLA_AFINIA:
        if datos.uvt is None or datos.uvt <= 0:
            faltan.append("uvt")
        if datos.umbral_kwh is None or datos.umbral_kwh <= 0:
            faltan.append("umbral_kwh")
        for t in datos.tarifas:
            if t.factor_uvt_minimo is None:
                faltan.append(f"{t.tarifa}: factor_uvt_minimo")
            if t.porcentaje_costo_variable is None:
                faltan.append(f"{t.tarifa}: porcentaje_costo_variable")
    else:
        for t in datos.tarifas:
            requeridos: tuple[str, ...]
            if t.tipo_regla is None:
                faltan.append(f"{t.tarifa}: tipo_regla")
                continue
            if t.tipo_regla == "fija":
                requeridos = ("valor_urbano", "valor_rural")
            elif t.tipo_regla == "mayor_porcentaje_minimo":
                requeridos = ("porcentaje_costo_variable", "valor_urbano", "valor_rural")
            else:
                requeridos = ("porcentaje_costo_variable",)
            faltan.extend(f"{t.tarifa}: {c}" for c in requeridos if getattr(t, c) is None)

    for e in datos.excepciones:
        if e.factor_uvt is None and not e.regla:
            faltan.append(f"excepción {e.identificador}: factor_uvt o regla")
        if regla == REGLA_AFINIA and e.factor_uvt is not None and datos.uvt is None:
            faltan.append("uvt (lo usan las excepciones)")
    return list(dict.fromkeys(faltan))


def validar_aprobable(estado: str, regla: str, datos: AcuerdoDatos) -> None:
    if estado != "borrador":
        raise ErrorDominioConfiguracion(409, "Solo se puede aprobar un acuerdo en borrador.")
    faltan = faltantes_para_aprobar(regla, datos)
    if faltan:
        raise ErrorDominioConfiguracion(
            422, f"El acuerdo está incompleto; falta: {'; '.join(faltan)}."
        )


def validar_editable(estado: str) -> None:
    if estado != "borrador":
        raise ErrorDominioConfiguracion(
            409,
            "Un acuerdo aprobado no se modifica: cópielo a un borrador y apruebe la nueva versión.",
        )
