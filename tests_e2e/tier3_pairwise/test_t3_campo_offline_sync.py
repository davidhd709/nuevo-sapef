"""Tier 3 pairwise E2E workflows: Field PWA offline capture -> sync -> conflicts -> Web Push."""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fixtures import (
    build_maintenance_components,
    generate_coordinates,
    make_mp4_aac,
    make_png,
    make_webp,
)
from harness.browser import BrowserDriver
from harness.client import SapefClient
from harness.config import E2EConfig
from harness.db import DbHelper

pytestmark = [pytest.mark.tier3, pytest.mark.pwa]

_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _admin_client(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    sede: str = "montelibano",
) -> SapefClient:
    assert e2e_config.admin_password, (
        "SAPEF_E2E_ADMIN_PASSWORD must be configured to run authenticated E2E tests"
    )
    return auth_session_factory(
        e2e_config.admin_user,
        e2e_config.admin_password,
        sede=sede,
    )


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    if isinstance(payload, dict):
        for key in ("items", "resultados", "datos", "ordenes", "materiales"):
            val = payload.get(key)
            if isinstance(val, list):
                return [dict(item) for item in val]
    raise AssertionError(f"Unexpected list payload: {payload!r}")


def _estado_codigo(dto: dict[str, Any]) -> str:
    val = dto.get("estado_codigo")
    if val is not None:
        return str(val)
    est = dto.get("estado")
    if isinstance(est, dict) and est.get("codigo") is not None:
        return str(est["codigo"])
    return str(est or "")


def _provision_tecnico_and_ots(
    admin: SapefClient,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
    *,
    num_ots: int = 1,
    sede: str = "montelibano",
) -> dict[str, Any]:
    tag = uuid.uuid4().hex[:6].upper()
    roles = _extract_items(admin.get("/api/v1/roles", omit_sede=True).json())
    tec_role = next(r for r in roles if str(r.get("codigo")).upper() == "TECNICO")
    sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    sede_obj = next(s for s in sedes if s.get("codigo") == sede)

    username = f"t3pwa_{run_id.lower()}_{tag.lower()}"
    password = f"PwaT3!{uuid.uuid4().hex[:12]}9x"
    u_resp = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": username,
            "nombre_completo": f"Técnico T3 {tag}",
            "identificacion": f"89{int(tag, 16) % 10000000:07d}",
            "correo": f"{username}@example.test",
            "clave": password,
            "rol_id": tec_role["id"],
            "sedes": [sede_obj["id"]],
            "activo": True,
            "debe_cambiar_clave": False,
        },
    )
    assert u_resp.status_code == 201, u_resp.text
    tec_id = u_resp.json()["id"]

    barrios = _extract_items(admin.get("/api/v1/barrios", sede=sede).json())
    estados = _extract_items(
        admin.get("/api/v1/estados", params={"proceso": "luminaria"}, omit_sede=True).json()
    )
    est_121 = next(e["id"] for e in estados if str(e.get("codigo")) == "121")
    tec_m = _extract_items(
        admin.get("/api/v1/maestros/LUMINARIA_TECNOLOGIA", omit_sede=True).json()
    )[0]["id"]
    pot_m = _extract_items(
        admin.get("/api/v1/maestros/LUMINARIA_POTENCIA", omit_sede=True).json()
    )[0]["id"]

    mat = admin.post(
        "/api/v1/materiales",
        sede=sede,
        json_body={
            "categoria": "ELECTRICO",
            "codigo": f"{run_id}-T3PMAT-{tag}",
            "descripcion": f"Material Campo T3 {tag}",
            "unidad": "UND",
            "existencias": 15,
            "existencias_minimas": 2,
        },
    ).json()

    coords = generate_coordinates(sede, num_ots, seed=777)
    lums: list[dict[str, Any]] = []
    ots: list[dict[str, Any]] = []
    for idx in range(num_ots):
        lat, lng = coords[idx]
        lum = admin.post(
            "/api/v1/luminarias",
            sede=sede,
            json_body={
                "codigo": f"{run_id}-T3PL-{idx}-{tag}",
                "barrio_id": barrios[0]["id"],
                "latitud": lat,
                "longitud": lng,
                "estado_id": est_121,
                "tecnologia_id": tec_m,
                "potencia_id": pot_m,
                "poste": f"P-T3P-{idx}-{tag}",
            },
        ).json()
        lums.append(lum)

        ot = admin.post(
            "/api/v1/ordenes",
            sede=sede,
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 1,
                "observaciones": f"OT Campo T3 #{idx} {run_id}",
                "luminarias": [{"luminaria_id": lum["id"], "rol": "intervenida"}],
            },
        ).json()
        asg = admin.post(
            f"/api/v1/ordenes/{ot['id']}/asignar",
            sede=sede,
            json_body={"tecnico_id": tec_id},
        )
        assert asg.status_code in (200, 202), asg.text
        ots.append(ot)

    tec_client = auth_session_factory(username, password, sede=sede, tipo_cliente="pwa")
    return {
        "username": username,
        "password": password,
        "tec_id": tec_id,
        "tec_client": tec_client,
        "mat": mat,
        "lums": lums,
        "ots": ots,
        "coords": coords,
    }


