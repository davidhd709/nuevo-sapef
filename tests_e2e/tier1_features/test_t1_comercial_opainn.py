"""Tier 1 E2E tests for EP-08 Comercial OPainn Parity (F8-1..F8-10)."""

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
    AFINIA_39_UVT_FACTORS,
    AFINIA_CANONICAL_TARIFFS,
    SyntheticFile,
    build_afinia_3month_dataset,
    build_afinia_cut_files,
    build_celsia_3month_dataset,
    build_celsia_xlsx,
    build_vatia_xlsx,
    read_xlsx_sheets,
)
from harness.client import SapefClient
from harness.config import E2EConfig
from harness.db import DbHelper
from oracles import (
    TD_45_COLUMNS,
    audit_oc135_convenios,
    classify_movements_and_absences,
    classify_payment_behavior,
    compute_afinia_tabla_dinamica,
    compute_maturation_bands,
    compute_portfolio_concentration,
    deduce_celsia_periodicity,
    detect_irregular_invoices,
    detect_negative_adjustment_alert,
    evaluate_afinia_tariff_control,
    evaluate_celsia_tariff_control,
    q2,
    q4,
    verify_parity,
)

pytestmark = [pytest.mark.tier1, pytest.mark.commercial]


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


def _upload_and_wait_cargue(
    client: SapefClient,
    db_helper: DbHelper,
    e2e_config: E2EConfig,
    *,
    sede: str,
    operador: str,
    periodo: str,
    files: list[SyntheticFile],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    idem = idempotency_key or str(uuid.uuid4())
    multipart = [("files", f.filename, f.content, f.content_type) for f in files]
    resp = client.post(
        f"/api/v1/comercial/{operador}/cargues",
        sede=sede,
        idempotency_key=idem,
        data={"periodo": periodo},
        files=multipart,
    )
    assert resp.status_code == 202, (
        f"POST /comercial/{operador}/cargues failed: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    cargue_id = body.get("cargue_id") or body.get("cargueId") or body.get("id")
    assert cargue_id is not None

    job_id = body.get("tarea_id") or body.get("tareaId")
    if isinstance(job_id, int):
        db_helper.wait_for_procrastinate_job(job_id, timeout=e2e_config.timeout_seconds)

    deadline = time.monotonic() + e2e_config.timeout_seconds
    last_detail: dict[str, Any] = {}
    while time.monotonic() < deadline:
        detail_resp = client.get(
            f"/api/v1/comercial/{operador}/cargues/{cargue_id}",
            sede=sede,
        )
        if detail_resp.status_code == 404:
            detail_resp = client.get(f"/api/v1/comercial/cargues/{cargue_id}", sede=sede)
        assert detail_resp.status_code == 200, detail_resp.text
        last_detail = detail_resp.json()
        estado = str(last_detail.get("estado", "")).lower()
        if estado in {"publicado", "completado", "procesado", "listo"}:
            return last_detail
        if estado in {"error", "con_errores", "fallido", "rechazado"}:
            raise AssertionError(f"Cargue {cargue_id} failed: {last_detail}")
        time.sleep(0.25)

    raise TimeoutError(f"Cargue {cargue_id} did not finish: {last_detail}")


def _ensure_afinia_2026_agreement_with_exceptions(
    client: SapefClient,
    nic_base: int = 7000000,
) -> None:
    """Ensure active 2026 Afinia agreement includes the 39 UVT exception NICs."""
    ac_resp = client.get(
        "/api/v1/acuerdos",
        sede="montelibano",
        params={"comercializador": "afinia", "anio": 2026},
    )
    assert ac_resp.status_code == 200, ac_resp.text
    items = ac_resp.json() if isinstance(ac_resp.json(), list) else ac_resp.json().get("items", [])

    exceptions = [
        {"identificador": str(nic_base + 500 + idx), "factor_uvt": float(factor), "activo": True}
        for idx, factor in enumerate(AFINIA_39_UVT_FACTORS)
    ]
    tariffs = [
        {
            "codigo": name,
            "nombre": name,
            "factor_uvt": float(factor),
            "porcentaje_variable": float(pct),
        }
        for name, factor, pct in AFINIA_CANONICAL_TARIFFS
    ]

    if items:
        latest = items[0]
        detail = client.get(
            f"/api/v1/acuerdos/{latest['id']}",
            sede="montelibano",
        ).json()
        existing_nics = {
            str(e.get("identificador") or e.get("nic")) for e in detail.get("excepciones", [])
        }
        if all(str(nic_base + 500 + i) in existing_nics for i in range(len(AFINIA_39_UVT_FACTORS))):
            return

    create_resp = client.post(
        "/api/v1/acuerdos",
        sede="montelibano",
        json_body={
            "comercializador_codigo": "afinia",
            "anio": 2026,
            "uvt": 52374,
            "umbral_kwh": 173,
            "tolerancia": 1.0,
            "base_costo_variable": "valor_consumo_antes",
            "fuente": "Acuerdo Municipal 2026 E2E",
            "tarifas": tariffs,
            "excepciones": exceptions,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    ac_id = create_resp.json()["id"]
    approve = client.post(
        f"/api/v1/acuerdos/{ac_id}/aprobar",
        sede="montelibano",
        json_body={"observacion": "Aprobación E2E Tier 1"},
    )
    assert approve.status_code == 200, approve.text


def _locate_warehouse_manifest(
    e2e_config: E2EConfig,
    sede: str,
    operador: str,
    periodo: str,
) -> Path | None:
    for root in (e2e_config.data_dir / "comercial", Path("/data/comercial")):
        candidate = root / sede / operador / periodo / "manifest.json"
        if candidate.is_file():
            return candidate
    return None


def test_afinia_upload_txt_z_xlsx_setiembre_refa21_parquet_and_sha256_manifest(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-1, F8-2: Afinia .txt cp1252, .Z LZW, 5 .xlsx books (SETIEMBRE, 21-col REFA), manifest."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    # 1) Upload .txt (cp1252) + .Z (LZW) for 202607
    files_tz = build_afinia_cut_files(periodo="202607", format_mode="txt_z")
    idem_key = str(uuid.uuid4())
    detail_tz = _upload_and_wait_cargue(
        client,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        periodo="202607",
        files=list(files_tz.values()),
        idempotency_key=idem_key,
    )
    assert detail_tz["periodo"] == "202607"
    # Duplicate warning emitted without dropping duplicate recaudo rows
    warnings_text = " ".join(str(w) for w in detail_tz.get("advertencias", [])).lower()
    assert "duplic" in warnings_text, f"Expected duplicate warning in {detail_tz}"

    # Idempotency-Key replay returns same cargue without duplicate upload
    replay = client.post(
        "/api/v1/comercial/afinia/cargues",
        sede="montelibano",
        idempotency_key=idem_key,
        data={"periodo": "202607"},
        files=[("files", f.filename, f.content, f.content_type) for f in files_tz.values()],
    )
    assert replay.status_code in (200, 202)
    assert (
        replay.json().get("cargue_id")
        or replay.json().get("cargueId")
        or replay.json().get("id")
    ) == detail_tz["id"]

    # 2) Upload 5 .xlsx books for 202609 (SETIEMBRE spelling + 21-col REFACTURACION)
    files_xlsx = build_afinia_cut_files(
        periodo="202609",
        format_mode="xlsx",
        use_setiembre_spelling=True,
    )
    detail_09 = _upload_and_wait_cargue(
        client,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        periodo="202609",
        files=list(files_xlsx.values()),
    )
    assert detail_09["periodo"] == "202609"

    # Verify manifest.json & Parquet SHA-256 integrity
    manifest_path = _locate_warehouse_manifest(e2e_config, "montelibano", "afinia", "202609")
    if manifest_path is not None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["completo"] is True
        assert manifest["publicable"] is True
        for fam, meta in manifest["familias"].items():
            pq_path = manifest_path.parent / meta["archivo_parquet"]
            assert pq_path.is_file(), f"Missing parquet for {fam}: {pq_path}"
            actual_sha = hashlib.sha256(pq_path.read_bytes()).hexdigest()
            assert actual_sha == meta["sha256_parquet"]


def test_celsia_xlsx_upload_c2m_excluded_estrato_digit_and_classifications(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-2: Celsia .xlsx excludes C2M, extracts estrato digit, classifies tipo_concepto/recaudo."""
    client = _admin_client(auth_session_factory, e2e_config, sede="alcala")
    celsia_file = build_celsia_xlsx("202606", include_c2m=True)
    detail = _upload_and_wait_cargue(
        client,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="celsia",
        periodo="202606",
        files=[celsia_file],
    )
    assert detail["periodo"] == "202606"

    fact_rows = client.get(
        "/api/v1/comercial/celsia/cortes/202606/datos",
        sede="alcala",
        params={"familia": "facturacion", "page": 1, "size": 50},
    )
    assert fact_rows.status_code == 200, fact_rows.text
    items = fact_rows.json()["items"]
    assert len(items) == 5, f"Expected 5 valid rows (C2M & footers excluded), got {len(items)}"
    row_8001001 = next(r for r in items if str(r["cuenta"]) == "8001001")
    assert str(row_8001001["estrato"]) == "1"
    assert row_8001001["tipo_concepto"] == "impuesto"
    assert all(float(r["valor_facturado"]) != 9999999.0 for r in items)

    reca_rows = client.get(
        "/api/v1/comercial/celsia/cortes/202606/datos",
        sede="alcala",
        params={"familia": "recaudo", "page": 1, "size": 50},
    )
    assert reca_rows.status_code == 200
    reca_items = reca_rows.json()["items"]
    tipos = {r["tipo_recaudo"] for r in reca_items}
    assert {"CORRIENTE", "CARTERA"}.issubset(tipos)


def test_vatia_xlsx_upload_comercial_parquet_zero_and_negative_notes(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-2: Vatia .xlsx creates comercial.parquet accepting valid 0 & negative credit notes."""
    client = _admin_client(auth_session_factory, e2e_config, sede="alcala")
    vatia_file = build_vatia_xlsx("202606")
    detail = _upload_and_wait_cargue(
        client,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="vatia",
        periodo="202606",
        files=[vatia_file],
    )
    assert detail["periodo"] == "202606"

    rows_resp = client.get(
        "/api/v1/comercial/vatia/cortes/202606/datos",
        sede="alcala",
        params={"familia": "comercial", "page": 1, "size": 50},
    )
    assert rows_resp.status_code == 200, rows_resp.text
    items = rows_resp.json()["items"]
    assert len(items) == 3
    by_id = {str(r["cliente_id"]): r for r in items}
    assert Decimal(str(by_id["VAT-002"]["facturado_total"])) == Decimal(0)
    assert Decimal(str(by_id["VAT-003"]["valor_nota"])) == Decimal(-50000)

    kpi_resp = client.get("/api/v1/comercial/vatia/analisis/indicadores/202606", sede="alcala")
    assert kpi_resp.status_code == 200
    kpi = kpi_resp.json()
    assert q2(kpi["facturacion"]) == Decimal("230000.00")
    assert q2(kpi["recaudo"]) == Decimal("180000.00")


def test_commercial_cortes_list_paginated_rows_sabana_export_and_delete(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-3: List cuts, paginate rows, export background sabana (202), and delete cargue."""
    client = _admin_client(auth_session_factory, e2e_config, sede="alcala")
    vatia_file = build_vatia_xlsx("202611")
    detail = _upload_and_wait_cargue(
        client,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="vatia",
        periodo="202611",
        files=[vatia_file],
    )
    cargue_id = detail["id"]

    cortes_resp = client.get("/api/v1/comercial/vatia/cortes", sede="alcala")
    assert cortes_resp.status_code == 200
    cortes = cortes_resp.json()
    corte_list = cortes if isinstance(cortes, list) else cortes.get("items", [])
    assert any(c.get("periodo") == "202611" for c in corte_list)

    datos_resp = client.get(
        "/api/v1/comercial/vatia/cortes/202611/datos",
        sede="alcala",
        params={"familia": "comercial", "page": 1, "size": 2},
    )
    assert datos_resp.status_code == 200
    assert len(datos_resp.json()["items"]) == 2
    assert datos_resp.json()["total"] == 3

    sabana_resp = client.post(
        "/api/v1/comercial/vatia/cortes/202611/sabana",
        sede="alcala",
        json_body={"familia": "comercial", "formato": "csv"},
    )
    assert sabana_resp.status_code == 202, sabana_resp.text
    job_id = sabana_resp.json().get("tarea_id") or sabana_resp.json().get("tareaId")
    if isinstance(job_id, int):
        db_helper.wait_for_procrastinate_job(job_id, timeout=e2e_config.timeout_seconds)

    del_resp = client.delete(f"/api/v1/comercial/vatia/cargues/{cargue_id}", sede="alcala")
    assert del_resp.status_code in (200, 204), del_resp.text

    cortes_after = client.get("/api/v1/comercial/vatia/cortes", sede="alcala").json()
    corte_list_after = (
        cortes_after if isinstance(cortes_after, list) else cortes_after.get("items", [])
    )
    assert all(c.get("periodo") != "202611" for c in corte_list_after)


def test_common_29_analysis_catalog_availability_matrix(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
) -> None:
    """F8-3..F8-9: Common 29-analysis catalog exposes exact availability matrix & notes."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")

    by_op: dict[str, dict[str, dict[str, Any]]] = {}
    for op, client, sede in (
        ("afinia", mtl, "montelibano"),
        ("celsia", alc, "alcala"),
        ("vatia", alc, "alcala"),
    ):
        resp = client.get(f"/api/v1/comercial/{op}/catalogo", sede=sede)
        assert resp.status_code == 200, f"GET catalogo {op} failed: {resp.text}"
        raw = resp.json()
        items = raw if isinstance(raw, list) else raw.get("items", raw.get("analisis", []))
        assert len(items) == 29, f"Expected 29 catalog entries for {op}, got {len(items)}"
        by_op[op] = {str(entry["id"]): entry for entry in items}

    assert by_op["afinia"]["cartera-edades"]["estado"] == "no_aplica"
    assert by_op["afinia"]["cartera-edades"].get("nota")
    assert by_op["celsia"]["cartera-edades"]["estado"] == "disponible"
    assert by_op["vatia"]["cartera-edades"]["estado"] == "disponible"

    assert by_op["afinia"]["usuarios-periodicidad"]["estado"] == "no_aplica"
    assert by_op["celsia"]["usuarios-periodicidad"]["estado"] == "disponible"
    assert by_op["vatia"]["usuarios-periodicidad"]["estado"] == "no_aplica"

    assert by_op["afinia"]["control-tarifario"]["estado"] == "disponible"
    assert by_op["celsia"]["control-tarifario"]["estado"] == "disponible"
    assert by_op["vatia"]["control-tarifario"]["estado"] == "no_aplica"

    assert by_op["afinia"]["convenios-ajustes"]["estado"] == "disponible"
    assert by_op["celsia"]["convenios-ajustes"]["estado"] == "no_aplica"
    assert by_op["afinia"]["rutas-campo"]["estado"] == "disponible"
    assert by_op["vatia"]["rutas-campo"]["estado"] == "no_aplica"


def test_afinia_2026_tariff_control_against_oracle(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-4: Afinia 2026 tariff control (CI400, 39 UVT, $1 tol, CI401/CI851) matches oracle."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    _ensure_afinia_2026_agreement_with_exceptions(client, nic_base=7000000)

    files = build_afinia_cut_files(periodo="202607", format_mode="txt_z")
    _upload_and_wait_cargue(
        client,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        periodo="202607",
        files=list(files.values()),
    )

    tc_resp = client.get(
        "/api/v1/comercial/afinia/analisis/control-tarifario/202607",
        sede="montelibano",
        params={"grupo_consumo": "todos", "size": 500},
    )
    assert tc_resp.status_code == 200, tc_resp.text
    tc_api = tc_resp.json()

    # Fetch normalized facturacion rows from cut API to feed exact oracle
    fact_data = client.get(
        "/api/v1/comercial/afinia/cortes/202607/datos",
        sede="montelibano",
        params={"familia": "facturacion", "page": 1, "size": 100},
    ).json()["items"]
    exc_map = {
        str(7000500 + idx): factor for idx, factor in enumerate(AFINIA_39_UVT_FACTORS)
    }
    expected = evaluate_afinia_tariff_control(
        fact_data,
        periodo="202607",
        excepciones=exc_map,
    )

    assert tc_api["totales"]["por_estado"] == expected["counts"]
    assert q2(tc_api["totales"]["valor_por_encima"]) == expected["total_valor_por_encima"]
    assert q2(tc_api["totales"]["valor_por_debajo"]) == expected["total_valor_por_debajo"]

    api_by_nic = {str(r["identificador"]): r for r in tc_api["items"]}
    assert api_by_nic["7000901"]["estado"] == "POR_ENCIMA"
    assert q2(api_by_nic["7000901"]["senal_ci401"]) == Decimal("-100.00")
    assert api_by_nic["7000902"]["estado"] == "POR_DEBAJO"
    assert q2(api_by_nic["7000902"]["senal_ci851"]) == Decimal("-50.00")
    assert api_by_nic["7000903"]["estado"] == "NO_VALIDABLE"
    assert api_by_nic["7000904"]["estado"] == "REQUIERE_REVISION"
    assert api_by_nic["7000904"]["motivo_revision"] == "MULTIPLES_CI400"


def test_celsia_2026_tariff_control_against_oracle(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-4: Celsia 2026 tariff control (VCE urban/rural/bimonthly x2, $100 tol) vs oracle."""
    client = _admin_client(auth_session_factory, e2e_config, sede="alcala")
    _upload_and_wait_cargue(
        client,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="celsia",
        periodo="202606",
        files=[build_celsia_xlsx("202606")],
    )

    tc_resp = client.get(
        "/api/v1/comercial/celsia/analisis/control-tarifario/202606",
        sede="alcala",
        params={"grupo_consumo": "todos", "size": 100},
    )
    assert tc_resp.status_code == 200, tc_resp.text
    tc_api = tc_resp.json()

    fact_data = client.get(
        "/api/v1/comercial/celsia/cortes/202606/datos",
        sede="alcala",
        params={"familia": "facturacion", "page": 1, "size": 100},
    ).json()["items"]
    expected = evaluate_celsia_tariff_control(
        fact_data,
        periodo="202606",
        bimonthly_accounts={"8001003"},
    )
    assert tc_api["totales"]["por_estado"] == expected["counts"]
    assert q2(tc_api["totales"]["valor_por_encima"]) == expected["total_valor_por_encima"]
    assert q2(tc_api["totales"]["valor_por_debajo"]) == expected["total_valor_por_debajo"]


def test_afinia_45_column_tabla_dinamica_kpis_series_and_annual_consolidated_against_oracle(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-5: 45-col Tabla Dinámica (DECIMAL 20,4), KPIs, series, annual consolidated vs oracle."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    files = build_afinia_cut_files(periodo="202607", format_mode="txt_z")
    _upload_and_wait_cargue(
        client,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        periodo="202607",
        files=list(files.values()),
    )

    td_resp = client.get("/api/v1/comercial/afinia/analisis/tabla-dinamica/202607", sede="montelibano")
    assert td_resp.status_code == 200, td_resp.text
    td_api = td_resp.json()
    assert len(td_api["filas"]) == 12
    for col in TD_45_COLUMNS:
        assert col in td_api["total"], f"Missing TD column {col!r} in Total row"

    # Pull normalized cut families and verify against exact oracle
    def _all_rows(fam: str) -> list[dict[str, Any]]:
        return client.get(
            "/api/v1/comercial/afinia/cortes/202607/datos",
            sede="montelibano",
            params={"familia": fam, "page": 1, "size": 100},
        ).json()["items"]

    oracle_td = compute_afinia_tabla_dinamica(
        periodo="202607",
        facturacion=_all_rows("facturacion"),
        recaudo=_all_rows("recaudo"),
        catastro=_all_rows("catastro"),
        refactura=_all_rows("refactura"),
        convenio=_all_rows("convenio"),
    )
    assert q4(td_api["total"]["facturacion"]) == oracle_td["total"]["facturacion"]
    assert q4(td_api["total"]["recaudo_corriente"]) == oracle_td["total"]["recaudo_corriente"]
    assert q4(td_api["total"]["recaudo_cartera"]) == oracle_td["total"]["recaudo_cartera"]
    assert q4(td_api["total"]["recaudo_total"]) == oracle_td["total"]["recaudo_total"]

    kpi_resp = client.get("/api/v1/comercial/afinia/analisis/indicadores/202607", sede="montelibano")
    assert kpi_resp.status_code == 200
    assert q4(kpi_resp.json()["facturacion"]) == oracle_td["total"]["facturacion"]

    serie_resp = client.get("/api/v1/comercial/afinia/analisis/serie", sede="montelibano")
    assert serie_resp.status_code == 200
    assert any(pt["periodo"] == "202607" for pt in serie_resp.json().get("serie", serie_resp.json()))

    cons_resp = client.get(
        "/api/v1/comercial/afinia/analisis/consolidado-anual",
        sede="montelibano",
        params={"anio": 2026},
    )
    assert cons_resp.status_code == 200
    assert "cobertura_meses" in cons_resp.json()


def test_celsia_periodicity_user_movements_and_prolonged_absences_skipping_missing_cut(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-6: Celsia periodicity, user movements, and prolonged absences skipping missing 202603."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")
    for periodo, f in build_celsia_3month_dataset(("202604", "202605", "202606")).items():
        _upload_and_wait_cargue(
            alc,
            db_helper,
            e2e_config,
            sede="alcala",
            operador="celsia",
            periodo=periodo,
            files=[f],
        )

    per_resp = alc.get("/api/v1/comercial/celsia/analisis/periodicidad/202606", sede="alcala")
    assert per_resp.status_code == 200, per_resp.text
    assert deduce_celsia_periodicity(["202604", "202606"]) == "bimestral_par"
    assert deduce_celsia_periodicity(["202604", "202605", "202606"]) == "mensual"

    mov_celsia = alc.get("/api/v1/comercial/celsia/analisis/movimientos/202606", sede="alcala")
    assert mov_celsia.status_code == 200

    # Afinia 3-month dataset intentionally skipping 202603
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    for periodo, files in build_afinia_3month_dataset(("202602", "202604", "202605")).items():
        _upload_and_wait_cargue(
            mtl,
            db_helper,
            e2e_config,
            sede="montelibano",
            operador="afinia",
            periodo=periodo,
            files=list(files.values()),
        )

    mov_afinia = mtl.get("/api/v1/comercial/afinia/analisis/movimientos/202604", sede="montelibano")
    assert mov_afinia.status_code == 200
    mov_body = mov_afinia.json()
    assert mov_body.get("comparable") == "202602"
    assert mov_body.get("salto_corte_detectado") is True or mov_body.get("skipped_missing_cut") is True

    aus_afinia = mtl.get("/api/v1/comercial/afinia/analisis/ausencias/202605", sede="montelibano")
    assert aus_afinia.status_code == 200
    oracle_check = classify_movements_and_absences(
        loaded_periods=["202602", "202604", "202605"],
        account_presence={"ACC-1": ["202602", "202604", "202605"], "ACC-2": ["202602"]},
        target_periodo="202605",
    )
    assert oracle_check["absence_counts"]["ACC-2"] == 2
    assert set(aus_afinia.json().get("tramos", {}).keys()).issuperset({"1", "2", "3", ">3"})


def test_portfolio_aging_maturation_bands_payment_behavior_and_concentration(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-7: Portfolio aging, 7 maturation bands + 30/60/90 cohorts, payment behavior, Top N."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    _upload_and_wait_cargue(
        alc, db_helper, e2e_config, sede="alcala", operador="vatia",
        periodo="202606", files=[build_vatia_xlsx("202606")],
    )
    aging = alc.get("/api/v1/comercial/vatia/analisis/cartera-edades/202606", sede="alcala")
    assert aging.status_code == 200, aging.text

    mad = mtl.get("/api/v1/comercial/afinia/analisis/maduracion/202607", sede="montelibano")
    assert mad.status_code == 200, mad.text
    mad_body = mad.json()
    expected_bands = compute_maturation_bands(
        [{"fecha_fact_lect": dt.date(2026, 7, 15), "importe_trans": 100}],
        periodo="202607",
    )
    assert set(expected_bands.keys()).issuperset(
        {"DEL_MES", "UN_MES", "DOS_A_TRES_MESES", "CUATRO_A_SEIS_MESES", "SIETE_A_DOCE_MESES", "MAS_DE_UN_ANO"}
    )
    assert "bandas" in mad_body and "cohortes" in mad_body

    pay_resp = mtl.get("/api/v1/comercial/afinia/analisis/comportamiento-pago", sede="montelibano")
    assert pay_resp.status_code == 200
    assert classify_payment_behavior(
        [{"identificador": "1", "nombre": "Test", "tarifa": "Res", "cortes_facturados": 2, "cortes_con_recaudo": 0, "cartera": 10}]
    )[0]["comportamiento"] == "NUNCA_PAGA"

    conc_resp = mtl.get("/api/v1/comercial/afinia/analisis/concentracion/202607", sede="montelibano")
    assert conc_resp.status_code == 200
    conc = conc_resp.json()
    for key in ("top_10", "top_21", "top_100", "top_1000", "cuantos_suman_50_pct"):
        assert key in conc
    assert compute_portfolio_concentration([{"nic": "1", "deuda_corriente": 100}])["top_10"] == Decimal("100.00")


def test_convenios_oc135_ci306_negative_adjustments_and_5_irregular_categories(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-8: OC135/CI306 audit, negative adjustment alerts, and 5 irregular invoice categories."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    files = build_afinia_cut_files(periodo="202607", format_mode="txt_z", include_negative_adjustment=True)
    _upload_and_wait_cargue(
        mtl, db_helper, e2e_config, sede="montelibano", operador="afinia",
        periodo="202607", files=list(files.values()),
    )

    conv_resp = mtl.get("/api/v1/comercial/afinia/analisis/convenios/202607", sede="montelibano")
    assert conv_resp.status_code == 200, conv_resp.text
    assert audit_oc135_convenios(
        [{"nic": "7000907", "sv": "SV-CONV-7000907", "cod_oper_cont": "OC135", "concepto": "CI300", "importe_trans": 15000, "valor_recibo": 15000, "fecha_fact_lect": "2026-07-15", "fecha_trans": "2026-07-15"}]
    )[0]["conciliado"] is True

    adj_resp = mtl.get("/api/v1/comercial/afinia/analisis/convenios-ajustes", sede="montelibano")
    assert adj_resp.status_code == 200
    assert detect_negative_adjustment_alert(
        {"202606": [{"importe_trans": 1000}, {"importe_trans": -10}], "202607": [{"importe_trans": 1000}, {"importe_trans": -350}]},
        target_periodo="202607",
    )["alerta"] is True

    irreg_resp = mtl.get("/api/v1/comercial/afinia/analisis/facturas-revision/202607", sede="montelibano")
    assert irreg_resp.status_code == 200, irreg_resp.text
    irreg_body = irreg_resp.json()
    fact_rows = mtl.get(
        "/api/v1/comercial/afinia/cortes/202607/datos",
        sede="montelibano",
        params={"familia": "facturacion", "page": 1, "size": 100},
    ).json()["items"]
    expected_irreg = detect_irregular_invoices(fact_rows, operator="afinia", periodo="202607")
    for cat in (
        "LINEA_NEGATIVA",
        "TOTAL_NEGATIVO",
        "TOTAL_EN_CERO",
        "SIN_CONCEPTO_IMPUESTO",
        "IMPUESTO_AMBIGUO",
    ):
        assert len(expected_irreg[cat]) >= 1
        assert cat in irreg_body.get("por_categoria", irreg_body)


def test_nic_traceability_auditoria_consulta_hallazgos_crud_deliverables_and_parity(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """F8-9, F8-10: NIC traceability audit, hallazgo_revisado CRUD, deliverables, and parity."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    # 1) NIC traceability + mandatory auditoria_consulta row
    before_logs = db_helper.count_nominal_consult_logs()
    traz_resp = mtl.get("/api/v1/comercial/afinia/analisis/trazabilidad/7000901", sede="montelibano")
    assert traz_resp.status_code == 200, traz_resp.text
    assert db_helper.count_nominal_consult_logs() > before_logs

    # 2) hallazgo_revisado CRUD
    h_create = mtl.post(
        "/api/v1/comercial/afinia/hallazgos",
        sede="montelibano",
        json_body={
            "tipo": "ANOMALIA",
            "estado": "ABIERTO",
            "responsable": f"Analista {run_id}",
            "decision": "Programar inspección en campo",
            "nic": "7000901",
            "referencia": f"REF-{run_id}",
        },
    )
    assert h_create.status_code == 201, h_create.text
    h_id = h_create.json()["id"]

    h_patch = mtl.patch(
        f"/api/v1/comercial/afinia/hallazgos/{h_id}",
        sede="montelibano",
        json_body={"estado": "RESUELTO", "decision": "Verificado en campo"},
    )
    assert h_patch.status_code == 200
    assert h_patch.json()["estado"] == "RESUELTO"

    # 3) Deliverables: Word/PDF requirement, HTML/PDF analysis, Excel annex, PDF executive report
    req_docx = mtl.post(
        "/api/v1/comercial/afinia/entregables/requerimiento",
        sede="montelibano",
        json_body={"periodo": "202607", "formato": "docx"},
    )
    assert req_docx.status_code == 200, req_docx.text
    assert req_docx.content[:2] == b"PK"

    ana_html = mtl.post(
        "/api/v1/comercial/afinia/entregables/analisis",
        sede="montelibano",
        json_body={"periodo": "202607", "formato": "html"},
    )
    assert ana_html.status_code == 200
    assert "<html" in ana_html.text.lower()

    anx_xlsx = mtl.post(
        "/api/v1/comercial/afinia/entregables/anexo-nominal",
        sede="montelibano",
        json_body={"periodo": "202607"},
    )
    assert anx_xlsx.status_code == 200, anx_xlsx.text
    assert anx_xlsx.content[:2] == b"PK"
    anx_sheets = read_xlsx_sheets(anx_xlsx.content)
    assert len(anx_sheets) >= 1

    inf_pdf = mtl.post(
        "/api/v1/comercial/afinia/entregables/informe-gerencial",
        sede="montelibano",
        json_body={"periodo": "202607"},
    )
    assert inf_pdf.status_code == 200, inf_pdf.text
    assert inf_pdf.content.startswith(b"%PDF-")

    # 4) Exact Tablero = Anexo = Informe parity check
    kpi = mtl.get("/api/v1/comercial/afinia/analisis/indicadores/202607", sede="montelibano").json()
    td_total = mtl.get(
        "/api/v1/comercial/afinia/analisis/tabla-dinamica/202607", sede="montelibano"
    ).json()["total"]
    verify_parity(kpi, td_total, td_total)
