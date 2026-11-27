"""Tier 4 Scenario 2: Alcalá Dual-Operator Commercial Cycle (Celsia + Vatia)."""

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
    build_vatia_xlsx,
    build_xlsx_bytes,
    read_xlsx_sheets,
)
from harness.client import SapefClient
from harness.config import E2EConfig
from harness.db import DbHelper
from oracles import (
    classify_movements_and_absences,
    deduce_celsia_periodicity,
    evaluate_celsia_tariff_control,
    q2,
)

pytestmark = [pytest.mark.tier4, pytest.mark.commercial]

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _admin_client(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    sede: str = "alcala",
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
    assert cargue_id is not None

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
    raise TimeoutError(f"Cargue {cargue_id} timed out: {last}")


def _build_celsia_scenario_month(
    periodo: str,
    *,
    include_bimonthly_rural: bool,
    include_all_5_states: bool,
) -> SyntheticFile:
    """Build Celsia .xlsx covering urban monthly, rural bimonthly, C2M, footers, estratos, aging."""
    year = int(periodo[:4])
    month = int(periodo[4:6])
    mes_map = {4: "ABRIL", 5: "MAYO", 6: "JUNIO"}
    yy = f"{year % 100:02d}"
    fname = f"CELSIA_ALCALA_{mes_map[month]}_{yy}.xlsx"
    f_date = dt.date(year, month, 15)
    vcto_date = dt.date(year, month, 28)

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
        "Barrio/Vereda/Corregimiento",
        "Periodicidad",
        "Mercado",
        "Descripción",
        "Valor del Impuesto Facturado",
        "Consumo kWh",
        "Valor del Consumo de Energía Antes de Subsidios o Contribuciones Pesos",
    ]
    fact_rows: list[list[Any]] = [
        fact_headers,
        # Urban monthly E1 fixed ($3,994.50 -> CORRECTO)
        [
            "8101001",
            f"FC-{periodo}-01",
            f_date,
            "Ana Urbano",
            "Cra 4 # 5-10",
            "1 Residencial",
            "R1",
            "Estrato 1",
            "Urbano",
            "ALCALA",
            "Centro",
            "Mensual",
            "Regulado",
            "Impuesto Alumbrado Público",
            3994.50,
            120.0,
            85000.0,
        ],
        # Urban monthly E2 fixed ($7,989.00 -> POR_ENCIMA +500.00)
        [
            "8101002",
            f"FC-{periodo}-02",
            f_date,
            "Luis Sobre",
            "Calle 6 # 2-30",
            "1 Residencial",
            "R2",
            "2",
            "Urbano",
            "ALCALA",
            "El Prado",
            "Mensual",
            "Regulado",
            "Impuesto Alumbrado Público",
            8489.00,
            150.0,
            110000.0,
        ],
        # Urban monthly Comercial empty estrato -> segmento fallback (10% * 250000 = 25000 -> CORRECTO)
        [
            "8101004",
            f"FC-{periodo}-04",
            f_date,
            "Ferretería Alcalá",
            "Cra 5 # 8-12",
            "2 Comercial",
            "C1",
            "",
            "Urbano",
            "ALCALA",
            "Centro",
            "Mensual",
            "Regulado",
            "Impuesto Alumbrado Público",
            25000.00,
            600.0,
            250000.0,
        ],
    ]
    if include_bimonthly_rural:
        # Rural bimonthly even-parity E3: min = 2 * 10564.99 = 21129.98 (CORRECTO)
        fact_rows.append(
            [
                "8101003",
                f"FC-{periodo}-03",
                f_date,
                "Finca El Congal",
                "Vereda El Congal",
                "1 Residencial",
                "R3",
                "Estrato 3",
                "Rural",
                "ALCALA",
                "El Congal",
                "Bimestral",
                "Regulado",
                "Impuesto Alumbrado Público",
                21129.98,
                300.0,
                150000.0,
            ]
        )

    if include_all_5_states:
        # POR_DEBAJO (E4 urbano min 20417.51, billed 18000.00 -> -2417.51)
        fact_rows.append(
            [
                "8101005",
                f"FC-{periodo}-05",
                f_date,
                "Predio Debajo",
                "Cra 7 # 2-11",
                "1 Residencial",
                "R4",
                "4",
                "Urbano",
                "ALCALA",
                "La Floresta",
                "Mensual",
                "Regulado",
                "Impuesto Alumbrado Público",
                18000.00,
                180.0,
                150000.0,
            ]
        )
        # REQUIERE_REVISION (missing VCE on pct_min rule; RN-006: falta un dato)
        fact_rows.append(
            [
                "8101006",
                f"FC-{periodo}-06",
                f_date,
                "Predio Sin VCE",
                "Cra 9 # 1-01",
                "1 Residencial",
                "R4",
                "4",
                "Urbano",
                "ALCALA",
                "La Floresta",
                "Mensual",
                "Regulado",
                "Impuesto Alumbrado Público",
                20417.51,
                200.0,
                None,
            ]
        )
        # NO_VALIDABLE (ESTRATO_SIN_REGLA; RN-006: la regla no permite calcular)
        fact_rows.append(
            [
                "8101007",
                f"FC-{periodo}-07",
                f_date,
                "Predio Sin Regla",
                "Cra 10 # 3-04",
                "1 Residencial",
                "R9",
                "",
                "Urbano",
                "ALCALA",
                "Centro",
                "Mensual",
                "Regulado",
                "Impuesto Alumbrado Público",
                9000.00,
                100.0,
                90000.0,
            ]
        )

    # Add 1 footer row without cuenta (<= 10%, safely discarded)
    fact_rows.append(
        [None, None, None, "TOTAL FACTURACION", None, None, None, None, None, None, None, None, None, None, 0.0, 0.0, 0.0]
    )

    reca_rows = [
        [
            "Cuenta",
            "Número de Factura",
            "Fecha Vencimiento",
            "Fecha de Pago",
            "Fecha Aplicación",
            "Nombre",
            "Dirección",
            "Clase de Cliente",
            "Tarifa",
            "Estrato",
            "Sector",
            "Municipio",
            "Descripción",
            "Valor del Impuesto Recaudado",
        ],
        [
            "8101001",
            f"FC-{periodo}-01",
            vcto_date,
            f_date + dt.timedelta(days=4),
            f_date + dt.timedelta(days=4),
            "Ana Urbano",
            "Cra 4 # 5-10",
            "1 Residencial",
            "R1",
            "Estrato 1",
            "Urbano",
            "ALCALA",
            "Impuesto Alumbrado Público",
            3994.50,
        ],
        [
            "8101004",
            f"FC-{periodo}-04",
            vcto_date - dt.timedelta(days=65),
            f_date + dt.timedelta(days=2),
            f_date + dt.timedelta(days=2),
            "Ferretería Alcalá",
            "Cra 5 # 8-12",
            "2 Comercial",
            "C1",
            "",
            "Urbano",
            "ALCALA",
            "Impuesto Alumbrado Público",
            25000.00,
        ],
    ]

    cart_rows = [
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
            "8101002",
            "Luis Sobre",
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
            2500.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            15989.0,
        ],
    ]

    sheets = [
        XlsxSheet("Facturacion", fact_rows),
        XlsxSheet("Recaudo", reca_rows),
        XlsxSheet("Cartera", cart_rows),
        XlsxSheet(
            "C2M",
            [
                ["Nota", "Valor del Impuesto Facturado"],
                ["Hoja C2M excluida", 8888888.0],
            ],
        ),
    ]
    return SyntheticFile(
        filename=fname,
        content=build_xlsx_bytes(sheets),
        content_type=_XLSX_MIME,
    )


