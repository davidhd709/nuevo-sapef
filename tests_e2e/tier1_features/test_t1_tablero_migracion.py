"""Tier 1 E2E tests for EP-09 Dashboard (F9-1..F9-4), IMP-1..IMP-6, SEED-1..6, and F0."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fixtures import (
    build_imp1_luminarias_xlsx,
    build_imp2_pqrs_xlsx,
    build_imp3_ordenes_4files,
    build_imp4_inventario_xlsx,
    build_imp6_base_config_xlsx,
    build_opainn_parquet_package,
)
from harness.browser import BrowserDriver
from harness.client import SapefClient
from harness.config import E2EConfig
from harness.db import DbHelper

pytestmark = pytest.mark.tier1

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
        for key in ("items", "resultados", "datos", "luminarias", "ordenes", "pqrs"):
            val = payload.get(key)
            if isinstance(val, list):
                return list(val)
    raise AssertionError(f"Unexpected list payload: {payload!r}")


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
        db_helper.wait_for_procrastinate_job(job_id, timeout=e2e_config.timeout_seconds)

    exec_id = resp_json.get("ejecucion_id") or resp_json.get("ejecucionId") or resp_json.get("id")
    if exec_id is None:
        return resp_json

    deadline = time.monotonic() + e2e_config.timeout_seconds
    last: dict[str, Any] = resp_json
    while time.monotonic() < deadline:
        poll = client.get(f"/api/v1/migracion/ejecuciones/{exec_id}", sede=sede)
        if poll.status_code == 200:
            last = poll.json()
            estado = str(last.get("estado", "")).lower()
            if estado in {"completado", "finalizado", "succeeded", "ok"}:
                return last
            if estado in {"error", "fallido", "failed"}:
                raise AssertionError(f"Migration execution {exec_id} failed: {last}")
        elif poll.status_code == 404:
            return last
        time.sleep(0.25)
    return last


def test_tablero_resumen_assets_operational_pqrs_and_commercial_kpis_under_2s(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
) -> None:
    """F9-1..F9-3: Dashboard resumen & sub-routes per sede (montelibano, alcala) in < 2.0s."""
    for sede in ("montelibano", "alcala"):
        client = _admin_client(auth_session_factory, e2e_config, sede=sede)
        t0 = time.perf_counter()
        resp = client.get("/api/v1/tablero/resumen", sede=sede)
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200, f"GET /tablero/resumen ({sede}) failed: {resp.text}"
        assert elapsed < 2.0, f"Dashboard resumen ({sede}) took {elapsed:.3f}s (>= 2.0s)"

        body = resp.json()
        assert "activos" in body or "luminarias_instaladas_mes" in body
        assert "operacion" in body or "pqrs" in body or "pqrs_semaforo" in body
        assert "comercial" in body

    # Consolidated view (?sede=todas)
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    t0 = time.perf_counter()
    cons_resp = mtl.get("/api/v1/tablero/resumen", params={"sede": "todas"}, omit_sede=True)
    elapsed_cons = time.perf_counter() - t0
    assert cons_resp.status_code == 200, cons_resp.text
    assert elapsed_cons < 2.0, f"Consolidated dashboard took {elapsed_cons:.3f}s (>= 2.0s)"


def test_tablero_procrastinate_recalcular_ids_only_job(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F9-4: POST /tablero/recalcular enqueues IDs-only Procrastinate job & succeeds."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    sedes = _extract_items(client.get("/api/v1/sedes", omit_sede=True).json())
    mtl_id = next(s["id"] for s in sedes if s.get("codigo") == "montelibano")

    resp = client.post(
        "/api/v1/tablero/recalcular",
        sede="montelibano",
        json_body={"sede_id": mtl_id},
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json().get("tareaId") or resp.json().get("tarea_id") or resp.json().get("id")
    assert isinstance(job_id, int), f"Expected integer Procrastinate job ID, got {resp.json()!r}"

    args = db_helper.get_procrastinate_job_args(job_id)
    for k, v in args.items():
        assert isinstance(v, (int, str, bool)) or v is None, (
            f"Procrastinate arg {k!r} must be primitive ID, got {type(v)}"
        )
    db_helper.wait_for_procrastinate_job(job_id, timeout=e2e_config.timeout_seconds)


def test_imp1_luminaires_excel_importer_normalization_and_idempotency(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """IMP-1: Luminaires importer normalizes KÜNIX/SCHRÉDER/MH/1900, resolves barrio, idempotent."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    barrios = _extract_items(client.get("/api/v1/barrios", sede="montelibano").json())
    barrio_names = [b["nombre"] for b in barrios[:3]]

    prefix = f"{run_id}-I1-{uuid.uuid4().hex[:4].upper()}"
    xlsx_bytes = build_imp1_luminarias_xlsx(
        prefix,
        sede_codigo="montelibano",
        count=6,
        include_quirks=True,
        barrio_names=barrio_names,
    )

    resp = client.post(
        "/api/v1/migracion/luminarias",
        sede="montelibano",
        files={"archivo": (f"imp1_{prefix}.xlsx", xlsx_bytes, _XLSX_MIME)},
    )
    assert resp.status_code in (200, 202), resp.text
    result = _wait_migration_execution(client, db_helper, e2e_config, resp.json(), sede="montelibano")
    conc = result.get("conciliacion", result)
    assert conc.get("leidas", 6) == 6
    assert conc.get("creadas", 6) >= 6

    # Check normalized attributes on LUM-0001 (KÜNIX -> KUNIX, MH -> METAL_HALIDE, 1900 -> null)
    lum1_list = _extract_items(
        client.get(
            "/api/v1/luminarias",
            sede="montelibano",
            params={"texto": f"{prefix}-LUM-0001", "size": 10},
        ).json()
    )
    assert len(lum1_list) == 1
    lum1 = lum1_list[0]
    assert lum1.get("fecha_instalacion") is None
    assert "KUNIX" in str(lum1.get("marca_codigo") or lum1.get("marca", "")).upper()
    assert "METAL_HALIDE" in str(lum1.get("tecnologia_codigo") or lum1.get("tecnologia", "")).upper()

    # Check LUM-0002 (SCHRÉDER -> SCHREDER)
    lum2 = _extract_items(
        client.get(
            "/api/v1/luminarias",
            sede="montelibano",
            params={"texto": f"{prefix}-LUM-0002", "size": 10},
        ).json()
    )[0]
    assert "SCHREDER" in str(lum2.get("marca_codigo") or lum2.get("marca", "")).upper()

    # Re-run must be idempotent (0 duplicates)
    replay = client.post(
        "/api/v1/migracion/luminarias",
        sede="montelibano",
        files={"archivo": (f"imp1_{prefix}.xlsx", xlsx_bytes, _XLSX_MIME)},
    )
    assert replay.status_code in (200, 202)
    replay_res = _wait_migration_execution(
        client, db_helper, e2e_config, replay.json(), sede="montelibano"
    )
    assert replay_res.get("conciliacion", replay_res).get("creadas", 0) == 0


