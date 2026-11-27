"""Integración de la Fase 3 contra PostgreSQL: paquete de campo, lote idempotente con conflictos
y suscripciones Web Push."""

import base64
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.main import crear_app
from app.modulos.trabajos import servicio as trabajos_servicio
from tests.conftest import iniciar_sesion_cliente
from tests.integration import test_fase2_api as f2

MT, AL, PNG, COMPONENTES = f2.MT, f2.AL, f2.PNG, f2.COMPONENTES
admin = f2.admin  # fixtures de la Fase 2 (sesión de administrador y catálogos)
cat = f2.cat


@pytest.fixture
def tecnico(db_configurado: Session, admin: TestClient) -> Iterator[tuple[int, TestClient]]:
    tecnico_id = f2._tecnico(db_configurado, "tec_campo")
    yield tecnico_id, _otro_cliente("tec_campo")


def _otro_cliente(usuario: str) -> TestClient:
    """Segundo navegador. Sin `with`: la cola ya la abrió el cliente del administrador y dos
    ciclos de vida anidados cerrarían la misma conexión de Procrastinate."""
    c = TestClient(crear_app())
    iniciar_sesion_cliente(c, usuario, tipo_cliente="pwa")
    return c


def _orden_asignada(c: TestClient, cat: dict, codigo: str, tecnico_id: int, **extra: Any) -> dict:
    lum = f2._luminaria(c, cat, codigo)
    orden = f2._orden(c, "mantenimiento", [(lum["id"], "intervenida")], **extra)
    r = c.post(
        f"/api/v1/ordenes/{orden['id']}/asignar", headers=MT, json={"tecnico_id": tecnico_id}
    )
    assert r.status_code == 200, r.text
    return {**orden, "luminaria": lum}


def _op(orden_id: int, **payload: Any) -> dict[str, Any]:
    return {
        "uuid": str(uuid.uuid4()),
        "tipo": "mantenimiento",
        "ordenId": orden_id,
        "creadaEn": "2026-07-15T10:30:00Z",
        "payload": {
            "sitio_arreglo": "Carrera 5",
            "quien_recibe": "Vecino",
            "componentes": dict.fromkeys(COMPONENTES, True),
            "materiales": [],
            "evidencias": [],
            **payload,
        },
    }


def _sync(c: TestClient, *ops: dict[str, Any]) -> dict[str, dict[str, Any]]:
    r = c.post("/api/v1/campo/sincronizar", headers=MT, json={"operaciones": list(ops)})
    assert r.status_code == 200, r.text
    return {x["uuid"]: x for x in r.json()["resultados"]}


# --- Paquete ------------------------------------------------------------------------------------


def test_paquete_completo_y_delta_con_ordenes_retiradas(
    admin: TestClient, cat: dict, tecnico: tuple[int, TestClient], db_configurado: Session
) -> None:
    tecnico_id, tec = tecnico
    otro_id = f2._tecnico(db_configurado, "tec_otro")
    o1 = _orden_asignada(admin, cat, "C-1", tecnico_id)
    o2 = _orden_asignada(admin, cat, "C-2", tecnico_id)
    o3 = _orden_asignada(admin, cat, "C-3", tecnico_id)
    ajena = _orden_asignada(admin, cat, "C-4", otro_id)
    f2._material(admin, "CAMPO-M", 5)
    f2._luminaria(admin, cat, "BOD-1", "124")

    r = tec.get("/api/v1/campo/paquete", headers=MT)
    assert r.status_code == 200, r.text
    pkg = r.json()
    assert pkg["completo"] is True and pkg["cursor"]
    assert [o["id"] for o in pkg["ordenes_asignadas"]] == [o1["id"], o2["id"], o3["id"]]
    primera = pkg["ordenes_asignadas"][0]
    assert primera["luminarias"][0]["codigo"] == "C-1"
    assert primera["luminarias"][0]["latitud"] == pytest.approx(7.98)
    codigos = {lum["codigo"] for lum in pkg["luminarias_zona"]}
    assert {"C-1", "C-4", "BOD-1"} <= codigos
    assert [lum["codigo"] for lum in pkg["luminarias_bodega"]] == ["BOD-1"]
    assert [m["codigo"] for m in pkg["materiales"]] == ["CAMPO-M"]
    assert len(pkg["catalogos"]["componentes"]) == 12
    assert pkg["catalogos"]["barrios"] and pkg["catalogos"]["tipos_modernizacion"]
    assert {d["codigo"] for d in pkg["catalogos"]["destinos_desmontada"]} >= {"124", "123"}
    assert pkg["mapa_base"]["url"] == "/api/v1/mapa/base/montelibano.pmtiles?v=20261125-ampliado"
    assert pkg["ordenes_anuladas_o_reasignadas"] == []
    assert ajena["id"] not in {o["id"] for o in pkg["ordenes_asignadas"]}

    # Mientras el técnico está sin señal: una se anula y otra se reasigna.
    assert (
        admin.post(
            f"/api/v1/ordenes/{o2['id']}/anular", headers=MT, json={"motivo": "Duplicada"}
        ).status_code
        == 200
    )
    assert (
        admin.post(
            f"/api/v1/ordenes/{o3['id']}/asignar", headers=MT, json={"tecnico_id": otro_id}
        ).status_code
        == 200
    )
    delta = tec.get("/api/v1/campo/paquete", headers=MT, params={"desde": pkg["cursor"]}).json()
    assert delta["completo"] is False
    assert [o["id"] for o in delta["ordenes_asignadas"]] == [o1["id"]]
    retiradas = {r["id"]: r["motivo"] for r in delta["ordenes_anuladas_o_reasignadas"]}
    assert retiradas == {o2["id"]: "anulada", o3["id"]: "reasignada"}
    # El delta trae solo luminarias que cambiaron (con margen), no toda la sede.
    assert len(delta["luminarias_zona"]) <= len(pkg["luminarias_zona"])

    assert (
        tec.get("/api/v1/campo/paquete", headers=MT, params={"desde": "basura"}).status_code == 422
    )


