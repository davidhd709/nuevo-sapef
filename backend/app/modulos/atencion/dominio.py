"""Reglas puras del módulo de atención (sin BD, HTTP ni cola)."""

from datetime import date, timedelta, timezone
from typing import Any

# Colombia no tiene horario de verano: UTC−5 fija (sin depender de tzdata en Windows).
HORA_COLOMBIA = timezone(timedelta(hours=-5), "COT")


class ErrorDominioAtencion(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


# Estados de la PQRS (§10.2): 301 → 302 → 305 → 303 · 304.
EN_ELABORACION, EN_PROCESO, EN_MANTENIMIENTO, ATENDIDA, ANULADA = (
    "301",
    "302",
    "305",
    "303",
    "304",
)
ABIERTOS = (EN_ELABORACION, EN_PROCESO, EN_MANTENIMIENTO)
CERRADOS = (ATENDIDA, ANULADA)

PRIORIDADES = {0: "Urgente", 1: "Alta", 2: "Media", 3: "Baja"}

# Estados de luminaria que se pueden reportar: en operación, ya con PQRS, o la comodín.
LUMINARIA_EN_OPERACION, LUMINARIA_ACTIVO_PQR, LUMINARIA_SIN_IDENTIFICAR = "121", "122", "110"
LUMINARIA_REPORTABLE = (LUMINARIA_EN_OPERACION, LUMINARIA_ACTIVO_PQR, LUMINARIA_SIN_IDENTIFICAR)

UMBRALES_POR_DEFECTO = {"verde_max_dias": 3, "amarillo_max_dias": 7}


def validar_abierta(estado_codigo: str) -> None:
    if estado_codigo in CERRADOS:
        nombre = "atendida" if estado_codigo == ATENDIDA else "anulada"
        raise ErrorDominioAtencion(409, f"La PQRS ya está {nombre}: no se puede modificar.")


def validar_luminaria_reportable(codigo: str, estado_codigo: str | None) -> None:
    if estado_codigo not in LUMINARIA_REPORTABLE:
        raise ErrorDominioAtencion(
            422,
            f"La luminaria {codigo} no está en operación (estado {estado_codigo}): "
            "no se puede reportar en una PQRS.",
        )


def validar_quitar_luminaria(total: int, reparada: bool) -> None:
    if reparada:
        raise ErrorDominioAtencion(409, "No se puede quitar una luminaria ya reparada.")
    if total <= 1:
        raise ErrorDominioAtencion(409, "La PQRS debe conservar al menos una luminaria.")


def umbrales(valor_parametro: Any) -> tuple[int, int]:
    datos = valor_parametro if isinstance(valor_parametro, dict) else UMBRALES_POR_DEFECTO
    try:
        return int(datos["verde_max_dias"]), int(datos["amarillo_max_dias"])
    except (KeyError, TypeError, ValueError):
        return UMBRALES_POR_DEFECTO["verde_max_dias"], UMBRALES_POR_DEFECTO["amarillo_max_dias"]


def color_semaforo(dias: int, verde_max: int, amarillo_max: int) -> str:
    """RN-015: verde ≤ verde_max días; amarillo ≤ amarillo_max; rojo después."""
    if dias <= verde_max:
        return "verde"
    if dias <= amarillo_max:
        return "amarillo"
    return "rojo"


def dias_abierta(fecha_reporte: date, hoy: date) -> int:
    return max((hoy - fecha_reporte).days, 0)


def siguiente_estado_por_orden(actual: str, evento: str) -> str | None:
    """Avance de la PQRS según su orden de trabajo (None si no cambia)."""
    if evento == "orden_creada" and actual == EN_ELABORACION:
        return EN_PROCESO
    if evento == "orden_asignada" and actual in (EN_ELABORACION, EN_PROCESO):
        return EN_MANTENIMIENTO
    return None


# --- Datos personales (RNF-006) ---------------------------------------------------------------


def _ocultar(valor: str, visibles: int) -> str:
    limpio = valor.strip()
    if len(limpio) <= visibles:
        return "•" * len(limpio)
    return "•" * (len(limpio) - visibles) + limpio[-visibles:]


def enmascarar_nombre(nombre: str) -> str:
    return " ".join(p[0] + "•" * (len(p) - 1) for p in nombre.split() if p)


def enmascarar_correo(correo: str) -> str:
    usuario, _, dominio = correo.partition("@")
    return (usuario[:1] + "•••@" + dominio) if dominio else _ocultar(correo, 2)


def enmascarar_ciudadano(datos: dict[str, Any]) -> dict[str, Any]:
    """Sin `atencion.datos_personales.ver` el valor completo nunca sale del servidor."""
    salida = dict(datos)
    if salida.get("nombre_completo"):
        salida["nombre_completo"] = enmascarar_nombre(salida["nombre_completo"])
    if salida.get("identificacion"):
        salida["identificacion"] = _ocultar(salida["identificacion"], 3)
    for campo in ("telefono", "celular"):
        if salida.get(campo):
            salida[campo] = _ocultar(salida[campo], 2)
    if salida.get("correo"):
        salida["correo"] = enmascarar_correo(salida["correo"])
    salida["enmascarado"] = True
    return salida
