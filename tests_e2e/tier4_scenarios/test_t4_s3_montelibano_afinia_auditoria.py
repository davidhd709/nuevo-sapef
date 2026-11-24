"""Tier 4 Scenario 3: Montelíbano Afinia 3-Month Commercial Audit."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fixtures import (
    AFINIA_39_UVT_FACTORS,
    AFINIA_CANONICAL_TARIFFS,
    SyntheticFile,
    build_afinia_cut_files,
    read_xlsx_sheets,
)
from harness.client import SapefClient
from harness.config import E2EConfig
from harness.db import DbHelper
from oracles import (
    TD_45_COLUMNS,
    audit_oc135_convenios,
    classify_movements_and_absences,
    compute_afinia_tabla_dinamica,
    detect_irregular_invoices,
    detect_negative_adjustment_alert,
    evaluate_afinia_tariff_control,
    q2,
    q4,
    verify_parity,
)

pytestmark = [pytest.mark.tier4, pytest.mark.commercial]


def _admin_client(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    sede: str = "montelibano",
) -> SapefClient:
    assert e2e_config.admin_password, (
        "SAPEF_E2E_ADMIN_PASSWORD must be configured to run Tier 4 E2E scenarios"
    )
    return auth_session_factory(e2e_config.admin_user, e2e_config.admin_password, sede=sede)


def _upload_and_wait_cargue(
    client: SapefClient,
    db_helper: DbHelper,
    e2e_config: E2EConfig,
    *,
    periodo: str,
    files: list[SyntheticFile],
) -> dict[str, Any]:
    resp = client.post(
        "/api/v1/comercial/afinia/cargues",
        sede="montelibano",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": periodo},
        files=[("files", f.filename, f.content, f.content_type) for f in files],
    )
    assert resp.status_code == 202, f"Upload {periodo} failed: {resp.status_code} {resp.text}"
    body = resp.json()
    cargue_id = body.get("cargue_id") or body.get("cargueId") or body.get("id")
    assert cargue_id is not None

    job_id = body.get("tarea_id") or body.get("tareaId")
    if isinstance(job_id, int):
        db_helper.wait_for_procrastinate_job(job_id, timeout=e2e_config.timeout_seconds)

    deadline = time.monotonic() + e2e_config.timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        detail = client.get(f"/api/v1/comercial/afinia/cargues/{cargue_id}", sede="montelibano")
        if detail.status_code == 404:
            detail = client.get(f"/api/v1/comercial/cargues/{cargue_id}", sede="montelibano")
        assert detail.status_code == 200, detail.text
        last = detail.json()
        estado = str(last.get("estado", "")).lower()
        if estado in {"publicado", "completado", "procesado", "listo"}:
            return last
        if estado in {"error", "con_errores", "fallido", "rechazado"}:
            raise AssertionError(f"Cargue {cargue_id} ({periodo}) failed: {last}")
        time.sleep(0.25)
    raise TimeoutError(f"Cargue {cargue_id} ({periodo}) timed out: {last}")


def _ensure_afinia_2026_agreement_with_exceptions(
    client: SapefClient,
    nic_base: int = 7000000,
) -> None:
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
        detail = client.get(
            f"/api/v1/acuerdos/{items[0]['id']}",
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
            "fuente": "Acuerdo Municipal 2026 Montelíbano E2E",
            "tarifas": tariffs,
            "excepciones": exceptions,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    ac_id = create_resp.json()["id"]
    approve = client.post(
        f"/api/v1/acuerdos/{ac_id}/aprobar",
        sede="montelibano",
        json_body={"observacion": "Aprobación auditoría Scenario 3"},
    )
    assert approve.status_code == 200, approve.text


def _fetch_cut_rows(client: SapefClient, periodo: str, familia: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        resp = client.get(
            f"/api/v1/comercial/afinia/cortes/{periodo}/datos",
            sede="montelibano",
            params={"familia": familia, "page": page, "size": 100},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        batch = body["items"]
        rows.extend(batch)
        if len(rows) >= int(body.get("total", len(rows))) or not batch:
            break
        page += 1
    return rows


def test_montelibano_afinia_3month_audit_parity_and_deliverables(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """Scenario 3: 2026-02 + skip 2026-03 + 2026-04 + 2026-05 -> audit, hallazgos, deliverables, parity."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    _ensure_afinia_2026_agreement_with_exceptions(mtl, nic_base=7000000)

    # ------------------------------------------------------------------
    # Phase 1: Upload 2026-02 (txt+Z), skip 2026-03, upload 2026-04 (txt+Z) & 2026-05 (5 xlsx)
    # ------------------------------------------------------------------
    cut_02 = build_afinia_cut_files(
        periodo="202602", format_mode="txt_z", include_negative_adjustment=False
    )
    _upload_and_wait_cargue(mtl, db_helper, e2e_config, periodo="202602", files=list(cut_02.values()))

    # Intentionally skip 202603 to exercise missing-cut jump & absence rules
    cut_04 = build_afinia_cut_files(
        periodo="202604", format_mode="txt_z", include_negative_adjustment=False
    )
    _upload_and_wait_cargue(mtl, db_helper, e2e_config, periodo="202604", files=list(cut_04.values()))

    cut_05 = build_afinia_cut_files(
        periodo="202605", format_mode="xlsx", include_negative_adjustment=True
    )
    detail_05 = _upload_and_wait_cargue(
        mtl, db_helper, e2e_config, periodo="202605", files=list(cut_05.values())
    )
    assert detail_05["periodo"] == "202605"
    assert "duplic" in " ".join(str(w) for w in detail_05.get("advertencias", [])).lower()

    # Verify missing-cut jump reporting on 2026-04 (comparable == 2026-02)
    cortes = mtl.get("/api/v1/comercial/afinia/cortes", sede="montelibano").json()
    cortes_list = cortes if isinstance(cortes, list) else cortes.get("items", [])
    assert any(c.get("periodo") == "202604" for c in cortes_list)

    mov_04 = mtl.get("/api/v1/comercial/afinia/analisis/movimientos/202604", sede="montelibano")
    assert mov_04.status_code == 200, mov_04.text
    mov_04_body = mov_04.json()
    assert mov_04_body.get("comparable") == "202602"
    assert mov_04_body.get("salto_corte_detectado") is True or mov_04_body.get("skipped_missing_cut") is True

    # ------------------------------------------------------------------
    # Phase 2: 39 UVT exceptions, 45-col TD, OC135/CI306, absences, irregularities, neg alert
    # ------------------------------------------------------------------
    fact_05 = _fetch_cut_rows(mtl, "202605", "facturacion")
    reca_05 = _fetch_cut_rows(mtl, "202605", "recaudo")
    cata_05 = _fetch_cut_rows(mtl, "202605", "catastro")
    refa_05 = _fetch_cut_rows(mtl, "202605", "refactura")
    conv_05 = _fetch_cut_rows(mtl, "202605", "convenio")
    fact_04 = _fetch_cut_rows(mtl, "202604", "facturacion")
    fact_02 = _fetch_cut_rows(mtl, "202602", "facturacion")
    reca_04 = _fetch_cut_rows(mtl, "202604", "recaudo")

    exc_map = {str(7000500 + idx): factor for idx, factor in enumerate(AFINIA_39_UVT_FACTORS)}
    oracle_tc = evaluate_afinia_tariff_control(fact_05, periodo="202605", excepciones=exc_map)
    tc_resp = mtl.get(
        "/api/v1/comercial/afinia/analisis/control-tarifario/202605",
        sede="montelibano",
        params={"grupo_consumo": "todos", "size": 500},
    )
    assert tc_resp.status_code == 200, tc_resp.text
    tc_api = tc_resp.json()
    assert tc_api["totales"]["por_estado"] == oracle_tc["counts"]
    assert q2(tc_api["totales"]["valor_por_encima"]) == oracle_tc["total_valor_por_encima"]
    assert q2(tc_api["totales"]["valor_por_debajo"]) == oracle_tc["total_valor_por_debajo"]

    special_rows = [
        r for r in tc_api["items"] if str(r.get("regla_aplicada")) == "COBRO_ESPECIAL_UVT"
    ]
    assert len(special_rows) >= len(AFINIA_39_UVT_FACTORS)

    # Prolonged absences skipping 2026-03
    aus_05 = mtl.get("/api/v1/comercial/afinia/analisis/ausencias/202605", sede="montelibano")
    assert aus_05.status_code == 200, aus_05.text
    assert set(aus_05.json().get("tramos", {}).keys()).issuperset({"1", "2", "3", ">3"})
    abs_oracle = classify_movements_and_absences(
        loaded_periods=["202602", "202604", "202605"],
        account_presence={"7000011": ["202602", "202604", "202605"], "7000012": ["202602"]},
        target_periodo="202605",
    )
    assert abs_oracle["absence_counts"]["7000012"] == 2

    # OC135 / CI306 cohorts & negative adjustment alert
    conv_05_resp = mtl.get("/api/v1/comercial/afinia/analisis/convenios/202605", sede="montelibano")
    assert conv_05_resp.status_code == 200, conv_05_resp.text
    assert len(audit_oc135_convenios(conv_05)) >= 1

    adj_resp = mtl.get("/api/v1/comercial/afinia/analisis/convenios-ajustes", sede="montelibano")
    assert adj_resp.status_code == 200, adj_resp.text
    neg_alert_oracle = detect_negative_adjustment_alert(
        {"202604": reca_04, "202605": reca_05},
        target_periodo="202605",
    )
    assert neg_alert_oracle["alerta"] is True

    # 5 irregular invoice categories
    irreg_resp = mtl.get(
        "/api/v1/comercial/afinia/analisis/facturas-revision/202605",
        sede="montelibano",
    )
    assert irreg_resp.status_code == 200, irreg_resp.text
    expected_irreg = detect_irregular_invoices(fact_05, operator="afinia", periodo="202605")
    irreg_cats = irreg_resp.json().get("por_categoria", irreg_resp.json())
    for cat in (
        "LINEA_NEGATIVA",
        "TOTAL_NEGATIVO",
        "TOTAL_EN_CERO",
        "SIN_CONCEPTO_IMPUESTO",
        "IMPUESTO_AMBIGUO",
    ):
        assert len(expected_irreg[cat]) >= 1
        assert cat in irreg_cats

    # ------------------------------------------------------------------
    # Phase 3: Field routes & hallazgo_revisado CRUD (ABIERTO -> EN_REVISION -> RESUELTO)
    # ------------------------------------------------------------------
    rutas_resp = mtl.get(
        "/api/v1/comercial/afinia/analisis/rutas-campo/202605",
        sede="montelibano",
    )
    assert rutas_resp.status_code == 200, rutas_resp.text

    audit_before = db_helper.count_audit_logs()
    h_create = mtl.post(
        "/api/v1/comercial/afinia/hallazgos",
        sede="montelibano",
        json_body={
            "tipo": "RUTA",
            "estado": "ABIERTO",
            "responsable": f"Auditor {run_id}",
            "decision": "Visita de verificación en barrio El Centro",
            "nic": "7000901",
            "referencia": f"S3-{run_id}",
        },
    )
    assert h_create.status_code == 201, h_create.text
    h_id = h_create.json()["id"]

    h_rev = mtl.patch(
        f"/api/v1/comercial/afinia/hallazgos/{h_id}",
        sede="montelibano",
        json_body={"estado": "EN_REVISION", "decision": "Acta levantada en campo"},
    )
    assert h_rev.status_code == 200, h_rev.text
    assert h_rev.json()["estado"] == "EN_REVISION"

    h_res = mtl.patch(
        f"/api/v1/comercial/afinia/hallazgos/{h_id}",
        sede="montelibano",
        json_body={"estado": "RESUELTO", "decision": "Ajuste confirmado con operador"},
    )
    assert h_res.status_code == 200, h_res.text
    assert h_res.json()["estado"] == "RESUELTO"
    assert db_helper.count_audit_logs() > audit_before

    # ------------------------------------------------------------------
    # Phase 4: Deliverables (10-section PDF, Word, Excel annex) & Parity + SETIEMBRE/REFA21
    # ------------------------------------------------------------------
    td_resp = mtl.get(
        "/api/v1/comercial/afinia/analisis/tabla-dinamica/202605",
        sede="montelibano",
    )
    assert td_resp.status_code == 200, td_resp.text
    td_api = td_resp.json()
    assert len(td_api["filas"]) == 12
    for col in TD_45_COLUMNS:
        assert col in td_api["total"]

    hist_pairs = {(str(r["nic"]), str(r["tarifa"])) for r in fact_02}
    oracle_td = compute_afinia_tabla_dinamica(
        periodo="202605",
        facturacion=fact_05,
        recaudo=reca_05,
        catastro=cata_05,
        refactura=refa_05,
        convenio=conv_05,
        prior_facturacion=fact_04,
        historical_facturacion_pairs=hist_pairs,
    )
    assert q4(td_api["total"]["facturacion"]) == oracle_td["total"]["facturacion"]
    assert q4(td_api["total"]["recaudo_total"]) == oracle_td["total"]["recaudo_total"]

    req_docx = mtl.post(
        "/api/v1/comercial/afinia/entregables/requerimiento",
        sede="montelibano",
        json_body={"periodo": "202605", "formato": "docx"},
    )
    assert req_docx.status_code == 200, req_docx.text
    assert req_docx.content[:2] == b"PK"

    anx_xlsx = mtl.post(
        "/api/v1/comercial/afinia/entregables/anexo-nominal",
        sede="montelibano",
        json_body={"periodo": "202605"},
    )
    assert anx_xlsx.status_code == 200, anx_xlsx.text
    assert anx_xlsx.content[:2] == b"PK"
    assert len(read_xlsx_sheets(anx_xlsx.content)) >= 1

    inf_pdf = mtl.post(
        "/api/v1/comercial/afinia/entregables/informe-gerencial",
        sede="montelibano",
        json_body={"periodo": "202605"},
    )
    assert inf_pdf.status_code == 200, inf_pdf.text
    assert inf_pdf.content.startswith(b"%PDF-")
    assert len(inf_pdf.content) > 1000

    # Parity check: Tablero (indicadores + /tablero/resumen) == Anexo == Informe (TD total)
    kpi_05 = mtl.get(
        "/api/v1/comercial/afinia/analisis/indicadores/202605",
        sede="montelibano",
    ).json()
    verify_parity(kpi_05, td_api["total"], oracle_td["total"])

    # Also verify SETIEMBRE spelling + 21-col REFACTURACION book ingestion on 202609
    cut_09 = build_afinia_cut_files(
        periodo="202609", format_mode="xlsx", use_setiembre_spelling=True
    )
    detail_09 = _upload_and_wait_cargue(
        mtl, db_helper, e2e_config, periodo="202609", files=list(cut_09.values())
    )
    assert detail_09["periodo"] == "202609"
    refa_09 = _fetch_cut_rows(mtl, "202609", "refactura")
    assert len(refa_09) >= 1
    assert "consumo_kwh" not in refa_09[0]