def test_campo_exige_permiso_y_sede(admin: TestClient, db_configurado: Session) -> None:
    f2.crear_usuario_db(
        db_configurado,
        nombre_usuario="lector_campo",
        correo="lector_campo@sapef.test",
        rol_codigo="LECTOR",
        sede_codigos=["montelibano"],
    )
    c = _otro_cliente("lector_campo")
    assert c.get("/api/v1/campo/paquete", headers=MT).status_code == 403
    r = c.post("/api/v1/campo/sincronizar", headers=MT, json={"operaciones": []})
    assert r.status_code == 403
    assert c.get("/api/v1/campo/paquete", headers=AL).status_code in (403, 404)


# --- Lote de subida -----------------------------------------------------------------------------


def test_lote_aplica_es_idempotente_y_conflictos_no_afectan_al_resto(
    admin: TestClient, cat: dict, tecnico: tuple[int, TestClient], db_configurado: Session
) -> None:
    tecnico_id, tec = tecnico
    otro_id = f2._tecnico(db_configurado, "tec_otro2")
    ciudadano = f2._ciudadano(admin, "1067000099")
    lum_pqrs = f2._luminaria(admin, cat, "P-1")
    pqrs = f2._pqrs(admin, cat, [lum_pqrs["id"]], ciudadano["id"], notificar_cliente=True)
    valida = f2._orden(
        admin, "mantenimiento", [(lum_pqrs["id"], "intervenida")], pqrs_id=pqrs["id"]
    )
    admin.post(
        f"/api/v1/ordenes/{valida['id']}/asignar", headers=MT, json={"tecnico_id": tecnico_id}
    )
    anulada = _orden_asignada(admin, cat, "A-1", tecnico_id)
    reasignada = _orden_asignada(admin, cat, "R-1", tecnico_id)
    material = f2._material(admin, "SYNC-M", 10)
    foto = tec.post(
        "/api/v1/archivos",
        headers={**MT, "Idempotency-Key": str(uuid.uuid4())},
        files={"archivo": ("f.png", PNG, "image/png")},
    )
    assert foto.status_code == 201, foto.text

    admin.post(f"/api/v1/ordenes/{anulada['id']}/anular", headers=MT, json={"motivo": "No va"})
    admin.post(
        f"/api/v1/ordenes/{reasignada['id']}/asignar", headers=MT, json={"tecnico_id": otro_id}
    )

    op_valida = _op(
        valida["id"],
        materiales=[{"material_id": material["id"], "cantidad": 2}],
        evidencias=[{"archivo_id": foto.json()["id"], "tipo": "foto"}],
        latitud=7.981,
        longitud=-75.421,
        observacion_tecnica="Fotocelda cambiada",
    )
    op_anulada, op_reasignada = _op(anulada["id"]), _op(reasignada["id"])
    op_invalida = _op(valida["id"])
    op_invalida["payload"]["componentes"] = {"fotocelda": True}
    op_tipo = {**_op(anulada["id"]), "tipo": "poda"}

    res = _sync(tec, op_valida, op_anulada, op_reasignada, op_tipo, op_valida)
    assert len(res) == 4  # la repetida dentro del lote aparece una vez
    assert res[op_valida["uuid"]]["estado"] == "aplicada"
    assert res[op_anulada["uuid"]]["estado"] == "conflicto"
    assert "anulada" in res[op_anulada["uuid"]]["motivo"]
    assert res[op_reasignada["uuid"]]["estado"] == "conflicto"
    assert "reasignada" in res[op_reasignada["uuid"]]["motivo"]
    assert res[op_tipo["uuid"]]["estado"] == "error"

    orden = admin.get(f"/api/v1/ordenes/{valida['id']}", headers=MT).json()
    assert orden["estado_codigo"] == "203"
    assert orden["fecha_ejecucion"].startswith("2026-07-15T10:30")  # la hora del teléfono
    assert [e["tipo"] for e in orden["evidencias"]] == ["foto"]
    assert admin.get(f"/api/v1/pqrs/{pqrs['id']}", headers=MT).json()["estado_codigo"] == "303"
    assert f2._jobs(db_configurado, "atencion.notificar_pqrs")[-1] == {
        "pqrs_id": pqrs["id"],
        "evento": "atencion",
    }

    # Reintento: ya_aplicada, sin doble descuento ni eventos repetidos.
    eventos = len(
        admin.get(f"/api/v1/luminarias/{lum_pqrs['id']}/historial", headers=MT).json()["eventos"]
    )
    res2 = _sync(tec, op_valida)
    assert res2[op_valida["uuid"]]["estado"] == "ya_aplicada"
    assert (
        admin.get(f"/api/v1/materiales/{material['id']}", headers=MT).json()["existencias"]
        == "8.000"
    )
    historial = admin.get(f"/api/v1/luminarias/{lum_pqrs['id']}/historial", headers=MT).json()
    assert len(historial["eventos"]) == eventos

    # Una operación con datos inválidos sobre una orden ya cerrada por otra: conflicto.
    assert _sync(tec, op_invalida)[op_invalida["uuid"]]["estado"] == "conflicto"

    # La oficina ve los conflictos.
    conflictos = admin.get(
        "/api/v1/campo/operaciones", headers=MT, params={"estado": "conflicto"}
    ).json()
    assert {c["uuid"] for c in conflictos["items"]} >= {op_anulada["uuid"], op_reasignada["uuid"]}
    assert conflictos["items"][0]["usuario_nombre"] == "Usuario tec_campo"
    assert {c["orden_id"] for c in conflictos["items"]} >= {anulada["id"], reasignada["id"]}
    assert tec.get("/api/v1/campo/operaciones", headers=MT).status_code == 403


