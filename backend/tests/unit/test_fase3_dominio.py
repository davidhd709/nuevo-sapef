"""Reglas puras de la Fase 3: cursor y conflictos de sincronización, validación de Web Push."""

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.modulos.notificaciones import dominio as push
from app.modulos.sincronizacion import dominio as sync
from app.modulos.trabajos import dominio as trabajos


def test_cursor_ida_y_vuelta_y_rechazo() -> None:
    momento = datetime(2026, 11, 24, 10, 30, tzinfo=UTC)
    assert sync.decodificar_cursor(sync.codificar_cursor(momento)) == momento
    for malo in ("basura", "", base64.urlsafe_b64encode(b'{"v":9,"t":"x"}').decode()):
        with pytest.raises(sync.ErrorDominioSincronizacion):
            sync.decodificar_cursor(malo)
    sin_zona = base64.urlsafe_b64encode(
        json.dumps({"v": 1, "t": "2026-11-24T10:30:00"}).encode()
    ).decode()
    with pytest.raises(sync.ErrorDominioSincronizacion):
        sync.decodificar_cursor(sin_zona)
    assert sync.desde_con_solape(momento) == momento - timedelta(minutes=2)


def test_fecha_ejecucion_usa_el_telefono_salvo_reloj_adelantado() -> None:
    ahora = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    ayer = ahora - timedelta(days=1)
    assert sync.fecha_ejecucion(ayer, ahora) == ayer
    assert sync.fecha_ejecucion(ahora + timedelta(hours=3), ahora) == ahora
    assert sync.fecha_ejecucion(None, ahora) is None
    assert sync.fecha_ejecucion(datetime(2026, 11, 24, 8, 0), ahora).tzinfo == UTC


@pytest.mark.parametrize(
    ("tipo", "orden_id", "orden", "esperado"),
    [
        ("poda", 1, None, "error"),
        ("mantenimiento", None, None, "error"),
        ("mantenimiento", 1, None, "conflicto"),
        (
            "mantenimiento",
            1,
            {"estado_codigo": "204", "es_mia": True, "tipo": "mantenimiento"},
            "conflicto",
        ),
        (
            "mantenimiento",
            1,
            {"estado_codigo": "203", "es_mia": True, "tipo": "mantenimiento"},
            "conflicto",
        ),
        (
            "mantenimiento",
            1,
            {"estado_codigo": "202", "es_mia": False, "tipo": "mantenimiento"},
            "conflicto",
        ),
        (
            "mantenimiento",
            1,
            {"estado_codigo": "202", "es_mia": True, "tipo": "expansion"},
            "error",
        ),
        (
            "mantenimiento",
            1,
            {"estado_codigo": "202", "es_mia": True, "tipo": "mantenimiento"},
            None,
        ),
    ],
)
def test_evaluar_operacion(tipo, orden_id, orden, esperado) -> None:
    if orden is not None:
        orden = {**orden, "numero": 7}
    decision = sync.evaluar_operacion(tipo, orden_id, orden)
    assert (decision[0] if decision else None) == esperado


def test_estado_por_http_y_motivo() -> None:
    assert [sync.estado_por_http(c) for c in (403, 404, 409, 422)] == [
        "conflicto",
        "conflicto",
        "conflicto",
        "error",
    ]
    assert len(sync.recortar_motivo("x" * 900)) == 500
    assert sync.recortar_motivo({"no": "texto"}).startswith("No se pudo")


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode().rstrip("=")


def test_validar_suscripcion_push() -> None:
    assert push.validar_endpoint(" https://fcm.googleapis.com/fcm/send/x ") == (
        "https://fcm.googleapis.com/fcm/send/x"
    )
    for malo in ("no-es-url", "http://push.test/x", "https://", "https://user@evil.test/x"):
        with pytest.raises(push.ErrorDominioNotificaciones):
            push.validar_endpoint(malo)
    p256dh, auth = _b64(b"\x04" + b"A" * 64), _b64(b"B" * 16)
    assert push.validar_claves(p256dh, auth) == (p256dh, auth)
    for p, a in (("", auth), (p256dh, ""), (_b64(b"\x03" + b"A" * 64), auth), (p256dh, _b64(b"x"))):
        with pytest.raises(push.ErrorDominioNotificaciones):
            push.validar_claves(p, a)
    with pytest.raises(push.ErrorDominioNotificaciones):
        push.validar_claves("%%%", auth)


def test_mensaje_push_sin_datos_personales_y_quitar_suscripcion() -> None:
    mensaje = trabajos.mensaje_orden_asignada(15, 42, "modernizacion")
    assert mensaje == {
        "titulo": "Nueva orden asignada",
        "cuerpo": "Orden N.º 42 · Modernización",
        "url": "/?orden=15",
        "etiqueta": "orden-15",
    }
    assert json.loads(push.serializar_mensaje(mensaje)) == mensaje
    with pytest.raises(push.ErrorDominioNotificaciones):
        push.serializar_mensaje({"cuerpo": "x" * 4000})
    assert push.quitar_suscripcion(410, 1) and push.quitar_suscripcion(404, 0)
    assert push.quitar_suscripcion(None, push.MAX_FALLOS)
    assert not push.quitar_suscripcion(500, 3)