def _grant_geolocation(driver: BrowserDriver, lat: float, lng: float) -> None:
    if driver.backend == "playwright" and driver._pw_context is not None:
        driver._pw_context.grant_permissions(["geolocation"])
        driver._pw_context.set_geolocation({"latitude": lat, "longitude": lng})
        return
    if driver.backend == "cdp":
        driver.cdp(
            "Emulation.setGeolocationOverride",
            {"latitude": lat, "longitude": lng, "accuracy": 10},
        )


def _discover_outbox_db_and_records(driver: BrowserDriver) -> tuple[str, list[dict[str, Any]]]:
    db_names: list[str] = driver.eval_js(
        """
        new Promise((resolve) => {
          if (!indexedDB.databases) { resolve(['sapef-campo', 'campo']); return; }
          indexedDB.databases().then((dbs) => resolve(dbs.map((d) => d.name).filter(Boolean)))
            .catch(() => resolve(['sapef-campo', 'campo']));
        })
        """,
        await_promise=True,
    )
    for db_name in db_names:
        records = driver.get_indexeddb_records(db_name, "outbox")
        if records:
            return db_name, records
    return (db_names[0] if db_names else "sapef-campo"), []


def _capture_offline_media_and_signature(driver: BrowserDriver) -> None:
    png_b64 = base64.b64encode(make_png(4, 4)).decode("ascii")
    mp4_b64 = base64.b64encode(make_mp4_aac()).decode("ascii")
    driver.eval_js(
        f"""
        (() => {{
          // Attach compressed photo & audio to any file inputs present
          const fileInputs = Array.from(document.querySelectorAll('input[type="file"]'));
          for (const inp of fileInputs) {{
            const accept = (inp.getAttribute('accept') || '').toLowerCase();
            const isAudio = accept.includes('audio');
            const raw = atob(isAudio ? {json.dumps(mp4_b64)} : {json.dumps(png_b64)});
            const arr = new Uint8Array(raw.length);
            for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
            const file = new File(
              [arr],
              isAudio ? 'audio_campo.m4a' : 'foto_campo.png',
              {{type: isAudio ? 'audio/mp4' : 'image/png'}}
            );
            const dt = new DataTransfer();
            dt.items.add(file);
            inp.files = dt.files;
            inp.dispatchEvent(new Event('change', {{bubbles: true}}));
          }}
          // Draw stroke on signature <canvas> if present
          const sigCanvas = document.querySelector('canvas');
          if (sigCanvas) {{
            const rect = sigCanvas.getBoundingClientRect();
            const x = rect.left + 10;
            const y = rect.top + 10;
            sigCanvas.dispatchEvent(
              new MouseEvent('mousedown', {{bubbles: true, clientX: x, clientY: y}})
            );
            sigCanvas.dispatchEvent(
              new MouseEvent('mousemove', {{bubbles: true, clientX: x + 20, clientY: y + 10}})
            );
            sigCanvas.dispatchEvent(
              new MouseEvent('mouseup', {{bubbles: true, clientX: x + 20, clientY: y + 10}})
            );
          }}
          return true;
        }})()
        """
    )