def test_lote_error_de_validacion_y_uuid_de_otro_usuario(
    admin: TestClient, cat: dict, tecnico: tuple[int, TestClient], db_configurado: Session
) -> None:
    tecnico_id, tec = tecnico
    orden = _orden_asignada(admin, cat, "V-1", tecnico_id)
    op = _op(orden["id"])
    op["payload"]["componentes"] = {"bombillo": True}
    res = _sync(tec, op)
    assert res[op["uuid"]]["estado"] == "error"
    assert "Checklist" in res[op["uuid"]]["motivo"]
    # Corregida, la misma operación (mismo uuid) se aplica.
    op["payload"]["componentes"] = dict.fromkeys(COMPONENTES, True)
    assert _sync(tec, op)[op["uuid"]]["estado"] == "aplicada"
    intentos = db_configurado.execute(
        text("SELECT intentos, estado FROM operacion_campo WHERE uuid = :u"), {"u": op["uuid"]}
    ).one()
    assert tuple(intentos) == (2, "aplicada")

    # El mismo uuid enviado por otra persona no se aplica.
    otro_id = f2._tecnico(db_configurado, "tec_ajeno")
    orden2 = _orden_asignada(admin, cat, "V-2", otro_id)
    otro = _otro_cliente("tec_ajeno")
    robada = {**_op(orden2["id"]), "uuid": op["uuid"]}
    assert _sync(otro, robada)[op["uuid"]]["estado"] == "error"
    assert admin.get(f"/api/v1/ordenes/{orden2['id']}", headers=MT).json()["estado_codigo"] == "202"

    # Más de 50 operaciones: 422.
    muchas = [_op(orden["id"]) for _ in range(51)]
    r = tec.post("/api/v1/campo/sincronizar", headers=MT, json={"operaciones": muchas})
    assert r.status_code == 422


def test_modernizacion_desde_campo(
    admin: TestClient, cat: dict, tecnico: tuple[int, TestClient]
) -> None:
    tecnico_id, tec = tecnico
    vieja = f2._luminaria(admin, cat, "MV-1")
    nueva = f2._luminaria(admin, cat, "MN-1", "124")
    orden = f2._orden(
        admin, "modernizacion", [(nueva["id"], "instalada"), (vieja["id"], "desmontada")]
    )
    admin.post(
        f"/api/v1/ordenes/{orden['id']}/asignar", headers=MT, json={"tecnico_id": tecnico_id}
    )
    op = {
        "uuid": str(uuid.uuid4()),
        "tipo": "modernizacion",
        "ordenId": orden["id"],
        "creadaEn": "2026-07-22T10:30:00Z",
        "payload": {
            "tipo_modernizacion_id": cat["tipo_mod"],
            "barrio_id": cat["barrio"],
            "poste": "P-MOD",
            "longitud_brazo": 1.5,
            "destino_desmontada": "124",
            "latitud": 7.982,
            "longitud": -75.422,
        },
    }
    assert _sync(tec, op)[op["uuid"]]["estado"] == "aplicada"
    assert f2._estado(admin, f"/api/v1/luminarias/{nueva['id']}") == "121"
    assert f2._estado(admin, f"/api/v1/luminarias/{vieja['id']}") == "124"


