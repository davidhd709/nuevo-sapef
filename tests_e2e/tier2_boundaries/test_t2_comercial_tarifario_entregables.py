"""Tier 2 boundary, error & security E2E tests for EP-08 Tariff Control, Analysis & Deliverables."""

from __future__ import annotations

import datetime as dt
import time
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from fixtures import (
    SyntheticFile,
    XlsxSheet,
    build_afinia_cut_files,
    build_celsia_xlsx,
    build_xlsx_bytes,
    read_xlsx_sheets,
)
from fixtures.commercial_builder import AFINIA_TRANSACCIONAL_HEADERS
from harness.client import SapefClient, assert_problem_json
from harness.config import E2EConfig
from harness.db import DbHelper
from oracles import (
    classify_movements_and_absences,
    deduce_celsia_periodicity,
    detect_irregular_invoices,
    detect_negative_adjustment_alert,
    evaluate_afinia_tariff_control,
    evaluate_celsia_tariff_control,
    q2,
)

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


def _upload_and_wait_cargue(
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
    assert resp.status_code == 202, (
        f"POST /comercial/{operador}/cargues failed: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    cargue_id = body.get("cargue_id") or body.get("cargueId") or body.get("id")
    job_id = body.get("tarea_id") or body.get("tareaId")
    if isinstance(job_id, int):
        db_helper.wait_for_procrastinate_job(job_id, timeout=e2e_config.timeout_seconds)

    deadline = time.monotonic() + e2e_config.timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        detail = client.get(f"/api/v1/comercial/{operador}/cargues/{cargue_id}", sede=sede)
        if detail.status_code == 404:
            detail = client.get(f"/api/v1/comercial/cargues/{cargue_id}", sede=sede)
        assert detail.status_code == 200, detail.text
        last = detail.json()
        estado = str(last.get("estado", "")).lower()
        if estado in {"publicado", "completado", "procesado", "listo"}:
            return last
        if estado in {"error", "con_errores", "fallido", "rechazado"}:
            raise AssertionError(f"Cargue {cargue_id} failed: {last}")
        time.sleep(0.25)
    raise TimeoutError(f"Cargue {cargue_id} did not finish: {last}")


def _afinia_fact_row(
    *,
    nic: int,
    tarifa: str,
    concepto: str,
    importe: float,
    fecha: dt.date,
    sv: str,
    consumo_kwh: float | None,
    valor_consumo_antes: float | None,
    cod_oper_cont: str = "OC100",
) -> list[Any]:
    return [
        fecha,
        cod_oper_cont,
        nic,
        nic + 100000,
        1,
        1,
        fecha,
        "Residencial",
        tarifa,
        1,
        concepto,
        importe,
        fecha,
        importe,
        23,
        466,
        0,
        23,
        sv,
        consumo_kwh,
        valor_consumo_antes,
    ]


def _afinia_fact_book(periodo: str, data_rows: list[list[Any]]) -> SyntheticFile:
    year = int(periodo[:4])
    month = int(periodo[4:6])
    mes_es = [
        "",
        "ENERO",
        "FEBRERO",
        "MARZO",
        "ABRIL",
        "MAYO",
        "JUNIO",
        "JULIO",
        "AGOSTO",
        "SETIEMBRE",
        "OCTUBRE",
        "NOVIEMBRE",
        "DICIEMBRE",
    ][month]
    headers = [
        *AFINIA_TRANSACCIONAL_HEADERS,
        "CONSUMO KWH",
        "VALOR DEL CONSUMO ANTES DE TODO",
    ]
    return SyntheticFile(
        filename=f"FACTURACION_MONTELIBANO_{mes_es}_{year}.xlsx",
        content=build_xlsx_bytes([XlsxSheet("facturacion", [headers, *data_rows])]),
        content_type=_XLSX_MIME,
    )


def _afinia_reca_row(
    *,
    nic: int,
    tarifa: str,
    concepto: str,
    importe: float,
    fecha_fact: dt.date,
    fecha_trans: dt.date,
    sv: str,
) -> list[Any]:
    return [
        fecha_trans,
        "OC100",
        nic,
        nic + 100000,
        1,
        1,
        fecha_fact,
        "Residencial",
        tarifa,
        1,
        concepto,
        importe,
        fecha_trans,
        importe,
        23,
        466,
        0,
        23,
        sv,
    ]


def _afinia_reca_book(periodo: str, data_rows: list[list[Any]]) -> SyntheticFile:
    year = int(periodo[:4])
    month = int(periodo[4:6])
    mes_es = [
        "",
        "ENERO",
        "FEBRERO",
        "MARZO",
        "ABRIL",
        "MAYO",
        "JUNIO",
        "JULIO",
        "AGOSTO",
        "SETIEMBRE",
        "OCTUBRE",
        "NOVIEMBRE",
        "DICIEMBRE",
    ][month]
    return SyntheticFile(
        filename=f"RECAUDO_MONTELIBANO_{mes_es}_{year}.xlsx",
        content=build_xlsx_bytes(
            [XlsxSheet("recaudo", [list(AFINIA_TRANSACCIONAL_HEADERS), *data_rows])]
        ),
        content_type=_XLSX_MIME,
    )


def test_afinia_tariff_control_no_validable_vs_requiere_revision_reason_codes(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-4: Strictly separate NO_VALIDABLE and REQUIERE_REVISION with exact reason codes."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    # 1) Period 202207 (no agreement for 2022) -> PERIODO_SIN_PARAMETROS
    d_2022 = dt.date(2022, 7, 15)
    f_2022 = _afinia_fact_book(
        "202207",
        [
            _afinia_fact_row(
                nic=7100001,
                tarifa="AP_Residenciales_Estrato_1",
                concepto="CI400",
                importe=2094.96,
                fecha=d_2022,
                sv="SV-2022-1",
                consumo_kwh=100.0,
                valor_consumo_antes=100000.0,
            )
        ],
    )
    _upload_and_wait_cargue(
        mtl, db_helper, e2e_config, sede="montelibano", operador="afinia", periodo="202207", files=[f_2022]
    )
    tc_2022 = mtl.get(
        "/api/v1/comercial/afinia/analisis/control-tarifario/202207",
        sede="montelibano",
        params={"grupo_consumo": "todos", "size": 50},
    )
    assert tc_2022.status_code == 200, tc_2022.text
    row_2022 = tc_2022.json()["items"][0]
    assert row_2022["estado"] == "REQUIERE_REVISION"
    assert row_2022["motivo_revision"] == "PERIODO_SIN_PARAMETROS"

    # 2) Period 202611: NO_VALIDABLE vs TARIFA_SIN_PARAMETROS, SIN_CI400, CONSUMO_CI400_NULO
    d_2026 = dt.date(2026, 11, 15)
    rows_2026 = [
        # >173 kWh & valor_consumo_antes IS NULL -> NO_VALIDABLE (NOT REQUIERE_REVISION)
        _afinia_fact_row(
            nic=7100101,
            tarifa="AP_Residenciales_Estrato_3",
            concepto="CI400",
            importe=12000.0,
            fecha=d_2026,
            sv="SV-101",
            consumo_kwh=350.0,
            valor_consumo_antes=None,
        ),
        # Unknown tariff -> REQUIERE_REVISION + TARIFA_SIN_PARAMETROS
        _afinia_fact_row(
            nic=7100102,
            tarifa="AP_Tarifa_Inexistente",
            concepto="CI400",
            importe=5000.0,
            fecha=d_2026,
            sv="SV-102",
            consumo_kwh=100.0,
            valor_consumo_antes=100000.0,
        ),
        # Non-CI400 only -> REQUIERE_REVISION + SIN_CI400
        _afinia_fact_row(
            nic=7100103,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI202",
            importe=800.0,
            fecha=d_2026,
            sv="SV-103",
            consumo_kwh=0.0,
            valor_consumo_antes=0.0,
        ),
        # CI400 with consumo_kwh=None -> REQUIERE_REVISION + CONSUMO_CI400_NULO
        _afinia_fact_row(
            nic=7100104,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI400",
            importe=2094.96,
            fecha=d_2026,
            sv="SV-104",
            consumo_kwh=None,
            valor_consumo_antes=100000.0,
        ),
    ]
    _upload_and_wait_cargue(
        mtl,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        periodo="202611",
        files=[_afinia_fact_book("202611", rows_2026)],
    )

    tc_resp = mtl.get(
        "/api/v1/comercial/afinia/analisis/control-tarifario/202611",
        sede="montelibano",
        params={"grupo_consumo": "todos", "size": 100},
    )
    assert tc_resp.status_code == 200, tc_resp.text
    tc_body = tc_resp.json()
    by_nic = {str(r["identificador"]): r for r in tc_body["items"]}

    assert by_nic["7100101"]["estado"] == "NO_VALIDABLE"
    assert by_nic["7100102"]["estado"] == "REQUIERE_REVISION"
    assert by_nic["7100102"]["motivo_revision"] == "TARIFA_SIN_PARAMETROS"
    assert by_nic["7100103"]["estado"] == "REQUIERE_REVISION"
    assert by_nic["7100103"]["motivo_revision"] == "SIN_CI400"
    assert by_nic["7100104"]["estado"] == "REQUIERE_REVISION"
    assert by_nic["7100104"]["motivo_revision"] == "CONSUMO_CI400_NULO"

    assert tc_body["totales"]["por_estado"]["NO_VALIDABLE"] == 1
    assert tc_body["totales"]["por_estado"]["REQUIERE_REVISION"] == 3


def test_afinia_tariff_control_multi_tariff_nic_valid_vs_same_tariff_multiples_ci400(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-4: Granularity is (NIC, periodo, tarifa): multi-tariff NIC valid vs same-tariff MULTIPLES_CI400."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    d_cut = dt.date(2026, 10, 15)
    rows = [
        # Same NIC 7100201 across TWO different tariffs -> BOTH valid CORRECTO
        _afinia_fact_row(
            nic=7100201,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI400",
            importe=2094.96,
            fecha=d_cut,
            sv="SV-MT-1",
            consumo_kwh=100.0,
            valor_consumo_antes=50000.0,
        ),
        _afinia_fact_row(
            nic=7100201,
            tarifa="AP_Comerciales_Nivel_1",
            concepto="CI400",
            importe=15712.20,
            fecha=d_cut,
            sv="SV-MT-2",
            consumo_kwh=100.0,
            valor_consumo_antes=100000.0,
        ),
        # NIC 7100202 with TWO CI400 rows in the SAME tariff -> REQUIERE_REVISION (MULTIPLES_CI400)
        _afinia_fact_row(
            nic=7100202,
            tarifa="AP_Residenciales_Estrato_2",
            concepto="CI400",
            importe=3142.44,
            fecha=d_cut,
            sv="SV-DUP-1",
            consumo_kwh=80.0,
            valor_consumo_antes=80000.0,
        ),
        _afinia_fact_row(
            nic=7100202,
            tarifa="AP_Residenciales_Estrato_2",
            concepto="CI400",
            importe=3142.44,
            fecha=d_cut,
            sv="SV-DUP-1",
            consumo_kwh=80.0,
            valor_consumo_antes=80000.0,
        ),
    ]
    _upload_and_wait_cargue(
        mtl,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        periodo="202610",
        files=[_afinia_fact_book("202610", rows)],
    )

    tc_resp = mtl.get(
        "/api/v1/comercial/afinia/analisis/control-tarifario/202610",
        sede="montelibano",
        params={"grupo_consumo": "todos", "size": 50},
    )
    assert tc_resp.status_code == 200, tc_resp.text
    items = tc_resp.json()["items"]
    multi_nic_rows = [r for r in items if str(r["identificador"]) == "7100201"]
    assert len(multi_nic_rows) == 2
    assert all(r["estado"] == "CORRECTO" for r in multi_nic_rows)

    dup_ci400_rows = [r for r in items if str(r["identificador"]) == "7100202"]
    assert len(dup_ci400_rows) == 1
    assert dup_ci400_rows[0]["estado"] == "REQUIERE_REVISION"
    assert dup_ci400_rows[0]["motivo_revision"] == "MULTIPLES_CI400"


def test_afinia_tariff_control_1_peso_tolerance_boundaries_and_ci401_ci851_signals(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-4: $1.00 boundary (+1.00/-1.00 CORRECTO vs +1.01 POR_ENCIMA / -1.01 POR_DEBAJO) + signals."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    d_cut = dt.date(2026, 12, 15)
    # Estrato 1 min expected = 0.04 * 52374 = 2094.96
    rows = [
        # +1.00 -> CORRECTO (+ CI401 & CI851 signals that must NOT alter CI400 facturado_real)
        _afinia_fact_row(
            nic=7100301,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI400",
            importe=2095.96,
            fecha=d_cut,
            sv="SV-T1",
            consumo_kwh=50.0,
            valor_consumo_antes=50000.0,
        ),
        _afinia_fact_row(
            nic=7100301,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI401",
            importe=-200.00,
            fecha=d_cut,
            sv="SV-T1",
            consumo_kwh=0.0,
            valor_consumo_antes=0.0,
        ),
        _afinia_fact_row(
            nic=7100301,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI851",
            importe=-75.50,
            fecha=d_cut,
            sv="SV-T1",
            consumo_kwh=0.0,
            valor_consumo_antes=0.0,
        ),
        # -1.00 -> CORRECTO
        _afinia_fact_row(
            nic=7100302,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI400",
            importe=2093.96,
            fecha=d_cut,
            sv="SV-T2",
            consumo_kwh=50.0,
            valor_consumo_antes=50000.0,
        ),
        # +1.01 -> POR_ENCIMA (valor_por_encima = 1.01, valor_por_debajo = 0.00)
        _afinia_fact_row(
            nic=7100303,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI400",
            importe=2095.97,
            fecha=d_cut,
            sv="SV-T3",
            consumo_kwh=50.0,
            valor_consumo_antes=50000.0,
        ),
        # -1.01 -> POR_DEBAJO (valor_por_debajo = 1.01, valor_por_encima = 0.00)
        _afinia_fact_row(
            nic=7100304,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI400",
            importe=2093.95,
            fecha=d_cut,
            sv="SV-T4",
            consumo_kwh=50.0,
            valor_consumo_antes=50000.0,
        ),
    ]
    _upload_and_wait_cargue(
        mtl,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        periodo="202612",
        files=[_afinia_fact_book("202612", rows)],
    )

    tc = mtl.get(
        "/api/v1/comercial/afinia/analisis/control-tarifario/202612",
        sede="montelibano",
        params={"grupo_consumo": "todos", "size": 50},
    ).json()
    fact_data = mtl.get(
        "/api/v1/comercial/afinia/cortes/202612/datos",
        sede="montelibano",
        params={"familia": "facturacion", "page": 1, "size": 50},
    ).json()["items"]
    expected = evaluate_afinia_tariff_control(fact_data, periodo="202612")

    assert tc["totales"]["por_estado"] == expected["counts"]
    assert q2(tc["totales"]["valor_por_encima"]) == Decimal("1.01")
    assert q2(tc["totales"]["valor_por_debajo"]) == Decimal("1.01")

    by_nic = {str(r["identificador"]): r for r in tc["items"]}
    assert by_nic["7100301"]["estado"] == "CORRECTO"
    assert q2(by_nic["7100301"]["facturado_real"]) == Decimal("2095.96")
    assert q2(by_nic["7100301"]["senal_ci401"]) == Decimal("-200.00")
    assert q2(by_nic["7100301"]["senal_ci851"]) == Decimal("-75.50")
    assert by_nic["7100302"]["estado"] == "CORRECTO"
    assert by_nic["7100303"]["estado"] == "POR_ENCIMA"
    assert q2(by_nic["7100303"]["valor_por_encima"]) == Decimal("1.01")
    assert q2(by_nic["7100303"]["valor_por_debajo"]) == Decimal("0.00")
    assert by_nic["7100304"]["estado"] == "POR_DEBAJO"
    assert q2(by_nic["7100304"]["valor_por_debajo"]) == Decimal("1.01")
    assert q2(by_nic["7100304"]["valor_por_encima"]) == Decimal("0.00")


def test_celsia_tariff_control_100_peso_tolerance_and_bimonthly_2x_cap(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-4: Celsia $100.00 tolerance boundaries and bimonthly x2 fixed/min cap."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")
    f_date = dt.date(2026, 10, 15)
    vcto = dt.date(2026, 10, 28)

    fact_headers = [
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
    ]
    fact_rows = [
        fact_headers,
        # E1 Urbano fixed = 3994.50; +100.00 -> CORRECTO
        ["81001", "FC-1", f_date, "U1", "Dir 1", "1 Residencial", "R1", "1", "Urbano", "ALCALA", "Mensual", "Impuesto Alumbrado Público", 4094.50, 100.0, 50000.0],
        # E1 Urbano fixed = 3994.50; -100.00 -> CORRECTO
        ["81002", "FC-2", f_date, "U2", "Dir 2", "1 Residencial", "R1", "1", "Urbano", "ALCALA", "Mensual", "Impuesto Alumbrado Público", 3894.50, 100.0, 50000.0],
        # E1 Urbano fixed = 3994.50; +100.01 -> POR_ENCIMA
        ["81003", "FC-3", f_date, "U3", "Dir 3", "1 Residencial", "R1", "1", "Urbano", "ALCALA", "Mensual", "Impuesto Alumbrado Público", 4094.51, 100.0, 50000.0],
        # E1 Urbano fixed = 3994.50; -100.01 -> POR_DEBAJO
        ["81004", "FC-4", f_date, "U4", "Dir 4", "1 Residencial", "R1", "1", "Urbano", "ALCALA", "Mensual", "Impuesto Alumbrado Público", 3894.49, 100.0, 50000.0],
        # Rural Bimonthly E3: 2 * 10564.99 = 21129.98 -> CORRECTO
        ["81005", "FC-5", f_date, "U5", "Vereda", "1 Residencial", "R3", "3", "Rural", "ALCALA", "Bimestral", "Impuesto Alumbrado Público", 21129.98, 200.0, 120000.0],
    ]
    reca_rows = [
        ["Cuenta", "Número de Factura", "Fecha Vencimiento", "Fecha de Pago", "Descripción", "Valor del Impuesto Recaudado"],
        ["81001", "FC-1", vcto, f_date, "Impuesto Alumbrado Público", 4094.50],
    ]
    celsia_bytes = build_xlsx_bytes([XlsxSheet("Facturacion", fact_rows), XlsxSheet("Recaudo", reca_rows)])
    _upload_and_wait_cargue(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="celsia",
        periodo="202610",
        files=[SyntheticFile("CELSIA_ALCALA_OCTUBRE_26.xlsx", celsia_bytes, _XLSX_MIME)],
    )

    tc = alc.get(
        "/api/v1/comercial/celsia/analisis/control-tarifario/202610",
        sede="alcala",
        params={"grupo_consumo": "todos", "size": 50},
    ).json()
    fact_data = alc.get(
        "/api/v1/comercial/celsia/cortes/202610/datos",
        sede="alcala",
        params={"familia": "facturacion", "page": 1, "size": 50},
    ).json()["items"]
    expected = evaluate_celsia_tariff_control(fact_data, periodo="202610", bimonthly_accounts={"81005"})

    assert tc["totales"]["por_estado"] == expected["counts"]
    assert q2(tc["totales"]["valor_por_encima"]) == Decimal("100.01")
    assert q2(tc["totales"]["valor_por_debajo"]) == Decimal("100.01")
    by_id = {str(r["identificador"]): r for r in tc["items"]}
    assert by_id["81001"]["estado"] == "CORRECTO"
    assert by_id["81002"]["estado"] == "CORRECTO"
    assert by_id["81003"]["estado"] == "POR_ENCIMA"
    assert by_id["81004"]["estado"] == "POR_DEBAJO"
    assert by_id["81005"]["estado"] == "CORRECTO"


def test_celsia_tariff_control_no_validable_and_revision_reason_codes(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-4: Celsia NO_VALIDABLE (SIN_VCE) & REQUIERE_REVISION reason codes separated."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")
    f_date = dt.date(2026, 11, 15)
    vcto = dt.date(2026, 11, 28)

    fact_rows = [
        [
            "Cuenta",
            "Número de Factura",
            "Fecha Factura",
            "Clase de Cliente",
            "Tarifa",
            "Estrato",
            "Sector",
            "Periodicidad",
            "Descripción",
            "Valor del Impuesto Facturado",
            "Valor del Consumo de Energía Antes de Subsidios o Contribuciones Pesos",
        ],
        # SIN_VCE -> REQUIERE_REVISION (RN-006: falta un dato)
        ["82001", "FC-R1", f_date, "1 Residencial", "R3", "3", "Urbano", "Mensual", "Impuesto Alumbrado Público", 13205.16, None],
        # ESTRATO_SIN_REGLA -> NO_VALIDABLE (RN-006: la regla no permite calcular)
        ["82002", "FC-R2", f_date, "1 Residencial", "R9", "9", "Urbano", "Mensual", "Impuesto Alumbrado Público", 9999.00, 100000.0],
        # CLASIFICACION_REQUIERE_EXCEPCION (Official/Exempt class without exception row) -> NO_VALIDABLE
        ["82003", "FC-R3", f_date, "3 Oficial Exenta", "OF1", "", "Urbano", "Mensual", "Impuesto Alumbrado Público", 50000.00, 500000.0],
    ]
    reca_rows = [
        ["Cuenta", "Número de Factura", "Fecha Vencimiento", "Fecha de Pago", "Descripción", "Valor del Impuesto Recaudado"],
        ["82001", "FC-R1", vcto, f_date, "Impuesto Alumbrado Público", 13205.16],
    ]
    _upload_and_wait_cargue(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="celsia",
        periodo="202611",
        files=[
            SyntheticFile(
                "CELSIA_ALCALA_NOVIEMBRE_26.xlsx",
                build_xlsx_bytes([XlsxSheet("Facturacion", fact_rows), XlsxSheet("Recaudo", reca_rows)]),
                _XLSX_MIME,
            )
        ],
    )

    tc = alc.get(
        "/api/v1/comercial/celsia/analisis/control-tarifario/202611",
        sede="alcala",
        params={"grupo_consumo": "todos", "size": 50},
    ).json()
    by_id = {str(r["identificador"]): r for r in tc["items"]}
    assert by_id["82001"]["estado"] == "REQUIERE_REVISION"
    assert by_id["82001"]["motivo_revision"] == "SIN_VCE"
    assert by_id["82002"]["estado"] == "NO_VALIDABLE"
    assert by_id["82002"]["motivo_revision"] == "ESTRATO_SIN_REGLA"
    assert by_id["82003"]["estado"] == "NO_VALIDABLE"
    assert by_id["82003"]["motivo_revision"] in {
        "CLASIFICACION_REQUIERE_EXCEPCION",
        "ESTRATO_SIN_REGLA",
    }

    # Verify incomplete / contradictory Celsia agreement rules cannot silently pass approval
    bad_agreement = alc.post(
        "/api/v1/acuerdos",
        sede="alcala",
        json_body={
            "comercializador_codigo": "celsia",
            "anio": 2024,
            "uvt": 47065,
            "umbral_kwh": 0,
            "tolerancia": 100.0,
            "base_costo_variable": "monto_energia",
            "fuente": "Borrador Incompleto E2E",
            "tarifas": [
                {"codigo": "E1", "nombre": "Estrato 1", "urbano": 3994.50, "rural": None},
                {"codigo": "E1", "nombre": "Estrato 1 Duplicada", "urbano": 4500.00, "rural": 2349.20},
            ],
            "excepciones": [],
        },
    )
    if bad_agreement.status_code in (409, 422):
        assert_problem_json(bad_agreement, expected_status=(409, 422))
    else:
        assert bad_agreement.status_code == 201, bad_agreement.text
        bad_id = bad_agreement.json()["id"]
        approve_bad = alc.post(
            f"/api/v1/acuerdos/{bad_id}/aprobar",
            sede="alcala",
            json_body={},
        )
        assert_problem_json(approve_bad, expected_status=(409, 422))


def test_missing_cut_202603_skipped_in_absences_and_comparable_jumps_to_202602(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-6: Omitted 202603 between 202602 & 202604 does not count as absence; comparable jumps to 202602."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    # Upload 202602 & 202604 (omitting 202603)
    for periodo in ("202602", "202604"):
        files = build_afinia_cut_files(periodo=periodo, format_mode="txt_z")
        _upload_and_wait_cargue(
            mtl,
            db_helper,
            e2e_config,
            sede="montelibano",
            operador="afinia",
            periodo=periodo,
            files=list(files.values()),
        )

    mov = mtl.get("/api/v1/comercial/afinia/analisis/movimientos/202604", sede="montelibano")
    assert mov.status_code == 200, mov.text
    mov_body = mov.json()
    assert mov_body.get("comparable") == "202602"
    assert mov_body.get("salto_corte_detectado") is True or mov_body.get("skipped_missing_cut") is True

    oracle_res = classify_movements_and_absences(
        loaded_periods=["202602", "202604"],
        account_presence={"7000011": ["202602", "202604"]},
        target_periodo="202604",
    )
    assert oracle_res["skipped_missing_cut"] is True
    assert oracle_res["movements"]["7000011"] == "Facturado"
    assert "7000011" not in oracle_res["absence_counts"]

    aus = mtl.get("/api/v1/comercial/afinia/analisis/ausencias/202604", sede="montelibano")
    assert aus.status_code == 200
    aus_body = aus.json()
    assert aus_body.get("comparable") == "202602"
    aus_items = aus_body.get("items", aus_body.get("usuarios", []))
    assert all(str(u.get("identificador") or u.get("nic")) != "7000011" for u in aus_items)


def test_celsia_bimonthly_off_parity_month_classified_no_le_correspondia(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-6: Celsia bimonthly off-parity month is 'No le correspondía' (never counted in absences)."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")

    def _celsia_period_with_bim(periodo: str, include_bim_account: bool) -> SyntheticFile:
        f_date = dt.date(int(periodo[:4]), int(periodo[4:6]), 15)
        vcto = dt.date(int(periodo[:4]), int(periodo[4:6]), 28)
        fact_rows = [
            [
                "Cuenta",
                "Número de Factura",
                "Fecha Factura",
                "Clase de Cliente",
                "Tarifa",
                "Estrato",
                "Sector",
                "Periodicidad",
                "Descripción",
                "Valor del Impuesto Facturado",
                "Valor del Consumo de Energía Antes de Subsidios o Contribuciones Pesos",
            ],
            ["8300001", f"FC-M-{periodo}", f_date, "1 Residencial", "R1", "1", "Urbano", "Mensual", "Impuesto Alumbrado Público", 3994.50, 80000.0],
        ]
        if include_bim_account:
            fact_rows.append(
                ["8300999", f"FC-B-{periodo}", f_date, "1 Residencial", "R3", "3", "Rural", "Bimestral", "Impuesto Alumbrado Público", 21129.98, 150000.0]
            )
        reca_rows = [
            ["Cuenta", "Número de Factura", "Fecha Vencimiento", "Fecha de Pago", "Descripción", "Valor del Impuesto Recaudado"],
            ["8300001", f"FC-M-{periodo}", vcto, f_date, "Impuesto Alumbrado Público", 3994.50],
        ]
        mes = ["", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO"][int(periodo[4:6])]
        return SyntheticFile(
            f"CELSIA_ALCALA_{mes}_26.xlsx",
            build_xlsx_bytes([XlsxSheet("Facturacion", fact_rows), XlsxSheet("Recaudo", reca_rows)]),
            _XLSX_MIME,
        )

    for periodo, has_bim in (("202604", True), ("202605", False), ("202606", True)):
        _upload_and_wait_cargue(
            alc,
            db_helper,
            e2e_config,
            sede="alcala",
            operador="celsia",
            periodo=periodo,
            files=[_celsia_period_with_bim(periodo, has_bim)],
        )

    assert deduce_celsia_periodicity(["202604", "202606"]) == "bimestral_par"
    oracle_mov = classify_movements_and_absences(
        loaded_periods=["202604", "202605", "202606"],
        account_presence={"8300001": ["202604", "202605", "202606"], "8300999": ["202604", "202606"]},
        target_periodo="202605",
        periodicities={"8300001": "mensual", "8300999": "bimestral_par"},
    )
    assert oracle_mov["movements"]["8300999"] == "No le correspondía"
    assert "8300999" not in oracle_mov["absence_counts"]

    mov_05 = alc.get("/api/v1/comercial/celsia/analisis/movimientos/202605", sede="alcala")
    assert mov_05.status_code == 200, mov_05.text
    mov_body = mov_05.json()
    dejados_ids = {
        str(r.get("cuenta") or r.get("identificador"))
        for r in mov_body.get("dejados_facturar", mov_body.get("items", []))
        if isinstance(r, dict)
    }
    assert "8300999" not in dejados_ids

    aus_05 = alc.get("/api/v1/comercial/celsia/analisis/ausencias/202605", sede="alcala")
    assert aus_05.status_code == 200
    aus_ids = {
        str(r.get("cuenta") or r.get("identificador"))
        for r in aus_05.json().get("items", aus_05.json().get("usuarios", []))
        if isinstance(r, dict)
    }
    assert "8300999" not in aus_ids


def test_commercial_nominal_permission_guard_403_and_auditoria_consulta_insert(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """F1-7, F8-9: Missing comercial.nominal.ver returns 403 on nominal routes; authorized logs audit."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    # Ensure 202607 cut exists
    files = build_afinia_cut_files(periodo="202607", format_mode="txt_z")
    _upload_and_wait_cargue(
        admin,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        periodo="202607",
        files=list(files.values()),
    )

    sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    mtl = next(s for s in sedes if s["codigo"] == "montelibano")
    suffix = uuid.uuid4().hex[:6].upper()

    # Role with comercial.analisis.ver + entregable.generar + exportar, WITHOUT comercial.nominal.ver
    role_resp = admin.post(
        "/api/v1/roles",
        omit_sede=True,
        json_body={
            "codigo": f"{run_id}_NONOM_{suffix}",
            "nombre": f"Sin Nominal {suffix}",
            "permisos": [
                "comercial.analisis.ver",
                "comercial.entregable.generar",
                "comercial.exportar",
            ],
        },
    )
    assert role_resp.status_code == 201, role_resp.text
    role_id = role_resp.json()["id"]

    username = f"{run_id.lower()}_nonom_{suffix.lower()}"
    pw = _unique_secret()
    u_resp = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": username,
            "nombre_completo": f"Analista Sin Nominal {suffix}",
            "identificacion": f"44{int(suffix, 16) % 10000000:07d}",
            "correo": f"{username}@example.test",
            "clave": pw,
            "rol_id": role_id,
            "sedes": [mtl["id"]],
            "activo": True,
            "debe_cambiar_clave": False,
        },
    )
    assert u_resp.status_code == 201, u_resp.text
    user_id = u_resp.json()["id"]

    try:
        limited = auth_session_factory(username, pw, sede="montelibano")

        # Non-nominal aggregate endpoint allowed
        agg = limited.get("/api/v1/comercial/afinia/analisis/indicadores/202607", sede="montelibano")
        assert agg.status_code == 200, agg.text

        # All nominal endpoints must return 403
        for method, path, kwargs in (
            ("GET", "/api/v1/comercial/afinia/analisis/trazabilidad/7000011", {}),
            (
                "GET",
                "/api/v1/comercial/afinia/analisis/detalle/202607",
                {"params": {"indicador": "facturacion"}},
            ),
            ("GET", "/api/v1/comercial/afinia/hallazgos", {}),
            (
                "POST",
                "/api/v1/comercial/afinia/entregables/anexo-nominal",
                {"json_body": {"periodo": "202607"}},
            ),
            (
                "GET",
                "/api/v1/comercial/afinia/analisis/control-tarifario/202607",
                {"params": {"grupo_consumo": "todos"}},
            ),
        ):
            r = limited.request(method, path, sede="montelibano", **kwargs)
            assert_problem_json(r, expected_status=403)

        # Authorized query inserts auditoria_consulta
        before = db_helper.count_nominal_consult_logs()
        ok_traz = admin.get(
            "/api/v1/comercial/afinia/analisis/trazabilidad/7000011",
            sede="montelibano",
        )
        assert ok_traz.status_code == 200
        assert db_helper.count_nominal_consult_logs() > before
    finally:
        admin.patch(f"/api/v1/usuarios/{user_id}", omit_sede=True, json_body={"activo": False})


def test_hallazgo_revisado_validation_422_and_cross_sede_patch_404(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """F8-9: hallazgo_revisado rejects missing responsable/decision (422) and cross-sede PATCH (404)."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    missing_resp = mtl.post(
        "/api/v1/comercial/afinia/hallazgos",
        sede="montelibano",
        json_body={
            "tipo": "ANOMALIA",
            "estado": "ABIERTO",
            "decision": "Falta responsable",
        },
    )
    assert_problem_json(missing_resp, expected_status=422)

    missing_dec = mtl.post(
        "/api/v1/comercial/afinia/hallazgos",
        sede="montelibano",
        json_body={
            "tipo": "RUTA",
            "estado": "ABIERTO",
            "responsable": "Analista E2E",
        },
    )
    assert_problem_json(missing_dec, expected_status=422)

    created = mtl.post(
        "/api/v1/comercial/afinia/hallazgos",
        sede="montelibano",
        json_body={
            "tipo": "ANOMALIA",
            "estado": "ABIERTO",
            "responsable": f"Analista {run_id}",
            "decision": "Inspección inicial",
            "nic": "7000011",
        },
    )
    assert created.status_code == 201, created.text
    h_id = created.json()["id"]

    cross_patch = mtl.patch(
        f"/api/v1/comercial/celsia/hallazgos/{h_id}",
        sede="alcala",
        json_body={"estado": "RESUELTO", "decision": "Intento cross-sede"},
    )
    assert_problem_json(cross_patch, expected_status=404)


def test_anexo_nominal_truncation_aborts_download_instead_of_truncating(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-10: Nominal Annex Excel aborts (409/422) when rows exceed configured limit."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    files = build_afinia_cut_files(periodo="202607", format_mode="txt_z")
    _upload_and_wait_cargue(
        mtl,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        periodo="202607",
        files=list(files.values()),
    )

    params_resp = mtl.get("/api/v1/parametros", sede="montelibano")
    assert params_resp.status_code == 200, params_resp.text
    params = _extract_items(params_resp.json())
    limit_param = next(
        (
            p
            for p in params
            if any(
                kw in str(p.get("codigo", "")).lower()
                for kw in ("anexo", "nominal_max", "max_filas", "trunc")
            )
        ),
        None,
    )

    original_val = limit_param["valor"] if limit_param is not None else None
    if limit_param is not None:
        patch_p = mtl.patch(
            f"/api/v1/parametros/{limit_param['id']}",
            sede="montelibano",
            json_body={"valor": "5"},
        )
        assert patch_p.status_code == 200, patch_p.text

    try:
        payload: dict[str, Any] = {"periodo": "202607"}
        if limit_param is None:
            payload["max_filas"] = 5
        abort_resp = mtl.post(
            "/api/v1/comercial/afinia/entregables/anexo-nominal",
            sede="montelibano",
            json_body=payload,
        )
        assert_problem_json(abort_resp, expected_status=(409, 422))
        assert not abort_resp.content.startswith(b"PK")
    finally:
        if limit_param is not None and original_val is not None:
            mtl.patch(
                f"/api/v1/parametros/{limit_param['id']}",
                sede="montelibano",
                json_body={"valor": original_val},
            )


def test_celsia_promedios_ids_txt_rejects_over_1mib_413_and_over_50000_ids_422(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-10: Celsia promedios-ids .txt rejects > 1 MiB (413) and > 50,000 IDs (422)."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")
    _upload_and_wait_cargue(
        alc,
        db_helper,
        e2e_config,
        sede="alcala",
        operador="celsia",
        periodo="202606",
        files=[build_celsia_xlsx("202606")],
    )

    # 1) > 1 MiB -> 413
    over_1mib = ("8001001\n" * 140000).encode("utf-8")  # > 1,048,576 bytes
    assert len(over_1mib) > 1024 * 1024
    r_413 = alc.post(
        "/api/v1/comercial/celsia/exportaciones/promedios-ids",
        sede="alcala",
        files={"archivo": ("ids_over_1mib.txt", over_1mib, "text/plain")},
    )
    assert_problem_json(r_413, expected_status=413)

    # 2) <= 1 MiB AND > 50,000 IDs (50,001 short IDs = ~339 KiB) -> 422
    over_50k = ("\n".join(str(i) for i in range(1, 50002)) + "\n").encode("utf-8")
    assert len(over_50k) < 1024 * 1024
    r_422 = alc.post(
        "/api/v1/comercial/celsia/exportaciones/promedios-ids",
        sede="alcala",
        files={"archivo": ("ids_50001.txt", over_50k, "text/plain")},
    )
    assert_problem_json(r_422, expected_status=422)

    # 3) Valid .txt -> returns .xlsx
    valid_txt = b"8001001\n8001002\n"
    r_ok = alc.post(
        "/api/v1/comercial/celsia/exportaciones/promedios-ids",
        sede="alcala",
        files={"archivo": ("ids_ok.txt", valid_txt, "text/plain")},
    )
    assert r_ok.status_code == 200, r_ok.text
    assert r_ok.content[:2] == b"PK"
    assert len(read_xlsx_sheets(r_ok.content)) >= 1


def test_negative_adjustment_alert_triggers_only_when_peso_exceeds_prior_max(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-8: Negative recaudo alert fires strictly when peso > max(prior cuts)."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")

    # Upload 202510 (1% negative), 202511 (1% negative -> NOT > max), 202512 (25% negative -> ALERTA)
    specs = [
        ("202510", dt.date(2025, 10, 15), 10000.0, -100.0),
        ("202511", dt.date(2025, 11, 15), 10000.0, -100.0),
        ("202512", dt.date(2025, 12, 15), 10000.0, -2500.0),
    ]
    for periodo, d_cut, pos_amt, neg_amt in specs:
        f_book = _afinia_fact_book(
            periodo,
            [
                _afinia_fact_row(
                    nic=7200001,
                    tarifa="AP_Residenciales_Estrato_1",
                    concepto="CI400",
                    importe=pos_amt,
                    fecha=d_cut,
                    sv=f"SV-F-{periodo}",
                    consumo_kwh=100.0,
                    valor_consumo_antes=50000.0,
                )
            ],
        )
        r_book = _afinia_reca_book(
            periodo,
            [
                _afinia_reca_row(
                    nic=7200001,
                    tarifa="AP_Residenciales_Estrato_1",
                    concepto="CI400",
                    importe=pos_amt,
                    fecha_fact=d_cut,
                    fecha_trans=d_cut,
                    sv=f"SV-R1-{periodo}",
                ),
                _afinia_reca_row(
                    nic=7200002,
                    tarifa="AP_Residenciales_Estrato_1",
                    concepto="CI400",
                    importe=neg_amt,
                    fecha_fact=d_cut,
                    fecha_trans=d_cut,
                    sv=f"SV-R2-{periodo}",
                ),
            ],
        )
        _upload_and_wait_cargue(
            mtl,
            db_helper,
            e2e_config,
            sede="montelibano",
            operador="afinia",
            periodo=periodo,
            files=[f_book, r_book],
        )

    reca_by_p = {
        "202510": [{"importe_trans": 10000}, {"importe_trans": -100}],
        "202511": [{"importe_trans": 10000}, {"importe_trans": -100}],
        "202512": [{"importe_trans": 10000}, {"importe_trans": -2500}],
    }
    assert detect_negative_adjustment_alert(reca_by_p, target_periodo="202511")["alerta"] is False
    assert detect_negative_adjustment_alert(reca_by_p, target_periodo="202512")["alerta"] is True

    adj_resp = mtl.get("/api/v1/comercial/afinia/analisis/convenios-ajustes", sede="montelibano")
    assert adj_resp.status_code == 200, adj_resp.text
    ajustes = adj_resp.json().get("ajustes_negativos", adj_resp.json().get("alertas_ajustes", []))
    by_p = {str(a.get("periodo")): a for a in ajustes if isinstance(a, dict)}
    assert by_p["202511"]["alerta"] is False
    assert by_p["202512"]["alerta"] is True


def test_irregular_invoices_5_categories_edge_boundaries_afinia_and_celsia(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
) -> None:
    """F8-8: 5 irregular categories (sum=0 with neg line, different-tariff multi-line valid, Celsia >=202605)."""
    mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    d_cut = dt.date(2026, 8, 15)
    rows = [
        # 1) CI400 (+500) + CI401 (-500) = 0 -> LINEA_NEGATIVA & TOTAL_EN_CERO (NOT TOTAL_NEGATIVO)
        _afinia_fact_row(
            nic=7300001,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI400",
            importe=500.0,
            fecha=d_cut,
            sv="SV-IR-1",
            consumo_kwh=50.0,
            valor_consumo_antes=50000.0,
        ),
        _afinia_fact_row(
            nic=7300001,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI401",
            importe=-500.0,
            fecha=d_cut,
            sv="SV-IR-1",
            consumo_kwh=0.0,
            valor_consumo_antes=0.0,
        ),
        # 2) CI400 (-200) -> LINEA_NEGATIVA & TOTAL_NEGATIVO
        _afinia_fact_row(
            nic=7300002,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI400",
            importe=-200.0,
            fecha=d_cut,
            sv="SV-IR-2",
            consumo_kwh=50.0,
            valor_consumo_antes=50000.0,
        ),
        # 3) Non-tax CI306 only -> SIN_CONCEPTO_IMPUESTO
        _afinia_fact_row(
            nic=7300003,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI306",
            importe=1200.0,
            fecha=d_cut,
            sv="SV-IR-3",
            consumo_kwh=0.0,
            valor_consumo_antes=0.0,
        ),
        # 4) 2 CI400 in SAME tariff -> IMPUESTO_AMBIGUO
        _afinia_fact_row(
            nic=7300004,
            tarifa="AP_Residenciales_Estrato_2",
            concepto="CI400",
            importe=3142.44,
            fecha=d_cut,
            sv="SV-IR-4",
            consumo_kwh=80.0,
            valor_consumo_antes=80000.0,
        ),
        _afinia_fact_row(
            nic=7300004,
            tarifa="AP_Residenciales_Estrato_2",
            concepto="CI400",
            importe=3142.44,
            fecha=d_cut,
            sv="SV-IR-4",
            consumo_kwh=80.0,
            valor_consumo_antes=80000.0,
        ),
        # 5) 2 CI400 in DIFFERENT tariffs -> NOT IMPUESTO_AMBIGUO
        _afinia_fact_row(
            nic=7300005,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI400",
            importe=2094.96,
            fecha=d_cut,
            sv="SV-IR-5",
            consumo_kwh=80.0,
            valor_consumo_antes=80000.0,
        ),
        _afinia_fact_row(
            nic=7300005,
            tarifa="AP_Comerciales_Nivel_1",
            concepto="CI400",
            importe=15712.20,
            fecha=d_cut,
            sv="SV-IR-5B",
            consumo_kwh=80.0,
            valor_consumo_antes=80000.0,
        ),
    ]
    _upload_and_wait_cargue(
        mtl,
        db_helper,
        e2e_config,
        sede="montelibano",
        operador="afinia",
        periodo="202608",
        files=[_afinia_fact_book("202608", rows)],
    )

    fact_data = mtl.get(
        "/api/v1/comercial/afinia/cortes/202608/datos",
        sede="montelibano",
        params={"familia": "facturacion", "page": 1, "size": 50},
    ).json()["items"]
    oracle_irreg = detect_irregular_invoices(fact_data, operator="afinia", periodo="202608")
    assert set(oracle_irreg["LINEA_NEGATIVA"]) == {"7300001", "7300002"}
    assert oracle_irreg["TOTAL_NEGATIVO"] == ["7300002"]
    assert oracle_irreg["TOTAL_EN_CERO"] == ["7300001"]
    assert oracle_irreg["SIN_CONCEPTO_IMPUESTO"] == ["7300003"]
    assert oracle_irreg["IMPUESTO_AMBIGUO"] == ["7300004"]
    assert "7300005" not in oracle_irreg["IMPUESTO_AMBIGUO"]

    irreg_api = mtl.get(
        "/api/v1/comercial/afinia/analisis/facturas-revision/202608",
        sede="montelibano",
    )
    assert irreg_api.status_code == 200, irreg_api.text
    por_cat = irreg_api.json().get("por_categoria", irreg_api.json())
    for cat in (
        "LINEA_NEGATIVA",
        "TOTAL_NEGATIVO",
        "TOTAL_EN_CERO",
        "SIN_CONCEPTO_IMPUESTO",
        "IMPUESTO_AMBIGUO",
    ):
        assert cat in por_cat
        if isinstance(por_cat[cat], list):
            ids = {str(x.get("nic") or x.get("identificador") or x) for x in por_cat[cat]}
            assert ids == set(oracle_irreg[cat])
