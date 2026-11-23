"""Tier 4 Scenario 4: Offline Field Technician Workday in PWA (apps/campo)."""

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
    MAINTENANCE_12_COMPONENTS,
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

pytestmark = [pytest.mark.tier4, pytest.mark.pwa, pytest.mark.browser]

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
        "SAPEF_E2E_ADMIN_PASSWORD must be configured to run Tier 4 E2E scenarios"
    )
    return auth_session_factory(e2e_config.admin_user, e2e_config.admin_password, sede=sede)


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    if isinstance(payload, dict):
        for key in ("items", "resultados", "datos", "ordenes", "materiales"):
            val = payload.get(key)
            if isinstance(val, list):
                return [dict(item) for item in val]
    raise AssertionError(f"Unexpected list/paginated payload: {payload!r}")


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


def test_campo_pwa_full_offline_workday_sync_conflict_idempotency_and_push(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    db_helper: DbHelper,
    browser_driver: BrowserDriver,
    run_id: str,
) -> None:
    """Scenario 4: PWA paquete+pmtiles+VAPID+SW -> offline outbox -> SW lock -> sync/conflict/retry."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tag = uuid.uuid4().hex[:6].upper()

    roles = _extract_items(admin.get("/api/v1/roles", omit_sede=True).json())
    tec_role = next(r for r in roles if str(r["codigo"]).upper() == "TECNICO")
    sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    mtl_sede_id = next(s["id"] for s in sedes if s["codigo"] == "montelibano")

    tec_username = f"s4_tec_{run_id.lower()}_{tag.lower()}"
    tec_secret = f"S4Pwa!{uuid.uuid4().hex[:10]}9z"
    tec_resp = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": tec_username,
            "nombre_completo": f"Técnico Jornada S4 {tag}",
            "identificacion": f"84{int(tag, 16) % 10000000:07d}",
            "correo": f"{tec_username}@example.test",
            "clave": tec_secret,
            "rol_id": tec_role["id"],
            "sedes": [mtl_sede_id],
            "activo": True,
            "debe_cambiar_clave": False,
        },
    )
    assert tec_resp.status_code == 201, tec_resp.text
    tec_id = tec_resp.json()["id"]

    try:
        # ------------------------------------------------------------------
        # Phase 1: Provision luminaires, PQRS, materials, and 3 assigned OTs
        # ------------------------------------------------------------------
        barrio = _extract_items(admin.get("/api/v1/barrios", sede="montelibano").json())[0]
        estados_lum = _extract_items(
            admin.get("/api/v1/estados", omit_sede=True, params={"proceso": "luminaria"}).json()
        )
        est_121 = next(e["id"] for e in estados_lum if str(e["codigo"]) == "121")
        est_124 = next(e["id"] for e in estados_lum if str(e["codigo"]) == "124")
        tech_led = _extract_items(
            admin.get("/api/v1/maestros/LUMINARIA_TECNOLOGIA", omit_sede=True).json()
        )[0]["id"]
        pot_id = _extract_items(
            admin.get("/api/v1/maestros/LUMINARIA_POTENCIA", omit_sede=True).json()
        )[0]["id"]
        tipo_mod_id = _extract_items(
            admin.get("/api/v1/maestros/TIPO_MODERNIZACION", omit_sede=True).json()
        )[0]["id"]
        canal_wa = next(
            c
            for c in _extract_items(admin.get("/api/v1/maestros/CANAL_PQRS", omit_sede=True).json())
            if c["codigo"] == "WHATSAPP"
        )

        coords = generate_coordinates("montelibano", 4, seed=444)

        def _mk_lum(suffix: str, estado_id: int, idx: int) -> dict[str, Any]:
            r = admin.post(
                "/api/v1/luminarias",
                sede="montelibano",
                json_body={
                    "codigo": f"{run_id}-S4-{suffix}-{tag}",
                    "barrio_id": barrio["id"],
                    "latitud": coords[idx][0],
                    "longitud": coords[idx][1],
                    "estado_id": estado_id,
                    "tecnologia_id": tech_led,
                    "potencia_id": pot_id,
                    "poste": f"P-S4-{suffix}-{tag}",
                },
            )
            assert r.status_code == 201, r.text
            return dict(r.json())

        lum_browser = _mk_lum("BRW", est_121, 0)
        lum_pqrs = _mk_lum("PQR", est_121, 1)
        lum_mod_in = _mk_lum("MIN", est_124, 2)
        lum_cancel = _mk_lum("CAN", est_121, 3)

        mat_resp = admin.post(
            "/api/v1/materiales",
            sede="montelibano",
            json_body={
                "categoria": "ELECTRICO",
                "codigo": f"{run_id}-S4MAT-{tag}",
                "descripcion": f"Conector S4 {tag}",
                "unidad": "UND",
                "existencias": 20,
                "existencias_minimas": 4,
            },
        )
        assert mat_resp.status_code == 201, mat_resp.text
        mat_id = mat_resp.json()["id"]

        cit_resp = admin.post(
            "/api/v1/ciudadanos",
            sede="montelibano",
            json_body={
                "identificacion": f"CC-S4-{tag}",
                "nombre_completo": f"Solicitante Campo {tag}",
                "telefono": "3008889900",
                "correo": f"s4.{tag.lower()}@example.test",
            },
        )
        assert cit_resp.status_code == 201, cit_resp.text
        pqrs_resp = admin.post(
            "/api/v1/pqrs",
            sede="montelibano",
            json_body={
                "canal_id": canal_wa["id"],
                "ciudadano_id": cit_resp.json()["id"],
                "prioridad": 1,
                "observacion_solicitante": f"PQRS campo offline {tag}",
                "notificar_cliente": False,
                "luminarias": [{"luminaria_id": lum_pqrs["id"]}],
            },
        )
        assert pqrs_resp.status_code == 201, pqrs_resp.text
        pqrs_id = pqrs_resp.json()["id"]

        def _mk_assigned_ot(body: dict[str, Any]) -> int:
            r = admin.post("/api/v1/ordenes", sede="montelibano", json_body=body)
            assert r.status_code == 201, r.text
            oid = int(r.json()["id"])
            asg = admin.post(
                f"/api/v1/ordenes/{oid}/asignar",
                sede="montelibano",
                json_body={"tecnico_id": tec_id},
            )
            assert asg.status_code in (200, 202), asg.text
            return oid

        ot_browser_id = _mk_assigned_ot(
            {
                "tipo": "mantenimiento",
                "prioridad": 1,
                "observaciones": f"OT Browser Offline {tag}",
                "luminarias": [{"luminaria_id": lum_browser["id"], "rol": "intervenida"}],
            }
        )
        ot_pqrs_id = _mk_assigned_ot(
            {
                "tipo": "mantenimiento",
                "prioridad": 1,
                "pqrs_id": pqrs_id,
                "observaciones": f"OT PQRS Offline {tag}",
                "luminarias": [{"luminaria_id": lum_pqrs["id"], "rol": "intervenida"}],
            }
        )
        ot_mod_id = _mk_assigned_ot(
            {
                "tipo": "modernizacion",
                "prioridad": 1,
                "observaciones": f"OT Mod Offline {tag}",
                "luminarias": [
                    {"luminaria_id": lum_mod_in["id"], "rol": "instalada"},
                    {"luminaria_id": lum_browser["id"], "rol": "desmontada"},
                ],
            }
        )
        ot_cancel_id = _mk_assigned_ot(
            {
                "tipo": "mantenimiento",
                "prioridad": 2,
                "observaciones": f"OT Conflicto Offline {tag}",
                "luminarias": [{"luminaria_id": lum_cancel["id"], "rol": "intervenida"}],
            }
        )

        # ------------------------------------------------------------------
        # Phase 2: PWA login (tipo_cliente=pwa), paquete, VAPID sub, Workbox SW & PMTiles cache
        # ------------------------------------------------------------------
        tec_client = auth_session_factory(
            tec_username, tec_secret, sede="montelibano", tipo_cliente="pwa"
        )
        pkg_resp = tec_client.get("/api/v1/campo/paquete", sede="montelibano")
        assert pkg_resp.status_code == 200, pkg_resp.text
        pkg = pkg_resp.json()
        assert pkg.get("cursor")
        assigned_ids = {o["id"] for o in pkg.get("ordenes_asignadas", [])}
        assert {ot_browser_id, ot_pqrs_id, ot_mod_id, ot_cancel_id}.issubset(assigned_ids)

        delta_pkg = tec_client.get(
            "/api/v1/campo/paquete",
            sede="montelibano",
            params={"desde": pkg["cursor"]},
        )
        assert delta_pkg.status_code == 200

        push_endpoint = f"https://fcm.googleapis.com/fcm/send/s4-{run_id}-{tag}"
        p256dh = base64.urlsafe_b64encode(b"\x04" + b"S" * 64).decode("ascii").rstrip("=")
        auth_key = base64.urlsafe_b64encode(b"A" * 16).decode("ascii").rstrip("=")
        sub_resp = tec_client.post(
            "/api/v1/notificaciones/push/suscripciones",
            sede="montelibano",
            json_body={
                "endpoint": push_endpoint,
                "claves": {"p256dh": p256dh, "auth": auth_key},
            },
        )
        assert sub_resp.status_code in (200, 201), sub_resp.text

        # Open apps/campo in Chromium: manifest, Workbox SW, storage.persist(), .pmtiles cache
        browser_driver.navigate(e2e_config.campo_url)
        browser_driver.wait_for_selector("input", timeout=e2e_config.timeout_seconds)

        sw_state = browser_driver.get_service_worker_state()
        assert sw_state.get("supported") is True
        assert len(sw_state.get("registrations", [])) >= 1 or sw_state.get("controller")
        initial_controller = sw_state.get("controller")

        has_persist = browser_driver.eval_js(
            "Boolean(navigator.storage && typeof navigator.storage.persist === 'function')"
        )
        assert has_persist is True

        browser_driver.fill('input[name="usuario"], input[type="text"]', tec_username)
        browser_driver.fill('input[name="clave"], input[type="password"]', tec_secret)
        browser_driver.click('button[type="submit"]')
        browser_driver.wait_for_selector("[data-testid='orden-item'], [data-orden-id], a, button")
        time.sleep(1.0)

        pm_deadline = time.monotonic() + e2e_config.timeout_seconds
        pm_cached = False
        while time.monotonic() < pm_deadline:
            pm_cached = bool(
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
            if pm_cached:
                break
            time.sleep(0.3)
        assert pm_cached, "Expected montelibano.pmtiles cached offline in CacheStorage"

        # ------------------------------------------------------------------
        # Phase 3: Offline execution in browser -> Dexie UUIDv4 outbox + SW update lock
        # ------------------------------------------------------------------
        browser_driver.set_offline(True)
        browser_driver.eval_js("window.dispatchEvent(new Event('offline'))")

        browser_driver.click("[data-testid='orden-item'], [data-orden-id], [data-testid='ejecutar-ot']")
        browser_driver.wait_for_selector("form")
        browser_driver.fill("input[name='sitio_arreglo']", f"Calle Campo Offline {tag}")
        browser_driver.fill("input[name='quien_recibe']", "Testigo Campo")

        # Attach compressed photo & draw canvas signature if signature pad exists
        png_b64 = base64.b64encode(make_png(8, 8)).decode("ascii")
        browser_driver.eval_js(
            f"""
            (() => {{
              const inp = document.querySelector('input[type="file"]');
              if (inp) {{
                const raw = atob({json.dumps(png_b64)});
                const arr = new Uint8Array(raw.length);
                for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
                const file = new File([arr], 'campo_s4.png', {{type: 'image/png'}});
                const dt = new DataTransfer();
                dt.items.add(file);
                inp.files = dt.files;
                inp.dispatchEvent(new Event('change', {{bubbles: true}}));
              }}
              const canvas = document.querySelector('canvas');
              if (canvas) {{
                const ctx = canvas.getContext('2d');
                if (ctx) {{ ctx.moveTo(2, 2); ctx.lineTo(20, 20); ctx.stroke(); }}
                canvas.dispatchEvent(new Event('pointerup', {{bubbles: true}}));
              }}
              return true;
            }})()
            """
        )
        browser_driver.click("button[type='submit']")

        outbox_deadline = time.monotonic() + e2e_config.timeout_seconds
        db_name = "sapef-campo"
        records: list[dict[str, Any]] = []
        while time.monotonic() < outbox_deadline:
            db_name, records = _discover_outbox_db_and_records(browser_driver)
            if records:
                break
            time.sleep(0.25)
        assert len(records) >= 1, "Offline execution must persist UUIDv4 operation in Dexie outbox"
        assert _UUID4_RE.match(str(records[0].get("uuid", "")))

        # Verify SW update lock while outbox is non-empty
        sw_lock = browser_driver.eval_js(
            """
            new Promise(async (resolve) => {
              let changed = false;
              const onChange = () => { changed = true; };
              navigator.serviceWorker.addEventListener('controllerchange', onChange);
              const regs = await navigator.serviceWorker.getRegistrations();
              for (const reg of regs) {
                if (reg.waiting) reg.waiting.postMessage({type: 'SKIP_WAITING'});
              }
              await new Promise((r) => setTimeout(r, 350));
              navigator.serviceWorker.removeEventListener('controllerchange', onChange);
              resolve({
                changed,
                controller: navigator.serviceWorker.controller
                  ? navigator.serviceWorker.controller.scriptURL : null,
              });
            })
            """,
            await_promise=True,
        )
        assert sw_lock["changed"] is False
        assert sw_lock["controller"] == initial_controller

        # Cancel ot_cancel_id on server while technician is offline
        cancel_resp = admin.post(
            f"/api/v1/ordenes/{ot_cancel_id}/anular",
            sede="montelibano",
            json_body={"motivo": "Anulada en servidor mientras técnico estaba offline"},
        )
        assert cancel_resp.status_code == 200, cancel_resp.text

        # Reconnect browser -> automatic batch sync drains outbox
        browser_driver.set_offline(False)
        browser_driver.eval_js("window.dispatchEvent(new Event('online'))")
        drain_deadline = time.monotonic() + e2e_config.timeout_seconds
        while time.monotonic() < drain_deadline:
            if len(browser_driver.get_indexeddb_records(db_name, "outbox")) == 0:
                break
            time.sleep(0.3)
        assert len(browser_driver.get_indexeddb_records(db_name, "outbox")) == 0

        # ------------------------------------------------------------------
        # Phase 4: Multi-op batch sync (12-comp + media + GPS + mod + PQRS 303 + conflicto + retry)
        # ------------------------------------------------------------------
        foto_up = tec_client.post(
            "/api/v1/archivos",
            sede="montelibano",
            idempotency_key=str(uuid.uuid4()),
            files={"archivo": ("foto_campo.webp", make_webp(), "image/webp")},
        )
        firma_up = tec_client.post(
            "/api/v1/archivos",
            sede="montelibano",
            idempotency_key=str(uuid.uuid4()),
            files={"archivo": ("firma.png", make_png(16, 8), "image/png")},
        )
        audio_up = tec_client.post(
            "/api/v1/archivos",
            sede="montelibano",
            idempotency_key=str(uuid.uuid4()),
            files={"archivo": ("audio.m4a", make_mp4_aac(), "audio/mp4")},
        )
        assert foto_up.status_code in (200, 201)
        assert firma_up.status_code in (200, 201)
        assert audio_up.status_code in (200, 201)

        u_pqrs_ot = str(uuid.uuid4())
        u_mod_ot = str(uuid.uuid4())
        u_conf_ot = str(uuid.uuid4())
        comps = build_maintenance_components(all_ok=True, overrides={"fotocelda": False})
        assert len(comps) == len(MAINTENANCE_12_COMPONENTS) == 12

        sync_batch = tec_client.post(
            "/api/v1/campo/sincronizar",
            sede="montelibano",
            json_body={
                "operaciones": [
                    {
                        "uuid": u_pqrs_ot,
                        "tipo": "mantenimiento",
                        "ordenId": ot_pqrs_id,
                        "creadaEn": "2026-07-22T09:15:00Z",
                        "payload": {
                            "sitio_arreglo": f"Barrio Centro {tag}",
                            "quien_recibe": "Vecino Testigo",
                            "requiere_desmonte": False,
                            "componentes": comps,
                            "materiales": [{"material_id": mat_id, "cantidad": 3}],
                            "evidencias": [
                                {"archivo_id": foto_up.json()["id"], "tipo": "foto"},
                                {"archivo_id": firma_up.json()["id"], "tipo": "firma"},
                                {"archivo_id": audio_up.json()["id"], "tipo": "audio"},
                            ],
                            "latitud": coords[1][0],
                            "longitud": coords[1][1],
                        },
                    },
                    {
                        "uuid": u_mod_ot,
                        "tipo": "modernizacion",
                        "ordenId": ot_mod_id,
                        "creadaEn": "2026-07-22T10:30:00Z",
                        "payload": {
                            "tipo_modernizacion_id": tipo_mod_id,
                            "barrio_id": barrio["id"],
                            "poste": f"P-MOD-{tag}",
                            "longitud_brazo": 1.5,
                            "destino_desmontada": "124",
                            "materiales": [],
                            "evidencias": [
                                {"archivo_id": foto_up.json()["id"], "tipo": "foto"},
                            ],
                            "latitud": coords[2][0],
                            "longitud": coords[2][1],
                        },
                    },
                    {
                        "uuid": u_conf_ot,
                        "tipo": "mantenimiento",
                        "ordenId": ot_cancel_id,
                        "creadaEn": "2026-07-22T11:00:00Z",
                        "payload": {
                            "sitio_arreglo": "Sitio Conflicto",
                            "quien_recibe": "Nadie",
                            "requiere_desmonte": False,
                            "componentes": build_maintenance_components(all_ok=True),
                            "materiales": [],
                            "evidencias": [],
                            "latitud": coords[3][0],
                            "longitud": coords[3][1],
                        },
                    },
                ]
            },
        )
        assert sync_batch.status_code == 200, sync_batch.text
        res_map = {r["uuid"]: r for r in sync_batch.json()["resultados"]}
        assert res_map[u_pqrs_ot]["estado"] == "aplicada"
        assert res_map[u_mod_ot]["estado"] == "aplicada"
        assert res_map[u_conf_ot]["estado"] == "conflicto"

        # Retry valid UUID -> ya_aplicada (idempotent, no double kardex deduction)
        retry_resp = tec_client.post(
            "/api/v1/campo/sincronizar",
            sede="montelibano",
            json_body={
                "operaciones": [
                    {
                        "uuid": u_pqrs_ot,
                        "tipo": "mantenimiento",
                        "ordenId": ot_pqrs_id,
                        "creadaEn": "2026-07-22T09:15:00Z",
                        "payload": {
                            "sitio_arreglo": f"Barrio Centro {tag}",
                            "quien_recibe": "Vecino Testigo",
                            "requiere_desmonte": False,
                            "componentes": comps,
                            "materiales": [{"material_id": mat_id, "cantidad": 3}],
                            "evidencias": [],
                        },
                    }
                ]
            },
        )
        assert retry_resp.status_code == 200
        assert retry_resp.json()["resultados"][0]["estado"] == "ya_aplicada"

        # Verify kardex (20 -> 17), PQRS auto-closed (303), and modernization states (121 / 124)
        mat_after = admin.get(f"/api/v1/materiales/{mat_id}", sede="montelibano").json()
        assert float(mat_after["existencias"]) == 17.0
        pqrs_after = admin.get(f"/api/v1/pqrs/{pqrs_id}", sede="montelibano").json()
        assert (
            str(pqrs_after.get("estado_codigo") or pqrs_after.get("estado", {}).get("codigo"))
            == "303"
        )
        mod_in_after = admin.get(f"/api/v1/luminarias/{lum_mod_in['id']}", sede="montelibano").json()
        assert (
            str(mod_in_after.get("estado_codigo") or mod_in_after.get("estado", {}).get("codigo"))
            == "121"
        )

        # Assign a new OT and verify Procrastinate Web Push IDs-only delivery job
        ot_new_id = _mk_assigned_ot(
            {
                "tipo": "mantenimiento",
                "prioridad": 1,
                "observaciones": f"OT Push Verify {tag}",
                "luminarias": [{"luminaria_id": lum_mod_in["id"], "rol": "intervenida"}],
            }
        )
        push_job = db_helper.fetch_one(
            """
            SELECT id, task_name, args
            FROM procrastinate_jobs
            WHERE task_name ILIKE '%push%'
              AND args::text LIKE %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (f"%{ot_new_id}%",),
        )
        assert push_job is not None, "Expected Procrastinate Web Push job on new OT assignment"
        push_args = db_helper.get_procrastinate_job_args(int(push_job["id"]))
        assert push_args
        for k, v in push_args.items():
            assert isinstance(v, (int, str, bool)) or v is None, (
                f"Procrastinate Web Push arg {k!r} must be primitive ID, got {type(v)}"
            )
        assert "vapid" not in str(push_args).lower() and "hash_clave" not in str(push_args).lower()
    finally:
        admin.patch(f"/api/v1/usuarios/{tec_id}", omit_sede=True, json_body={"activo": False})
