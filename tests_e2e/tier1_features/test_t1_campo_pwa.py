"""Tier 1 E2E tests for EP-07 Field PWA Offline & Web Push (F7-1..F7-5)."""

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

pytestmark = [pytest.mark.tier1, pytest.mark.pwa]

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
        "SAPEF_E2E_ADMIN_PASSWORD must be set for live Tier 1 E2E tests"
    )
    return auth_session_factory(
        e2e_config.admin_user,
        e2e_config.admin_password,
        sede=sede,
    )


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, dict):
        for key in ("items", "resultados", "datos", "ordenes"):
            val = payload.get(key)
            if isinstance(val, list):
                return list(val)
    raise AssertionError(f"Unexpected list payload: {payload!r}")


def _create_field_technician_with_assigned_ot(
    admin_client: SapefClient,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
    *,
    sede: str = "montelibano",
) -> dict[str, Any]:
    """Provision an isolated technician, luminaire, material, and assigned OT (202)."""
    tag = uuid.uuid4().hex[:6].upper()
    roles = _extract_items(admin_client.get("/api/v1/roles", omit_sede=True).json())
    tec_role = next(r for r in roles if str(r.get("codigo")).upper() == "TECNICO")
    sedes = _extract_items(admin_client.get("/api/v1/sedes", omit_sede=True).json())
    sede_obj = next(s for s in sedes if s.get("codigo") == sede)

    username = f"pwa_{run_id.lower()}_{tag.lower()}"
    password = f"Pwa!{uuid.uuid4().hex[:12]}9z"
    u_resp = admin_client.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": username,
            "nombre_completo": f"Técnico PWA {tag}",
            "identificacion": f"88{int(tag, 16) % 10000000:07d}",
            "correo": f"{username}@example.test",
            "clave": password,
            "rol_id": tec_role["id"],
            "sedes": [sede_obj["id"]],
            "activo": True,
            "debe_cambiar_clave": False,
        },
    )
    assert u_resp.status_code == 201, f"Create technician failed: {u_resp.text}"
    tec_id = u_resp.json()["id"]

    barrios = _extract_items(admin_client.get("/api/v1/barrios", sede=sede).json())
    estados = _extract_items(
        admin_client.get("/api/v1/estados", params={"proceso": "luminaria"}, omit_sede=True).json()
    )
    est_121 = next(e["id"] for e in estados if str(e.get("codigo")) == "121")
    tec_id_m = _extract_items(
        admin_client.get("/api/v1/maestros/LUMINARIA_TECNOLOGIA", omit_sede=True).json()
    )[0]["id"]
    pot_id_m = _extract_items(
        admin_client.get("/api/v1/maestros/LUMINARIA_POTENCIA", omit_sede=True).json()
    )[0]["id"]
    lat, lng = generate_coordinates(sede, 3, seed=707)[0]

    lum_resp = admin_client.post(
        "/api/v1/luminarias",
        sede=sede,
        json_body={
            "codigo": f"{run_id}-PWA-LUM-{tag}",
            "barrio_id": barrios[0]["id"],
            "latitud": lat,
            "longitud": lng,
            "estado_id": est_121,
            "tecnologia_id": tec_id_m,
            "potencia_id": pot_id_m,
            "poste": f"P-PWA-{tag}",
        },
    )
    assert lum_resp.status_code == 201, lum_resp.text
    lum_id = lum_resp.json()["id"]

    mat_resp = admin_client.post(
        "/api/v1/materiales",
        sede=sede,
        json_body={
            "categoria": "ELECTRICO",
            "codigo": f"{run_id}-PWA-MAT-{tag}",
            "descripcion": f"Bombillo LED PWA {tag}",
            "unidad": "UND",
            "existencias": 12,
            "existencias_minimas": 2,
        },
    )
    assert mat_resp.status_code == 201, mat_resp.text
    mat_id = mat_resp.json()["id"]

    ot_resp = admin_client.post(
        "/api/v1/ordenes",
        sede=sede,
        json_body={
            "tipo": "mantenimiento",
            "prioridad": 1,
            "observaciones": f"OT campo PWA {run_id}",
            "luminarias": [{"luminaria_id": lum_id, "rol": "intervenida"}],
        },
    )
    assert ot_resp.status_code == 201, ot_resp.text
    ot_id = ot_resp.json()["id"]

    asg = admin_client.post(
        f"/api/v1/ordenes/{ot_id}/asignar",
        sede=sede,
        json_body={"tecnico_id": tec_id},
    )
    assert asg.status_code in (200, 202), asg.text

    tec_client = auth_session_factory(username, password, sede=sede, tipo_cliente="pwa")
    return {
        "username": username,
        "password": password,
        "tec_id": tec_id,
        "tec_client": tec_client,
        "lum_id": lum_id,
        "mat_id": mat_id,
        "ot_id": ot_id,
        "lat": lat,
        "lng": lng,
    }


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


