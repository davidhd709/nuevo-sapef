"""Tier 2 boundary, error & isolation E2E tests for EP-09 Tablero & IMP-1..IMP-6."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fixtures import (
    XlsxSheet,
    build_imp1_luminarias_xlsx,
    build_imp2_pqrs_xlsx,
    build_imp3_ordenes_4files,
    build_opainn_parquet_package,
    build_xlsx_bytes,
    generate_coordinates,
)
from harness.client import SapefClient, assert_problem_json
from harness.config import E2EConfig
from harness.db import DbHelper

pytestmark = [pytest.mark.tier2, pytest.mark.isolation]

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _admin_client(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    sede: str = "montelibano",
) -> SapefClient:
    assert e2e_config.admin_password, (
        "SAPEF_E2E_ADMIN_PASSWORD must be configured for live Tier 2 E2E tests"
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
        for key in ("items", "resultados", "datos", "luminarias", "ordenes", "materiales"):
            val = payload.get(key)
            if isinstance(val, list):
                return list(val)
    raise AssertionError(f"Unexpected list/paginated payload: {payload!r}")


def _unique_secret() -> str:
    return f"SapefT2!{uuid.uuid4().hex[:10]}9Z"


def _wait_migration_terminal(
    client: SapefClient,
    db_helper: DbHelper,
    e2e_config: E2EConfig,
    resp_json: dict[str, Any],
    *,
    sede: str,
) -> dict[str, Any]:
    job_id = resp_json.get("tarea_id") or resp_json.get("tareaId")
    if isinstance(job_id, int):
        db_helper.wait_for_procrastinate_job(
            job_id,
            timeout=e2e_config.timeout_seconds,
            allow_failed=True,
        )

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
            if estado in {
                "completado",
                "finalizado",
                "succeeded",
                "ok",
                "completado_con_errores",
                "con_errores",
                "error",
                "fallido",
                "failed",
                "rechazado",
            }:
                return last
        elif poll.status_code == 404:
            return last
        time.sleep(0.25)
    return last


def _create_scoped_user(
    admin: SapefClient,
    *,
    run_id: str,
    permisos: list[str],
    sede_codigos: list[str],
) -> tuple[int, str, str]:
    sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    sede_ids = [next(s["id"] for s in sedes if s["codigo"] == c) for c in sede_codigos]
    suffix = uuid.uuid4().hex[:6].upper()
    role_resp = admin.post(
        "/api/v1/roles",
        omit_sede=True,
        json_body={
            "codigo": f"{run_id}_TAB_{suffix}",
            "nombre": f"Rol Tablero {suffix}",
            "permisos": permisos,
        },
    )
    assert role_resp.status_code == 201, role_resp.text
    role_id = role_resp.json()["id"]

    username = f"{run_id.lower()}_tab_{suffix.lower()}"
    pw = _unique_secret()
    u_resp = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": username,
            "nombre_completo": f"Usuario Tablero {suffix}",
            "identificacion": f"33{int(suffix, 16) % 10000000:07d}",
            "correo": f"{username}@example.test",
            "clave": pw,
            "rol_id": role_id,
            "sedes": sede_ids,
            "activo": True,
            "debe_cambiar_clave": False,
        },
    )
    assert u_resp.status_code == 201, u_resp.text
    return int(u_resp.json()["id"]), username, pw


def _total_luminaires_from_tablero(body: dict[str, Any]) -> int:
    act = body.get("activos", body)
    for key in ("total_luminarias", "total", "luminarias_total"):
        if key in act and isinstance(act[key], (int, float)):
            return int(act[key])
    por_estado = body.get("operacion", body).get("luminarias_por_estado")
    if isinstance(por_estado, list):
        return sum(int(item.get("cantidad", item.get("total", 0))) for item in por_estado)
    if isinstance(por_estado, dict):
        return sum(int(v) for v in por_estado.values())
    raise AssertionError(f"Could not extract luminaire total from tablero payload: {body!r}")


def test_tablero_todas_requires_consolidado_permission_403(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """F1-5, F9-1: Querying ?sede=todas without tablero.consolidado.ver returns HTTP 403."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    uid, username, pw = _create_scoped_user(
        admin,
        run_id=run_id,
        permisos=["tablero.ver"],
        sede_codigos=["montelibano", "alcala"],
    )
    try:
        user = auth_session_factory(username, pw, sede="montelibano")
        ok_single = user.get("/api/v1/tablero/resumen", sede="montelibano")
        assert ok_single.status_code == 200, ok_single.text

        denied = user.get("/api/v1/tablero/resumen", params={"sede": "todas"}, omit_sede=True)
        assert_problem_json(denied, expected_status=403)
    finally:
        admin.patch(f"/api/v1/usuarios/{uid}", omit_sede=True, json_body={"activo": False})


