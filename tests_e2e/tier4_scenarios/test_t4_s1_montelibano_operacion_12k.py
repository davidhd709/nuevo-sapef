"""Tier 4 Scenario 1: Montelíbano Full Operational Lifecycle (12,000+ Luminaires)."""

from __future__ import annotations

import datetime as dt
import json
import math
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fixtures import (
    MAINTENANCE_12_COMPONENTS,
    MONTELIBANO_BBOX,
    XlsxSheet,
    build_maintenance_components,
    build_xlsx_bytes,
    generate_coordinates,
    make_png,
)
from harness.browser import BrowserDriver
from harness.client import SapefClient
from harness.config import E2EConfig
from harness.db import DbHelper

pytestmark = [pytest.mark.tier4, pytest.mark.browser]

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
        for key in ("items", "resultados", "datos", "luminarias", "ordenes", "materiales"):
            val = payload.get(key)
            if isinstance(val, list):
                return [dict(item) for item in val]
    raise AssertionError(f"Unexpected list/paginated payload: {payload!r}")


def _latlng_to_tile(lat: float, lng: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    x = int((lng + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _browser_errors(driver: BrowserDriver) -> list[str]:
    errs: list[str] = []
    for ev in driver.events:
        method = ev.get("method")
        params = ev.get("params", {})
        if method == "Runtime.exceptionThrown":
            errs.append(f"JS exception: {json.dumps(params)}")
        elif method == "Runtime.consoleAPICalled" and params.get("type") == "error":
            errs.append(f"Console error: {json.dumps(params)}")
    return errs


def _wait_migration_execution(
    client: SapefClient,
    db_helper: DbHelper,
    e2e_config: E2EConfig,
    resp_json: dict[str, Any],
    *,
    sede: str,
) -> dict[str, Any]:
    job_id = resp_json.get("tarea_id") or resp_json.get("tareaId")
    if isinstance(job_id, int):
        db_helper.wait_for_procrastinate_job(job_id, timeout=max(e2e_config.timeout_seconds, 60.0))

    exec_id = resp_json.get("ejecucion_id") or resp_json.get("ejecucionId") or resp_json.get("id")
    if exec_id is None:
        return resp_json

    deadline = time.monotonic() + max(e2e_config.timeout_seconds, 60.0)
    last: dict[str, Any] = resp_json
    while time.monotonic() < deadline:
        poll = client.get(f"/api/v1/migracion/ejecuciones/{exec_id}", sede=sede)
        if poll.status_code == 200:
            last = poll.json()
            estado = str(last.get("estado", "")).lower()
            if estado in {"completado", "finalizado", "succeeded", "ok"}:
                return last
            if estado in {"error", "fallido", "failed", "rechazado"}:
                raise AssertionError(f"Migration execution {exec_id} failed: {last}")
        elif poll.status_code == 404:
            return last
        time.sleep(0.25)
    return last


def _ensure_montelibano_12200_luminaires(
    client: SapefClient,
    db_helper: DbHelper,
    e2e_config: E2EConfig,
    barrio_names: list[str],
    run_id: str,
) -> int:
    """Ensure Montelíbano has >= 12,200 luminaires inside MONTELIBANO_BBOX (SYN-1 or IMP-1)."""
    probe = client.get(
        "/api/v1/luminarias",
        sede="montelibano",
        params={"page": 1, "size": 1},
    )
    assert probe.status_code == 200, probe.text
    current_total = int(probe.json()["total"])
    if current_total >= 12200:
        return current_total

    needed = 12200 - current_total
    coords = generate_coordinates("montelibano", needed, seed=2026)
    batch_size = 3500
    headers = [
        "codigo",
        "barrio",
        "latitud",
        "longitud",
        "estado",
        "marca",
        "tecnologia",
        "potencia",
        "tipo_intervencion",
        "fecha_instalacion",
        "poste",
        "es_rural",
    ]
    for offset in range(0, needed, batch_size):
        chunk = coords[offset : offset + batch_size]
        rows: list[list[Any]] = [headers]
        for idx, (lat, lng) in enumerate(chunk):
            seq = offset + idx + 1
            estado = "124" if seq % 3 == 0 else "121"
            rows.append(
                [
                    f"{run_id}-SYN1-{seq:05d}",
                    barrio_names[seq % len(barrio_names)],
                    lat,
                    lng,
                    estado,
                    "PHILIPS" if seq % 2 == 0 else "SCHREDER",
                    "LED",
                    70 if seq % 2 == 0 else 100,
                    "RECIBO_INICIAL" if estado == "121" else "BODEGA",
                    dt.date(2025, (seq % 12) + 1, (seq % 28) + 1),
                    f"P-S1-{seq:05d}",
                    seq % 5 == 0,
                ]
            )
        xlsx_bytes = build_xlsx_bytes([XlsxSheet("Luminarias", rows)])
        up = client.post(
            "/api/v1/migracion/luminarias",
            sede="montelibano",
            files={"archivo": (f"syn1_mtl_{offset}.xlsx", xlsx_bytes, _XLSX_MIME)},
        )
        assert up.status_code in (200, 202), f"Batch IMP-1 seed failed: {up.status_code} {up.text}"
        _wait_migration_execution(client, db_helper, e2e_config, up.json(), sede="montelibano")

    after = client.get(
        "/api/v1/luminarias",
        sede="montelibano",
        params={"page": 1, "size": 25},
    )
    assert after.status_code == 200
    final_total = int(after.json()["total"])
    assert final_total >= 12200, f"Expected >= 12,200 luminaires in Montelíbano, got {final_total}"
    return final_total


def _browser_login_web(driver: BrowserDriver, e2e_config: E2EConfig) -> None:
    driver.navigate(f"{e2e_config.web_url}/ingresar")
    driver.wait_for_selector("input[type='password']", timeout=e2e_config.timeout_seconds)
    driver.fill(
        "input[name='usuario'], input[autocomplete='username'], input[type='text']",
        e2e_config.admin_user,
    )
    driver.fill("input[name='clave'], input[type='password']", e2e_config.admin_password)
    driver.click("button[type='submit']")
    deadline = time.monotonic() + e2e_config.timeout_seconds
    while time.monotonic() < deadline and "/ingresar" in driver.current_url():
        time.sleep(0.2)
    assert "/ingresar" not in driver.current_url(), (
        f"Login did not navigate away from /ingresar: {driver.current_url()}"
    )


def test_montelibano_full_operational_lifecycle_12k_map_pqrs_ot_kardex_tablero(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    db_helper: DbHelper,
    browser_driver: BrowserDriver,
    run_id: str,
) -> None:
    """Scenario 1: 12.2k+ luminaires -> MVT z12/z16 + PMTiles Range + /mapa -> PQRS -> OT -> Dashboard."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tag = uuid.uuid4().hex[:6].upper()

    # ------------------------------------------------------------------
    # Phase 1: Catalogs, 12,200+ Montelíbano luminaires, MVT & PMTiles
    # ------------------------------------------------------------------
    barrios = _extract_items(admin.get("/api/v1/barrios", sede="montelibano").json())
    assert barrios, "Montelíbano must have seeded barrios"
    barrio_names = [str(b["nombre"]) for b in barrios[:10]]
    barrio = next((b for b in barrios if b["nombre"] == "El Centro"), barrios[0])

    total_lums = _ensure_montelibano_12200_luminaires(
        admin, db_helper, e2e_config, barrio_names, run_id
    )
    assert total_lums >= 12200

    # Verify sample coordinates fall inside MONTELIBANO_BBOX
    min_lat, min_lng, max_lat, max_lng = MONTELIBANO_BBOX
    estados = _extract_items(
        admin.get("/api/v1/estados", omit_sede=True, params={"proceso": "luminaria"}).json()
    )
    est_121 = next(e for e in estados if str(e["codigo"]) == "121")
    est_124 = next(e for e in estados if str(e["codigo"]) == "124")
    tech_led = next(
        t
        for t in _extract_items(
            admin.get("/api/v1/maestros/LUMINARIA_TECNOLOGIA", omit_sede=True).json()
        )
        if t["codigo"] == "LED"
    )
    pot_70 = next(
        (
            p
            for p in _extract_items(
                admin.get("/api/v1/maestros/LUMINARIA_POTENCIA", omit_sede=True).json()
            )
            if str(p["codigo"]) == "70"
        )
    )
    marca_philips = next(
        m
        for m in _extract_items(
            admin.get("/api/v1/maestros/LUMINARIA_MARCA", omit_sede=True).json()
        )
        if m["codigo"] == "PHILIPS"
    )
    canal_wa = next(
        c
        for c in _extract_items(
            admin.get("/api/v1/maestros/CANAL_PQRS", omit_sede=True).json()
        )
        if c["codigo"] == "WHATSAPP"
    )

    center_lat = round((min_lat + max_lat) / 2.0, 6)
    center_lng = round((min_lng + max_lng) / 2.0, 6)

    # Create dedicated active (121) & replacement (124) luminaires at Montelíbano center
    lum_act = admin.post(
        "/api/v1/luminarias",
        sede="montelibano",
        json_body={
            "codigo": f"{run_id}-S1-ACT-{tag}",
            "barrio_id": barrio["id"],
            "latitud": center_lat,
            "longitud": center_lng,
            "estado_id": est_121["id"],
            "tecnologia_id": tech_led["id"],
            "potencia_id": pot_70["id"],
            "marca_id": marca_philips["id"],
            "poste": f"P-S1A-{tag}",
        },
    )
    assert lum_act.status_code == 201, lum_act.text
    lum_act_dto = lum_act.json()

    lum_rep = admin.post(
        "/api/v1/luminarias",
        sede="montelibano",
        json_body={
            "codigo": f"{run_id}-S1-REP-{tag}",
            "barrio_id": barrio["id"],
            "latitud": center_lat + 0.0002,
            "longitud": center_lng + 0.0002,
            "estado_id": est_124["id"],
            "tecnologia_id": tech_led["id"],
            "potencia_id": pot_70["id"],
            "marca_id": marca_philips["id"],
            "poste": f"P-S1R-{tag}",
        },
    )
    assert lum_rep.status_code == 201, lum_rep.text
    lum_rep_dto = lum_rep.json()

    # MVT clustering at low zoom (z=12) and point resolution at high zoom (z=16)
    tx12, ty12 = _latlng_to_tile(center_lat, center_lng, 12)
    mvt_z12 = admin.get(
        f"/api/v1/mapa/luminarias/12/{tx12}/{ty12}.mvt",
        sede="montelibano",
    )
    assert mvt_z12.status_code == 200, mvt_z12.text
    assert mvt_z12.content_type.lower().startswith("application/vnd.mapbox-vector-tile")
    assert len(mvt_z12.content) > 0, "Expected non-empty clustered MVT tile at z=12"

    tx16, ty16 = _latlng_to_tile(center_lat, center_lng, 16)
    mvt_z16 = admin.get(
        f"/api/v1/mapa/luminarias/16/{tx16}/{ty16}.mvt",
        sede="montelibano",
        params={"tecnologia": tech_led["id"]},
    )
    assert mvt_z16.status_code == 200, mvt_z16.text
    assert mvt_z16.content_type.lower().startswith("application/vnd.mapbox-vector-tile")
    assert len(mvt_z16.content) > 0, "Expected non-empty point-level MVT tile at z=16"

    # PMTiles HTTP Range 206
    pm_head = admin.get(
        "/api/v1/mapa/base/montelibano.pmtiles",
        omit_sede=True,
        byte_range="bytes=0-1023",
    )
    assert pm_head.status_code == 206, pm_head.text
    assert pm_head.header("accept-ranges", "").lower() == "bytes"
    assert pm_head.header("content-range")
    assert len(pm_head.content) == 1024
    assert pm_head.content[:7] == b"PMTiles"

    # Browser /mapa <canvas> render check
    _browser_login_web(browser_driver, e2e_config)
    browser_driver.navigate(f"{e2e_config.web_url}/mapa")
    browser_driver.wait_for_selector("canvas", timeout=e2e_config.timeout_seconds)
    map_counts = browser_driver.has_canvas_or_svg()
    assert map_counts["canvas"] >= 1, f"Expected MapLibre <canvas> on /mapa, got {map_counts}"
    assert not _browser_errors(browser_driver), _browser_errors(browser_driver)

    # ------------------------------------------------------------------
    # Phase 2: PQRS Semaphore (verde / amarillo / rojo) per sede params
    # ------------------------------------------------------------------
    params_items = _extract_items(admin.get("/api/v1/parametros", sede="montelibano").json())
    semaforo_param = next(p for p in params_items if p["codigo"] == "semaforo_pqrs_umbrales")
    verde_max = int(semaforo_param["valor"]["verde_max_dias"])
    amarillo_max = int(semaforo_param["valor"]["amarillo_max_dias"])

    # Import aged PQRS via IMP-2 so verde, amarillo, and rojo thresholds are all populated
    aged_lums = []
    for idx in range(2):
        resp_l = admin.post(
            "/api/v1/luminarias",
            sede="montelibano",
            json_body={
                "codigo": f"{run_id}-S1-SEM{idx}-{tag}",
                "barrio_id": barrio["id"],
                "latitud": center_lat + 0.0005 * (idx + 1),
                "longitud": center_lng + 0.0005 * (idx + 1),
                "estado_id": est_121["id"],
                "tecnologia_id": tech_led["id"],
                "potencia_id": pot_70["id"],
                "marca_id": marca_philips["id"],
            },
        )
        assert resp_l.status_code == 201, resp_l.text
        aged_lums.append(resp_l.json())

    today = dt.date.today()
    imp2_bytes = build_xlsx_bytes(
        [
            XlsxSheet(
                "PQRS",
                [
                    [
                        "numero_origen",
                        "fecha_registro",
                        "canal",
                        "prioridad",
                        "estado_pqrs",
                        "identificacion_ciudadano",
                        "nombre_ciudadano",
                        "telefono",
                        "correo",
                        "luminaria_codigo",
                        "reparada",
                        "fecha_reparacion",
                        "observacion",
                    ],
                    [
                        f"{run_id}-SEM-AMA-{tag}",
                        today - dt.timedelta(days=verde_max + 1),
                        "WHATSAPP",
                        1,
                        "301",
                        f"CC-S1A-{tag}",
                        f"Ciudadano Amarillo {tag}",
                        "3001230001",
                        f"ama.{tag.lower()}@example.test",
                        aged_lums[0]["codigo"],
                        False,
                        None,
                        "PQRS amarilla por umbral",
                    ],
                    [
                        f"{run_id}-SEM-ROJ-{tag}",
                        today - dt.timedelta(days=amarillo_max + 2),
                        "PRESENCIAL",
                        0,
                        "301",
                        f"CC-S1R-{tag}",
                        f"Ciudadano Rojo {tag}",
                        "3001230002",
                        f"roj.{tag.lower()}@example.test",
                        aged_lums[1]["codigo"],
                        False,
                        None,
                        "PQRS roja por umbral",
                    ],
                ],
            )
        ]
    )
    imp2_up = admin.post(
        "/api/v1/migracion/pqrs",
        sede="montelibano",
        files={"archivo": (f"s1_sem_{tag}.xlsx", imp2_bytes, _XLSX_MIME)},
    )
    assert imp2_up.status_code in (200, 202), imp2_up.text
    _wait_migration_execution(admin, db_helper, e2e_config, imp2_up.json(), sede="montelibano")

    # Create live PQRS (verde) on lum_act_dto with email notification hook
    cit_resp = admin.post(
        "/api/v1/ciudadanos",
        sede="montelibano",
        json_body={
            "identificacion": f"CC-S1V-{tag}",
            "nombre_completo": f"Ciudadano Verde {tag}",
            "barrio_id": barrio["id"],
            "telefono": "3007778899",
            "correo": f"verde.{tag.lower()}@example.test",
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
            "observacion_solicitante": f"Falla activa Scenario 1 {tag}",
            "notificar_cliente": True,
            "luminarias": [{"luminaria_id": lum_act_dto["id"]}],
        },
    )
    assert pqrs_resp.status_code == 201, pqrs_resp.text
    pqrs_id = pqrs_resp.json()["id"]

    # Verify verde / amarillo / rojo filtering against sede thresholds
    for expected_color, target_lum_id in (
        ("verde", lum_act_dto["id"]),
        ("amarillo", aged_lums[0]["id"]),
        ("rojo", aged_lums[1]["id"]),
    ):
        pend = admin.get(
            "/api/v1/pqrs/pendientes",
            sede="montelibano",
            params={"semaforo": expected_color, "page": 1, "size": 100},
        )
        assert pend.status_code == 200, pend.text
        rows = _extract_items(pend.json())
        assert any(
            (r.get("luminaria_id") or (r.get("luminaria") or {}).get("id")) == target_lum_id
            for r in rows
        ), f"Expected luminaire {target_lum_id} in semaphore {expected_color!r}: {rows[:5]}"
        for row in rows:
            days = int(row["dias_abierta"])
            calc = (
                "verde" if days <= verde_max else ("amarillo" if days <= amarillo_max else "rojo")
            )
            assert row["semaforo"] == calc == expected_color

    # ------------------------------------------------------------------
    # Phase 3: Maintenance OT (12 components + replacement + kardex) -> PQRS 303
    # ------------------------------------------------------------------
    mat_resp = admin.post(
        "/api/v1/materiales",
        sede="montelibano",
        json_body={
            "categoria": "ELECTRICO",
            "codigo": f"{run_id}-S1MAT-{tag}",
            "descripcion": f"Fotocelda S1 {tag}",
            "unidad": "UND",
            "existencias": 15,
            "existencias_minimas": 3,
        },
    )
    assert mat_resp.status_code == 201, mat_resp.text
    mat_id = mat_resp.json()["id"]

    roles = _extract_items(admin.get("/api/v1/roles", omit_sede=True).json())
    tec_role = next(r for r in roles if str(r["codigo"]).upper() == "TECNICO")
    sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    mtl_sede_id = next(s["id"] for s in sedes if s["codigo"] == "montelibano")
    tec_user = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": f"s1_tec_{tag.lower()}",
            "nombre_completo": f"Técnico S1 {tag}",
            "identificacion": f"77{int(tag, 16) % 10000000:07d}",
            "correo": f"s1.tec.{tag.lower()}@example.test",
            "clave": f"S1Tec!{uuid.uuid4().hex[:10]}9z",
            "rol_id": tec_role["id"],
            "sedes": [mtl_sede_id],
            "activo": True,
            "debe_cambiar_clave": False,
        },
    )
    assert tec_user.status_code == 201, tec_user.text
    tec_id = tec_user.json()["id"]

    try:
        ot_resp = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 1,
                "pqrs_id": pqrs_id,
                "observaciones": f"Mantenimiento S1 {tag}",
                "luminarias": [{"luminaria_id": lum_act_dto["id"], "rol": "intervenida"}],
            },
        )
        assert ot_resp.status_code == 201, ot_resp.text
        ot_id = ot_resp.json()["id"]

        asg_resp = admin.post(
            f"/api/v1/ordenes/{ot_id}/asignar",
            sede="montelibano",
            json_body={"tecnico_id": tec_id},
        )
        assert asg_resp.status_code in (200, 202), asg_resp.text

        ev_resp = admin.post(
            "/api/v1/archivos",
            sede="montelibano",
            idempotency_key=str(uuid.uuid4()),
            files={"archivo": ("s1_cierre.png", make_png(8, 8), "image/png")},
        )
        assert ev_resp.status_code in (200, 201), ev_resp.text

        componentes = build_maintenance_components(
            all_ok=True,
            overrides={"fotocelda": False, "bombillo": False},
        )
        assert len(componentes) == len(MAINTENANCE_12_COMPONENTS) == 12

        close_resp = admin.post(
            f"/api/v1/ordenes/{ot_id}/cerrar",
            sede="montelibano",
            json_body={
                "sitio_arreglo": "Centro Montelíbano Cra 5",
                "quien_recibe": "Líder Comunal S1",
                "requiere_desmonte": True,
                "causal_desmonte": "Luminaria dañada por descarga",
                "luminaria_reemplazo_id": lum_rep_dto["id"],
                "componentes": componentes,
                "materiales": [{"material_id": mat_id, "cantidad": 4}],
                "evidencias": [{"archivo_id": ev_resp.json()["id"], "tipo": "foto"}],
            },
        )
        assert close_resp.status_code == 200, close_resp.text
        assert (
            str(
                close_resp.json().get("estado_codigo")
                or close_resp.json().get("estado", {}).get("codigo")
            )
            == "203"
        )

        # Atomic kardex deduction (15 - 4 = 11), replacement active (121), PQRS auto-closed (303)
        mat_after = admin.get(f"/api/v1/materiales/{mat_id}", sede="montelibano").json()
        assert float(mat_after["existencias"]) == 11.0
        rep_after = admin.get(f"/api/v1/luminarias/{lum_rep_dto['id']}", sede="montelibano").json()
        assert (
            str(rep_after.get("estado_codigo") or rep_after.get("estado", {}).get("codigo"))
            == "121"
        )
        pqrs_after = admin.get(f"/api/v1/pqrs/{pqrs_id}", sede="montelibano").json()
        assert (
            str(pqrs_after.get("estado_codigo") or pqrs_after.get("estado", {}).get("codigo"))
            == "303"
        )

        # ------------------------------------------------------------------
        # Phase 4: Recalculate summary tables & verify /tablero < 2.0s + ECharts
        # ------------------------------------------------------------------
        recalc = admin.post(
            "/api/v1/tablero/recalcular",
            sede="montelibano",
            json_body={"sede_id": mtl_sede_id},
        )
        assert recalc.status_code == 202, recalc.text
        recalc_job = recalc.json().get("tareaId") or recalc.json().get("tarea_id")
        if isinstance(recalc_job, int):
            db_helper.wait_for_procrastinate_job(recalc_job, timeout=e2e_config.timeout_seconds)

        t0 = time.perf_counter()
        resumen = admin.get("/api/v1/tablero/resumen", sede="montelibano")
        elapsed = time.perf_counter() - t0
        assert resumen.status_code == 200, resumen.text
        assert elapsed < 2.0, f"GET /tablero/resumen took {elapsed:.3f}s (>= 2.0s)"

        browser_driver.navigate(f"{e2e_config.web_url}/tablero")
        chart_deadline = time.monotonic() + e2e_config.timeout_seconds
        chart_counts = {"canvas": 0, "svg": 0}
        while time.monotonic() < chart_deadline:
            chart_counts = browser_driver.has_canvas_or_svg()
            if chart_counts["canvas"] > 0 or chart_counts["svg"] > 0:
                break
            time.sleep(0.25)
        assert chart_counts["canvas"] > 0 or chart_counts["svg"] > 0, (
            f"Expected ECharts <canvas>/<svg> on /tablero, got {chart_counts}"
        )
        assert not _browser_errors(browser_driver), _browser_errors(browser_driver)
    finally:
        admin.patch(f"/api/v1/usuarios/{tec_id}", omit_sede=True, json_body={"activo": False})
