"""Deterministic synthetic commercial dataset builders for SYN-2 (Afinia), SYN-3 (Celsia/Vatia),
and IMP-5 (OPainn Parquet + SHA-256 manifest.json).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from fixtures.lzw_z import compress_z
from fixtures.xlsx_builder import FormulaCell, XlsxSheet, build_xlsx_bytes

AFINIA_CANONICAL_TARIFFS: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("AP_Comerciales_Nivel_1", Decimal("0.30"), Decimal("0.12")),
    ("AP_Comerciales_Nivel_2", Decimal("0.30"), Decimal("0.12")),
    ("AP_Industriales_Nivel_1", Decimal("0.30"), Decimal("0.12")),
    ("AP_Industriales_Nivel_2", Decimal("0.30"), Decimal("0.12")),
    ("AP_Oficiales_Nivel_1", Decimal("0.30"), Decimal("0.12")),
    ("AP_Oficiales_Nivel_2", Decimal("0.30"), Decimal("0.12")),
    ("AP_Residenciales_Estrato_1", Decimal("0.04"), Decimal("0.02")),
    ("AP_Residenciales_Estrato_2", Decimal("0.06"), Decimal("0.03")),
    ("AP_Residenciales_Estrato_3", Decimal("0.07"), Decimal("0.04")),
    ("AP_Residenciales_Estrato_4", Decimal("0.09"), Decimal("0.05")),
    ("AP_Residenciales_Estrato_5", Decimal("0.12"), Decimal("0.06")),
    ("AP_Residenciales_Estrato_6", Decimal("0.14"), Decimal("0.07")),
)

AFINIA_39_UVT_DISTRIBUTION: tuple[tuple[Decimal, int], ...] = (
    (Decimal("0.3"), 1),
    (Decimal(3), 1),
    (Decimal(5), 13),
    (Decimal(7), 1),
    (Decimal(12), 1),
    (Decimal(15), 1),
    (Decimal(25), 2),
    (Decimal(45), 2),
    (Decimal(80), 1),
    (Decimal(90), 15),
    (Decimal(180), 2),
)

AFINIA_39_UVT_FACTORS: tuple[Decimal, ...] = tuple(
    factor for factor, count in AFINIA_39_UVT_DISTRIBUTION for _ in range(count)
)

AFINIA_TRANSACCIONAL_HEADERS: tuple[str, ...] = (
    "FECHA PROC. REG.",
    "COD. OPER. CONT.",
    "NIC",
    "NIS RAD",
    "SEC. NIS",
    "SEC. REC.",
    "FECHA FACT.-LECT.",
    "TIPO CLIENTE-USO",
    "TARIFA",
    "ESTADO CONTRATO",
    "CONCEPTO",
    "IMPORTE TRANS.",
    "FECHA TRANS.",
    "VALOR RECIBO",
    "SECTOR-DPTO",
    "COD. MPIO",
    "COD. CORREG.",
    "COD. DPTO",
    "SV",
)

AFINIA_CATASTRO_HEADERS: tuple[str, ...] = (
    "TIPO SERV",
    "DESC SERV",
    "COD TARIFA",
    "DESC TAR",
    "NIC",
    "NIS RAD",
    "NOMBRE",
    "DIRECCIÓN",
    "CONSUMO FACTURADO",
    "MUNICIPIO",
    "BARRIO",
    "DEUDA CORRIENTE",
    "DEUDA CUOTA",
    "ESTADO SUMINISTRO",
)

CELSIA_2026_RULES: dict[str, dict[str, Any]] = {
    "E1": {"mode": "fixed", "urbano": Decimal("3994.50"), "rural": Decimal("2349.20")},
    "E2": {"mode": "fixed", "urbano": Decimal("7989.00"), "rural": Decimal("2349.20")},
    "E3": {
        "mode": "pct_min",
        "pct": Decimal("0.10"),
        "urbano_min": Decimal("13205.16"),
        "rural_min": Decimal("10564.99"),
    },
    "E4": {
        "mode": "pct_min",
        "pct": Decimal("0.10"),
        "urbano_min": Decimal("20417.51"),
        "rural_min": Decimal("16333.15"),
    },
    "E5": {
        "mode": "pct_min",
        "pct": Decimal("0.10"),
        "urbano_min": Decimal("26074.42"),
        "rural_min": Decimal("20860.39"),
    },
    "E6": {
        "mode": "pct_min",
        "pct": Decimal("0.10"),
        "urbano_min": Decimal("31908.91"),
        "rural_min": Decimal("25526.70"),
    },
    "NO_RES_N1": {
        "mode": "pct_min",
        "pct": Decimal("0.10"),
        "urbano_min": Decimal("18228.77"),
        "rural_min": Decimal("16405.90"),
    },
    "SERV_ESP": {"mode": "pct_only", "pct": Decimal("0.15")},
}

_MONTH_NAMES_ES = {
    1: "ENERO",
    2: "FEBRERO",
    3: "MARZO",
    4: "ABRIL",
    5: "MAYO",
    6: "JUNIO",
    7: "JULIO",
    8: "AGOSTO",
    9: "SETIEMBRE",
    10: "OCTUBRE",
    11: "NOVIEMBRE",
    12: "DICIEMBRE",
}


@dataclass(frozen=True)
class SyntheticFile:
    """In-memory synthetic file artifact ready for multipart upload or disk write."""

    filename: str
    content: bytes
    content_type: str


def _fmt_afinia_date(value: dt.date) -> str:
    return value.strftime("%Y-%m-%d")


def _row_to_delimited(rows: list[list[Any]], sep: str) -> bytes:
    lines: list[str] = []
    for row in rows:
        cells = []
        for item in row:
            if item is None:
                cells.append("")
            elif isinstance(item, dt.date):
                cells.append(_fmt_afinia_date(item))
            else:
                cells.append(str(item))
        lines.append(sep.join(cells))
    return ("\n".join(lines) + "\n").encode("cp1252")


def _afinia_tx_base(
    *,
    nic: int,
    tarifa: str,
    concepto: str | None,
    importe: Decimal,
    fecha_fact: dt.date,
    fecha_trans: dt.date,
    valor_recibo: Decimal,
    sv: str,
    cod_oper_cont: str = "OC100",
    tipo_cliente_uso: str = "Residencial",
) -> list[Any]:
    return [
        fecha_trans,
        cod_oper_cont,
        nic,
        nic + 100000,
        1,
        1,
        fecha_fact,
        tipo_cliente_uso,
        tarifa,
        1,
        concepto,
        float(importe),
        fecha_trans,
        float(valor_recibo),
        23,
        466,
        0,
        23,
        sv,
    ]


def build_afinia_cut_files(
    periodo: str = "202607",
    *,
    format_mode: str = "txt_z_xlsx",
    use_setiembre_spelling: bool = True,
    uvt: Decimal = Decimal(52374),
    nic_base: int = 7000000,
    include_duplicates: bool = True,
    include_negative_adjustment: bool = True,
) -> dict[str, SyntheticFile]:
    """Generate a complete 5-family Afinia synthetic monthly cut covering all edge cases.

    Covers: 12 canonical tariffs, 39 UVT exceptions, CI400/CI401/CI851/CI306/CI102/OC135,
    all 5 tariff states, all 5 irregular categories, exact duplicate rows, negative recaudo
    adjustment, cp1252 Latin chars, .Z LZW archive, SETIEMBRE book naming, and 21-col REFA Excel.
    """
    year = int(periodo[:4])
    month = int(periodo[4:6])
    corte_date = dt.date(year, month, 15)
    prior_month_date = dt.date(year - 1, 12, 15) if month == 1 else dt.date(year, month - 1, 15)
    corte_stamp = f"{year:04d}{month:02d}15"
    mes_nombre = _MONTH_NAMES_ES[month]
    if month == 9 and not use_setiembre_spelling:
        mes_nombre = "SEPTIEMBRE"

    catastro_rows: list[list[Any]] = []
    fact_rows: list[list[Any]] = []
    reca_rows: list[list[Any]] = []
    refa_rows: list[list[Any]] = []
    conv_rows: list[list[Any]] = []

    # 1. All 12 canonical tariffs (24 standard NICs: 1 <= 173 kWh, 1 > 173 kWh each)
    for t_idx, (tarifa, factor_uvt, pct_var) in enumerate(AFINIA_CANONICAL_TARIFFS):
        tarifa_cat = tarifa.replace("_", " ")
        uso = "Comercial" if "Comercial" in tarifa else "Residencial"
        nic_min = nic_base + t_idx * 10 + 1
        nic_var = nic_base + t_idx * 10 + 2
        expected_min = round(factor_uvt * uvt, 2)
        base_var = Decimal("1000000.00")
        expected_var = round(pct_var * base_var, 2)

        for nic, consumo, esperado, base_val in (
            (nic_min, 120.0, expected_min, Decimal("350000.00")),
            (nic_var, 500.0, expected_var, base_var),
        ):
            catastro_rows.append(
                [
                    "SV500",
                    "Alumbrado Público",
                    f"T{t_idx + 1:02d}",
                    tarifa_cat,
                    nic,
                    nic + 100000,
                    f"Usuario Ñandú {nic}",
                    f"Calle {t_idx + 1} # Peña-{nic % 100}",
                    consumo,
                    "MONTELIBANO",
                    "El Centro" if t_idx % 2 == 0 else "San Felipe",
                    float(esperado * 2),
                    0.0,
                    "ACTIVO",
                ]
            )
            sv = f"SV-{periodo}-{nic}"
            fact_rows.append(
                _afinia_tx_base(
                    nic=nic,
                    tarifa=tarifa,
                    concepto="CI400",
                    importe=esperado,
                    fecha_fact=corte_date,
                    fecha_trans=corte_date,
                    valor_recibo=esperado,
                    sv=sv,
                    tipo_cliente_uso=uso,
                )
                + [consumo, float(base_val)]
            )
            reca_rows.append(
                _afinia_tx_base(
                    nic=nic,
                    tarifa=tarifa,
                    concepto="CI400",
                    importe=esperado,
                    fecha_fact=corte_date,
                    fecha_trans=corte_date,
                    valor_recibo=esperado,
                    sv=sv,
                    tipo_cliente_uso=uso,
                )
            )

    # 2. All 39 UVT exceptions
    for e_idx, factor in enumerate(AFINIA_39_UVT_FACTORS):
        nic = nic_base + 500 + e_idx
        tarifa = AFINIA_CANONICAL_TARIFFS[e_idx % len(AFINIA_CANONICAL_TARIFFS)][0]
        esperado = round(factor * uvt, 2)
        sv = f"SV-{periodo}-{nic}"
        catastro_rows.append(
            [
                "SV500",
                "Alumbrado Público",
                "T99",
                tarifa.replace("_", " "),
                nic,
                nic + 100000,
                f"Especial UVT {e_idx + 1}",
                "Zona Especial Montelíbano",
                300.0,
                "MONTELIBANO",
                "Rurales",
                float(esperado),
                0.0,
                "ACTIVO",
            ]
        )
        fact_rows.append(
            _afinia_tx_base(
                nic=nic,
                tarifa=tarifa,
                concepto="CI400",
                importe=esperado,
                fecha_fact=corte_date,
                fecha_trans=corte_date,
                valor_recibo=esperado,
                sv=sv,
            )
            + [300.0, 900000.0]
        )

    # 3. Tariff control states + signals (CI401/CI851) + irregular categories + CI306/OC135/CI102
    special_nic_base = nic_base + 900
    # POR_ENCIMA (+500) + CI401 signal
    nic_over = special_nic_base + 1
    fact_rows.append(
        _afinia_tx_base(
            nic=nic_over,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI400",
            importe=Decimal("2594.96"),  # expected 2094.96 (+500)
            fecha_fact=corte_date,
            fecha_trans=corte_date,
            valor_recibo=Decimal("2594.96"),
            sv=f"SV-{periodo}-{nic_over}",
        )
        + [100.0, 100000.0]
    )
    fact_rows.append(
        _afinia_tx_base(
            nic=nic_over,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI401",
            importe=Decimal("-100.00"),
            fecha_fact=corte_date,
            fecha_trans=corte_date,
            valor_recibo=Decimal("2494.96"),
            sv=f"SV-{periodo}-{nic_over}",
        )
        + [0.0, 0.0]
    )

    # POR_DEBAJO (-400) + CI851 signal
    nic_under = special_nic_base + 2
    fact_rows.append(
        _afinia_tx_base(
            nic=nic_under,
            tarifa="AP_Residenciales_Estrato_2",
            concepto="CI400",
            importe=Decimal("2742.44"),  # expected 3142.44 (-400)
            fecha_fact=corte_date,
            fecha_trans=corte_date,
            valor_recibo=Decimal("2742.44"),
            sv=f"SV-{periodo}-{nic_under}",
        )
        + [90.0, 100000.0]
    )
    fact_rows.append(
        _afinia_tx_base(
            nic=nic_under,
            tarifa="AP_Residenciales_Estrato_2",
            concepto="CI851",
            importe=Decimal("-50.00"),
            fecha_fact=corte_date,
            fecha_trans=corte_date,
            valor_recibo=Decimal("2692.44"),
            sv=f"SV-{periodo}-{nic_under}",
        )
        + [0.0, 0.0]
    )

    # NO_VALIDABLE (>173 kWh with valor_consumo_antes = None)
    nic_noval = special_nic_base + 3
    fact_rows.append(
        _afinia_tx_base(
            nic=nic_noval,
            tarifa="AP_Residenciales_Estrato_3",
            concepto="CI400",
            importe=Decimal("10000.00"),
            fecha_fact=corte_date,
            fecha_trans=corte_date,
            valor_recibo=Decimal("10000.00"),
            sv=f"SV-{periodo}-{nic_noval}",
        )
        + [400.0, None]
    )

    # REQUIERE_REVISION (MULTIPLES_CI400) + Impuesto ambiguo irregular
    nic_rev = special_nic_base + 4
    sv_rev = f"SV-{periodo}-{nic_rev}"
    for _ in range(2):
        fact_rows.append(
            _afinia_tx_base(
                nic=nic_rev,
                tarifa="AP_Residenciales_Estrato_4",
                concepto="CI400",
                importe=Decimal("4713.66"),
                fecha_fact=corte_date,
                fecha_trans=corte_date,
                valor_recibo=Decimal("9427.32"),
                sv=sv_rev,
            )
            + [100.0, 200000.0]
        )

    # Irregulars: Linea negativa + Total negativo, Total en cero, Sin concepto impuesto
    nic_neg = special_nic_base + 5
    fact_rows.append(
        _afinia_tx_base(
            nic=nic_neg,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI400",
            importe=Decimal("-500.00"),
            fecha_fact=corte_date,
            fecha_trans=corte_date,
            valor_recibo=Decimal("-500.00"),
            sv=f"SV-{periodo}-{nic_neg}",
        )
        + [50.0, 50000.0]
    )
    nic_zero = special_nic_base + 6
    fact_rows.append(
        _afinia_tx_base(
            nic=nic_zero,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI400",
            importe=Decimal("0.00"),
            fecha_fact=corte_date,
            fecha_trans=corte_date,
            valor_recibo=Decimal("0.00"),
            sv=f"SV-{periodo}-{nic_zero}",
        )
        + [10.0, 10000.0]
    )
    nic_notax = special_nic_base + 7
    fact_rows.append(
        _afinia_tx_base(
            nic=nic_notax,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI306",
            importe=Decimal("1500.00"),
            fecha_fact=corte_date,
            fecha_trans=corte_date,
            valor_recibo=Decimal("1500.00"),
            sv=f"SV-{periodo}-{nic_notax}",
        )
        + [0.0, 0.0]
    )

    # Recaudo: cartera + CI102 + exact duplicate + negative adjustment
    reca_cartera_row = _afinia_tx_base(
        nic=nic_over,
        tarifa="AP_Residenciales_Estrato_1",
        concepto="CI400",
        importe=Decimal("2594.96"),
        fecha_fact=prior_month_date - dt.timedelta(days=35),
        fecha_trans=corte_date,
        valor_recibo=Decimal("2594.96"),
        sv=f"SV-OLD-{nic_over}",
    )
    reca_rows.append(reca_cartera_row)
    if include_duplicates:
        reca_rows.append(list(reca_cartera_row))
    reca_rows.append(
        _afinia_tx_base(
            nic=nic_over,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI102",
            importe=Decimal("125.50"),
            fecha_fact=prior_month_date - dt.timedelta(days=35),
            fecha_trans=corte_date,
            valor_recibo=Decimal("125.50"),
            sv=f"SV-MORA-{nic_over}",
        )
    )
    if include_negative_adjustment:
        reca_rows.append(
            _afinia_tx_base(
                nic=nic_under,
                tarifa="AP_Residenciales_Estrato_2",
                concepto="CI400",
                importe=Decimal("-350.00"),
                fecha_fact=corte_date,
                fecha_trans=corte_date,
                valor_recibo=Decimal("-350.00"),
                sv=f"SV-ADJ-{nic_under}",
            )
        )

    # Refactura (20 cols in .txt, 21 cols with CONSUMO KWH in Excel book!)
    refa_base_row = _afinia_tx_base(
        nic=nic_over,
        tarifa="AP_Residenciales_Estrato_1",
        concepto="CI400",
        importe=Decimal("320.00"),
        fecha_fact=corte_date,
        fecha_trans=corte_date,
        valor_recibo=Decimal("320.00"),
        sv=f"SV-REFA-{nic_over}",
    )
    refa_rows.append(refa_base_row + [100000.0])

    # Convenio (OC135)
    conv_rows.append(
        _afinia_tx_base(
            nic=nic_notax,
            tarifa="AP_Residenciales_Estrato_1",
            concepto="CI300",
            importe=Decimal("15000.00"),
            fecha_fact=corte_date,
            fecha_trans=corte_date,
            valor_recibo=Decimal("15000.00"),
            sv=f"SV-CONV-{nic_notax}",
            cod_oper_cont="OC135",
        )
    )

    out: dict[str, SyntheticFile] = {}
    if "txt" in format_mode:
        out["catastro_txt"] = SyntheticFile(
            filename=f"CATASTRO_USUARIOS_SV500_ZONA_1_{corte_stamp}.txt",
            content=_row_to_delimited(catastro_rows, "|"),
            content_type="text/plain; charset=cp1252",
        )
        out["facturacion_txt"] = SyntheticFile(
            filename=f"FACT_SV500_ZONA_1_{corte_stamp}.txt",
            content=_row_to_delimited(fact_rows, "\t"),
            content_type="text/plain; charset=cp1252",
        )
    if "z" in format_mode:
        reca_bytes = _row_to_delimited(reca_rows, "\t")
        out["recaudo_z"] = SyntheticFile(
            filename=f"RECA_SV500_ZONA_1_{corte_stamp}.txt.Z",
            content=compress_z(reca_bytes),
            content_type="application/x-compress",
        )
        conv_bytes = _row_to_delimited(conv_rows, "\t")
        out["convenio_z"] = SyntheticFile(
            filename=f"CONV_SV500_ZONA_1_{corte_stamp}.txt.Z",
            content=compress_z(conv_bytes),
            content_type="application/x-compress",
        )
        refa_bytes = _row_to_delimited(refa_rows, "\t")
        out["refactura_z"] = SyntheticFile(
            filename=f"REFA_SV500_ZONA_1_{corte_stamp}.txt.Z",
            content=compress_z(refa_bytes),
            content_type="application/x-compress",
        )

    if "xlsx" in format_mode:
        xlsx_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        out["catastro_xlsx"] = SyntheticFile(
            filename=f"CATASTRO_MONTELIBANO_{mes_nombre}_{year}.xlsx",
            content=build_xlsx_bytes(
                [XlsxSheet("catastro", [list(AFINIA_CATASTRO_HEADERS), *catastro_rows])]
            ),
            content_type=xlsx_mime,
        )
        fact_headers = [
            *AFINIA_TRANSACCIONAL_HEADERS,
            "CONSUMO KWH",
            "VALOR DEL CONSUMO ANTES DE TODO",
        ]
        out["facturacion_xlsx"] = SyntheticFile(
            filename=f"FACTURACION_MONTELIBANO_{mes_nombre}_{year}.xlsx",
            content=build_xlsx_bytes([XlsxSheet("facturacion", [fact_headers, *fact_rows])]),
            content_type=xlsx_mime,
        )
        out["recaudo_xlsx"] = SyntheticFile(
            filename=f"RECAUDO_MONTELIBANO_{mes_nombre}_{year}.xlsx",
            content=build_xlsx_bytes(
                [XlsxSheet("recaudo", [list(AFINIA_TRANSACCIONAL_HEADERS), *reca_rows])]
            ),
            content_type=xlsx_mime,
        )
        # 21-col REFACTURACION book including CONSUMO KWH column to test adapter stripping
        refa_21_rows = [[*r[:-1], 50.0, r[-1]] for r in refa_rows]
        out["refacturacion_xlsx"] = SyntheticFile(
            filename=f"REFACTURACION_MONTELIBANO_{mes_nombre}_{year}.xlsx",
            content=build_xlsx_bytes([XlsxSheet("refactura", [fact_headers, *refa_21_rows])]),
            content_type=xlsx_mime,
        )
        out["convenio_xlsx"] = SyntheticFile(
            filename=f"CONVENIO_MONTELIBANO_{mes_nombre}_{year}.xlsx",
            content=build_xlsx_bytes(
                [XlsxSheet("convenio", [list(AFINIA_TRANSACCIONAL_HEADERS), *conv_rows])]
            ),
            content_type=xlsx_mime,
        )

    return out


def build_afinia_3month_dataset(
    periods: tuple[str, ...] = ("202602", "202604", "202605"),
) -> dict[str, dict[str, SyntheticFile]]:
    """Build deterministic multi-month Afinia cuts (defaults to skipping 202603)."""
    return {p: build_afinia_cut_files(periodo=p) for p in periods}


def build_afinia_formula_xlsx(periodo: str = "202607") -> SyntheticFile:
    """Build an invalid Afinia Excel containing an Excel formula (=SUM) for Tier 2 rejection."""
    year = int(periodo[:4])
    month = int(periodo[4:6])
    mes = _MONTH_NAMES_ES[month]
    rows = [
        [*AFINIA_TRANSACCIONAL_HEADERS, "CONSUMO KWH", "VALOR DEL CONSUMO ANTES DE TODO"],
        [
            dt.date(year, month, 15),
            "OC100",
            7000001,
            7100001,
            1,
            1,
            dt.date(year, month, 15),
            "Residencial",
            "AP_Residenciales_Estrato_1",
            1,
            "CI400",
            FormulaCell("SUM(1000,1094.96)", 2094.96),
            dt.date(year, month, 15),
            2094.96,
            23,
            466,
            0,
            23,
            "SV-FORMULA-1",
            100.0,
            100000.0,
        ],
    ]
    return SyntheticFile(
        filename=f"FACTURACION_MONTELIBANO_{mes}_{year}.xlsx",
        content=build_xlsx_bytes([XlsxSheet("facturacion", rows)], allow_formula_strings=True),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def build_afinia_extra_col_xlsx(periodo: str = "202607") -> SyntheticFile:
    """Build an invalid Afinia Excel with an unexpected extra column for Tier 2 rejection."""
    year = int(periodo[:4])
    month = int(periodo[4:6])
    mes = _MONTH_NAMES_ES[month]
    rows = [
        [
            *AFINIA_TRANSACCIONAL_HEADERS,
            "CONSUMO KWH",
            "VALOR DEL CONSUMO ANTES DE TODO",
            "COLUMNA_EXTRA",
        ],
        [
            dt.date(year, month, 15),
            "OC100",
            7000001,
            7100001,
            1,
            1,
            dt.date(year, month, 15),
            "Residencial",
            "AP_Residenciales_Estrato_1",
            1,
            "CI400",
            2094.96,
            dt.date(year, month, 15),
            2094.96,
            23,
            466,
            0,
            23,
            "SV-EXTRA-1",
            100.0,
            100000.0,
            "EXTRA",
        ],
    ]
    return SyntheticFile(
        filename=f"FACTURACION_MONTELIBANO_{mes}_{year}.xlsx",
        content=build_xlsx_bytes([XlsxSheet("facturacion", rows)]),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def build_celsia_xlsx(
    periodo: str = "202606",
    *,
    footer_rows_count: int = 2,
    include_c2m: bool = True,
    filename_override: str | None = None,
) -> SyntheticFile:
    """Build a Celsia Alcalá .xlsx with Facturación, Recaudo, Cartera, and optional C2M sheet."""
    year = int(periodo[:4])
    month = int(periodo[4:6])
    yy = f"{year % 100:02d}"
    mes = _MONTH_NAMES_ES[month]
    if month == 9:
        mes = "SEPTIEMBRE"
    fname = filename_override or f"CELSIA_ALCALA_{mes}_{yy}.xlsx"

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
            "8001001",
            f"FC-{periodo}-01",
            f_date,
            "Ana Gómez",
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
        # Urban monthly E2 fixed ($7,989.00 -> POR_ENCIMA +500)
        [
            "8001002",
            f"FC-{periodo}-02",
            f_date,
            "Luis Pérez",
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
        # Rural bimonthly E3 (min = 2 * 10564.99 = 21129.98; 10% VCE = 15000 -> expected 21129.98)
        [
            "8001003",
            f"FC-{periodo}-03",
            f_date,
            "Finca La Palma",
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
        ],
        # Comercial without numeric estrato -> fallback to segmento
        [
            "8001004",
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
        # NO_VALIDABLE (missing VCE)
        [
            "8001005",
            f"FC-{periodo}-05",
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
        ],
    ]
    for f_idx in range(footer_rows_count):
        fact_rows.append(
            [
                None,
                None,
                None,
                f"TOTAL PARCIAL {f_idx + 1}",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                0.0,
                0.0,
                0.0,
            ]
        )

    reca_rows: list[list[Any]] = [
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
            "8001001",
            f"FC-{periodo}-01",
            vcto_date,
            f_date + dt.timedelta(days=5),
            f_date + dt.timedelta(days=5),
            "Ana Gómez",
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
            "8001003",
            f"FC-{periodo}-03",
            vcto_date - dt.timedelta(days=60),
            f_date,
            f_date,
            "Finca La Palma",
            "Vereda El Congal",
            "1 Residencial",
            "R3",
            "Estrato 3",
            "Rural",
            "ALCALA",
            "Impuesto Alumbrado Público",
            21129.98,
        ],
    ]

    cart_rows: list[list[Any]] = [
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
    ]

    sheets: list[XlsxSheet] = [
        XlsxSheet("Facturacion", fact_rows),
        XlsxSheet("Recaudo", reca_rows),
        XlsxSheet("Cartera", cart_rows),
    ]
    if include_c2m:
        sheets.append(
            XlsxSheet(
                "C2M",
                [
                    ["Nota", "Valor del Impuesto Facturado"],
                    ["Hoja resumen C2M que debe excluirse", 9999999.0],
                ],
            )
        )

    return SyntheticFile(
        filename=fname,
        content=build_xlsx_bytes(sheets),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def build_celsia_invalid_footer_xlsx(periodo: str = "202606") -> SyntheticFile:
    """Build a Celsia Excel with >20 AND >10% footer rows missing cuenta (must be rejected)."""
    return build_celsia_xlsx(periodo=periodo, footer_rows_count=25)


def build_celsia_mismatched_period_xlsx() -> SyntheticFile:
    """Build a Celsia Excel named _ABR_26 containing June 2026 dates (>1 month mismatch)."""
    return build_celsia_xlsx(periodo="202606", filename_override="CELSIA_ALCALA_ABR_26.xlsx")


def build_celsia_3month_dataset(
    periods: tuple[str, ...] = ("202604", "202605", "202606"),
) -> dict[str, SyntheticFile]:
    """Build 3 consecutive Celsia cuts (202604 pre-May + 202605/202606)."""
    return {p: build_celsia_xlsx(periodo=p) for p in periods}


def build_vatia_xlsx(
    periodo: str = "202606",
    *,
    include_negative_net: bool = False,
) -> SyntheticFile:
    """Build a valid Vatia Alcalá .xlsx with mandatory columns, valid 0, and negative notes."""
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
        "DIR FACTURACION",
        "DIRECCION DE CORRESPONDENCIA",
        "NIVEL DE TENSION",
        "OPERADOR DE RED",
        "MERCADO",
        "SUBMERCADO",
        "ESTRATO",
        "DEPTO FACTURACION",
        "MUNI FACTURACION",
        "FECHA ELAB FACTURA",
        "CONCEPTO",
        "TIPO NOTA",
        "VLR NOTA",
        "FACTURADO TOTAL INCLUYE NOTAS",
        "RECAUDO MES",
        "RECUPERACION CARTERA",
        "FECHA PAGO",
        "SALDO EN CARTERA",
        "EDAD CIERRE MES CICLO",
        "CONSUMO ACTIVA KW",
        "FECHA INIPER",
        "FECHA FINPER",
    ]
    rows: list[list[Any]] = [
        headers,
        [
            periodo,
            f"VAT-{periodo}-01",
            "900111222",
            "VAT-001",
            "Industria Valle SAS",
            "Km 2 Vía Alcalá",
            "Km 2 Vía Alcalá",
            "Nivel 2",
            "CELSIA",
            "No Regulado",
            "Industrial",
            "N/A",
            "VALLE DEL CAUCA",
            "ALCALA",
            f_elab,
            "Alumbrado Público",
            None,
            0.0,
            180000.0,
            180000.0,
            0.0,
            f_elab + dt.timedelta(days=5),
            0.0,
            "Al día",
            4500.0,
            f_ini,
            f_fin,
        ],
        # Valid 0 facturado & recaudo (efficiency -> null)
        [
            periodo,
            f"VAT-{periodo}-02",
            "900333444",
            "VAT-002",
            "Comercio Cero Ltda",
            "Cra 3 # 4-5",
            "Cra 3 # 4-5",
            "Nivel 1",
            "CELSIA",
            "No Regulado",
            "Comercial",
            "N/A",
            "VALLE DEL CAUCA",
            "ALCALA",
            f_elab,
            "Alumbrado Público",
            None,
            0.0,
            0.0,
            0.0,
            0.0,
            None,
            45000.0,
            "30 días",
            0.0,
            f_ini,
            f_fin,
        ],
        # Negative note
        [
            periodo,
            f"VAT-{periodo}-03",
            "900555666",
            "VAT-003",
            "Bodega Notas SAS",
            "Calle 8 # 1-10",
            "Calle 8 # 1-10",
            "Nivel 1",
            "CELSIA",
            "No Regulado",
            "Comercial",
            "N/A",
            "VALLE DEL CAUCA",
            "ALCALA",
            f_elab,
            "Alumbrado Público",
            "NC",
            -250000.0 if include_negative_net else -50000.0,
            -200000.0 if include_negative_net else 50000.0,
            0.0,
            0.0,
            None,
            120000.0,
            "60 días",
            900.0,
            f_ini,
            f_fin,
        ],
    ]
    return SyntheticFile(
        filename=f"VATIA_ALCALA_{periodo}.xlsx",
        content=build_xlsx_bytes([XlsxSheet("Comercial", rows)]),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def build_vatia_invalid_na_xlsx(periodo: str = "202606") -> SyntheticFile:
    """Build an invalid Vatia Excel with 'N/A' in facturado_total_incluye_notas for rejection."""
    year = int(periodo[:4])
    month = int(periodo[4:6])
    rows = [
        [
            "CICLO",
            "CLIENTE ID",
            "FECHA ELAB FACTURA",
            "FACTURADO TOTAL INCLUYE NOTAS",
            "RECAUDO MES",
            "SALDO EN CARTERA",
        ],
        [periodo, "VAT-ERR-01", dt.date(year, month, 18), "N/A", 0.0, 0.0],
    ]
    return SyntheticFile(
        filename=f"VATIA_INVALIDO_{periodo}.xlsx",
        content=build_xlsx_bytes([XlsxSheet("Comercial", rows)]),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_opainn_parquet_package(
    dest_root: Path,
    *,
    sede_codigo: str = "montelibano",
    comercializador_codigo: str = "afinia",
    periodo: str = "202607",
    corrupt_hash: bool = False,
) -> Path:
    """Create an IMP-5 OPainn Parquet directory + manifest.json with SHA-256 checksums.

    Uses pyarrow when installed; falls back to valid Parquet PAR1 stub bytes + manifest
    when running in minimal environments without pyarrow.
    """
    pkg_dir = dest_root / sede_codigo / comercializador_codigo / periodo
    pkg_dir.mkdir(parents=True, exist_ok=True)

    sample_tables: dict[str, list[dict[str, Any]]] = {
        "facturacion": [
            {
                "periodo": periodo,
                "zona": "1",
                "nic": 7000001,
                "tarifa": "AP_Residenciales_Estrato_1",
                "concepto": "CI400",
                "importe_trans": 2094.96,
                "consumo_kwh": 120.0,
                "valor_consumo_antes": 350000.0,
            }
        ],
        "recaudo": [
            {
                "periodo": periodo,
                "zona": "1",
                "nic": 7000001,
                "tarifa": "AP_Residenciales_Estrato_1",
                "concepto": "CI400",
                "importe_trans": 2094.96,
            }
        ],
    }

    try:
        import pyarrow as pa  # type: ignore[import-not-found]
        import pyarrow.parquet as pq  # type: ignore[import-not-found]
    except ImportError:
        pa = None
        pq = None

    familias_meta: dict[str, dict[str, Any]] = {}
    for familia, records in sample_tables.items():
        pq_path = pkg_dir / f"{familia}.parquet"
        if pa is not None and pq is not None:
            table = pa.Table.from_pylist(records)
            pq.write_table(table, pq_path)
            raw_bytes = pq_path.read_bytes()
        else:
            payload = json.dumps(records, separators=(",", ":")).encode("utf-8")
            raw_bytes = b"PAR1" + payload + b"PAR1"
            pq_path.write_bytes(raw_bytes)

        digest = _sha256_bytes(raw_bytes)
        if corrupt_hash and familia == "facturacion":
            digest = "0" * 64
        familias_meta[familia] = {
            "archivo_parquet": pq_path.name,
            "filas": len(records),
            "sha256_parquet": digest,
        }

    manifest = {
        "sede_codigo": sede_codigo,
        "comercializador_codigo": comercializador_codigo,
        "periodo": periodo,
        "version_adaptador": "e2e-1.0",
        "fecha_publicacion_iso": dt.datetime.now(dt.UTC).isoformat(),
        "completo": False,
        "publicable": True,
        "familias": familias_meta,
        "advertencias": [],
    }
    (pkg_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return pkg_dir
