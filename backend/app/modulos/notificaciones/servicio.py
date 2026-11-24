"""Servicio público del módulo de notificaciones (HU-064, RF-105).

Las suscripciones Web Push se guardan por usuario. El envío corre en el worker (las tareas solo
reciben ids) y usa VAPID con la clave privada de `SAPEF_VAPID_CLAVE_PRIVADA`. Sin clave, la API
acepta suscripciones pero no envía nada (lo deja en el log). Nunca se registra el endpoint en
los logs: es una credencial del dispositivo.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from app.core.config import obtener_configuracion
from app.modulos.notificaciones import dominio, repositorio
from app.modulos.notificaciones.esquemas import (
    ClavePublicaSalida,
    SuscripcionBorrarEntrada,
    SuscripcionEntrada,
    SuscripcionSalida,
)
from app.modulos.notificaciones.modelos import SuscripcionPush
from app.modulos.seguridad.servicio import UsuarioAutenticado

log = logging.getLogger("sapef.notificaciones")


def _http(exc: dominio.ErrorDominioNotificaciones) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _vapid() -> Vapid | None:
    clave = obtener_configuracion().vapid_clave_privada
    if clave is None or not clave.get_secret_value().strip():
        return None
    return Vapid.from_string(private_key=clave.get_secret_value().strip())


def _clave_publica(vapid: Vapid) -> str:
    punto = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return dominio.codificar_b64url(punto)


def obtener_clave_publica() -> ClavePublicaSalida:
    vapid = _vapid()
    if vapid is None:
        return ClavePublicaSalida(habilitado=False, clave_publica=None)
    return ClavePublicaSalida(habilitado=True, clave_publica=_clave_publica(vapid))


def generar_claves_vapid() -> tuple[str, str]:
    """(privada, pública) en base64url, para `SAPEF_VAPID_CLAVE_PRIVADA` y para verificar."""
    privada = ec.generate_private_key(ec.SECP256R1())
    numero = privada.private_numbers().private_value.to_bytes(32, "big")
    publica = privada.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return dominio.codificar_b64url(numero), dominio.codificar_b64url(publica)


def suscribir(
    db: Session, actor: UsuarioAutenticado, entrada: SuscripcionEntrada, agente: str | None
) -> tuple[SuscripcionSalida, bool]:
    try:
        endpoint = dominio.validar_endpoint(entrada.endpoint)
        p256dh, auth = dominio.validar_claves(entrada.claves.p256dh, entrada.claves.auth)
    except dominio.ErrorDominioNotificaciones as exc:
        raise _http(exc) from exc
    existente = repositorio.obtener_por_endpoint(db, endpoint)
    creada = existente is None
    if existente is None:
        existente = repositorio.agregar(
            db,
            SuscripcionPush(
                usuario_id=actor.id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                agente=(agente or "")[:255] or None,
            ),
        )
    else:
        # El mismo teléfono con otra persona: la suscripción pasa a quien inició sesión.
        existente.usuario_id = actor.id
        existente.p256dh = p256dh
        existente.auth = auth
        existente.fallos = 0
    db.commit()
    db.refresh(existente)
    return SuscripcionSalida(id=existente.id, creado_en=existente.creado_en), creada


def desuscribir(db: Session, actor: UsuarioAutenticado, entrada: SuscripcionBorrarEntrada) -> None:
    if repositorio.borrar_de_usuario(db, actor.id, entrada.endpoint.strip()) == 0:
        raise HTTPException(status_code=404, detail="La suscripción no existe.")
    db.commit()


def enviar_a_usuarios(db: Session, usuario_ids: list[int], mensaje: dict[str, Any]) -> int:
    """Envía el aviso a todos los dispositivos de las personas. Devuelve cuántos aceptó el
    servicio push. Borra las suscripciones vencidas (404/410) o con demasiados fallos."""
    if not usuario_ids:
        return 0
    suscripciones = repositorio.listar_de_usuarios(db, usuario_ids)
    if not suscripciones:
        return 0
    vapid = _vapid()
    if vapid is None:
        log.warning("Web Push sin clave VAPID: %s aviso(s) sin enviar", len(suscripciones))
        return 0
    config = obtener_configuracion()
    datos = dominio.serializar_mensaje(mensaje)
    entregados = 0
    for s in suscripciones:
        estado: int | None = None
        try:
            claves = {"p256dh": s.p256dh, "auth": s.auth}
            webpush(
                subscription_info={"endpoint": s.endpoint, "keys": claves},
                data=datos,
                vapid_private_key=vapid,
                vapid_claims={"sub": config.vapid_sujeto},
                ttl=config.push_ttl_segundos,
                timeout=10,
            )
            s.fallos = 0
            s.ultimo_envio_en = datetime.now(UTC)
            entregados += 1
        except WebPushException as exc:
            estado = exc.response.status_code if exc.response is not None else None
            s.fallos += 1
            log.info("Web Push rechazado (suscripción %s, estado %s)", s.id, estado)
        except Exception:  # red caída, DNS: se reintenta en el próximo aviso
            s.fallos += 1
            log.warning("Web Push falló por red (suscripción %s)", s.id)
        if dominio.quitar_suscripcion(estado, s.fallos):
            repositorio.borrar(db, s)
    db.commit()
    return entregados