def _build_vatia_zero_billing_xlsx(periodo: str = "202605") -> SyntheticFile:
    """Build a Vatia cut where all rows have facturado_total = 0 (eficiencia must be null)."""
    year = int(periodo[:4])
    month = int(periodo[4:6])
    f_elab = dt.date(year, month, 18)
    f_ini = dt.date(year, month, 1)
    f_fin = dt.date(year, month, 28)
    headers = [
        "CICLO",
        "NUMERO DE FACTURA",
        "CLIENTE NIT",
        "CLIENTE ID",
        "CLIENTE NOMBRE",
        "NIVEL DE TENSION",
        "OPERADOR DE RED",
        "MERCADO",
        "SUBMERCADO",
        "ESTRATO",
        "FECHA ELAB FACTURA",
        "FACTURADO TOTAL INCLUYE NOTAS",
        "RECAUDO MES",
        "RECUPERACION CARTERA",
        "SALDO EN CARTERA",
        "EDAD CIERRE MES CICLO",
        "CONSUMO ACTIVA KW",
        "FECHA INIPER",
        "FECHA FINPER",
    ]
    rows = [
        headers,
        [
            periodo,
            f"VAT-{periodo}-01",
            "900111222",
            "VAT-001",
            "Industria Cero Facturacion",
            "Nivel 2",
            "CELSIA",
            "No Regulado",
            "Industrial",
            "N/A",
            f_elab,
            0.0,
            0.0,
            0.0,
            25000.0,
            "30 días",
            0.0,
            f_ini,
            f_fin,
        ],
    ]
    return SyntheticFile(
        filename=f"VATIA_ALCALA_{periodo}.xlsx",
        content=build_xlsx_bytes([XlsxSheet("Comercial", rows)]),
        content_type=_XLSX_MIME,
    )