def test_tablero_unassigned_sede_returns_403(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """F1-6, F9-1: Requesting an unassigned sede in /tablero returns HTTP 403."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    uid, username, pw = _create_scoped_user(
        admin,
        run_id=run_id,
        permisos=["tablero.ver"],
        sede_codigos=["montelibano"],
    )
    try:
        user = auth_session_factory(username, pw, sede="montelibano")
        by_header = user.get("/api/v1/tablero/resumen", sede="alcala")
        assert_problem_json(by_header, expected_status=403)

        by_query = user.get(
            "/api/v1/tablero/resumen",
            params={"sede": "alcala"},
            omit_sede=True,
        )
        assert_problem_json(by_query, expected_status=403)
    finally:
        admin.patch(f"/api/v1/usuarios/{uid}", omit_sede=True, json_body={"activo": False})


def test_tablero_consolidado_scoped_to_user_assigned_sedes_never_leaks_alcala(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """F1-6, F9-1: User with tablero.consolidado.ver assigned only to montelibano never sees alcala."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="alcala")

    # Ensure Alcalá has at least 1 luminaire and recalculated resumen_*
    alc_barrios = _extract_items(admin.get("/api/v1/barrios", sede="alcala").json())
    estados = _extract_items(admin.get("/api/v1/estados", omit_sede=True, params={"proceso": "luminaria"}).json())
    est_121 = next(e["id"] for e in estados if str(e["codigo"]) == "121")
    tec_led = _extract_items(admin.get("/api/v1/maestros/LUMINARIA_TECNOLOGIA", omit_sede=True).json())[0]["id"]
    pot_id = _extract_items(admin.get("/api/v1/maestros/LUMINARIA_POTENCIA", omit_sede=True).json())[0]["id"]
    lat, lng = generate_coordinates("alcala", 1, seed=909)[0]
    lum_resp = admin.post(
        "/api/v1/luminarias",
        sede="alcala",
        json_body={
            "codigo": f"{run_id}-ALC-TAB-{uuid.uuid4().hex[:5].upper()}",
            "barrio_id": alc_barrios[0]["id"],
            "latitud": lat,
            "longitud": lng,
            "estado_id": est_121,
            "tecnologia_id": tec_led,
            "potencia_id": pot_id,
        },
    )
    assert lum_resp.status_code == 201, lum_resp.text

    recalc = admin.post("/api/v1/tablero/recalcular", omit_sede=True, json_body={})
    assert recalc.status_code == 202, recalc.text
    job_id = recalc.json().get("tareaId") or recalc.json().get("tarea_id") or recalc.json().get("id")
    if isinstance(job_id, int):
        db_helper.wait_for_procrastinate_job(job_id, timeout=e2e_config.timeout_seconds)

    uid, username, pw = _create_scoped_user(
        admin,
        run_id=run_id,
        permisos=["tablero.ver", "tablero.consolidado.ver"],
        sede_codigos=["montelibano"],
    )
    try:
        mtl_consolidado = auth_session_factory(username, pw, sede="montelibano")
        scoped_todas = mtl_consolidado.get(
            "/api/v1/tablero/resumen",
            params={"sede": "todas"},
            omit_sede=True,
        )
        assert scoped_todas.status_code == 200, scoped_todas.text
        scoped_body = scoped_todas.json()
        assert "alcala" not in json.dumps(scoped_body.get("sedes_incluidas", [])).lower()

        scoped_mtl = mtl_consolidado.get("/api/v1/tablero/resumen", sede="montelibano").json()
        admin_todas = admin.get("/api/v1/tablero/resumen", params={"sede": "todas"}, omit_sede=True).json()

        scoped_total = _total_luminaires_from_tablero(scoped_body)
        mtl_only_total = _total_luminaires_from_tablero(scoped_mtl)
        all_sedes_total = _total_luminaires_from_tablero(admin_todas)

        assert scoped_total == mtl_only_total
        assert scoped_total < all_sedes_total
    finally:
        admin.patch(f"/api/v1/usuarios/{uid}", omit_sede=True, json_body={"activo": False})


def test_tablero_commercial_section_returns_sin_cortes_cargados_when_zero_cuts(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """F9-2: Dashboard commercial section returns 'sin_cortes_cargados' cleanly when zero cuts exist."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    suffix = uuid.uuid4().hex[:6].lower()
    sede_code = f"{run_id.lower()}_empty_{suffix}"

    create_sede = admin.post(
        "/api/v1/sedes",
        omit_sede=True,
        json_body={
            "codigo": sede_code,
            "nombre": f"Sede Sin Cortes {suffix}",
            "municipio": f"Municipio {suffix}",
            "departamento": "Córdoba",
            "activa": True,
        },
    )
    assert create_sede.status_code == 201, create_sede.text
    sede_id = create_sede.json()["id"]

    put_com = admin.put(
        f"/api/v1/sedes/{sede_id}/comercializadores",
        omit_sede=True,
        json_body=[{"comercializador_codigo": "afinia", "activo": True, "desde": "2026-01-01"}],
    )
    assert put_com.status_code == 200, put_com.text

    uid, username, pw = _create_scoped_user(
        admin,
        run_id=run_id,
        permisos=["tablero.ver"],
        sede_codigos=[sede_code],
    )
    try:
        user = auth_session_factory(username, pw, sede=sede_code)
        res = user.get("/api/v1/tablero/resumen", sede=sede_code)
        assert res.status_code == 200, res.text
        comercial_sec = res.json().get("comercial", {})
        assert "sin_cortes_cargados" in json.dumps(comercial_sec)
    finally:
        admin.patch(f"/api/v1/usuarios/{uid}", omit_sede=True, json_body={"activo": False})


def test_imp1_converts_1900_dates_to_null_and_flags_atypical_powers_over_1000w(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """IMP-1: 01/01/1900 dates convert to null (never 1900-01-01); powers >1000W (1947W) flagged."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    barrios = _extract_items(mtl.get("/api/v1/barrios", sede="montelibano").json())
    prefix = f"{run_id}-T2I1-{uuid.uuid4().hex[:4].upper()}"

    xlsx_bytes = build_imp1_luminarias_xlsx(
        prefix,
        sede_codigo="montelibano",
        count=5,
        include_quirks=True,
        barrio_names=[barrios[0]["nombre"]],
    )
    resp = mtl.post(
        "/api/v1/migracion/luminarias",
        sede="montelibano",
        files={"archivo": (f"imp1_{prefix}.xlsx", xlsx_bytes, _XLSX_MIME)},
    )
    assert resp.status_code in (200, 202), resp.text
    res = _wait_migration_terminal(mtl, db_helper, e2e_config, resp.json(), sede="montelibano")

    # Atypical power 1947W (>1000W) must be flagged in warnings/review report
    res_dump = json.dumps(res).lower()
    assert any(k in res_dump for k in ("1947", "atipic", "potencia", "revision")), (
        f"Expected atypical power >1000W review flag in IMP-1 result: {res}"
    )

    lum1 = _extract_items(
        mtl.get(
            "/api/v1/luminarias",
            sede="montelibano",
            params={"texto": f"{prefix}-LUM-0001", "size": 10},
        ).json()
    )[0]
    assert lum1.get("fecha_instalacion") is None
    assert lum1.get("fecha_mision") is None
    assert lum1.get("fecha_baja") is None
    assert "1900-01-01" not in json.dumps(lum1)


def test_imp1_reports_invalid_rows_without_aborting_valid_rows_or_duplicating_codigo(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """IMP-1: Invalid rows reported without aborting valid rows or duplicating (sede_id, codigo)."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    barrios = _extract_items(mtl.get("/api/v1/barrios", sede="montelibano").json())
    valid_barrio = barrios[0]["nombre"]
    prefix = f"{run_id}-T2I1E-{uuid.uuid4().hex[:4].upper()}"
    lat, lng = generate_coordinates("montelibano", 1, seed=55)[0]

    rows = [
        [
            "codigo",
            "barrio",
            "latitud",
            "longitud",
            "estado",
            "marca",
            "tecnologia",
            "potencia",
            "fecha_instalacion",
        ],
        [f"{prefix}-OK-1", valid_barrio, lat, lng, "121", "PHILIPS", "LED", 70, dt.date(2025, 4, 1)],
        [f"{prefix}-BAD-1", "BARRIO_INEXISTENTE_XYZ", 999.0, lng, "121", "PHILIPS", "LED", 70, dt.date(2025, 4, 1)],
    ]
    xlsx_bytes = build_xlsx_bytes([XlsxSheet("Luminarias", rows)])

    r1 = mtl.post(
        "/api/v1/migracion/luminarias",
        sede="montelibano",
        files={"archivo": (f"imp1_mix_{prefix}.xlsx", xlsx_bytes, _XLSX_MIME)},
    )
    assert r1.status_code in (200, 202), r1.text
    res1 = _wait_migration_terminal(mtl, db_helper, e2e_config, r1.json(), sede="montelibano")
    assert res1.get("errores"), f"Expected invalid row error detail in IMP-1: {res1}"

    ok_list = _extract_items(
        mtl.get("/api/v1/luminarias", sede="montelibano", params={"texto": f"{prefix}-OK-1"}).json()
    )
    assert len(ok_list) == 1

    # Re-run same file -> idempotent, zero duplicate (sede_id, codigo)
    r2 = mtl.post(
        "/api/v1/migracion/luminarias",
        sede="montelibano",
        files={"archivo": (f"imp1_mix_{prefix}.xlsx", xlsx_bytes, _XLSX_MIME)},
    )
    assert r2.status_code in (200, 202)
    _wait_migration_terminal(mtl, db_helper, e2e_config, r2.json(), sede="montelibano")

    ok_after = _extract_items(
        mtl.get("/api/v1/luminarias", sede="montelibano", params={"texto": f"{prefix}-OK-1"}).json()
    )
    assert len(ok_after) == 1


def test_imp2_reports_invalid_pqrs_rows_and_preserves_valid_records(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """IMP-2: PQRS importer reports invalid rows while preserving valid PQRS records."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    barrios = _extract_items(mtl.get("/api/v1/barrios", sede="montelibano").json())
    prefix = f"{run_id}-T2I2-{uuid.uuid4().hex[:4].upper()}"

    lum_xlsx = build_imp1_luminarias_xlsx(
        prefix,
        sede_codigo="montelibano",
        count=2,
        include_quirks=False,
        barrio_names=[barrios[0]["nombre"]],
    )
    r_lum = mtl.post(
        "/api/v1/migracion/luminarias",
        sede="montelibano",
        files={"archivo": (f"imp1_{prefix}.xlsx", lum_xlsx, _XLSX_MIME)},
    )
    assert r_lum.status_code in (200, 202)
    _wait_migration_terminal(mtl, db_helper, e2e_config, r_lum.json(), sede="montelibano")

    # Valid PQRS + row referencing non-existent luminaire
    bad_pqrs = build_xlsx_bytes(
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
                        "luminaria_codigo",
                        "reparada",
                        "observacion",
                    ],
                    [
                        f"{prefix}-PQR-OK",
                        dt.date(2026, 6, 1),
                        "WHATSAPP",
                        1,
                        "301",
                        f"CC-{prefix}-1",
                        "Ciudadano Válido",
                        f"{prefix}-LUM-0001",
                        False,
                        "Falla en luminaria",
                    ],
                    [
                        f"{prefix}-PQR-BAD",
                        dt.date(2026, 6, 2),
                        "CANAL_INVALIDO",
                        99,
                        "301",
                        f"CC-{prefix}-2",
                        "Ciudadano Inválido",
                        f"{prefix}-LUM-NO-EXISTE",
                        False,
                        "Registro inválido",
                    ],
                ],
            )
        ]
    )
    r_pqr = mtl.post(
        "/api/v1/migracion/pqrs",
        sede="montelibano",
        files={"archivo": (f"imp2_bad_{prefix}.xlsx", bad_pqrs, _XLSX_MIME)},
    )
    assert r_pqr.status_code in (200, 202), r_pqr.text
    res = _wait_migration_terminal(mtl, db_helper, e2e_config, r_pqr.json(), sede="montelibano")
    assert res.get("errores"), f"Expected invalid PQRS row error detail: {res}"

    cit = _extract_items(
        mtl.get("/api/v1/ciudadanos", sede="montelibano", params={"buscar": f"CC-{prefix}-1"}).json()
    )
    assert len(cit) == 1

    # Confirm valid wildcard PQRS still works cleanly
    wild_xlsx = build_imp2_pqrs_xlsx(prefix, [f"{prefix}-LUM-0002"], include_wildcard=True)
    r_w = mtl.post(
        "/api/v1/migracion/pqrs",
        sede="montelibano",
        files={"archivo": (f"imp2_ok_{prefix}.xlsx", wild_xlsx, _XLSX_MIME)},
    )
    assert r_w.status_code in (200, 202)
    _wait_migration_terminal(mtl, db_helper, e2e_config, r_w.json(), sede="montelibano")


