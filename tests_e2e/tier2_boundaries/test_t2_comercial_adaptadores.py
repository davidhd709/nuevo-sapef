"""Tier 2 boundary, error & security E2E tests for EP-08 Comercial Adapters & Upload Limits."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import uuid
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fixtures import (
    SyntheticFile,
    XlsxSheet,
    build_afinia_cut_files,
    build_afinia_extra_col_xlsx,
    build_afinia_formula_xlsx,
    build_celsia_invalid_footer_xlsx,
    build_celsia_mismatched_period_xlsx,
    build_celsia_xlsx,
    build_vatia_invalid_na_xlsx,
    build_vatia_xlsx,
    build_xlsx_bytes,
    make_forged_file,
    make_oversized_payload,
)
from harness.client import SapefClient, assert_problem_json
from harness.config import E2EConfig
from harness.db import DbHelper
from oracles import q2

pytestmark = [pytest.mark.tier2, pytest.mark.commercial]

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
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [dict(item) for item in payload["items"]]
    raise AssertionError(f"Unexpected list/paginated payload: {payload!r}")


def _unique_secret() -> str:
    return f"SapefT2!{uuid.uuid4().hex[:10]}9Z"


def _poll_cargue_terminal(
    client: SapefClient,
    db_helper: DbHelper,
    e2e_config: E2EConfig,
    *,
    sede: str,
    operador: str,
    cargue_id: Any,
    job_id: Any = None,
) -> dict[str, Any]:
    if isinstance(job_id, int):
        db_helper.wait_for_procrastinate_job(
            job_id,
            timeout=e2e_config.timeout_seconds,
            allow_failed=True,
        )

    deadline = time.monotonic() + e2e_config.timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/comercial/{operador}/cargues/{cargue_id}", sede=sede)
        if resp.status_code == 404:
            resp = client.get(f"/api/v1/comercial/cargues/{cargue_id}", sede=sede)
        assert resp.status_code == 200, resp.text
        last = resp.json()
        estado = str(last.get("estado", "")).lower()
        if estado in {
            "publicado",
            "completado",
            "procesado",
            "listo",
            "error",
            "con_errores",
            "fallido",
            "rechazado",
            "no_publicable",
        }:
            return last
        time.sleep(0.25)
    raise TimeoutError(f"Cargue {cargue_id} did not reach terminal state: {last}")


def _upload_expect_rejected(
    client: SapefClient,
    db_helper: DbHelper,
    e2e_config: E2EConfig,
    *,
    sede: str,
    operador: str,
    periodo: str,
    files: list[SyntheticFile],
) -> dict[str, Any]:
    resp = client.post(
        f"/api/v1/comercial/{operador}/cargues",
        sede=sede,
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": periodo},
        files=[("files", f.filename, f.content, f.content_type) for f in files],
    )
    if resp.status_code in (400, 413, 415, 422):
        return assert_problem_json(resp, expected_status=(400, 413, 415, 422))

    assert resp.status_code == 202, f"Expected rejection or 202 async validation, got {resp.text}"
    body = resp.json()
    cargue_id = body.get("cargue_id") or body.get("cargueId") or body.get("id")
    job_id = body.get("tarea_id") or body.get("tareaId")
    detail = _poll_cargue_terminal(
        client,
        db_helper,
        e2e_config,
        sede=sede,
        operador=operador,
        cargue_id=cargue_id,
        job_id=job_id,
    )
    estado = str(detail.get("estado", "")).lower()
    assert estado in {"error", "con_errores", "fallido", "rechazado"}, (
        f"Expected rejected cargue state, got {estado!r}: {detail}"
    )
    assert detail.get("errores"), f"Expected detailed errors on rejected cargue: {detail}"
    return detail


def _locate_warehouse_dir(
    e2e_config: E2EConfig,
    sede: str,
    operador: str,
    periodo: str,
) -> Path | None:
    for root in (e2e_config.data_dir / "comercial", Path("/data/comercial")):
        candidate = root / sede / operador / periodo
        if candidate.exists():
            return candidate
    return None


def test_comercial_upload_rejects_over_64_files(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
) -> None:
    """F8-1: Uploading > 64 files in one commercial cargue request is rejected (413/422)."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    many_files = [
        (
            "files",
            f"FACT_SV500_ZONA_{i}_20260815.txt",
            b"",
            "text/plain",
        )
        for i in range(65)
    ]
    resp = client.post(
        "/api/v1/comercial/afinia/cargues",
        sede="montelibano",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202608"},
        files=many_files,
    )
    assert_problem_json(resp, expected_status=(413, 422))


