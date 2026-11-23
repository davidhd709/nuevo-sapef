"""Deterministic self-verification of E2E builders, encodings, magic bytes, and math oracles."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import zipfile
from decimal import Decimal

import pytest
from fixtures import (
    AFINIA_39_UVT_DISTRIBUTION,
    AFINIA_39_UVT_FACTORS,
    AFINIA_CANONICAL_TARIFFS,
    ALCALA_BBOX,
    MONTELIBANO_BBOX,
    FormulaCell,
    XlsxSheet,
    build_afinia_3month_dataset,
    build_afinia_cut_files,
    build_afinia_extra_col_xlsx,
    build_afinia_formula_xlsx,
    build_bulk_ot_xlsx,
    build_celsia_invalid_footer_xlsx,
    build_celsia_mismatched_period_xlsx,
    build_celsia_xlsx,
    build_imp1_luminarias_xlsx,
    build_imp2_pqrs_xlsx,
    build_imp3_ordenes_4files,
    build_imp4_inventario_xlsx,
    build_imp6_base_config_xlsx,
    build_opainn_parquet_package,
    build_vatia_invalid_na_xlsx,
    build_vatia_xlsx,
    build_xlsx_bytes,
    compress_z,
    decompress_z,
    generate_coordinates,
    make_forged_file,
    make_jpeg,
    make_mp4_aac,
    make_oversized_payload,
    make_pdf,
    make_png,
    make_webp,
    read_xlsx_formulas,
    read_xlsx_sheets,
)
from harness.config import E2EConfig
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
    verify_parity,
)


@pytest.mark.fase0
def test_xlsx_builder_roundtrip_and_formula_injection() -> None:
    xlsx_bytes = build_xlsx_bytes(
        [
            XlsxSheet(
                "Datos",
                [
                    ["codigo", "valor", "fecha", "activo"],
                    ["LUM-01", 123.45, dt.date(2026, 7, 15), True],
                    ["LUM-02", FormulaCell("SUM(B2:B2)", 123.45), "=A2", False],
                ],
            ),
            XlsxSheet("Resumen", [["Total", 1]]),
        ]
    )
    assert xlsx_bytes[:2] == b"PK"
    with zipfile.ZipFile(__import__("io").BytesIO(xlsx_bytes), "r") as zf:
        assert "xl/workbook.xml" in zf.namelist()
        assert "xl/worksheets/sheet1.xml" in zf.namelist()
        assert "xl/worksheets/sheet2.xml" in zf.namelist()

    sheets = read_xlsx_sheets(xlsx_bytes)
    assert list(sheets.keys()) == ["Datos", "Resumen"]
    assert sheets["Datos"][0] == ["codigo", "valor", "fecha", "activo"]
    assert sheets["Datos"][1][0] == "LUM-01"
    assert sheets["Datos"][1][1] == 123.45
    assert sheets["Datos"][1][3] is True
    assert sheets["Resumen"] == [["Total", 1]]

    formulas = read_xlsx_formulas(xlsx_bytes)
    assert ("Datos", "B3", "SUM(B2:B2)") in formulas
    assert ("Datos", "C3", "A2") in formulas


@pytest.mark.fase0
def test_lzw_z_roundtrip_cp1252_and_large_payload() -> None:
    sample = (
        "SV500|Alumbrado Público|T01|AP Residenciales Estrato 1|7000001|"
        "José Peña Ñandú|Calle 10 # 5-20|120.0|MONTELIBANO|El Centro|2094.96|0|ACTIVO\n"
    ) * 40
    raw_cp1252 = sample.encode("cp1252")
    compressed = compress_z(raw_cp1252)
    assert compressed[:2] == b"\x1f\x9d"
    assert len(compressed) < len(raw_cp1252)

    restored = decompress_z(compressed)
    assert restored == raw_cp1252
    assert restored.decode("cp1252") == sample


@pytest.mark.fase0
def test_media_builder_magic_bytes_and_forgeries() -> None:
    png = make_png(4, 4)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in png and b"IEND" in png

    jpeg = make_jpeg()
    assert jpeg.startswith(b"\xff\xd8\xff\xe0")
    assert jpeg.endswith(b"\xff\xd9")

    webp = make_webp()
    assert webp[:4] == b"RIFF" and webp[8:12] == b"WEBP"

    pdf = make_pdf("Prueba SAPEF")
    assert pdf.startswith(b"%PDF-1.4") and b"%%EOF" in pdf

    mp4 = make_mp4_aac()
    assert mp4[4:8] == b"ftyp" and b"mdat" in mp4

    fname, payload, mime = make_forged_file(
        "foto.jpg", actual_kind="pdf", claimed_mime="image/jpeg"
    )
    assert fname == "foto.jpg"
    assert mime == "image/jpeg"
    assert payload.startswith(b"%PDF-1.4")

    oversized = make_oversized_payload(1024)
    assert len(oversized) == 1024
    assert oversized.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.fase0
def test_operational_builders_and_geo_bounds() -> None:
    mtl_coords = generate_coordinates("montelibano", 25, seed=7)
    assert len(mtl_coords) == 25
    for lat, lng in mtl_coords:
        assert MONTELIBANO_BBOX[0] <= lat <= MONTELIBANO_BBOX[2]
        assert MONTELIBANO_BBOX[1] <= lng <= MONTELIBANO_BBOX[3]

    alc_coords = generate_coordinates("alcala", 25, seed=7)
    for lat, lng in alc_coords:
        assert ALCALA_BBOX[0] <= lat <= ALCALA_BBOX[2]
        assert ALCALA_BBOX[1] <= lng <= ALCALA_BBOX[3]

    imp1 = read_xlsx_sheets(build_imp1_luminarias_xlsx("E2E", count=6))
    assert any("KÜNIX" in row for row in imp1["Luminarias"])
    assert any("MH" in row for row in imp1["Luminarias"])
    assert any(1947 in row for row in imp1["Luminarias"])

    imp2 = read_xlsx_sheets(build_imp2_pqrs_xlsx("E2E", ["E2E-LUM-0001", "E2E-LUM-0002"]))
    assert any("SIN-IDENTIFICAR" in row for row in imp2["PQRS"])

    imp3 = build_imp3_ordenes_4files("E2E", ["E2E-LUM-0001", "E2E-LUM-0002"])
    assert set(imp3.keys()) == {
        "mantenimientos.xlsx",
        "expansiones.xlsx",
        "modernizaciones.xlsx",
        "reubicaciones.xlsx",
    }

    imp4 = read_xlsx_sheets(build_imp4_inventario_xlsx("E2E"))
    assert set(imp4.keys()) == {"Materiales", "Movimientos", "Bodega"}

    imp6 = read_xlsx_sheets(build_imp6_base_config_xlsx("E2E"))
    assert "clave" not in imp6["Usuarios"][0]
    assert "password" not in imp6["Usuarios"][0]

    bulk_bad = read_xlsx_sheets(
        build_bulk_ot_xlsx("expansion", [{"luminaria_codigo": "L1"}], include_invalid_row=True)
    )
    assert len(bulk_bad["Expansion"]) == 3


@pytest.mark.fase0
def test_commercial_builders_and_opainn_manifest(e2e_config: E2EConfig) -> None:
    cut_09 = build_afinia_cut_files(periodo="202609", use_setiembre_spelling=True)
    assert cut_09["facturacion_xlsx"].filename == "FACTURACION_MONTELIBANO_SETIEMBRE_2026.xlsx"
    assert cut_09["recaudo_z"].content[:2] == b"\x1f\x9d"
    assert "Ñandú" in cut_09["catastro_txt"].content.decode("cp1252")

    refa_sheets = read_xlsx_sheets(cut_09["refacturacion_xlsx"].content)
    assert len(refa_sheets["refactura"][0]) == 21
    assert "CONSUMO KWH" in refa_sheets["refactura"][0]

    three_months = build_afinia_3month_dataset()
    assert list(three_months.keys()) == ["202602", "202604", "202605"]

    formula_f = build_afinia_formula_xlsx()
    assert len(read_xlsx_formulas(formula_f.content)) == 1
    extra_f = build_afinia_extra_col_xlsx()
    assert len(read_xlsx_sheets(extra_f.content)["facturacion"][0]) == 22

    celsia_ok = build_celsia_xlsx("202606")
    celsia_sheets = read_xlsx_sheets(celsia_ok.content)
    assert "C2M" in celsia_sheets
    celsia_bad = build_celsia_invalid_footer_xlsx("202606")
    bad_fact_rows = read_xlsx_sheets(celsia_bad.content)["Facturacion"]
    missing_cuenta = sum(1 for r in bad_fact_rows[1:] if r[0] is None)
    assert missing_cuenta > 20 and missing_cuenta / (len(bad_fact_rows) - 1) > 0.10

    mismatch = build_celsia_mismatched_period_xlsx()
    assert "_ABR_26" in mismatch.filename

    vatia_ok = read_xlsx_sheets(build_vatia_xlsx("202606").content)
    assert any(r[18] == 0.0 for r in vatia_ok["Comercial"][1:])
    vatia_bad = read_xlsx_sheets(build_vatia_invalid_na_xlsx("202606").content)
    assert vatia_bad["Comercial"][1][3] == "N/A"

    pkg_dir = build_opainn_parquet_package(e2e_config.data_dir / "opainn_pkg", periodo="202607")
    manifest = json.loads((pkg_dir / "manifest.json").read_text(encoding="utf-8"))
    for fam_meta in manifest["familias"].values():
        pq_bytes = (pkg_dir / fam_meta["archivo_parquet"]).read_bytes()
        assert hashlib.sha256(pq_bytes).hexdigest() == fam_meta["sha256_parquet"]


@pytest.mark.fase0
@pytest.mark.commercial
def test_commercial_oracle_afinia_tariffs_exceptions_and_td() -> None:
    assert len(AFINIA_CANONICAL_TARIFFS) == 12
    assert len(AFINIA_39_UVT_DISTRIBUTION) == 11
    assert len(AFINIA_39_UVT_FACTORS) == sum(cnt for _, cnt in AFINIA_39_UVT_DISTRIBUTION)

    # Verify exact 2026 minimum values (factor * 52374 ROUND_HALF_UP)
    expected_e1_min = q2(Decimal("0.04") * Decimal(52374))
    assert expected_e1_min == Decimal("2094.96")
    assert q2(Decimal("0.30") * Decimal(52374)) == Decimal("15712.20")

    fact_rows = [
        # <= 173 kWh within $1 tolerance (+1.00 -> CORRECTO)
        {
            "nic": "1001",
            "periodo": "202607",
            "tarifa": "AP_Residenciales_Estrato_1",
            "concepto": "CI400",
            "consumo_kwh": 173,
            "valor_consumo_antes": 100000,
            "importe_trans": "2095.96",
        },
        # > 173 kWh POR_ENCIMA (+1.01) + CI401 signal (must NOT alter CI400)
        {
            "nic": "1002",
            "periodo": "202607",
            "tarifa": "AP_Residenciales_Estrato_1",
            "concepto": "CI400",
            "consumo_kwh": 174,
            "valor_consumo_antes": 500000,  # 2% = 10000.00
            "importe_trans": "10001.01",
        },
        {
            "nic": "1002",
            "periodo": "202607",
            "tarifa": "AP_Residenciales_Estrato_1",
            "concepto": "CI401",
            "consumo_kwh": 0,
            "valor_consumo_antes": 0,
            "importe_trans": "-500.00",
        },
        # POR_DEBAJO (-50.00)
        {
            "nic": "1003",
            "periodo": "202607",
            "tarifa": "AP_Residenciales_Estrato_2",
            "concepto": "CI400",
            "consumo_kwh": 100,
            "valor_consumo_antes": 100000,
            "importe_trans": "3092.44",  # expected 3142.44
        },
        # Exception UVT (5 * 52374 = 261870.00)
        {
            "nic": "1004",
            "periodo": "202607",
            "tarifa": "AP_Comerciales_Nivel_1",
            "concepto": "CI400",
            "consumo_kwh": 1000,
            "valor_consumo_antes": 1000000,
            "importe_trans": "261870.00",
        },
        # NO_VALIDABLE (>173 kWh without valor_consumo_antes)
        {
            "nic": "1005",
            "periodo": "202607",
            "tarifa": "AP_Residenciales_Estrato_3",
            "concepto": "CI400",
            "consumo_kwh": 250,
            "valor_consumo_antes": None,
            "importe_trans": "9000.00",
        },
        # REQUIERE_REVISION (MULTIPLES_CI400)
        {
            "nic": "1006",
            "periodo": "202607",
            "tarifa": "AP_Residenciales_Estrato_4",
            "concepto": "CI400",
            "consumo_kwh": 100,
            "valor_consumo_antes": 100000,
            "importe_trans": "4713.66",
        },
        {
            "nic": "1006",
            "periodo": "202607",
            "tarifa": "AP_Residenciales_Estrato_4",
            "concepto": "CI400",
            "consumo_kwh": 100,
            "valor_consumo_antes": 100000,
            "importe_trans": "4713.66",
        },
    ]
    tc = evaluate_afinia_tariff_control(
        fact_rows,
        periodo="202607",
        excepciones={"1004": Decimal(5)},
    )
    assert tc["counts"] == {
        "CORRECTO": 2,
        "POR_ENCIMA": 1,
        "POR_DEBAJO": 1,
        "NO_VALIDABLE": 1,
        "REQUIERE_REVISION": 1,
    }
    assert tc["total_valor_por_encima"] == Decimal("1.01")
    assert tc["total_valor_por_debajo"] == Decimal("50.00")
    by_nic = {r.identificador: r for r in tc["rows"]}
    assert by_nic["1002"].senal_ci401 == Decimal("-500.00")
    assert by_nic["1004"].regla_aplicada == "COBRO_ESPECIAL_UVT"
    assert by_nic["1006"].motivo_revision == "MULTIPLES_CI400"

    assert len(TD_45_COLUMNS) == 45
    td = compute_afinia_tabla_dinamica(
        periodo="202607",
        facturacion=fact_rows,
        recaudo=[
            {
                "nic": "1001",
                "tarifa": "AP_Residenciales_Estrato_1",
                "concepto": "CI400",
                "importe_trans": "2095.96",
                "fecha_fact_lect": dt.date(2026, 7, 15),
            }
        ],
        catastro=[
            {"nic": "1002", "tarifa": "AP_Residenciales_Estrato_1", "deuda_corriente": "15000.00"}
        ],
    )
    assert len(td["rows"]) == 12
    assert td["total"]["estrato_uso"] == "Total"
    assert td["total"]["n_factura"] == 6
    assert td["total"]["recaudo_corriente"] == Decimal("2095.9600")
    verify_parity(td["total"], td["total"], td["total"])


@pytest.mark.fase0
@pytest.mark.commercial
def test_commercial_oracle_celsia_movements_absences_and_irregulars() -> None:
    celsia_rows = [
        {
            "cuenta": "C1",
            "periodo": "202606",
            "clase": "1 Residencial",
            "estrato": "3",
            "sector": "Rural",
            "periodicidad": "Bimestral",
            "tipo_concepto": "impuesto",
            "valor_facturado": "21129.98",
            "monto_energia": "100000",
        },
        {
            "cuenta": "C2",
            "periodo": "202606",
            "clase": "1 Residencial",
            "estrato": "1",
            "sector": "Urbano",
            "periodicidad": "Mensual",
            "tipo_concepto": "impuesto",
            "valor_facturado": "4194.50",  # 3994.50 + 200 (> $100 tol -> POR_ENCIMA)
            "monto_energia": "50000",
        },
        {
            "cuenta": "C3",
            "periodo": "202606",
            "clase": "1 Residencial",
            "estrato": "4",
            "sector": "Urbano",
            "periodicidad": "Mensual",
            "tipo_concepto": "impuesto",
            "valor_facturado": "20417.51",
            "monto_energia": None,
        },
    ]
    tc = evaluate_celsia_tariff_control(celsia_rows, periodo="202606", bimonthly_accounts={"C1"})
    assert tc["counts"]["CORRECTO"] == 1
    assert tc["counts"]["POR_ENCIMA"] == 1
    assert tc["counts"]["NO_VALIDABLE"] == 1

    assert deduce_celsia_periodicity(["202602", "202604"]) == "bimestral_par"
    assert deduce_celsia_periodicity(["202604", "202605"]) == "mensual"

    mov_04 = classify_movements_and_absences(
        loaded_periods=["202602", "202604", "202605"],  # 202603 skipped
        account_presence={
            "M_KEEP": ["202602", "202604", "202605"],
            "M_LEFT": ["202602"],
            "BIM_PAR": ["202602", "202604"],
        },
        target_periodo="202604",
        periodicities={"BIM_PAR": "bimestral_par"},
    )
    assert mov_04["comparable"] == "202602"
    assert mov_04["skipped_missing_cut"] is True
    assert mov_04["absence_counts"]["M_LEFT"] == 1  # 202603 skipped!

    mov = classify_movements_and_absences(
        loaded_periods=["202602", "202604", "202605"],  # 202603 skipped
        account_presence={
            "M_KEEP": ["202602", "202604", "202605"],
            "M_LEFT": ["202602"],
            "M_NEW": ["202605"],
            "M_REINT": ["202602", "202605"],
            "BIM_PAR": ["202602", "202604"],
        },
        target_periodo="202605",
        periodicities={"BIM_PAR": "bimestral_par"},
    )
    assert mov["comparable"] == "202604"
    assert mov["movements"]["M_KEEP"] == "Facturado"
    assert mov["movements"]["M_NEW"] == "Nuevo"
    assert mov["movements"]["M_REINT"] == "Reintegrado"
    assert mov["movements"]["BIM_PAR"] == "No le correspondía"
    assert mov["absence_counts"]["M_LEFT"] == 2  # 202604 and 202605 (202603 skipped!)

    bands = compute_maturation_bands(
        [
            {"fecha_fact_lect": None, "importe_trans": 10},
            {"fecha_fact_lect": dt.date(2026, 8, 5), "importe_trans": 20},
            {"fecha_fact_lect": dt.date(2026, 7, 10), "importe_trans": 30},
            {"fecha_fact_lect": dt.date(2026, 6, 15), "importe_trans": 40},
            {"fecha_fact_lect": dt.date(2025, 1, 1), "importe_trans": 50},
        ],
        periodo="202607",
    )
    assert bands["SIN_FECHA"] == Decimal("10.00")
    assert bands["FECHA_FUTURA"] == Decimal("20.00")
    assert bands["DEL_MES"] == Decimal("30.00")
    assert bands["UN_MES"] == Decimal("40.00")
    assert bands["MAS_DE_UN_ANO"] == Decimal("50.00")

    pay = classify_payment_behavior(
        [
            {
                "identificador": "1",
                "nombre": "Municipio Alcalá",
                "tarifa": "Oficial",
                "cortes_facturados": 3,
                "cortes_con_recaudo": 0,
                "cartera": 500,
            },
            {
                "identificador": "2",
                "nombre": "Juan",
                "tarifa": "Res",
                "cortes_facturados": 3,
                "cortes_con_recaudo": 3,
                "cartera": 0,
            },
        ]
    )
    assert pay[0]["comportamiento"] == "NUNCA_PAGA"
    assert pay[0]["tipo_gestion"] == "INSTITUCIONAL"
    assert pay[1]["comportamiento"] == "PAGA_SIEMPRE"

    conc = compute_portfolio_concentration(
        [
            {"nic": "A", "deuda_corriente": 600},
            {"nic": "B", "deuda_corriente": 300},
            {"nic": "C", "deuda_corriente": 100},
        ]
    )
    assert conc["cuantos_suman_50_pct"] == 1
    assert conc["top_10"] == Decimal("1000.00")

    oc = audit_oc135_convenios(
        [
            {
                "nic": "901",
                "sv": "SV-1",
                "cod_oper_cont": "OC135",
                "concepto": "CI300",
                "importe_trans": 5000,
                "valor_recibo": 5000,
                "fecha_fact_lect": "2026-07-01",
                "fecha_trans": "2026-07-02",
            }
        ]
    )
    assert oc[0]["conciliado"] is True

    alert = detect_negative_adjustment_alert(
        {
            "202606": [{"importe_trans": 1000}, {"importe_trans": -50}],
            "202607": [{"importe_trans": 1000}, {"importe_trans": -200}],
        },
        target_periodo="202607",
    )
    assert alert["alerta"] is True

    # Irregulars: 5 categories in Afinia, and Celsia < 202605 skips evaluation
    irreg_afinia = detect_irregular_invoices(
        [
            {
                "nic": "N1",
                "periodo": "202607",
                "concepto": "CI400",
                "tarifa": "T1",
                "importe_trans": -100,
            },
            {
                "nic": "N2",
                "periodo": "202607",
                "concepto": "CI400",
                "tarifa": "T1",
                "importe_trans": 0,
            },
            {
                "nic": "N3",
                "periodo": "202607",
                "concepto": "CI306",
                "tarifa": "T1",
                "importe_trans": 500,
            },
            {
                "nic": "N4",
                "periodo": "202607",
                "concepto": "CI400",
                "tarifa": "T1",
                "importe_trans": 100,
            },
            {
                "nic": "N4",
                "periodo": "202607",
                "concepto": "CI400",
                "tarifa": "T1",
                "importe_trans": 200,
            },
        ],
        operator="afinia",
        periodo="202607",
    )
    assert irreg_afinia["LINEA_NEGATIVA"] == ["N1"]
    assert irreg_afinia["TOTAL_NEGATIVO"] == ["N1"]
    assert irreg_afinia["TOTAL_EN_CERO"] == ["N2"]
    assert irreg_afinia["SIN_CONCEPTO_IMPUESTO"] == ["N3"]
    assert irreg_afinia["IMPUESTO_AMBIGUO"] == ["N4"]

    irreg_celsia_pre = detect_irregular_invoices(
        [
            {
                "cuenta": "C1",
                "periodo": "202604",
                "tipo_concepto": "impuesto",
                "tarifa": "R1",
                "valor_facturado": -10,
            }
        ],
        operator="celsia",
        periodo="202604",
    )
    assert all(len(v) == 0 for v in irreg_celsia_pre.values())