def test_alcala_dual_commercial_cycle_celsia_vatia_and_tablero_kpis(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    db_helper: DbHelper,
) -> None:
    """Scenario 2: 3m Celsia + 3m Vatia -> tariff/periodicity/aging/29-catalog -> deliverables -> RF-066."""
    alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")

    # ------------------------------------------------------------------
    # Phase 1: Upload 3 months of Celsia (.xlsx: C2M, footers, estratos, bimonthly)
    # ------------------------------------------------------------------
    celsia_cuts = {
        "202604": _build_celsia_scenario_month(
            "202604", include_bimonthly_rural=True, include_all_5_states=False
        ),
        "202605": _build_celsia_scenario_month(
            "202605", include_bimonthly_rural=False, include_all_5_states=False
        ),
        "202606": _build_celsia_scenario_month(
            "202606", include_bimonthly_rural=True, include_all_5_states=True
        ),
    }
    for periodo, sfile in celsia_cuts.items():
        detail = _upload_and_wait_cargue(
            alc,
            db_helper,
            e2e_config,
            sede="alcala",
            operador="celsia",
            periodo=periodo,
            files=[sfile],
        )
        assert detail["periodo"] == periodo

    # Verify C2M excluded, footer discarded, and estrato digit/segment fallback
    fact_06 = alc.get(
        "/api/v1/comercial/celsia/cortes/202606/datos",
        sede="alcala",
        params={"familia": "facturacion", "page": 1, "size": 50},
    )
    assert fact_06.status_code == 200, fact_06.text
    fact_items = fact_06.json()["items"]
    assert len(fact_items) == 7, f"Expected 7 valid rows (C2M & footer excluded), got {len(fact_items)}"
    assert all(float(r["valor_facturado"]) != 8888888.0 for r in fact_items)
    by_acc = {str(r["cuenta"]): r for r in fact_items}
    assert str(by_acc["8101001"]["estrato"]) == "1"
    assert str(by_acc["8101002"]["estrato"]) == "2"

    # Verify Celsia VCE tariff control (all 5 states + bimonthly x2 + $100 tolerance)
    tc_resp = alc.get(
        "/api/v1/comercial/celsia/analisis/control-tarifario/202606",
        sede="alcala",
        params={"grupo_consumo": "todos", "size": 100},
    )
    assert tc_resp.status_code == 200, tc_resp.text
    tc_api = tc_resp.json()
    oracle_tc = evaluate_celsia_tariff_control(
        fact_items,
        periodo="202606",
        bimonthly_accounts={"8101003"},
    )
    assert tc_api["totales"]["por_estado"] == oracle_tc["counts"]
    for state in ("CORRECTO", "POR_ENCIMA", "POR_DEBAJO", "NO_VALIDABLE", "REQUIERE_REVISION"):
        assert tc_api["totales"]["por_estado"][state] >= 1, (
            f"Expected >= 1 account in state {state}: {tc_api['totales']}"
        )
    assert q2(tc_api["totales"]["valor_por_encima"]) == oracle_tc["total_valor_por_encima"]
    assert q2(tc_api["totales"]["valor_por_debajo"]) == oracle_tc["total_valor_por_debajo"]

    api_by_acc = {str(r["identificador"]): r for r in tc_api["items"]}
    assert q2(api_by_acc["8101003"]["esperado"]) == Decimal("21129.98")
    assert api_by_acc["8101003"]["estado"] == "CORRECTO"

    # Verify periodicity & off-parity month movement ('No le correspondía' on 202605)
    per_06 = alc.get("/api/v1/comercial/celsia/analisis/periodicidad/202606", sede="alcala")
    assert per_06.status_code == 200, per_06.text
    assert deduce_celsia_periodicity(["202604", "202606"]) == "bimestral_par"
    assert deduce_celsia_periodicity(["202604", "202605", "202606"]) == "mensual"

    mov_05 = alc.get("/api/v1/comercial/celsia/analisis/movimientos/202605", sede="alcala")
    assert mov_05.status_code == 200, mov_05.text
    oracle_mov = classify_movements_and_absences(
        loaded_periods=["202604", "202605", "202606"],
        account_presence={
            "8101001": ["202604", "202605", "202606"],
            "8101003": ["202604", "202606"],
        },
        target_periodo="202605",
        periodicities={"8101001": "mensual", "8101003": "bimestral_par"},
    )
    assert oracle_mov["movements"]["8101003"] == "No le correspondía"
    mov_text = str(mov_05.json())
    assert "8101003" not in mov_text, (
        "Bimonthly account on off-parity month must neither be counted nor listed in movements"
    )

    # Celsia portfolio aging (cartera-edades)
    celsia_aging = alc.get(
        "/api/v1/comercial/celsia/analisis/cartera-edades/202606", sede="alcala"
    )
    assert celsia_aging.status_code == 200, celsia_aging.text

    # ------------------------------------------------------------------
    # Phase 2: Upload 3 months of Vatia (.xlsx: cycles, submarkets, NC, zero-billing)
    # ------------------------------------------------------------------
    vatia_files = {
        "202604": build_vatia_xlsx("202604", include_negative_net=False),
        "202605": _build_vatia_zero_billing_xlsx("202605"),
        "202606": build_vatia_xlsx("202606", include_negative_net=True),
    }
    for periodo, vfile in vatia_files.items():
        v_det = _upload_and_wait_cargue(
            alc,
            db_helper,
            e2e_config,
            sede="alcala",
            operador="vatia",
            periodo=periodo,
            files=[vfile],
        )
        assert v_det["periodo"] == periodo

    # Zero-billing month -> eficiencia is null (never 0 or division-by-zero 500)
    vat_05 = alc.get("/api/v1/comercial/vatia/analisis/indicadores/202605", sede="alcala")
    assert vat_05.status_code == 200, vat_05.text
    assert vat_05.json().get("eficiencia") is None

    # Negative credit notes + submarkets + portfolio aging on 202606
    vat_06 = alc.get("/api/v1/comercial/vatia/analisis/indicadores/202606", sede="alcala")
    assert vat_06.status_code == 200, vat_06.text
    assert q2(vat_06.json()["facturacion"]) == Decimal("-20000.00")
    assert q2(vat_06.json()["recaudo"]) == Decimal("180000.00")

    vat_aging = alc.get("/api/v1/comercial/vatia/analisis/cartera-edades/202606", sede="alcala")
    assert vat_aging.status_code == 200, vat_aging.text
    vat_sub = alc.get("/api/v1/comercial/vatia/analisis/historico-comerciales", sede="alcala")
    assert vat_sub.status_code == 200, vat_sub.text

    # ------------------------------------------------------------------
    # Phase 3: Verify 29-analysis availability differences (Celsia vs Vatia)
    # ------------------------------------------------------------------
    cat_celsia = alc.get("/api/v1/comercial/celsia/catalogo", sede="alcala").json()
    cat_vatia = alc.get("/api/v1/comercial/vatia/catalogo", sede="alcala").json()
    c_items = cat_celsia if isinstance(cat_celsia, list) else cat_celsia.get("items", cat_celsia.get("analisis", []))
    v_items = cat_vatia if isinstance(cat_vatia, list) else cat_vatia.get("items", cat_vatia.get("analisis", []))
    assert len(c_items) == 29 and len(v_items) == 29
    c_map = {str(x["id"]): x for x in c_items}
    v_map = {str(x["id"]): x for x in v_items}

    assert c_map["control-tarifario"]["estado"] == "disponible"
    assert v_map["control-tarifario"]["estado"] == "no_aplica" and v_map["control-tarifario"].get("nota")
    assert c_map["usuarios-periodicidad"]["estado"] == "disponible"
    assert v_map["usuarios-periodicidad"]["estado"] == "no_aplica" and v_map["usuarios-periodicidad"].get("nota")
    assert c_map["convenios-ajustes"]["estado"] == "no_aplica" and c_map["convenios-ajustes"].get("nota")
    assert v_map["facturas-revision"]["estado"] == "no_aplica" and v_map["facturas-revision"].get("nota")
    assert v_map["maduracion-recaudo"]["estado"] == "no_aplica" and v_map["maduracion-recaudo"].get("nota")

    # ------------------------------------------------------------------
    # Phase 4: Generate Celsia & Vatia deliverables + RF-066 Dashboard KPIs
    # ------------------------------------------------------------------
    cel_req = alc.post(
        "/api/v1/comercial/celsia/entregables/requerimiento",
        sede="alcala",
        json_body={"periodo": "202606", "formato": "docx"},
    )
    assert cel_req.status_code == 200, cel_req.text
    assert cel_req.content[:2] == b"PK"

    cel_anx = alc.post(
        "/api/v1/comercial/celsia/entregables/anexo-nominal",
        sede="alcala",
        json_body={"periodo": "202606"},
    )
    assert cel_anx.status_code == 200, cel_anx.text
    assert cel_anx.content[:2] == b"PK"
    assert len(read_xlsx_sheets(cel_anx.content)) >= 1

    cel_inf = alc.post(
        "/api/v1/comercial/celsia/entregables/informe-gerencial",
        sede="alcala",
        json_body={"periodo": "202606"},
    )
    assert cel_inf.status_code == 200, cel_inf.text
    assert cel_inf.content.startswith(b"%PDF-")

    cel_zip = alc.post(
        "/api/v1/comercial/celsia/exportaciones/cartera",
        sede="alcala",
        json_body={"periodo": "202606"},
    )
    assert cel_zip.status_code in (200, 202), cel_zip.text
    if cel_zip.status_code == 200:
        assert cel_zip.content[:2] == b"PK"

    ids_txt = b"8101001\n8101002\n8101003\n"
    prom_ids = alc.post(
        "/api/v1/comercial/celsia/exportaciones/promedios-ids",
        sede="alcala",
        files={"archivo": ("cuentas.txt", ids_txt, "text/plain")},
    )
    assert prom_ids.status_code == 200, prom_ids.text
    assert prom_ids.content[:2] == b"PK"

    vat_inf = alc.post(
        "/api/v1/comercial/vatia/entregables/informe-gerencial",
        sede="alcala",
        json_body={"periodo": "202606"},
    )
    assert vat_inf.status_code == 200, vat_inf.text
    assert vat_inf.content.startswith(b"%PDF-")

    sedes = alc.get("/api/v1/sedes", omit_sede=True).json()
    sede_items = sedes if isinstance(sedes, list) else sedes.get("items", [])
    alc_id = next(s["id"] for s in sede_items if s["codigo"] == "alcala")

    recalc = alc.post(
        "/api/v1/tablero/recalcular",
        sede="alcala",
        json_body={"sede_id": alc_id},
    )
    assert recalc.status_code == 202, recalc.text
    job_id = recalc.json().get("tareaId") or recalc.json().get("tarea_id")
    if isinstance(job_id, int):
        db_helper.wait_for_procrastinate_job(job_id, timeout=e2e_config.timeout_seconds)

    tablero = alc.get("/api/v1/tablero/resumen", sede="alcala")
    assert tablero.status_code == 200, tablero.text
    com_sec = tablero.json().get("comercial", {})
    assert com_sec, f"Expected RF-066 commercial KPIs in /tablero/resumen: {tablero.json()}"
    assert "sin_cortes_cargados" not in str(com_sec)