def test_comercial_upload_rejects_oversized_file_over_256mib(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
) -> None:
    """F8-1: Commercial upload > 256 MiB per file is rejected with HTTP 413 RFC 9457."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    oversized = make_oversized_payload(256 * 1024 * 1024 + 1024, magic=b"PK\x03\x04")
    try:
        resp = client.post(
            "/api/v1/comercial/afinia/cargues",
            sede="montelibano",
            idempotency_key=str(uuid.uuid4()),
            data={"periodo": "202608"},
            files=[("files", "FACTURACION_MONTELIBANO_AGOSTO_2026.xlsx", oversized, _XLSX_MIME)],
        )
    finally:
        del oversized
    assert_problem_json(resp, expected_status=413)


def test_comercial_upload_rejects_invalid_extension_and_forged_magic_mime_415(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
) -> None:
    """F8-1: Invalid extension (.exe/.sh) and forged magic-bytes MIME return HTTP 415."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    bad_ext = client.post(
        "/api/v1/comercial/afinia/cargues",
        sede="montelibano",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202608"},
        files=[("files", "payload_malicioso.exe", b"MZ\x90\x00" + b"\x00" * 32, "application/octet-stream")],
    )
    assert_problem_json(bad_ext, expected_status=415)

    forged_name, forged_bytes, forged_mime = make_forged_file(
        "FACTURACION_MONTELIBANO_AGOSTO_2026.xlsx",
        actual_kind="exe",
        claimed_mime=_XLSX_MIME,
    )
    forged_resp = client.post(
        "/api/v1/comercial/afinia/cargues",
        sede="montelibano",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202608"},
        files=[("files", forged_name, forged_bytes, forged_mime)],
    )
    assert_problem_json(forged_resp, expected_status=415)