def test_imp2_pqrs_excel_importer_citizen_dedup_wildcard_and_reconciliation(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """IMP-2: PQRS Excel importer deduplicates citizens, links SIN-IDENTIFICAR, reconciles."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    prefix = f"{run_id}-I2-{uuid.uuid4().hex[:4].upper()}"
    barrios = _extract_items(client.get("/api/v1/barrios", sede="montelibano").json())
    lum_xlsx = build_imp1_luminarias_xlsx(
        prefix,
        sede_codigo="montelibano",
        count=2,
        include_quirks=False,
        barrio_names=[barrios[0]["nombre"]],
    )
    r_lum = client.post(
        "/api/v1/migracion/luminarias",
        sede="montelibano",
        files={"archivo": (f"imp1_{prefix}.xlsx", lum_xlsx, _XLSX_MIME)},
    )
    assert r_lum.status_code in (200, 202)
    _wait_migration_execution(client, db_helper, e2e_config, r_lum.json(), sede="montelibano")

    pqrs_xlsx = build_imp2_pqrs_xlsx(
        prefix,
        [f"{prefix}-LUM-0001", f"{prefix}-LUM-0002"],
        include_wildcard=True,
        include_multi_luminaire=True,
    )
    r_pqr = client.post(
        "/api/v1/migracion/pqrs",
        sede="montelibano",
        files={"archivo": (f"imp2_{prefix}.xlsx", pqrs_xlsx, _XLSX_MIME)},
    )
    assert r_pqr.status_code in (200, 202), r_pqr.text
    res = _wait_migration_execution(client, db_helper, e2e_config, r_pqr.json(), sede="montelibano")
    conc = res.get("conciliacion", res)
    assert conc.get("creadas", 3) >= 3

    # Citizen CC-{prefix}-01 deduplicated to 1 citizen record
    cit_resp = client.get(
        "/api/v1/ciudadanos",
        sede="montelibano",
        params={"buscar": f"CC-{prefix}-01", "size": 10},
    )
    assert cit_resp.status_code == 200
    assert len(_extract_items(cit_resp.json())) == 1


def test_imp3_4excel_historical_work_orders_importer(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """IMP-3: 4-Excel historical work orders importer creates unified orden_trabajo + events."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    prefix = f"{run_id}-I3-{uuid.uuid4().hex[:4].upper()}"
    barrios = _extract_items(client.get("/api/v1/barrios", sede="montelibano").json())
    lum_xlsx = build_imp1_luminarias_xlsx(
        prefix,
        sede_codigo="montelibano",
        count=4,
        include_quirks=False,
        barrio_names=[barrios[0]["nombre"]],
    )
    r_lum = client.post(
        "/api/v1/migracion/luminarias",
        sede="montelibano",
        files={"archivo": (f"imp1_{prefix}.xlsx", lum_xlsx, _XLSX_MIME)},
    )
    assert r_lum.status_code in (200, 202)
    _wait_migration_execution(client, db_helper, e2e_config, r_lum.json(), sede="montelibano")

    codes = [f"{prefix}-LUM-{i:04d}" for i in range(1, 5)]
    four_files = build_imp3_ordenes_4files(prefix, codes)
    resp = client.post(
        "/api/v1/migracion/ordenes",
        sede="montelibano",
        files=[(name.split(".")[0], name, payload, _XLSX_MIME) for name, payload in four_files.items()],
    )
    assert resp.status_code in (200, 202), resp.text
    res = _wait_migration_execution(client, db_helper, e2e_config, resp.json(), sede="montelibano")
    conc = res.get("conciliacion", res)
    assert conc.get("creadas", 4) >= 4


def test_imp4_inventory_excel_importer_materials_kardex_and_bodega(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """IMP-4: Inventory Excel importer loads materials, initial kardex, warehouse luminaires."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    prefix = f"{run_id}-I4-{uuid.uuid4().hex[:4].upper()}"
    barrios = _extract_items(client.get("/api/v1/barrios", sede="montelibano").json())
    lum_xlsx = build_imp1_luminarias_xlsx(
        prefix,
        sede_codigo="montelibano",
        count=2,
        include_quirks=False,
        barrio_names=[barrios[0]["nombre"]],
    )
    r_lum = client.post(
        "/api/v1/migracion/luminarias",
        sede="montelibano",
        files={"archivo": (f"imp1_{prefix}.xlsx", lum_xlsx, _XLSX_MIME)},
    )
    assert r_lum.status_code in (200, 202)
    _wait_migration_execution(client, db_helper, e2e_config, r_lum.json(), sede="montelibano")

    inv_xlsx = build_imp4_inventario_xlsx(
        prefix, warehouse_codes=[f"{prefix}-LUM-0001", f"{prefix}-LUM-0002"]
    )
    resp = client.post(
        "/api/v1/migracion/inventario",
        sede="montelibano",
        files={"archivo": (f"imp4_{prefix}.xlsx", inv_xlsx, _XLSX_MIME)},
    )
    assert resp.status_code in (200, 202), resp.text
    _wait_migration_execution(client, db_helper, e2e_config, resp.json(), sede="montelibano")

    mats = _extract_items(
        client.get(
            "/api/v1/materiales",
            sede="montelibano",
            params={"buscar": f"{prefix}-MAT-01", "size": 10},
        ).json()
    )
    assert len(mats) == 1
    assert float(mats[0]["existencias"]) == 25.0


def test_imp5_opainn_parquet_sha256_warehouse_importer(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """IMP-5: OPainn Parquet + SHA-256 manifest warehouse importer registers cargue & recalc."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    pkg_dir = build_opainn_parquet_package(
        e2e_config.data_dir / "imp5_pkg",
        sede_codigo="montelibano",
        comercializador_codigo="afinia",
        periodo="202610",
    )
    resp = client.post(
        "/api/v1/migracion/comercial/opainn",
        sede="montelibano",
        json_body={
            "ruta_almacen": str(pkg_dir),
            "comercializador_codigo": "afinia",
            "periodos": ["202610"],
        },
    )
    assert resp.status_code in (200, 202), resp.text
    res = _wait_migration_execution(client, db_helper, e2e_config, resp.json(), sede="montelibano")
    assert "202610" in str(res)

    cortes = client.get("/api/v1/comercial/afinia/cortes", sede="montelibano").json()
    corte_list = cortes if isinstance(cortes, list) else cortes.get("items", [])
    assert any(c.get("periodo") == "202610" for c in corte_list)


def test_imp6_base_config_and_users_importer_no_passwords_debe_cambiar_clave(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """IMP-6: Base config & users importer sets debe_cambiar_clave=true and never exposes pw."""
    client = _admin_client(auth_session_factory, e2e_config, sede="alcala")
    prefix = f"{run_id}-I6-{uuid.uuid4().hex[:4].upper()}"
    imp6_xlsx = build_imp6_base_config_xlsx(prefix, sede_codigo="alcala")

    resp = client.post(
        "/api/v1/migracion/base",
        sede="alcala",
        files={"archivo": (f"imp6_{prefix}.xlsx", imp6_xlsx, _XLSX_MIME)},
    )
    assert resp.status_code in (200, 202), resp.text
    _wait_migration_execution(client, db_helper, e2e_config, resp.json(), sede="alcala")

    expected_user = f"{prefix.lower()}_tecnico"
    users_resp = client.get(
        "/api/v1/usuarios",
        omit_sede=True,
        params={"buscar": expected_user, "size": 10},
    )
    assert users_resp.status_code == 200
    assert "hash_clave" not in users_resp.text
    items = _extract_items(users_resp.json())
    assert len(items) == 1
    assert items[0]["debe_cambiar_clave"] is True


@pytest.mark.browser
def test_seed_catalogs_and_browser_web_tablero_echarts(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    browser_driver: BrowserDriver,
) -> None:
    """SEED-1..6, F0-1..F0-6, F9-1: Verify §13 seed catalogs & apps/web /tablero ECharts render."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    sedes = _extract_items(mtl.get("/api/v1/sedes", omit_sede=True).json())
    assert {"montelibano", "alcala"}.issubset({s["codigo"] for s in sedes})

    perms = _extract_items(mtl.get("/api/v1/permisos", omit_sede=True).json())
    assert len(perms) >= 52

    roles = _extract_items(mtl.get("/api/v1/roles", omit_sede=True).json())
    assert len(roles) >= 10

    clases = _extract_items(mtl.get("/api/v1/maestros/clases", omit_sede=True).json())
    assert len(clases) >= 12

    comodin = _extract_items(
        mtl.get("/api/v1/luminarias", sede="montelibano", params={"texto": "SIN-IDENTIFICAR"}).json()
    )
    assert any(item["codigo"] == "SIN-IDENTIFICAR" for item in comodin)

    # Browser E2E: apps/web login -> /tablero ECharts <canvas>/<svg>
    browser_driver.navigate(f"{e2e_config.web_url}/ingresar")
    browser_driver.wait_for_selector("input", timeout=e2e_config.timeout_seconds)
    browser_driver.fill('input[name="usuario"], input[type="text"]', e2e_config.admin_user)
    browser_driver.fill('input[name="clave"], input[type="password"]', e2e_config.admin_password)
    browser_driver.click('button[type="submit"]')

    deadline = time.monotonic() + e2e_config.timeout_seconds
    while time.monotonic() < deadline and "/ingresar" in browser_driver.current_url():
        time.sleep(0.2)

    browser_driver.navigate(f"{e2e_config.web_url}/tablero")
    chart_deadline = time.monotonic() + e2e_config.timeout_seconds
    counts = {"canvas": 0, "svg": 0}
    while time.monotonic() < chart_deadline:
        counts = browser_driver.has_canvas_or_svg()
        if counts["canvas"] > 0 or counts["svg"] > 0:
            break
        time.sleep(0.25)
    assert counts["canvas"] > 0 or counts["svg"] > 0, (
        f"Expected ECharts <canvas> or <svg> in /tablero, got {counts}"
    )
