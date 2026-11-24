"""Reglas puras de la sincronización de campo (sin BD, HTTP ni cola).

Diseño (§9.7): la app baja un paquete con un cursor; la siguiente bajada pide solo lo que cambió
desde ese cursor. La subida es un lote de operaciones con uuid: cada una se aplica una sola vez,
y si la orden cambió en la oficina mientras el técnico estaba sin señal, queda en conflicto sin
afectar a las demás del lote.
"""

import base64
import binascii
import json
from datetime import UTC, datetime, timedelta
from typing import Any


class ErrorDominioSincronizacion(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


TIPOS_OPERACION = ("mantenimiento", "modernizacion", "expansion", "reubicacion")
MAX_OPERACIONES = 50
VERSION_CURSOR = 1
# Margen al pedir cambios desde el cursor: cubre transacciones que empezaron antes de emitirlo
# y terminaron después. Bajar dos veces lo mismo no hace daño (la app reemplaza por id).
SOLAPE = timedelta(minutes=2)
# Una operación «creada» en el futuro (reloj del teléfono adelantado) se toma como de ahora.
TOLERANCIA_RELOJ = timedelta(minutes=5)

ORDEN_CERRADA, ORDEN_ANULADA = "203", "204"
ESTADOS_ABIERTOS = ("201", "202", "205")

APLICADA, YA_APLICADA, CONFLICTO, ERROR = "aplicada", "ya_aplicada", "conflicto", "error"


def codificar_cursor(momento: datetime) -> str:
    datos = json.dumps({"v": VERSION_CURSOR, "t": momento.astimezone(UTC).isoformat()})
    return base64.urlsafe_b64encode(datos.encode()).decode().rstrip("=")


def decodificar_cursor(cursor: str) -> datetime:
    try:
        relleno = "=" * (-len(cursor) % 4)
        datos = json.loads(base64.urlsafe_b64decode(cursor + relleno))
        if datos.get("v") != VERSION_CURSOR:
            raise ValueError("versión")
        momento = datetime.fromisoformat(datos["t"])
    except (binascii.Error, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ErrorDominioSincronizacion(422, "Cursor de sincronización inválido.") from exc
    if momento.tzinfo is None:
        raise ErrorDominioSincronizacion(422, "Cursor de sincronización inválido.")
    return momento


def desde_con_solape(cursor: datetime) -> datetime:
    return cursor - SOLAPE


def fecha_ejecucion(creada_en: datetime | None, ahora: datetime) -> datetime | None:
    """Fecha real del trabajo: cuando el técnico lo registró en el teléfono, no cuando volvió la
    señal. Si el reloj del teléfono está adelantado, se usa la hora del servidor."""
    if creada_en is None:
        return None
    if creada_en.tzinfo is None:
        creada_en = creada_en.replace(tzinfo=UTC)
    return ahora if creada_en > ahora + TOLERANCIA_RELOJ else creada_en


def evaluar_operacion(
    tipo: str, orden_id: int | None, orden: dict[str, Any] | None
) -> tuple[str, str] | None:
    """Decide antes de aplicar. Devuelve (estado, motivo) si la operación no puede aplicarse;
    None si puede intentarse."""
    if tipo not in TIPOS_OPERACION:
        return ERROR, f"Tipo de operación desconocido: {tipo}."
    if orden_id is None:
        return ERROR, "La operación no indica la orden."
    if orden is None:
        return CONFLICTO, "La orden ya no existe en la sede."
    numero = orden.get("numero")
    if orden["estado_codigo"] == ORDEN_ANULADA:
        return CONFLICTO, f"La orden N.º {numero} fue anulada en la oficina."
    if orden["estado_codigo"] == ORDEN_CERRADA:
        return CONFLICTO, f"La orden N.º {numero} ya estaba cerrada."
    if not orden["es_mia"]:
        return CONFLICTO, f"La orden N.º {numero} fue reasignada a otra persona."
    if orden["tipo"] != tipo:
        return ERROR, f"La orden N.º {numero} es de {orden['tipo']}, no de {tipo}."
    return None


def estado_por_http(status_code: int) -> str:
    """Un rechazo del cierre: 403/404/409 dependen del estado del servidor (conflicto); el resto
    son datos que el técnico debe corregir (error)."""
    return CONFLICTO if status_code in (403, 404, 409) else ERROR


def recortar_motivo(motivo: Any) -> str:
    texto = motivo if isinstance(motivo, str) else "No se pudo aplicar la operación."
    return texto[:500]