def test_comercial_upload_idempotency_key_reuse_and_conflict(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-1: Idempotency-Key replay returns same cargue; reuse with different payload conflicts."""
    client = _admin_client(auth_session_factory, e2e_config, sede="alcala")
    idem_key = str(uuid.uuid4())
    vatia_a = build_vatia_xlsx("202608", include_negative_net=False)

    first = client.post(
        "/api/v1/comercial/vatia/cargues",
        sede="alcala",
        idempotency_key=idem_key,
        data={"periodo": "202608"},
        files=[("files", vatia_a.filename, vatia_a.content, vatia_a.content_type)],
    )
    assert first.status_code == 202, first.text
    first_id = first.json().get("cargue_id") or first.json().get("cargueId") or first.json().get("id")
    assert first_id is not None

    # Same key + identical payload -> same cargue returned idempotently
    replay = client.post(
        "/api/v1/comercial/vatia/cargues",
        sede="alcala",
        idempotency_key=idem_key,
        data={"periodo": "202608"},
        files=[("files", vatia_a.filename, vatia_a.content, vatia_a.content_type)],
    )
    assert replay.status_code in (200, 202), replay.text
    replay_id = (
        replay.json().get("cargue_id") or replay.json().get("cargueId") or replay.json().get("id")
    )
    assert replay_id == first_id

    _poll_cargue_terminal(
        client,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="vatia",
        cargue_id=first_id,
        job_id=first.json().get("tarea_id") or first.json().get("tareaId"),
    )

    # Same key + different payload -> 409 or 422 conflict
    vatia_b = build_vatia_xlsx("202609", include_negative_net=True)
    conflict = client.post(
        "/api/v1/comercial/vatia/cargues",
        sede="alcala",
        idempotency_key=idem_key,
        data={"periodo": "202609"},
        files=[("files", vatia_b.filename, vatia_b.content, vatia_b.content_type)],
    )
    assert_problem_json(conflict, expected_status=(409, 422))


def test_comercial_missing_x_sede_400_and_cross_sede_operator_isolation(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
) -> None:
    """F1-6, F8-1: Missing X-Sede returns 400; mismatched operator/sede rejected cleanly."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    missing_get = client.get("/api/v1/comercial/afinia/cortes", omit_sede=True)
    assert_problem_json(missing_get, expected_status=400)

    vatia_f = build_vatia_xlsx("202608")
    missing_post = client.post(
        "/api/v1/comercial/vatia/cargues",
        omit_sede=True,
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202608"},
        files=[("files", vatia_f.filename, vatia_f.content, vatia_f.content_type)],
    )
    assert_problem_json(missing_post, expected_status=400)

    # afinia is NOT enabled on alcala; celsia/vatia are NOT enabled on montelibano
    afinia_on_alcala = client.get("/api/v1/comercial/afinia/cortes", sede="alcala")
    assert_problem_json(afinia_on_alcala, expected_status=(403, 404, 422))

    celsia_on_mtl = client.get("/api/v1/comercial/celsia/cortes", sede="montelibano")
    assert_problem_json(celsia_on_mtl, expected_status=(403, 404, 422))

    vatia_on_mtl = client.post(
        "/api/v1/comercial/vatia/cargues",
        sede="montelibano",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202608"},
        files=[("files", vatia_f.filename, vatia_f.content, vatia_f.content_type)],
    )
    assert_problem_json(vatia_on_mtl, expected_status=(403, 404, 422))


def test_comercial_cross_sede_cargue_lookup_returns_404_and_unassigned_user_403(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """F1-6: Cross-sede GET /comercial/cargues/{id} returns 404; unassigned sede returns 403."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    files = build_afinia_cut_files(periodo="202608", format_mode="txt_z")
    up = admin.post(
        "/api/v1/comercial/afinia/cargues",
        sede="montelibano",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202608"},
        files=[("files", f.filename, f.content, f.content_type) for f in files.values()],
    )
    assert up.status_code == 202, up.text
    cargue_id = up.json().get("cargue_id") or up.json().get("cargueId") or up.json().get("id")
    _poll_cargue_terminal(
        admin,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        cargue_id=cargue_id,
        job_id=up.json().get("tarea_id") or up.json().get("tareaId"),
    )

    cross_sede = admin.get(f"/api/v1/comercial/cargues/{cargue_id}", sede="alcala")
    assert_problem_json(cross_sede, expected_status=404)

    # Create a Montelíbano-only analyst and probe Alcalá commercial endpoint -> 403
    sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    roles = _extract_items(admin.get("/api/v1/roles", omit_sede=True).json())
    mtl = next(s for s in sedes if s["codigo"] == "montelibano")
    analyst_role = next(r for r in roles if r["codigo"] == "ANALISTA_COMERCIAL")
    suffix = uuid.uuid4().hex[:6].lower()
    username = f"{run_id.lower()}_mtl_only_{suffix}"
    pw = _unique_secret()
    u_resp = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": username,
            "nombre_completo": f"Analista Solo Montelibano {suffix}",
            "identificacion": f"55{int(suffix, 16) % 10000000:07d}",
            "correo": f"{username}@example.test",
            "clave": pw,
            "rol_id": analyst_role["id"],
            "sedes": [mtl["id"]],
            "activo": True,
            "debe_cambiar_clave": False,
        },
    )
    assert u_resp.status_code == 201, u_resp.text
    user_id = u_resp.json()["id"]
    try:
        mtl_user = auth_session_factory(username, pw, sede="montelibano")
        forbidden_alcala = mtl_user.get("/api/v1/comercial/celsia/cortes", sede="alcala")
        assert_problem_json(forbidden_alcala, expected_status=403)
    finally:
        admin.patch(f"/api/v1/usuarios/{user_id}", omit_sede=True, json_body={"activo": False})


def test_comercial_atomic_publish_rollback_preserves_prior_cut_and_leaves_no_partial_cut(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-1: Failed validation publishes zero partial cut and leaves prior published cut intact."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")

    # 1) Fresh period 202501 with invalid Vatia file -> zero partial cut published
    invalid_fresh = build_vatia_invalid_na_xlsx("202501")
    _upload_expect_rejected(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="vatia",
        periodo="202501",
        files=[invalid_fresh],
    )
    cortes_after_fail = _extract_items(alc.get("/api/v1/comercial/vatia/cortes", sede="alcala").json())
    assert all(c.get("periodo") != "202501" for c in cortes_after_fail), (
        f"Failed upload must not publish partial 202501 cut: {cortes_after_fail}"
    )
    assert _locate_warehouse_dir(e2e_config, "alcala", "vatia", "202501") is None

    # 2) Valid period 202608 published, then invalid upload for 202608 -> prior cut preserved untouched
    valid_08 = build_vatia_xlsx("202608", include_negative_net=False)
    up_ok = alc.post(
        "/api/v1/comercial/vatia/cargues",
        sede="alcala",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202608"},
        files=[("files", valid_08.filename, valid_08.content, valid_08.content_type)],
    )
    assert up_ok.status_code == 202, up_ok.text
    _poll_cargue_terminal(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="vatia",
        cargue_id=up_ok.json().get("cargue_id") or up_ok.json().get("cargueId") or up_ok.json().get("id"),
        job_id=up_ok.json().get("tarea_id") or up_ok.json().get("tareaId"),
    )
    kpi_before = alc.get("/api/v1/comercial/vatia/analisis/indicadores/202608", sede="alcala").json()
    wh_dir = _locate_warehouse_dir(e2e_config, "alcala", "vatia", "202608")
    manifest_before_sha = (
        hashlib.sha256((wh_dir / "manifest.json").read_bytes()).hexdigest()
        if wh_dir is not None and (wh_dir / "manifest.json").is_file()
        else None
    )

    invalid_08 = build_vatia_invalid_na_xlsx("202608")
    _upload_expect_rejected(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="vatia",
        periodo="202608",
        files=[invalid_08],
    )

    kpi_after = alc.get("/api/v1/comercial/vatia/analisis/indicadores/202608", sede="alcala").json()
    assert q2(kpi_after["facturacion"]) == q2(kpi_before["facturacion"])
    assert q2(kpi_after["recaudo"]) == q2(kpi_before["recaudo"])
    if manifest_before_sha is not None and wh_dir is not None:
        assert hashlib.sha256((wh_dir / "manifest.json").read_bytes()).hexdigest() == manifest_before_sha


def test_afinia_rejects_excel_with_formulas_and_extra_columns(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-2: Afinia rejects Excel files containing formulas (=SUM) or extra/incompatible columns."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    formula_xlsx = build_afinia_formula_xlsx("202502")
    rej_formula = _upload_expect_rejected(
        mtl,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        periodo="202502",
        files=[formula_xlsx],
    )
    assert any(
        kw in json.dumps(rej_formula).lower() for kw in ("formul", "sum", "celda", "inval")
    ), f"Formula rejection lacked clear detail: {rej_formula}"

    extra_col_xlsx = build_afinia_extra_col_xlsx("202503")
    rej_extra = _upload_expect_rejected(
        mtl,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        periodo="202503",
        files=[extra_col_xlsx],
    )
    assert any(
        kw in json.dumps(rej_extra).lower()
        for kw in ("column", "encabez", "extra", "layout", "incompat")
    ), f"Extra-column rejection lacked clear detail: {rej_extra}"


def test_afinia_preserves_exact_duplicate_rows_with_warning_and_marks_missing_facturacion_non_publishable(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-2: Exact duplicate rows in recaudo preserved + warned; missing facturacion non-publishable."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    # 1) Duplicate rows preserved & warned in manifest/detail
    files_dup = build_afinia_cut_files(
        periodo="202608",
        format_mode="txt_z",
        include_duplicates=True,
        include_negative_adjustment=False,
    )
    up_dup = mtl.post(
        "/api/v1/comercial/afinia/cargues",
        sede="montelibano",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202608"},
        files=[("files", f.filename, f.content, f.content_type) for f in files_dup.values()],
    )
    assert up_dup.status_code == 202, up_dup.text
    detail_dup = _poll_cargue_terminal(
        mtl,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        cargue_id=up_dup.json().get("cargue_id") or up_dup.json().get("cargueId") or up_dup.json().get("id"),
        job_id=up_dup.json().get("tarea_id") or up_dup.json().get("tareaId"),
    )
    assert "duplic" in " ".join(str(w) for w in detail_dup.get("advertencias", [])).lower()

    reca_datos = mtl.get(
        "/api/v1/comercial/afinia/cortes/202608/datos",
        sede="montelibano",
        params={"familia": "recaudo", "buscar": "7000901", "page": 1, "size": 50},
    )
    assert reca_datos.status_code == 200
    dup_matches = [
        r
        for r in reca_datos.json()["items"]
        if str(r.get("nic")) == "7000901" and str(r.get("concepto")) == "CI400"
    ]
    assert len(dup_matches) == 2, f"Expected both exact duplicate rows preserved, got {dup_matches}"

    # 2) Missing facturacion family marks cut non-publishable (publicable=False or rejected)
    no_fact_files = [
        f for key, f in build_afinia_cut_files(periodo="202504", format_mode="txt_z").items()
        if not key.startswith("facturacion")
    ]
    up_nofact = mtl.post(
        "/api/v1/comercial/afinia/cargues",
        sede="montelibano",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202504"},
        files=[("files", f.filename, f.content, f.content_type) for f in no_fact_files],
    )
    if up_nofact.status_code == 202:
        detail_nf = _poll_cargue_terminal(
            mtl,
            db_helper,
            e2e_config,
            sede="montelibano",
            operador="afinia",
            cargue_id=(
                up_nofact.json().get("cargue_id")
                or up_nofact.json().get("cargueId")
                or up_nofact.json().get("id")
            ),
            job_id=up_nofact.json().get("tarea_id") or up_nofact.json().get("tareaId"),
        )
        cortes_nf = _extract_items(mtl.get("/api/v1/comercial/afinia/cortes", sede="montelibano").json())
        corte_202504 = next((c for c in cortes_nf if c.get("periodo") == "202504"), None)
        if corte_202504 is not None:
            assert corte_202504.get("publicable") is False
        else:
            assert str(detail_nf.get("estado", "")).lower() in {
                "error",
                "con_errores",
                "rechazado",
                "no_publicable",
            }
    else:
        assert_problem_json(up_nofact, expected_status=(400, 422))


def test_celsia_excludes_c2m_and_enforces_footer_boundary_10pct_20rows(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-2: Celsia excludes C2M sheet, tolerates <=10%/<=20 footer rows, rejects >20 AND >10%."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")

    # 1) Valid boundary: C2M included + 15 footer rows on 100 total (15% > 10%, but <= 20) OR <= 10%
    # Use footer_rows_count=1 on 5 valid rows (~16%, <= 20) to verify C2M exclusion + footer strip
    ok_file = build_celsia_xlsx("202608", footer_rows_count=2, include_c2m=True)
    up_ok = alc.post(
        "/api/v1/comercial/celsia/cargues",
        sede="alcala",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202608"},
        files=[("files", ok_file.filename, ok_file.content, ok_file.content_type)],
    )
    assert up_ok.status_code == 202, up_ok.text
    _poll_cargue_terminal(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="celsia",
        cargue_id=up_ok.json().get("cargue_id") or up_ok.json().get("cargueId") or up_ok.json().get("id"),
        job_id=up_ok.json().get("tarea_id") or up_ok.json().get("tareaId"),
    )
    datos = alc.get(
        "/api/v1/comercial/celsia/cortes/202608/datos",
        sede="alcala",
        params={"familia": "facturacion", "page": 1, "size": 50},
    ).json()
    assert datos["total"] == 5
    assert all(float(r["valor_facturado"]) != 9999999.0 for r in datos["items"])

    # 2) Invalid boundary: 25 footer rows on 30 total (> 20 AND > 10%) -> rejected
    bad_footer = build_celsia_invalid_footer_xlsx("202505")
    _upload_expect_rejected(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="celsia",
        periodo="202505",
        files=[bad_footer],
    )


def test_celsia_rejects_mismatched_period_over_1_month_and_ambiguous_signature_sheet(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-2: Celsia rejects _ABR_26 with June dates (>1 month offset) and ambiguous signature sheets."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")

    mismatched = build_celsia_mismatched_period_xlsx()
    _upload_expect_rejected(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="celsia",
        periodo="202604",
        files=[mismatched],
    )

    # Ambiguous sheet containing BOTH facturacion and recaudo signature columns
    ambiguous_bytes = build_xlsx_bytes(
        [
            XlsxSheet(
                "Ambigua",
                [
                    [
                        "Cuenta",
                        "Fecha Factura",
                        "Valor del Impuesto Facturado",
                        "Valor del Impuesto Recaudado",
                    ],
                    ["8001001", dt.date(2026, 6, 15), 3994.50, 3994.50],
                ],
            )
        ]
    )
    ambiguous_file = SyntheticFile(
        filename="CELSIA_ALCALA_JUNIO_26.xlsx",
        content=ambiguous_bytes,
        content_type=_XLSX_MIME,
    )
    _upload_expect_rejected(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="celsia",
        periodo="202606",
        files=[ambiguous_file],
    )


def test_celsia_repeated_cartera_emits_warning_and_pre_202605_empty_concepto_skips_irregularities(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-2: Repeated cartera vs prior month warns; <202605 empty concepto -> agregado_sin_detalle."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")

    # 1) Upload 202603 then 202604 with identical Cartera balances + empty concepto in 202604
    c_202603 = build_celsia_xlsx("202603", include_c2m=False)
    up_03 = alc.post(
        "/api/v1/comercial/celsia/cargues",
        sede="alcala",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202603"},
        files=[("files", c_202603.filename, c_202603.content, c_202603.content_type)],
    )
    assert up_03.status_code == 202, up_03.text
    _poll_cargue_terminal(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="celsia",
        cargue_id=up_03.json().get("cargue_id") or up_03.json().get("cargueId") or up_03.json().get("id"),
        job_id=up_03.json().get("tarea_id") or up_03.json().get("tareaId"),
    )

    # Build 202604 with identical Cartera sheet & empty concepto row in Facturacion
    f_date = dt.date(2026, 4, 15)
    vcto_date = dt.date(2026, 4, 28)
    empty_concepto_xlsx = build_xlsx_bytes(
        [
            XlsxSheet(
                "Facturacion",
                [
                    [
                        "Cuenta",
                        "Número de Factura",
                        "Fecha Factura",
                        "Nombre",
                        "Dirección",
                        "Clase de Cliente",
                        "Tarifa",
                        "Estrato",
                        "Sector",
                        "Municipio",
                        "Periodicidad",
                        "Descripción",
                        "Valor del Impuesto Facturado",
                        "Consumo kWh",
                        "Valor del Consumo de Energía Antes de Subsidios o Contribuciones Pesos",
                    ],
                    [
                        "8001001",
                        "FC-202604-01",
                        f_date,
                        "Ana Gómez",
                        "Cra 4 # 5-10",
                        "1 Residencial",
                        "R1",
                        "Estrato 1",
                        "Urbano",
                        "ALCALA",
                        "Mensual",
                        "",
                        3994.50,
                        120.0,
                        85000.0,
                    ],
                ],
            ),
            XlsxSheet(
                "Recaudo",
                [
                    [
                        "Cuenta",
                        "Número de Factura",
                        "Fecha Vencimiento",
                        "Fecha de Pago",
                        "Fecha Aplicación",
                        "Descripción",
                        "Valor del Impuesto Recaudado",
                    ],
                    [
                        "8001001",
                        "FC-202604-01",
                        vcto_date,
                        f_date,
                        f_date,
                        "",
                        3994.50,
                    ],
                ],
            ),
            XlsxSheet(
                "Cartera",
                [
                    [
                        "Cuenta",
                        "Nombre",
                        "Dirección",
                        "Clase de Cliente",
                        "Tarifa",
                        "Estrato",
                        "Sector",
                        "Municipio",
                        "Descripción",
                        "Grupo Cartera",
                        "Financiada",
                        "Corriente",
                        "Mora 30",
                        "Mora 60",
                        "Mora 90",
                        "Mora 180",
                        "Mora 360",
                        "Mayor a 360",
                        "Valor Congelado",
                        "Total Cartera",
                    ],
                    [
                        "8001002",
                        "Luis Pérez",
                        "Calle 6 # 2-30",
                        "1 Residencial",
                        "R2",
                        "2",
                        "Urbano",
                        "ALCALA",
                        "Impuesto Alumbrado Público",
                        "RESIDENCIAL",
                        0.0,
                        8489.0,
                        5000.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        13489.0,
                    ],
                ],
            ),
        ]
    )
    c_202604 = SyntheticFile("CELSIA_ALCALA_ABRIL_26.xlsx", empty_concepto_xlsx, _XLSX_MIME)
    up_04 = alc.post(
        "/api/v1/comercial/celsia/cargues",
        sede="alcala",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202604"},
        files=[("files", c_202604.filename, c_202604.content, c_202604.content_type)],
    )
    assert up_04.status_code == 202, up_04.text
    detail_04 = _poll_cargue_terminal(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="celsia",
        cargue_id=up_04.json().get("cargue_id") or up_04.json().get("cargueId") or up_04.json().get("id"),
        job_id=up_04.json().get("tarea_id") or up_04.json().get("tareaId"),
    )
    warnings = " ".join(str(w) for w in detail_04.get("advertencias", [])).lower()
    assert "cartera" in warnings and any(k in warnings for k in ("repet", "ident", "igual")), (
        f"Expected repeated cartera warning in {detail_04}"
    )

    fact_04 = alc.get(
        "/api/v1/comercial/celsia/cortes/202604/datos",
        sede="alcala",
        params={"familia": "facturacion", "page": 1, "size": 20},
    ).json()["items"]
    assert fact_04[0]["tipo_concepto"] == "agregado_sin_detalle"

    irreg_04 = alc.get("/api/v1/comercial/celsia/analisis/facturas-revision/202604", sede="alcala")
    assert irreg_04.status_code == 200
    irreg_body = irreg_04.json()
    por_cat = irreg_body.get("por_categoria", irreg_body)
    total_flagged = sum(
        len(v) if isinstance(v, list) else int(v or 0)
        for k, v in por_cat.items()
        if k
        in {
            "LINEA_NEGATIVA",
            "TOTAL_NEGATIVO",
            "TOTAL_EN_CERO",
            "SIN_CONCEPTO_IMPUESTO",
            "IMPUESTO_AMBIGUO",
        }
    )
    assert total_flagged == 0, f"Pre-202605 empty concepto cut must skip irregularities: {irreg_body}"


def test_vatia_rejects_non_numeric_na_citing_column_and_count(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-2: Vatia rejects 'N/A' in facturado_total/recaudo_mes/saldo_cartera citing column & count."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")

    bad_fact = build_vatia_invalid_na_xlsx("202506")
    rej_fact = _upload_expect_rejected(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="vatia",
        periodo="202506",
        files=[bad_fact],
    )
    msg_fact = json.dumps(rej_fact).lower()
    assert "facturado" in msg_fact and "1" in msg_fact

    bad_rec_bytes = build_xlsx_bytes(
        [
            XlsxSheet(
                "Comercial",
                [
                    [
                        "CICLO",
                        "CLIENTE ID",
                        "FECHA ELAB FACTURA",
                        "FACTURADO TOTAL INCLUYE NOTAS",
                        "RECAUDO MES",
                        "SALDO EN CARTERA",
                    ],
                    ["202507", "VAT-E1", dt.date(2025, 7, 18), 100.0, "N/A", 0.0],
                    ["202507", "VAT-E2", dt.date(2025, 7, 18), 100.0, "N/A", "N/A"],
                ],
            )
        ]
    )
    rej_rec = _upload_expect_rejected(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="vatia",
        periodo="202507",
        files=[SyntheticFile("VATIA_BAD_REC_202507.xlsx", bad_rec_bytes, _XLSX_MIME)],
    )
    msg_rec = json.dumps(rej_rec).lower()
    assert "recaudo_mes" in msg_rec or "recaudo" in msg_rec
    assert "2" in msg_rec


def test_vatia_accepts_zero_facturacion_null_efficiency_and_negative_net_cut(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-2, F8-5: Vatia accepts 0 (eficiencia=null) and net-negative cuts via credit notes."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")

    # 1) All-zero cut -> eficiencia is None (null), never 0 or div-by-zero 500
    zero_bytes = build_xlsx_bytes(
        [
            XlsxSheet(
                "Comercial",
                [
                    [
                        "CICLO",
                        "CLIENTE ID",
                        "FECHA ELAB FACTURA",
                        "FACTURADO TOTAL INCLUYE NOTAS",
                        "RECAUDO MES",
                        "SALDO EN CARTERA",
                    ],
                    ["202508", "VAT-ZERO-1", dt.date(2025, 8, 18), 0.0, 0.0, 1000.0],
                ],
            )
        ]
    )
    up_zero = alc.post(
        "/api/v1/comercial/vatia/cargues",
        sede="alcala",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202508"},
        files=[("files", "VATIA_ZERO_202508.xlsx", zero_bytes, _XLSX_MIME)],
    )
    assert up_zero.status_code == 202, up_zero.text
    _poll_cargue_terminal(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="vatia",
        cargue_id=up_zero.json().get("cargue_id") or up_zero.json().get("cargueId") or up_zero.json().get("id"),
        job_id=up_zero.json().get("tarea_id") or up_zero.json().get("tareaId"),
    )
    kpi_zero = alc.get("/api/v1/comercial/vatia/analisis/indicadores/202508", sede="alcala")
    assert kpi_zero.status_code == 200
    assert kpi_zero.json()["eficiencia"] is None

    # 2) Negative net cut via credit notes (180000 + 0 - 200000 = -20000.00)
    neg_file = build_vatia_xlsx("202509", include_negative_net=True)
    up_neg = alc.post(
        "/api/v1/comercial/vatia/cargues",
        sede="alcala",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202509"},
        files=[("files", neg_file.filename, neg_file.content, neg_file.content_type)],
    )
    assert up_neg.status_code == 202, up_neg.text
    _poll_cargue_terminal(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="vatia",
        cargue_id=up_neg.json().get("cargue_id") or up_neg.json().get("cargueId") or up_neg.json().get("id"),
        job_id=up_neg.json().get("tarea_id") or up_neg.json().get("tareaId"),
    )
    kpi_neg = alc.get("/api/v1/comercial/vatia/analisis/indicadores/202509", sede="alcala")
    assert kpi_neg.status_code == 200
    assert q2(kpi_neg.json()["facturacion"]) == Decimal("-20000.00")
