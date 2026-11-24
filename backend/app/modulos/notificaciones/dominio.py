"""Reglas puras de Web Push: validación de suscripciones y claves VAPID (sin BD ni HTTP)."""

import base64
import binascii
import json
from typing import Any
from urllib.parse import urlparse


class ErrorDominioNotificaciones(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


# Respuestas del servicio push que indican que la suscripción ya no existe (RFC 8030).
ESTADOS_SUSCRIPCION_VENCIDA = (404, 410)
MAX_FALLOS = 10
MAX_BYTES_MENSAJE = 3000  # los servicios push aceptan ~4 KB cifrados


def _b64url(valor: str) -> bytes:
    relleno = "=" * (-len(valor) % 4)
    try:
        return base64.urlsafe_b64decode(valor + relleno)
    except (binascii.Error, ValueError) as exc:
        raise ErrorDominioNotificaciones(422, "Clave de suscripción mal codificada.") from exc


def validar_endpoint(endpoint: str) -> str:
    valor = endpoint.strip()
    partes = urlparse(valor)
    if partes.scheme != "https" or not partes.netloc or "@" in partes.netloc:
        raise ErrorDominioNotificaciones(
            422, "El endpoint de la suscripción debe ser una URL https válida."
        )
    return valor


def validar_claves(p256dh: str, auth: str) -> tuple[str, str]:
    """p256dh: punto P-256 sin comprimir (65 bytes, empieza en 0x04); auth: 16 bytes."""
    p256dh, auth = p256dh.strip(), auth.strip()
    if not p256dh or not auth:
        raise ErrorDominioNotificaciones(422, "Faltan las claves de la suscripción.")
    punto = _b64url(p256dh)
    if len(punto) != 65 or punto[0] != 0x04:
        raise ErrorDominioNotificaciones(422, "La clave p256dh no es un punto P-256 válido.")
    if len(_b64url(auth)) != 16:
        raise ErrorDominioNotificaciones(422, "La clave auth debe tener 16 bytes.")
    return p256dh, auth


def serializar_mensaje(mensaje: dict[str, Any]) -> str:
    datos = json.dumps(mensaje, ensure_ascii=False, separators=(",", ":"))
    if len(datos.encode("utf-8")) > MAX_BYTES_MENSAJE:
        raise ErrorDominioNotificaciones(422, "El aviso es demasiado largo para Web Push.")
    return datos


def quitar_suscripcion(estado_http: int | None, fallos: int) -> bool:
    return estado_http in ESTADOS_SUSCRIPCION_VENCIDA or fallos >= MAX_FALLOS


def codificar_b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")