# --- Web Push -----------------------------------------------------------------------------------


def _claves() -> dict[str, str]:
    p256dh = base64.urlsafe_b64encode(b"\x04" + b"A" * 64).decode().rstrip("=")
    auth = base64.urlsafe_b64encode(b"B" * 16).decode().rstrip("=")
    return {"p256dh": p256dh, "auth": auth}


def test_suscripciones_push(tecnico: tuple[int, TestClient], db_configurado: Session) -> None:
    tecnico_id, tec = tecnico
    endpoint = "https://fcm.googleapis.com/fcm/send/abc123"
    r = tec.post(
        "/api/v1/notificaciones/push/suscripciones",
        json={"endpoint": endpoint, "keys": _claves(), "expirationTime": None},
    )
    assert r.status_code == 201, r.text
    # Repetida (formato `claves`): se actualiza.
    r = tec.post(
        "/api/v1/notificaciones/push/suscripciones",
        json={"endpoint": endpoint, "claves": _claves()},
    )
    assert r.status_code == 200, r.text
    malas = [
        {"endpoint": "no-es-url", "claves": _claves()},
        {"endpoint": "http://inseguro.test/x", "claves": _claves()},
        {"endpoint": endpoint, "claves": {"p256dh": "", "auth": ""}},
        {"endpoint": endpoint, "claves": {"p256dh": _claves()["auth"], "auth": "x"}},
    ]
    for cuerpo in malas:
        assert tec.post("/api/v1/notificaciones/push/suscripciones", json=cuerpo).status_code == 422
    clave = tec.get("/api/v1/notificaciones/push/clave-publica").json()
    assert set(clave) == {"habilitado", "clave_publica"}

    filas = db_configurado.execute(
        text("SELECT usuario_id FROM suscripcion_push WHERE endpoint = :e"), {"e": endpoint}
    ).scalars()
    assert list(filas) == [tecnico_id]
    borrar = tec.request(
        "DELETE", "/api/v1/notificaciones/push/suscripciones", json={"endpoint": endpoint}
    )
    assert borrar.status_code == 204
    otra = tec.request(
        "DELETE", "/api/v1/notificaciones/push/suscripciones", json={"endpoint": endpoint}
    )
    assert otra.status_code == 404


def test_push_de_asignacion_envia_con_vapid(
    admin: TestClient,
    cat: dict,
    tecnico: tuple[int, TestClient],
    db_configurado: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import obtener_configuracion
    from app.modulos.notificaciones import servicio as notificaciones_servicio

    tecnico_id, tec = tecnico
    privada, publica = notificaciones_servicio.generar_claves_vapid()
    monkeypatch.setenv("SAPEF_VAPID_CLAVE_PRIVADA", privada)
    obtener_configuracion.cache_clear()
    assert tec.get("/api/v1/notificaciones/push/clave-publica").json() == {
        "habilitado": True,
        "clave_publica": publica,
    }
    for sufijo in ("viva", "vencida"):
        tec.post(
            "/api/v1/notificaciones/push/suscripciones",
            json={"endpoint": f"https://push.example.org/{sufijo}", "keys": _claves()},
        )

    enviados: list[dict[str, Any]] = []

    class _Respuesta:
        status_code = 410

    def _webpush(**kwargs: Any) -> None:
        enviados.append(kwargs)
        if kwargs["subscription_info"]["endpoint"].endswith("vencida"):
            raise notificaciones_servicio.WebPushException("Gone", response=_Respuesta())

    monkeypatch.setattr(notificaciones_servicio, "webpush", _webpush)
    orden = _orden_asignada(admin, cat, "PU-1", tecnico_id)
    assert trabajos_servicio.procesar_push_asignacion(db_configurado, orden["id"]) == 1
    assert len(enviados) == 2
    assert '"Nueva orden asignada"' in enviados[0]["data"]
    assert "PU-1" not in enviados[0]["data"]  # sin direcciones ni códigos en la pantalla bloqueada
    restantes = db_configurado.execute(text("SELECT endpoint FROM suscripcion_push")).scalars()
    assert list(restantes) == ["https://push.example.org/viva"]
    obtener_configuracion.cache_clear()