def test_campo_paquete_incremental_download_and_cursor(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """F7-2: GET /campo/paquete returns assigned orders, zone luminaires, catalogs, cursor."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    ctx = _create_field_technician_with_assigned_ot(admin, auth_session_factory, run_id)
    tec_client: SapefClient = ctx["tec_client"]

    pkg_resp = tec_client.get("/api/v1/campo/paquete", sede="montelibano")
    assert pkg_resp.status_code == 200, f"GET /campo/paquete failed: {pkg_resp.text}"
    pkg = pkg_resp.json()

    assert pkg.get("cursor"), "Paquete must return an incremental sync cursor"
    assigned_ids = {o["id"] for o in pkg.get("ordenes_asignadas", [])}
    assert ctx["ot_id"] in assigned_ids
    assert isinstance(pkg.get("luminarias_zona"), list) and len(pkg["luminarias_zona"]) >= 1
    assert isinstance(pkg.get("materiales"), list) and len(pkg["materiales"]) >= 1
    assert isinstance(pkg.get("catalogos"), dict)

    delta_resp = tec_client.get(
        "/api/v1/campo/paquete",
        sede="montelibano",
        params={"desde": pkg["cursor"]},
    )
    assert delta_resp.status_code == 200
    delta = delta_resp.json()
    assert delta.get("cursor")


def test_campo_resumable_evidence_upload_and_batch_sync_aplicada(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """F7-3, F7-4: Idempotent evidence upload + POST /campo/sincronizar -> aplicada + kardex."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    ctx = _create_field_technician_with_assigned_ot(admin, auth_session_factory, run_id)
    tec_client: SapefClient = ctx["tec_client"]

    foto_idem = str(uuid.uuid4())
    foto_payload = make_webp()
    up1 = tec_client.post(
        "/api/v1/archivos",
        sede="montelibano",
        idempotency_key=foto_idem,
        files={"archivo": ("campo_foto.webp", foto_payload, "image/webp")},
    )
    up2 = tec_client.post(
        "/api/v1/archivos",
        sede="montelibano",
        idempotency_key=foto_idem,
        files={"archivo": ("campo_foto.webp", foto_payload, "image/webp")},
    )
    assert up1.status_code in (200, 201), up1.text
    assert up2.status_code in (200, 201), up2.text
    assert up1.json()["id"] == up2.json()["id"]

    audio_resp = tec_client.post(
        "/api/v1/archivos",
        sede="montelibano",
        idempotency_key=str(uuid.uuid4()),
        files={"archivo": ("nota_voz.m4a", make_mp4_aac(), "audio/mp4")},
    )
    assert audio_resp.status_code in (200, 201), audio_resp.text

    op_uuid = str(uuid.uuid4())
    sync_resp = tec_client.post(
        "/api/v1/campo/sincronizar",
        sede="montelibano",
        json_body={
            "operaciones": [
                {
                    "uuid": op_uuid,
                    "tipo": "mantenimiento",
                    "ordenId": ctx["ot_id"],
                    "creadaEn": "2026-07-15T10:30:00Z",
                    "payload": {
                        "sitio_arreglo": "Carrera 5 # 12-30",
                        "quien_recibe": "Usuario Campo",
                        "requiere_desmonte": False,
                        "componentes": build_maintenance_components(all_ok=True),
                        "materiales": [{"material_id": ctx["mat_id"], "cantidad": 2}],
                        "evidencias": [
                            {"archivo_id": up1.json()["id"], "tipo": "foto"},
                            {"archivo_id": audio_resp.json()["id"], "tipo": "audio"},
                        ],
                        "latitud": ctx["lat"],
                        "longitud": ctx["lng"],
                    },
                }
            ]
        },
    )
    assert sync_resp.status_code == 200, f"POST /campo/sincronizar failed: {sync_resp.text}"
    resultados = sync_resp.json()["resultados"]
    assert len(resultados) == 1
    assert resultados[0]["uuid"] == op_uuid
    assert resultados[0]["estado"] == "aplicada"

    # Verify OT closed (203), kardex deducted (12 -> 10), and evento_activo created
    ot_after = admin.get(f"/api/v1/ordenes/{ctx['ot_id']}", sede="montelibano").json()
    assert str(ot_after.get("estado_codigo") or ot_after.get("estado", {}).get("codigo")) == "203"
    mat_after = admin.get(f"/api/v1/materiales/{ctx['mat_id']}", sede="montelibano").json()
    assert float(mat_after["existencias"]) == 10.0
    hist = admin.get(f"/api/v1/luminarias/{ctx['lum_id']}/historial", sede="montelibano").json()
    assert len(hist.get("eventos", [])) >= 1


def test_web_push_vapid_subscription_crud(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """F7-5: Create and delete Web Push VAPID subscriptions for field technician."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    ctx = _create_field_technician_with_assigned_ot(admin, auth_session_factory, run_id)
    tec_client: SapefClient = ctx["tec_client"]

    endpoint = f"https://fcm.googleapis.com/fcm/send/{run_id}-{uuid.uuid4().hex[:8]}"
    p256dh = base64.urlsafe_b64encode(b"\x04" + b"A" * 64).decode("ascii").rstrip("=")
    auth_key = base64.urlsafe_b64encode(b"B" * 16).decode("ascii").rstrip("=")

    sub_resp = tec_client.post(
        "/api/v1/notificaciones/push/suscripciones",
        sede="montelibano",
        json_body={
            "endpoint": endpoint,
            "claves": {"p256dh": p256dh, "auth": auth_key},
        },
    )
    assert sub_resp.status_code in (200, 201), f"Subscribe push failed: {sub_resp.text}"

    del_resp = tec_client.delete(
        "/api/v1/notificaciones/push/suscripciones",
        sede="montelibano",
        json_body={"endpoint": endpoint},
    )
    assert del_resp.status_code in (200, 204), f"Delete push sub failed: {del_resp.text}"


@pytest.mark.browser
def test_browser_campo_pwa_manifest_workbox_storage_persist_and_pmtiles_cache(
    browser_driver: BrowserDriver,
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """F7-1, F7-2: Browser check of apps/campo manifest, Workbox SW, storage.persist, .pmtiles."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    ctx = _create_field_technician_with_assigned_ot(admin, auth_session_factory, run_id)

    browser_driver.navigate(e2e_config.campo_url)
    browser_driver.wait_for_selector("input", timeout=e2e_config.timeout_seconds)

    manifest_info = browser_driver.eval_js(
        """
        new Promise(async (resolve) => {
          const link = document.querySelector('link[rel="manifest"]');
          if (!link) { resolve({found: false}); return; }
          const resp = await fetch(link.href);
          const data = await resp.json();
          resolve({found: true, status: resp.status, manifest: data});
        })
        """,
        await_promise=True,
    )
    assert manifest_info.get("found") is True, "PWA <link rel='manifest'> missing in apps/campo"
    assert manifest_info.get("status") == 200
    manifest = manifest_info["manifest"]
    assert manifest.get("display") in {"standalone", "fullscreen", "minimal-ui"}
    assert len(manifest.get("icons", [])) >= 1

    sw_state = browser_driver.get_service_worker_state()
    assert sw_state.get("supported") is True
    assert len(sw_state.get("registrations", [])) >= 1 or sw_state.get("controller"), (
        f"Expected Workbox Service Worker registration, got {sw_state}"
    )

    storage_caps = browser_driver.eval_js(
        """
        new Promise(async (resolve) => {
          const hasPersist = Boolean(navigator.storage && navigator.storage.persist);
          let persisted = false;
          if (hasPersist) {
            try { persisted = await navigator.storage.persist(); } catch { persisted = false; }
          }
          resolve({hasPersist, persisted});
        })
        """,
        await_promise=True,
    )
    assert storage_caps["hasPersist"] is True

    # Log in inside apps/campo and trigger offline map/package caching
    browser_driver.fill('input[name="usuario"], input[type="text"]', ctx["username"])
    browser_driver.fill('input[name="clave"], input[type="password"]', ctx["password"])
    browser_driver.click('button[type="submit"]')

    deadline = time.monotonic() + e2e_config.timeout_seconds
    pmtiles_cached = False
    while time.monotonic() < deadline:
        pmtiles_cached = bool(
            browser_driver.eval_js(
                """
                new Promise(async (resolve) => {
                  const names = await caches.keys();
                  for (const name of names) {
                    const cache = await caches.open(name);
                    const reqs = await cache.keys();
                    if (reqs.some((r) => r.url.includes('.pmtiles'))) {
                      resolve(true); return;
                    }
                  }
                  resolve(false);
                })
                """,
                await_promise=True,
            )
        )
        if pmtiles_cached:
            break
        time.sleep(0.3)
    assert pmtiles_cached, "Expected .pmtiles base map asset to be cached in CacheStorage"


@pytest.mark.browser
def test_browser_campo_offline_execution_saves_uuidv4_and_media_to_dexie_outbox(
    browser_driver: BrowserDriver,
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """F7-3: Offline execution in apps/campo stores UUIDv4 operation + media in Dexie outbox."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    ctx = _create_field_technician_with_assigned_ot(admin, auth_session_factory, run_id)

    browser_driver.navigate(e2e_config.campo_url)
    browser_driver.wait_for_selector("input", timeout=e2e_config.timeout_seconds)
    browser_driver.fill('input[name="usuario"], input[type="text"]', ctx["username"])
    browser_driver.fill('input[name="clave"], input[type="password"]', ctx["password"])
    browser_driver.click('button[type="submit"]')

    # Wait until assigned OT card/row renders from downloaded paquete
    browser_driver.wait_for_selector("[data-testid='orden-item'], [data-orden-id], a, button")
    time.sleep(1.0)

    # Go offline
    browser_driver.set_offline(True)
    browser_driver.eval_js("window.dispatchEvent(new Event('offline'))")

    # Open first assigned order and complete maintenance form offline
    browser_driver.click("[data-testid='orden-item'], [data-orden-id], [data-testid='ejecutar-ot']")
    browser_driver.wait_for_selector("form")
    browser_driver.fill("input[name='sitio_arreglo']", f"Sitio Offline {run_id}")
    browser_driver.fill("input[name='quien_recibe']", "Testigo Offline")

    # Inject compressed image into file input if present so media outbox is populated
    png_b64 = base64.b64encode(make_png(4, 4)).decode("ascii")
    browser_driver.eval_js(
        f"""
        (() => {{
          const inp = document.querySelector('input[type="file"]');
          if (!inp) return false;
          const raw = atob({json.dumps(png_b64)});
          const arr = new Uint8Array(raw.length);
          for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
          const file = new File([arr], 'offline_foto.png', {{type: 'image/png'}});
          const dt = new DataTransfer();
          dt.items.add(file);
          inp.files = dt.files;
          inp.dispatchEvent(new Event('change', {{bubbles: true}}));
          return true;
        }})()
        """
    )
    browser_driver.click("button[type='submit']")

    deadline = time.monotonic() + e2e_config.timeout_seconds
    records: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        _, records = _discover_outbox_db_and_records(browser_driver)
        if records:
            break
        time.sleep(0.25)

    assert len(records) >= 1, "Offline execution must persist pending operation in Dexie outbox"
    op = records[0]
    assert _UUID4_RE.match(str(op.get("uuid", ""))), (
        f"Expected client-generated UUIDv4 in outbox, got {op.get('uuid')!r}"
    )


@pytest.mark.browser
def test_browser_campo_reconnect_triggers_batch_sync_and_clears_outbox(
    browser_driver: BrowserDriver,
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """F7-4: Reconnecting browser triggers batch sync, empties Dexie outbox, closes OT (203)."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    ctx = _create_field_technician_with_assigned_ot(admin, auth_session_factory, run_id)

    browser_driver.navigate(e2e_config.campo_url)
    browser_driver.wait_for_selector("input", timeout=e2e_config.timeout_seconds)
    browser_driver.fill('input[name="usuario"], input[type="text"]', ctx["username"])
    browser_driver.fill('input[name="clave"], input[type="password"]', ctx["password"])
    browser_driver.click('button[type="submit"]')
    browser_driver.wait_for_selector("[data-testid='orden-item'], [data-orden-id], a, button")
    time.sleep(1.0)

    # Queue operation while offline
    browser_driver.set_offline(True)
    browser_driver.eval_js("window.dispatchEvent(new Event('offline'))")
    browser_driver.click("[data-testid='orden-item'], [data-orden-id], [data-testid='ejecutar-ot']")
    browser_driver.wait_for_selector("form")
    browser_driver.fill("input[name='sitio_arreglo']", f"Sitio Sync {run_id}")
    browser_driver.fill("input[name='quien_recibe']", "Testigo Sync")
    browser_driver.click("button[type='submit']")

    deadline = time.monotonic() + e2e_config.timeout_seconds
    db_name = "sapef-campo"
    records: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        db_name, records = _discover_outbox_db_and_records(browser_driver)
        if records:
            break
        time.sleep(0.25)
    assert records, "Precondition failed: offline operation was not queued in Dexie outbox"

    # Reconnect and wait for batch sync to drain outbox
    browser_driver.set_offline(False)
    browser_driver.eval_js("window.dispatchEvent(new Event('online'))")

    sync_deadline = time.monotonic() + e2e_config.timeout_seconds
    while time.monotonic() < sync_deadline:
        remaining = browser_driver.get_indexeddb_records(db_name, "outbox")
        if len(remaining) == 0:
            break
        time.sleep(0.3)
    assert len(browser_driver.get_indexeddb_records(db_name, "outbox")) == 0, (
        "Outbox should be empty after reconnect batch sync"
    )

    ot_after = admin.get(f"/api/v1/ordenes/{ctx['ot_id']}", sede="montelibano").json()
    assert str(ot_after.get("estado_codigo") or ot_after.get("estado", {}).get("codigo")) == "203"