@pytest.mark.browser
def test_t3_browser_campo_offline_media_gps_sync_and_idempotent_replay(
    browser_driver: BrowserDriver,
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """Offline PWA execution (Dexie UUIDv4 + media + GPS) -> reconnect sync -> replay ya_aplicada."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    ctx = _provision_tecnico_and_ots(admin, auth_session_factory, run_id, num_ots=1)
    lat, lng = ctx["coords"][0]
    ot_id = ctx["ots"][0]["id"]
    lum_id = ctx["lums"][0]["id"]
    mat_id = ctx["mat"]["id"]
    tec_client: SapefClient = ctx["tec_client"]

    try:
        _grant_geolocation(browser_driver, lat, lng)
        browser_driver.navigate(e2e_config.campo_url)
        browser_driver.wait_for_selector("input", timeout=e2e_config.timeout_seconds)
        browser_driver.fill('input[name="usuario"], input[type="text"]', ctx["username"])
        browser_driver.fill('input[name="clave"], input[type="password"]', ctx["password"])
        browser_driver.click('button[type="submit"]')

        browser_driver.wait_for_selector("[data-testid='orden-item'], [data-orden-id], a, button")
        time.sleep(1.0)

        # Go offline and execute OT with photo/signature/GPS in Dexie outbox
        browser_driver.set_offline(True)
        browser_driver.eval_js("window.dispatchEvent(new Event('offline'))")
        browser_driver.click(
            "[data-testid='orden-item'], [data-orden-id], [data-testid='ejecutar-ot']"
        )
        browser_driver.wait_for_selector("form")
        browser_driver.fill("input[name='sitio_arreglo']", f"Sitio T3 Offline {run_id}")
        browser_driver.fill("input[name='quien_recibe']", "Testigo T3")
        _capture_offline_media_and_signature(browser_driver)
        browser_driver.click("button[type='submit']")

        deadline = time.monotonic() + e2e_config.timeout_seconds
        db_name = "sapef-campo"
        records: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            db_name, records = _discover_outbox_db_and_records(browser_driver)
            if records:
                break
            time.sleep(0.25)

        assert len(records) >= 1, "Offline execution must persist pending operation in Dexie outbox"
        op_record = records[0]
        op_uuid = str(op_record.get("uuid", ""))
        assert _UUID4_RE.match(op_uuid), f"Expected UUIDv4 outbox key, got {op_uuid!r}"

        # Reconnect -> resumable /archivos + /campo/sincronizar drains outbox & closes OT
        browser_driver.set_offline(False)
        browser_driver.eval_js("window.dispatchEvent(new Event('online'))")

        sync_deadline = time.monotonic() + e2e_config.timeout_seconds
        while time.monotonic() < sync_deadline:
            remaining = browser_driver.get_indexeddb_records(db_name, "outbox")
            if len(remaining) == 0:
                break
            time.sleep(0.3)
        assert len(browser_driver.get_indexeddb_records(db_name, "outbox")) == 0

        ot_after = admin.get(f"/api/v1/ordenes/{ot_id}", sede="montelibano").json()
        assert _estado_codigo(ot_after) == "203"

        hist_before = admin.get(f"/api/v1/luminarias/{lum_id}/historial", sede="montelibano").json()
        events_before = len(hist_before.get("eventos", []))
        assert events_before >= 1

        mat_before = float(
            admin.get(f"/api/v1/materiales/{mat_id}", sede="montelibano").json()["existencias"]
        )

        # Replay exact same op_uuid + resumable Idempotency-Key upload -> ya_aplicada, zero dupes
        idem_file = str(uuid.uuid4())
        webp = make_webp()
        up1 = tec_client.post(
            "/api/v1/archivos",
            sede="montelibano",
            idempotency_key=idem_file,
            files={"archivo": ("replay.webp", webp, "image/webp")},
        )
        up2 = tec_client.post(
            "/api/v1/archivos",
            sede="montelibano",
            idempotency_key=idem_file,
            files={"archivo": ("replay.webp", webp, "image/webp")},
        )
        assert up1.status_code in (200, 201) and up2.status_code in (200, 201)
        assert up1.json()["id"] == up2.json()["id"]

        replay = tec_client.post(
            "/api/v1/campo/sincronizar",
            sede="montelibano",
            json_body={
                "operaciones": [
                    {
                        "uuid": op_uuid,
                        "tipo": "mantenimiento",
                        "ordenId": ot_id,
                        "creadaEn": "2026-07-20T12:00:00Z",
                        "payload": {
                            "sitio_arreglo": f"Sitio T3 Offline {run_id}",
                            "quien_recibe": "Testigo T3",
                            "requiere_desmonte": False,
                            "componentes": build_maintenance_components(all_ok=True),
                            "materiales": [],
                            "evidencias": [],
                            "latitud": lat,
                            "longitud": lng,
                        },
                    }
                ]
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["resultados"][0]["estado"] == "ya_aplicada"

        mat_after = float(
            admin.get(f"/api/v1/materiales/{mat_id}", sede="montelibano").json()["existencias"]
        )
        assert mat_after == mat_before
        hist_after = admin.get(f"/api/v1/luminarias/{lum_id}/historial", sede="montelibano").json()
        assert len(hist_after.get("eventos", [])) == events_before
    finally:
        admin.patch(
            f"/api/v1/usuarios/{ctx['tec_id']}",
            omit_sede=True,
            json_body={"activo": False},
        )


@pytest.mark.browser
def test_t3_campo_conflict_cancelled_reassigned_ot_surfaced_in_ui_and_valid_sibling_aplicada(
    browser_driver: BrowserDriver,
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """Tech downloads paquete -> server cancels/reassigns OT -> sync returns conflicto + UI alert
    while valid sibling op in the same batch succeeds (aplicada)."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    ctx_a = _provision_tecnico_and_ots(admin, auth_session_factory, run_id, num_ots=3)
    ctx_b = _provision_tecnico_and_ots(admin, auth_session_factory, f"{run_id}B", num_ots=0)

    ot_valid_id = ctx_a["ots"][0]["id"]
    ot_cancel_id = ctx_a["ots"][1]["id"]
    ot_reasg_id = ctx_a["ots"][2]["id"]
    tec_a_client: SapefClient = ctx_a["tec_client"]
    mat_id = ctx_a["mat"]["id"]
    lat, lng = ctx_a["coords"][0]

    try:
        # 1. Tech A downloads initial /campo/paquete
        pkg_initial = tec_a_client.get("/api/v1/campo/paquete", sede="montelibano")
        assert pkg_initial.status_code == 200, pkg_initial.text
        cursor = pkg_initial.json()["cursor"]
        assert {ot_valid_id, ot_cancel_id, ot_reasg_id}.issubset(
            {o["id"] for o in pkg_initial.json()["ordenes_asignadas"]}
        )

        # 2. Browser loads PWA while online so ot_valid & ot_cancel are cached locally
        _grant_geolocation(browser_driver, lat, lng)
        browser_driver.navigate(e2e_config.campo_url)
        browser_driver.wait_for_selector("input", timeout=e2e_config.timeout_seconds)
        browser_driver.fill('input[name="usuario"], input[type="text"]', ctx_a["username"])
        browser_driver.fill('input[name="clave"], input[type="password"]', ctx_a["password"])
        browser_driver.click('button[type="submit"]')
        browser_driver.wait_for_selector("[data-testid='orden-item'], [data-orden-id], a, button")
        time.sleep(1.0)

        # 3. Tech goes offline and queues ot_cancel in UI
        browser_driver.set_offline(True)
        browser_driver.eval_js("window.dispatchEvent(new Event('offline'))")
        clicked_cancel = browser_driver.eval_js(
            f"""
            (() => {{
              const byId = document.querySelector('[data-orden-id="{ot_cancel_id}"]');
              if (byId) {{ byId.click(); return true; }}
              const items = document.querySelectorAll(
                "[data-testid='orden-item'], [data-orden-id]"
              );
              if (items.length > 1) {{ items[1].click(); return true; }}
              if (items.length > 0) {{ items[0].click(); return true; }}
              return false;
            }})()
            """
        )
        assert clicked_cancel, "Expected assigned order card in apps/campo UI"
        browser_driver.wait_for_selector("form")
        browser_driver.fill("input[name='sitio_arreglo']", f"Conflicto Anulada {run_id}")
        browser_driver.fill("input[name='quien_recibe']", "Testigo Conflicto")
        browser_driver.click("button[type='submit']")

        deadline = time.monotonic() + e2e_config.timeout_seconds
        records: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            _, records = _discover_outbox_db_and_records(browser_driver)
            if records:
                break
            time.sleep(0.25)
        assert records, "Offline op must be saved in Dexie outbox before conflict sync"

        # 4. Coordinator cancels ot_cancel & reassigns ot_reasg on server while tech is offline
        cancel_resp = admin.post(
            f"/api/v1/ordenes/{ot_cancel_id}/anular",
            sede="montelibano",
            json_body={"motivo": f"Anulada en servidor {run_id}"},
        )
        assert cancel_resp.status_code == 200, cancel_resp.text

        reasg_resp = admin.post(
            f"/api/v1/ordenes/{ot_reasg_id}/asignar",
            sede="montelibano",
            json_body={"tecnico_id": ctx_b["tec_id"]},
        )
        assert reasg_resp.status_code in (200, 202), reasg_resp.text

        # Delta paquete flags cancelled/reassigned orders
        delta_pkg = tec_a_client.get(
            "/api/v1/campo/paquete",
            sede="montelibano",
            params={"desde": cursor},
        ).json()
        removed_ids = {
            x.get("id", x) if isinstance(x, dict) else x
            for x in delta_pkg.get("ordenes_anuladas_o_reasignadas", [])
        }
        assert ot_cancel_id in removed_ids or ot_reasg_id in removed_ids

        # 5. Browser reconnects -> sync runs -> conflict surfaced in UI
        browser_driver.set_offline(False)
        browser_driver.eval_js("window.dispatchEvent(new Event('online'))")

        conflict_deadline = time.monotonic() + e2e_config.timeout_seconds
        surfaced = False
        while time.monotonic() < conflict_deadline:
            body_txt = str(browser_driver.eval_js("document.body.innerText") or "").lower()
            has_sel = bool(
                browser_driver.eval_js(
                    "Boolean(document.querySelector('[data-testid*=\"conflicto\"], [role=\"alert\"]'))"
                )
            )
            if "conflicto" in body_txt or has_sel:
                surfaced = True
                break
            time.sleep(0.3)
        assert surfaced, "Expected conflict notification/screen surfaced in apps/campo UI"

        # 6. Mixed batch via /campo/sincronizar: valid sibling op + reassigned op -> aplicada & conflicto
        u_valid = str(uuid.uuid4())
        u_reasg = str(uuid.uuid4())
        batch = tec_a_client.post(
            "/api/v1/campo/sincronizar",
            sede="montelibano",
            json_body={
                "operaciones": [
                    {
                        "uuid": u_valid,
                        "tipo": "mantenimiento",
                        "ordenId": ot_valid_id,
                        "creadaEn": "2026-07-21T09:00:00Z",
                        "payload": {
                            "sitio_arreglo": "Sibling Válido",
                            "quien_recibe": "Usuario Sibling",
                            "requiere_desmonte": False,
                            "componentes": build_maintenance_components(all_ok=True),
                            "materiales": [{"material_id": mat_id, "cantidad": 3}],
                            "evidencias": [],
                            "latitud": lat,
                            "longitud": lng,
                        },
                    },
                    {
                        "uuid": u_reasg,
                        "tipo": "mantenimiento",
                        "ordenId": ot_reasg_id,
                        "creadaEn": "2026-07-21T09:05:00Z",
                        "payload": {
                            "sitio_arreglo": "OT Reasignada",
                            "quien_recibe": "Usuario",
                            "requiere_desmonte": False,
                            "componentes": build_maintenance_components(all_ok=True),
                            "materiales": [],
                            "evidencias": [],
                            "latitud": lat,
                            "longitud": lng,
                        },
                    },
                ]
            },
        )
        assert batch.status_code == 200, batch.text
        by_uuid = {r["uuid"]: r for r in batch.json()["resultados"]}
        assert by_uuid[u_valid]["estado"] == "aplicada"
        assert by_uuid[u_reasg]["estado"] == "conflicto"

        assert (
            _estado_codigo(admin.get(f"/api/v1/ordenes/{ot_valid_id}", sede="montelibano").json())
            == "203"
        )
        mat_after = admin.get(f"/api/v1/materiales/{mat_id}", sede="montelibano").json()
        assert float(mat_after["existencias"]) == 12.0
    finally:
        for uid in (ctx_a["tec_id"], ctx_b["tec_id"]):
            admin.patch(f"/api/v1/usuarios/{uid}", omit_sede=True, json_body={"activo": False})


def test_t3_web_push_vapid_registration_and_ot_assign_enqueues_ids_only_push_job(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """Web Push VAPID registration + OT assign enqueues IDs-only Procrastinate push job (no PII)."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    ctx = _provision_tecnico_and_ots(admin, auth_session_factory, run_id, num_ots=0)
    tec_client: SapefClient = ctx["tec_client"]
    tec_id = ctx["tec_id"]

    try:
        endpoint = f"https://fcm.googleapis.com/fcm/send/t3-{run_id}-{uuid.uuid4().hex[:8]}"
        p256dh = base64.urlsafe_b64encode(b"\x04" + b"P" * 64).decode("ascii").rstrip("=")
        auth_key = base64.urlsafe_b64encode(b"A" * 16).decode("ascii").rstrip("=")

        sub_resp = tec_client.post(
            "/api/v1/notificaciones/push/suscripciones",
            sede="montelibano",
            json_body={
                "endpoint": endpoint,
                "claves": {"p256dh": p256dh, "auth": auth_key},
            },
        )
        assert sub_resp.status_code in (200, 201), sub_resp.text

        barrios = _extract_items(admin.get("/api/v1/barrios", sede="montelibano").json())
        est_121 = next(
            e["id"]
            for e in _extract_items(
                admin.get(
                    "/api/v1/estados", params={"proceso": "luminaria"}, omit_sede=True
                ).json()
            )
            if str(e.get("codigo")) == "121"
        )
        tec_m = _extract_items(
            admin.get("/api/v1/maestros/LUMINARIA_TECNOLOGIA", omit_sede=True).json()
        )[0]["id"]
        pot_m = _extract_items(
            admin.get("/api/v1/maestros/LUMINARIA_POTENCIA", omit_sede=True).json()
        )[0]["id"]
        lat, lng = generate_coordinates("montelibano", 1, seed=888)[0]

        lum = admin.post(
            "/api/v1/luminarias",
            sede="montelibano",
            json_body={
                "codigo": f"{run_id}-PSHLUM-{uuid.uuid4().hex[:5].upper()}",
                "barrio_id": barrios[0]["id"],
                "latitud": lat,
                "longitud": lng,
                "estado_id": est_121,
                "tecnologia_id": tec_m,
                "potencia_id": pot_m,
            },
        ).json()

        ot_id = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 1,
                "luminarias": [{"luminaria_id": lum["id"], "rol": "intervenida"}],
            },
        ).json()["id"]

        max_job_before = int(
            db_helper.scalar("SELECT COALESCE(MAX(id), 0) FROM procrastinate_jobs") or 0
        )
        asg_resp = admin.post(
            f"/api/v1/ordenes/{ot_id}/asignar",
            sede="montelibano",
            json_body={"tecnico_id": tec_id},
        )
        assert asg_resp.status_code in (200, 202), asg_resp.text
        assert _estado_codigo(asg_resp.json()) == "202"

        push_job = db_helper.fetch_one(
            """
            SELECT id, task_name, args
            FROM procrastinate_jobs
            WHERE id > %s
              AND task_name ILIKE '%%push%%'
              AND args::text LIKE %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (max_job_before, f"%{ot_id}%"),
        )
        assert push_job is not None, f"Expected Procrastinate push job for OT {ot_id}"
        args = db_helper.get_procrastinate_job_args(int(push_job["id"]))
        assert args
        for k, v in args.items():
            assert isinstance(v, (int, str, bool)) or v is None, (
                f"Procrastinate push arg {k!r} must be primitive ID, got {type(v).__name__}"
            )
        serialized = str(args).lower()
        for forbidden in ("endpoint", "p256dh", "vapid", "correo", "hash_clave", endpoint.lower()):
            assert forbidden not in serialized, (
                f"Push job leaked sensitive/PII data {forbidden!r}: {args}"
            )

        del_resp = tec_client.delete(
            "/api/v1/notificaciones/push/suscripciones",
            sede="montelibano",
            json_body={"endpoint": endpoint},
        )
        assert del_resp.status_code in (200, 204), del_resp.text
    finally:
        admin.patch(f"/api/v1/usuarios/{tec_id}", omit_sede=True, json_body={"activo": False})