def test_imp3_reports_orphan_work_order_luminaire_in_detail(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """IMP-3: Work-orders importer reports orphan luminaire references in detail without crashing."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    barrios = _extract_items(mtl.get("/api/v1/barrios", sede="montelibano").json())
    prefix = f"{run_id}-T2I3-{uuid.uuid4().hex[:4].upper()}"

    lum_xlsx = build_imp1_luminarias_xlsx(
        prefix,
        sede_codigo="montelibano",
        count=4,
        include_quirks=False,
        barrio_names=[barrios[0]["nombre"]],
    )
    r_lum = mtl.post(
        "/api/v1/migracion/luminarias",
        sede="montelibano",
        files={"archivo": (f"imp1_{prefix}.xlsx", lum_xlsx, _XLSX_MIME)},
    )
    assert r_lum.status_code in (200, 202)
    _wait_migration_terminal(mtl, db_helper, e2e_config, r_lum.json(), sede="montelibano")

    codes = [f"{prefix}-LUM-{i:04d}" for i in range(1, 5)]
    four_files = build_imp3_ordenes_4files(prefix, codes, include_orphan_row=True)
    resp = mtl.post(
        "/api/v1/migracion/ordenes",
        sede="montelibano",
        files=[(name.split(".")[0], name, payload, _XLSX_MIME) for name, payload in four_files.items()],
    )
    assert resp.status_code in (200, 202), resp.text
    res = _wait_migration_terminal(mtl, db_helper, e2e_config, resp.json(), sede="montelibano")

    detail_str = json.dumps(res).lower()
    assert f"{prefix.lower()}-lum-inexistente" in detail_str or "huerfan" in detail_str, (
        f"Expected orphan luminaire report in IMP-3 result: {res}"
    )


def test_imp4_rejects_negative_inventory_balance_cleanly(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """IMP-4: Inventory importer rejects negative stock/kardex balance cleanly without negative DB state."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    prefix = f"{run_id}-T2I4-{uuid.uuid4().hex[:4].upper()}"

    neg_inv = build_xlsx_bytes(
        [
            XlsxSheet(
                "Materiales",
                [
                    ["codigo", "categoria", "descripcion", "unidad", "existencias", "existencias_minimas"],
                    [f"{prefix}-MAT-NEG", "ELECTRICO", "Material Saldo Negativo", "UND", 5, 2],
                ],
            ),
            XlsxSheet(
                "Movimientos",
                [
                    ["material_codigo", "tipo", "cantidad", "descripcion", "uuid_origen"],
                    [f"{prefix}-MAT-NEG", "SALIDA", 50, "Salida excede saldo", f"{prefix}-KDX-NEG"],
                ],
            ),
        ]
    )
    resp = mtl.post(
        "/api/v1/migracion/inventario",
        sede="montelibano",
        files={"archivo": (f"imp4_neg_{prefix}.xlsx", neg_inv, _XLSX_MIME)},
    )
    if resp.status_code in (409, 422):
        assert_problem_json(resp, expected_status=(409, 422))
    else:
        assert resp.status_code in (200, 202), resp.text
        res = _wait_migration_terminal(mtl, db_helper, e2e_config, resp.json(), sede="montelibano")
        assert res.get("errores") or str(res.get("estado", "")).lower() in {
            "error",
            "fallido",
            "completado_con_errores",
            "rechazado",
        }, f"Expected negative inventory balance rejection in {res}"

    mats = _extract_items(
        mtl.get("/api/v1/materiales", sede="montelibano", params={"buscar": f"{prefix}-MAT-NEG"}).json()
    )
    for m in mats:
        assert float(m["existencias"]) >= 0.0


def test_imp5_rejects_corrupted_sha256_manifest_without_publishing_cut(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """IMP-5: OPainn Parquet importer rejects corrupted SHA-256 in manifest.json without publishing."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    pkg_dir = build_opainn_parquet_package(
        e2e_config.data_dir / "imp5_corrupt_sha",
        sede_codigo="montelibano",
        comercializador_codigo="afinia",
        periodo="202301",
        corrupt_hash=True,
    )
    resp = mtl.post(
        "/api/v1/migracion/comercial/opainn",
        sede="montelibano",
        json_body={
            "ruta_almacen": str(pkg_dir),
            "comercializador_codigo": "afinia",
            "periodos": ["202301"],
        },
    )
    if resp.status_code in (400, 422):
        assert_problem_json(resp, expected_status=(400, 422))
    else:
        assert resp.status_code in (200, 202), resp.text
        res = _wait_migration_terminal(mtl, db_helper, e2e_config, resp.json(), sede="montelibano")
        estado = str(res.get("estado", "")).lower()
        assert estado in {"error", "fallido", "failed", "rechazado"} or res.get("errores")

    cortes = _extract_items(mtl.get("/api/v1/comercial/afinia/cortes", sede="montelibano").json())
    assert all(c.get("periodo") != "202301" for c in cortes)


def test_imp5_rejects_incompatible_parquet_schema_without_publishing_cut(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """IMP-5: OPainn Parquet importer rejects incompatible Parquet schema even with valid SHA-256."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    pkg_dir = Path(e2e_config.data_dir) / "imp5_bad_schema" / "montelibano" / "afinia" / "202302"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    pq_path = pkg_dir / "facturacion.parquet"

    try:
        import pyarrow as pa  # type: ignore[import-not-found]
        import pyarrow.parquet as pq  # type: ignore[import-not-found]

        pq.write_table(pa.Table.from_pylist([{"columna_incompatible": "valor_erroneo"}]), pq_path)
    except ImportError:
        pq_path.write_bytes(b"NOT_A_VALID_PARQUET_SCHEMA_PAYLOAD")

    digest = hashlib.sha256(pq_path.read_bytes()).hexdigest()
    manifest = {
        "sede_codigo": "montelibano",
        "comercializador_codigo": "afinia",
        "periodo": "202302",
        "version_adaptador": "e2e-bad-schema",
        "fecha_publicacion_iso": dt.datetime.now(dt.UTC).isoformat(),
        "completo": False,
        "publicable": True,
        "familias": {
            "facturacion": {
                "archivo_parquet": "facturacion.parquet",
                "filas": 1,
                "sha256_parquet": digest,
            }
        },
        "advertencias": [],
    }
    (pkg_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    resp = mtl.post(
        "/api/v1/migracion/comercial/opainn",
        sede="montelibano",
        json_body={
            "ruta_almacen": str(pkg_dir),
            "comercializador_codigo": "afinia",
            "periodos": ["202302"],
        },
    )
    if resp.status_code in (400, 422):
        assert_problem_json(resp, expected_status=(400, 422))
    else:
        assert resp.status_code in (200, 202), resp.text
        res = _wait_migration_terminal(mtl, db_helper, e2e_config, resp.json(), sede="montelibano")
        estado = str(res.get("estado", "")).lower()
        assert estado in {"error", "fallido", "failed", "rechazado"} or res.get("errores")

    cortes = _extract_items(mtl.get("/api/v1/comercial/afinia/cortes", sede="montelibano").json())
    assert all(c.get("periodo") != "202302" for c in cortes)


def test_imp6_never_imports_or_exposes_passwords_and_forces_debe_cambiar_clave(
    auth_session_factory: Callable[..., SapefClient],
    inprocess_or_live_client: SapefClient,
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """IMP-6: Base & users importer ignores/never exposes plaintext passwords & sets debe_cambiar_clave=true."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")
    prefix = f"{run_id}-T2I6-{uuid.uuid4().hex[:4].upper()}"
    username = f"{prefix.lower()}_sapef_usr"
    decoy_pw = "PlaintextSapefPassword999!"

    # Include an extra decoy 'clave' column in the Excel to verify IMP-6 NEVER imports it
    imp6_bytes = build_xlsx_bytes(
        [
            XlsxSheet(
                "ZonasBarrios",
                [
                    ["sede_codigo", "zona", "barrio"],
                    ["alcala", f"{prefix}-ZONA", f"{prefix}-BARRIO"],
                ],
            ),
            XlsxSheet(
                "Usuarios",
                [
                    [
                        "nombre_usuario",
                        "nombre_completo",
                        "identificacion",
                        "correo",
                        "rol_codigo",
                        "sedes",
                        "clave",
                    ],
                    [
                        username,
                        "Usuario Migrado SAPEF",
                        f"22{abs(hash(prefix)) % 1000000:06d}",
                        f"{username}@example.test",
                        "TECNICO",
                        "alcala",
                        decoy_pw,
                    ],
                ],
            ),
        ]
    )

    resp = alc.post(
        "/api/v1/migracion/base",
        sede="alcala",
        files={"archivo": (f"imp6_{prefix}.xlsx", imp6_bytes, _XLSX_MIME)},
    )
    assert resp.status_code in (200, 202), resp.text
    assert decoy_pw not in resp.text
    assert "hash_clave" not in resp.text.lower()
    _wait_migration_terminal(alc, db_helper, e2e_config, resp.json(), sede="alcala")

    users_resp = alc.get(
        "/api/v1/usuarios",
        omit_sede=True,
        params={"buscar": username, "size": 10},
    )
    assert users_resp.status_code == 200
    assert decoy_pw not in users_resp.text
    assert "hash_clave" not in users_resp.text.lower()
    users = _extract_items(users_resp.json())
    assert len(users) == 1
    assert users[0]["debe_cambiar_clave"] is True

    # Decoy SAPEF plaintext password must NOT authenticate
    login_attempt = inprocess_or_live_client.login(username, decoy_pw, expect_ok=False)
    assert_problem_json(login_attempt, expected_status=401)
