"""Exact DECIMAL(20,4) ROUND_HALF_UP mathematical oracle for EP-08 Comercial (OPainn parity)."""

from __future__ import annotations

import datetime as dt
import itertools
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fixtures.commercial_builder import AFINIA_CANONICAL_TARIFFS, CELSIA_2026_RULES

_Q2 = Decimal("0.01")
_Q4 = Decimal("0.0001")
_ZERO = Decimal(0)

AFINIA_TARIFF_MAP: dict[str, tuple[Decimal, Decimal]] = {
    name: (factor, pct) for name, factor, pct in AFINIA_CANONICAL_TARIFFS
}

TD_45_COLUMNS: tuple[str, ...] = (
    "estrato_uso",  # E
    "estrato_uso_catastro",  # F
    "n_factura",  # G
    "pct_n_factura",  # H
    "promedio_consumo_kwh",  # I
    "facturacion",  # J
    "tarifa_promedio",  # K
    "refacturacion",  # L
    "total_facturacion",  # M
    "n_rec",  # N
    "pct_n_rec",  # O
    "recaudo_corriente",  # P
    "factura_promedio_rec_corriente",  # Q
    "pct_recaudo_corriente",  # R
    "recaudo_total",  # S
    "factura_promedio_rec_total",  # T
    "pct_recaudo_total",  # U
    "n_facturas_recaudo_cartera",  # V
    "recaudo_cartera",  # W
    "pct_recaudo_cartera",  # X
    "factura_promedio_cartera",  # Y
    "n_facturacion_cartera_ordinaria",  # Z
    "pct_facturacion_cartera_ordinaria",  # AA
    "cartera_periodo",  # AB
    "eficiencia_con_cartera",  # AC
    "eficiencia_corriente",  # AD
    "eficiencia_facturacion",  # AE
    "n_usuarios_cartera_acumulada",  # AF
    "pct_n_usuarios_cartera",  # AG
    "cartera_acumulada",  # AH
    "pct_cartera_valor",  # AI
    "n_usuarios_cartera_recuperada",  # AJ
    "cartera_recuperada",  # AK
    "n_usuarios_interes_mora",  # AL
    "interes_mora_periodo",  # AM
    "n_usuarios_convenios",  # AN
    "valor_convenios_periodo",  # AO
    "n_usuarios_total_convenios",  # AP
    "total_valor_convenios",  # AQ
    "usuarios_dejados_facturar",  # AR
    "nuevos_usuarios",  # AS
    "usuarios_reintegrados",  # AT
    "n_facturas_convenios",  # AU
    "valor_promedio_factura_convenio",  # AV
    "n_usuarios_multiples_facturas_convenio",  # AW
)


def D(value: Any) -> Decimal:
    """Convert numeric input into exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return _ZERO
    return Decimal(str(value))


def q2(value: Any) -> Decimal:
    return D(value).quantize(_Q2, rounding=ROUND_HALF_UP)


def q4(value: Any) -> Decimal:
    return D(value).quantize(_Q4, rounding=ROUND_HALF_UP)


def safe_div(
    num: Decimal,
    den: Decimal,
    *,
    zero_fallback: Decimal | None = _ZERO,
) -> Decimal | None:
    if den == _ZERO:
        return zero_fallback
    return q4(num / den)


def _first_day_of_period(periodo: str) -> dt.date:
    return dt.date(int(periodo[:4]), int(periodo[4:6]), 1)


def _shift_months(day: dt.date, delta_months: int) -> dt.date:
    month_idx = (day.year * 12 + (day.month - 1)) + delta_months
    year, rem = divmod(month_idx, 12)
    return dt.date(year, rem + 1, 1)


def classify_recaudo_tipo_afinia(fecha_fact_lect: dt.date | None, periodo: str) -> str:
    if fecha_fact_lect is None:
        return "NO_CLASIFICADO"
    cutoff = _shift_months(_first_day_of_period(periodo), -1)
    return "CORRIENTE" if fecha_fact_lect >= cutoff else "CARTERA"


@dataclass(frozen=True)
class TariffControlRow:
    identificador: str
    periodo: str
    tarifa: str
    estado: str
    motivo_revision: str | None
    regla_aplicada: str | None
    facturado_real: Decimal
    esperado: Decimal | None
    diferencia: Decimal | None
    valor_por_encima: Decimal
    valor_por_debajo: Decimal
    senal_ci401: Decimal = _ZERO
    senal_ci851: Decimal = _ZERO


def evaluate_afinia_tariff_control(
    facturacion_rows: Sequence[Mapping[str, Any]],
    *,
    periodo: str,
    uvt: Decimal = Decimal(52374),
    umbral_kwh: Decimal = Decimal(173),
    tolerancia: Decimal = Decimal("1.00"),
    tarifas: Mapping[str, tuple[Decimal, Decimal]] = AFINIA_TARIFF_MAP,
    excepciones: Mapping[str, Decimal] | None = None,
    has_vigencia: bool = True,
) -> dict[str, Any]:
    """Exact Afinia 2026 tariff control oracle (CI400 + 39 UVT exceptions + $1 tolerance)."""
    exc_map = {str(k): D(v) for k, v in (excepciones or {}).items()}
    ci400_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    all_nics: set[str] = set()
    nics_with_ci400: set[str] = set()
    signals: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"CI401": _ZERO, "CI851": _ZERO})

    for row in facturacion_rows:
        if str(row.get("periodo", periodo)) != periodo:
            continue
        nic = str(row["nic"])
        all_nics.add(nic)
        concepto = str(row.get("concepto") or "")
        if concepto == "CI400":
            nics_with_ci400.add(nic)
            ci400_groups[(nic, str(row.get("tarifa") or ""))].append(row)
        elif concepto == "CI401":
            signals[nic]["CI401"] += D(row.get("importe_trans"))
        elif concepto == "CI851":
            signals[nic]["CI851"] += D(row.get("importe_trans"))

    results: list[TariffControlRow] = []

    for nic in sorted(all_nics - nics_with_ci400):
        results.append(
            TariffControlRow(
                identificador=nic,
                periodo=periodo,
                tarifa="",
                estado="REQUIERE_REVISION",
                motivo_revision="SIN_CI400",
                regla_aplicada=None,
                facturado_real=_ZERO,
                esperado=None,
                diferencia=None,
                valor_por_encima=_ZERO,
                valor_por_debajo=_ZERO,
                senal_ci401=q2(signals[nic]["CI401"]),
                senal_ci851=q2(signals[nic]["CI851"]),
            )
        )

    for (nic, tarifa), group in sorted(ci400_groups.items()):
        sig_401 = q2(signals[nic]["CI401"])
        sig_851 = q2(signals[nic]["CI851"])
        facturado = q2(sum((D(r.get("importe_trans")) for r in group), _ZERO))

        if not has_vigencia:
            results.append(
                TariffControlRow(
                    identificador=nic,
                    periodo=periodo,
                    tarifa=tarifa,
                    estado="REQUIERE_REVISION",
                    motivo_revision="PERIODO_SIN_PARAMETROS",
                    regla_aplicada=None,
                    facturado_real=facturado,
                    esperado=None,
                    diferencia=None,
                    valor_por_encima=_ZERO,
                    valor_por_debajo=_ZERO,
                    senal_ci401=sig_401,
                    senal_ci851=sig_851,
                )
            )
            continue

        if len(group) > 1:
            results.append(
                TariffControlRow(
                    identificador=nic,
                    periodo=periodo,
                    tarifa=tarifa,
                    estado="REQUIERE_REVISION",
                    motivo_revision="MULTIPLES_CI400",
                    regla_aplicada=None,
                    facturado_real=facturado,
                    esperado=None,
                    diferencia=None,
                    valor_por_encima=_ZERO,
                    valor_por_debajo=_ZERO,
                    senal_ci401=sig_401,
                    senal_ci851=sig_851,
                )
            )
            continue

        row = group[0]
        is_exception = nic in exc_map
        if not is_exception and tarifa not in tarifas:
            results.append(
                TariffControlRow(
                    identificador=nic,
                    periodo=periodo,
                    tarifa=tarifa,
                    estado="REQUIERE_REVISION",
                    motivo_revision="TARIFA_SIN_PARAMETROS",
                    regla_aplicada=None,
                    facturado_real=facturado,
                    esperado=None,
                    diferencia=None,
                    valor_por_encima=_ZERO,
                    valor_por_debajo=_ZERO,
                    senal_ci401=sig_401,
                    senal_ci851=sig_851,
                )
            )
            continue

        consumo_raw = row.get("consumo_kwh")
        if not is_exception and consumo_raw is None:
            results.append(
                TariffControlRow(
                    identificador=nic,
                    periodo=periodo,
                    tarifa=tarifa,
                    estado="REQUIERE_REVISION",
                    motivo_revision="CONSUMO_CI400_NULO",
                    regla_aplicada=None,
                    facturado_real=facturado,
                    esperado=None,
                    diferencia=None,
                    valor_por_encima=_ZERO,
                    valor_por_debajo=_ZERO,
                    senal_ci401=sig_401,
                    senal_ci851=sig_851,
                )
            )
            continue

        if is_exception:
            regla = "COBRO_ESPECIAL_UVT"
            esperado: Decimal | None = q2(exc_map[nic] * uvt)
        else:
            consumo = D(consumo_raw)
            factor_uvt, pct_var = tarifas[tarifa]
            if consumo <= umbral_kwh:
                regla = "FACTURACION_MINIMA"
                esperado = q2(factor_uvt * uvt)
            else:
                regla = "COSTO_VARIABLE"
                vca_raw = row.get("valor_consumo_antes")
                if vca_raw is None:
                    results.append(
                        TariffControlRow(
                            identificador=nic,
                            periodo=periodo,
                            tarifa=tarifa,
                            estado="NO_VALIDABLE",
                            motivo_revision=None,
                            regla_aplicada=regla,
                            facturado_real=facturado,
                            esperado=None,
                            diferencia=None,
                            valor_por_encima=_ZERO,
                            valor_por_debajo=_ZERO,
                            senal_ci401=sig_401,
                            senal_ci851=sig_851,
                        )
                    )
                    continue
                esperado = q2(pct_var * D(vca_raw))

        assert esperado is not None
        diff = q2(facturado - esperado)
        if abs(diff) <= tolerancia:
            estado = "CORRECTO"
            v_encima = _ZERO
            v_debajo = _ZERO
        elif diff > tolerancia:
            estado = "POR_ENCIMA"
            v_encima = diff
            v_debajo = _ZERO
        else:
            estado = "POR_DEBAJO"
            v_encima = _ZERO
            v_debajo = abs(diff)

        results.append(
            TariffControlRow(
                identificador=nic,
                periodo=periodo,
                tarifa=tarifa,
                estado=estado,
                motivo_revision=None,
                regla_aplicada=regla,
                facturado_real=facturado,
                esperado=esperado,
                diferencia=diff,
                valor_por_encima=v_encima,
                valor_por_debajo=v_debajo,
                senal_ci401=sig_401,
                senal_ci851=sig_851,
            )
        )

    return _summarize_tariff_results(results)


def evaluate_celsia_tariff_control(
    facturacion_rows: Sequence[Mapping[str, Any]],
    *,
    periodo: str,
    bimonthly_accounts: set[str] | None = None,
    tolerancia: Decimal = Decimal("100.00"),
    rules: Mapping[str, Mapping[str, Any]] = CELSIA_2026_RULES,
) -> dict[str, Any]:
    """Exact Celsia 2026 tariff control oracle (urban/rural, bimonthly x2, $100 tolerance)."""
    bimonthly = bimonthly_accounts or set()
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in facturacion_rows:
        if str(row.get("periodo", periodo)) != periodo:
            continue
        if str(row.get("tipo_concepto", "")) != "impuesto":
            continue
        grouped[str(row["cuenta"])].append(row)

    results: list[TariffControlRow] = []
    for cuenta, rows in sorted(grouped.items()):
        first = rows[0]
        facturado = q2(sum((D(r.get("valor_facturado")) for r in rows), _ZERO))
        clase_norm = str(first.get("clase", "")).lower()
        estrato = str(first.get("estrato", "")).strip()
        sector = str(first.get("sector", "urbano")).strip().lower()
        is_rural = "rural" in sector
        is_bim = cuenta in bimonthly or "bim" in str(first.get("periodicidad", "")).lower()
        mult = Decimal(2) if is_bim else Decimal(1)

        rule_key: str | None = None
        if "especial" in clase_norm:
            rule_key = "SERV_ESP"
        elif "residencial" in clase_norm and "no" not in clase_norm:
            if estrato in {"1", "2", "3", "4", "5", "6"}:
                rule_key = f"E{estrato}"
        elif any(
            kw in clase_norm for kw in ("comercial", "industrial", "no residencial")
        ):
            rule_key = "NO_RES_N1"

        if rule_key is None or rule_key not in rules:
            results.append(
                TariffControlRow(
                    identificador=cuenta,
                    periodo=periodo,
                    tarifa=str(first.get("tarifa", "")),
                    estado="REQUIERE_REVISION",
                    motivo_revision="ESTRATO_SIN_REGLA",
                    regla_aplicada=None,
                    facturado_real=facturado,
                    esperado=None,
                    diferencia=None,
                    valor_por_encima=_ZERO,
                    valor_por_debajo=_ZERO,
                )
            )
            continue

        rule = rules[rule_key]
        mode = rule["mode"]
        if mode == "fixed":
            base_fixed = D(rule["rural"] if is_rural else rule["urbano"])
            esperado = q2(base_fixed * mult)
        else:
            vce_raw = first.get("monto_energia")
            if vce_raw is None:
                results.append(
                    TariffControlRow(
                        identificador=cuenta,
                        periodo=periodo,
                        tarifa=str(first.get("tarifa", "")),
                        estado="NO_VALIDABLE",
                        motivo_revision="SIN_VCE",
                        regla_aplicada=rule_key,
                        facturado_real=facturado,
                        esperado=None,
                        diferencia=None,
                        valor_por_encima=_ZERO,
                        valor_por_debajo=_ZERO,
                    )
                )
                continue
            vce = D(vce_raw)
            pct_val = q2(D(rule["pct"]) * vce)
            if mode == "pct_min":
                min_val = q2(D(rule["rural_min"] if is_rural else rule["urbano_min"]) * mult)
                esperado = max(pct_val, min_val)
            else:
                esperado = pct_val

        diff = q2(facturado - esperado)
        if abs(diff) <= tolerancia:
            estado = "CORRECTO"
            v_encima = _ZERO
            v_debajo = _ZERO
        elif diff > tolerancia:
            estado = "POR_ENCIMA"
            v_encima = diff
            v_debajo = _ZERO
        else:
            estado = "POR_DEBAJO"
            v_encima = _ZERO
            v_debajo = abs(diff)

        results.append(
            TariffControlRow(
                identificador=cuenta,
                periodo=periodo,
                tarifa=rule_key,
                estado=estado,
                motivo_revision=None,
                regla_aplicada=rule_key,
                facturado_real=facturado,
                esperado=esperado,
                diferencia=diff,
                valor_por_encima=v_encima,
                valor_por_debajo=v_debajo,
            )
        )

    return _summarize_tariff_results(results)


def _summarize_tariff_results(results: Sequence[TariffControlRow]) -> dict[str, Any]:
    counts: dict[str, int] = {
        "CORRECTO": 0,
        "POR_ENCIMA": 0,
        "POR_DEBAJO": 0,
        "NO_VALIDABLE": 0,
        "REQUIERE_REVISION": 0,
    }
    total_encima = _ZERO
    total_debajo = _ZERO
    for r in results:
        counts[r.estado] = counts.get(r.estado, 0) + 1
        total_encima += r.valor_por_encima
        total_debajo += r.valor_por_debajo

    return {
        "rows": results,
        "counts": counts,
        "total_valor_por_encima": q2(total_encima),
        "total_valor_por_debajo": q2(total_debajo),
    }


def compute_afinia_tabla_dinamica(
    *,
    periodo: str,
    facturacion: Sequence[Mapping[str, Any]],
    recaudo: Sequence[Mapping[str, Any]],
    catastro: Sequence[Mapping[str, Any]],
    refactura: Sequence[Mapping[str, Any]] = (),
    convenio: Sequence[Mapping[str, Any]] = (),
    prior_facturacion: Sequence[Mapping[str, Any]] = (),
    historical_facturacion_pairs: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Compute the exact 45-column Tabla Dinámica (E..AW) + Total row for Afinia."""
    hist_pairs = historical_facturacion_pairs or set()
    prior_pairs = {(str(r["nic"]), str(r["tarifa"])) for r in prior_facturacion}

    total_n_factura_by_tariff: dict[str, int] = {}
    total_n_rec_by_tariff: dict[str, int] = {}
    total_recaudo_cartera_by_tariff: dict[str, Decimal] = {}
    total_cartera_acum_by_tariff: dict[str, Decimal] = {}

    tariffs_order = [t[0] for t in AFINIA_CANONICAL_TARIFFS]

    # Pre-pass for denominator totals across the 12 canonical tariffs
    for tarifa in tariffs_order:
        f_rows = [r for r in facturacion if str(r.get("tarifa")) == tarifa]
        r_rows = [r for r in recaudo if str(r.get("tarifa")) == tarifa]
        c_rows = [r for r in catastro if str(r.get("tarifa")) == tarifa]
        total_n_factura_by_tariff[tarifa] = len({str(r["nic"]) for r in f_rows})
        total_n_rec_by_tariff[tarifa] = len({str(r["nic"]) for r in r_rows})
        total_recaudo_cartera_by_tariff[tarifa] = sum(
            (
                D(r.get("importe_trans"))
                for r in r_rows
                if classify_recaudo_tipo_afinia(r.get("fecha_fact_lect"), periodo) == "CARTERA"
            ),
            _ZERO,
        )
        total_cartera_acum_by_tariff[tarifa] = sum(
            (D(r.get("deuda_corriente")) for r in c_rows), _ZERO
        )

    sum_n_factura = sum(total_n_factura_by_tariff.values())
    sum_n_rec = sum(total_n_rec_by_tariff.values())
    sum_recaudo_cartera = sum(total_recaudo_cartera_by_tariff.values(), _ZERO)
    sum_cartera_acum = sum(total_cartera_acum_by_tariff.values(), _ZERO)

    rows_out: list[dict[str, Any]] = []
    tot_consumo_num = _ZERO
    tot_consumo_cnt = 0
    tot_consumo_ci400 = _ZERO
    tot_facturados_pagaron = 0

    all_recaudo_nics = {str(r["nic"]) for r in recaudo}

    for tarifa in tariffs_order:
        f_rows = [r for r in facturacion if str(r.get("tarifa")) == tarifa]
        f_no_306 = [r for r in f_rows if r.get("concepto") != "CI306"]
        r_rows = [r for r in recaudo if str(r.get("tarifa")) == tarifa]
        c_rows = [r for r in catastro if str(r.get("tarifa")) == tarifa]
        rf_rows = [
            r
            for r in refactura
            if str(r.get("tarifa")) == tarifa and r.get("concepto") != "CI306"
        ]
        cv_rows = [
            r
            for r in convenio
            if str(r.get("tarifa")) == tarifa and r.get("cod_oper_cont") == "OC135"
        ]

        f_nics = {str(r["nic"]) for r in f_rows}
        r_nics = {str(r["nic"]) for r in r_rows}
        n_factura = len(f_nics)
        n_rec = len(r_nics)

        consumo_vals = [
            D(r.get("consumo_kwh"))
            for r in f_no_306
            if r.get("consumo_kwh") is not None
        ]
        tot_consumo_num += sum(consumo_vals, _ZERO)
        tot_consumo_cnt += len(consumo_vals)
        prom_consumo = (
            q4(sum(consumo_vals, _ZERO) / Decimal(len(consumo_vals))) if consumo_vals else _ZERO
        )
        consumo_ci400 = q4(
            sum((D(r.get("consumo_kwh")) for r in f_rows if r.get("concepto") == "CI400"), _ZERO)
        )
        tot_consumo_ci400 += consumo_ci400

        facturacion_val = q4(sum((D(r.get("importe_trans")) for r in f_no_306), _ZERO))
        refacturacion_val = q4(sum((D(r.get("importe_trans")) for r in rf_rows), _ZERO))
        total_fact = q4(facturacion_val + refacturacion_val)
        tarifa_prom = safe_div(total_fact, prom_consumo) or _ZERO

        rec_corr_rows = [
            r
            for r in r_rows
            if classify_recaudo_tipo_afinia(r.get("fecha_fact_lect"), periodo) == "CORRIENTE"
        ]
        rec_cart_rows = [
            r
            for r in r_rows
            if classify_recaudo_tipo_afinia(r.get("fecha_fact_lect"), periodo) == "CARTERA"
        ]
        rec_corr = q4(sum((D(r.get("importe_trans")) for r in rec_corr_rows), _ZERO))
        rec_cart = q4(sum((D(r.get("importe_trans")) for r in rec_cart_rows), _ZERO))
        rec_total = q4(sum((D(r.get("importe_trans")) for r in r_rows), _ZERO))
        n_fact_rec_cart = len({str(r["nic"]) for r in rec_cart_rows})

        c_debt_nics = {str(r["nic"]) for r in c_rows if D(r.get("deuda_corriente")) > _ZERO}
        cartera_acum = q4(sum((D(r.get("deuda_corriente")) for r in c_rows), _ZERO))
        facturados_con_cartera = len(f_nics & c_debt_nics)

        mora_rows = [r for r in r_rows if r.get("concepto") == "CI102"]
        n_mora = len({str(r["nic"]) for r in mora_rows})
        interes_mora = q4(sum((D(r.get("importe_trans")) for r in mora_rows), _ZERO))

        n_conv_users = len({str(r["nic"]) for r in cv_rows})
        val_conv = q4(sum((D(r.get("importe_trans")) for r in cv_rows), _ZERO))
        sv_by_nic: dict[str, set[str]] = defaultdict(set)
        conv_pairs: set[tuple[str, str]] = set()
        for r in cv_rows:
            nic_s = str(r["nic"])
            sv_s = str(r.get("sv") or "")
            sv_by_nic[nic_s].add(sv_s)
            conv_pairs.add((nic_s, sv_s))
        n_fact_conv = len(conv_pairs)
        n_mult_conv = sum(1 for svs in sv_by_nic.values() if len(svs) > 1)

        cur_pairs_t = {(nic, tarifa) for nic in f_nics}
        prior_pairs_t = {p for p in prior_pairs if p[1] == tarifa}
        dejados = len(prior_pairs_t - cur_pairs_t)
        nuevos = len([p for p in (cur_pairs_t - prior_pairs_t) if p not in hist_pairs])
        reintegrados = len([p for p in (cur_pairs_t - prior_pairs_t) if p in hist_pairs])

        facturados_pagaron_t = len(f_nics & all_recaudo_nics)
        tot_facturados_pagaron += facturados_pagaron_t

        row_dict: dict[str, Any] = {
            "estrato_uso": tarifa,
            "estrato_uso_catastro": tarifa,
            "n_factura": n_factura,
            "pct_n_factura": safe_div(Decimal(n_factura), Decimal(sum_n_factura)) or _ZERO,
            "promedio_consumo_kwh": prom_consumo,
            "facturacion": facturacion_val,
            "tarifa_promedio": tarifa_prom,
            "refacturacion": refacturacion_val,
            "total_facturacion": total_fact,
            "n_rec": n_rec,
            "pct_n_rec": safe_div(Decimal(n_rec), Decimal(sum_n_rec)) or _ZERO,
            "recaudo_corriente": rec_corr,
            "factura_promedio_rec_corriente": safe_div(rec_corr, Decimal(n_rec)) or _ZERO,
            "pct_recaudo_corriente": safe_div(rec_corr, facturacion_val) or _ZERO,
            "recaudo_total": rec_total,
            "factura_promedio_rec_total": safe_div(rec_total, Decimal(n_rec)) or _ZERO,
            "pct_recaudo_total": safe_div(rec_total, facturacion_val) or _ZERO,
            "n_facturas_recaudo_cartera": n_fact_rec_cart,
            "recaudo_cartera": rec_cart,
            "pct_recaudo_cartera": safe_div(rec_cart, sum_recaudo_cartera) or _ZERO,
            "factura_promedio_cartera": safe_div(rec_cart, Decimal(n_fact_rec_cart)) or _ZERO,
            "n_facturacion_cartera_ordinaria": n_factura - n_rec,
            "pct_facturacion_cartera_ordinaria": (
                safe_div(Decimal(n_factura - n_rec), Decimal(n_factura)) or _ZERO
            ),
            "cartera_periodo": q4(facturacion_val - rec_total),
            "eficiencia_con_cartera": safe_div(rec_total, facturacion_val) or _ZERO,
            "eficiencia_corriente": safe_div(rec_corr, facturacion_val) or _ZERO,
            "eficiencia_facturacion": safe_div(Decimal(n_rec), Decimal(n_factura)) or _ZERO,
            "n_usuarios_cartera_acumulada": len(c_debt_nics),
            "pct_n_usuarios_cartera": (
                safe_div(Decimal(facturados_con_cartera), Decimal(n_factura)) or _ZERO
            ),
            "cartera_acumulada": cartera_acum,
            "pct_cartera_valor": safe_div(cartera_acum, sum_cartera_acum) or _ZERO,
            "n_usuarios_cartera_recuperada": n_fact_rec_cart,
            "cartera_recuperada": rec_cart,
            "n_usuarios_interes_mora": n_mora,
            "interes_mora_periodo": interes_mora,
            "n_usuarios_convenios": n_conv_users,
            "valor_convenios_periodo": val_conv,
            "n_usuarios_total_convenios": n_conv_users,
            "total_valor_convenios": val_conv,
            "usuarios_dejados_facturar": dejados,
            "nuevos_usuarios": nuevos,
            "usuarios_reintegrados": reintegrados,
            "n_facturas_convenios": n_fact_conv,
            "valor_promedio_factura_convenio": safe_div(val_conv, Decimal(n_fact_conv)) or _ZERO,
            "n_usuarios_multiples_facturas_convenio": n_mult_conv,
            "consumo_kwh": consumo_ci400,
            "n_facturados_pagaron": facturados_pagaron_t,
            "eficiencia_usuarios": (
                safe_div(Decimal(facturados_pagaron_t), Decimal(n_factura)) or _ZERO
            ),
        }
        rows_out.append(row_dict)

    # Total row: additive counts & money summed across the 12 tariffs; ratios recomputed
    tot_fact = sum((r["facturacion"] for r in rows_out), _ZERO)
    tot_refact = sum((r["refacturacion"] for r in rows_out), _ZERO)
    tot_total_fact = q4(tot_fact + tot_refact)
    tot_rec_corr = sum((r["recaudo_corriente"] for r in rows_out), _ZERO)
    tot_rec_cart = sum((r["recaudo_cartera"] for r in rows_out), _ZERO)
    tot_rec_total = sum((r["recaudo_total"] for r in rows_out), _ZERO)
    tot_n_fact_cart = sum(int(r["n_facturas_recaudo_cartera"]) for r in rows_out)
    tot_prom_consumo = (
        q4(tot_consumo_num / Decimal(tot_consumo_cnt)) if tot_consumo_cnt else _ZERO
    )
    tot_val_conv = sum((r["valor_convenios_periodo"] for r in rows_out), _ZERO)
    tot_n_fact_conv = sum(int(r["n_facturas_convenios"]) for r in rows_out)

    total_row: dict[str, Any] = {
        "estrato_uso": "Total",
        "estrato_uso_catastro": "Total",
        "n_factura": sum_n_factura,
        "pct_n_factura": Decimal("1.0000") if sum_n_factura else _ZERO,
        "promedio_consumo_kwh": tot_prom_consumo,
        "facturacion": q4(tot_fact),
        "tarifa_promedio": safe_div(tot_total_fact, tot_prom_consumo) or _ZERO,
        "refacturacion": q4(tot_refact),
        "total_facturacion": tot_total_fact,
        "n_rec": sum_n_rec,
        "pct_n_rec": Decimal("1.0000") if sum_n_rec else _ZERO,
        "recaudo_corriente": q4(tot_rec_corr),
        "factura_promedio_rec_corriente": safe_div(tot_rec_corr, Decimal(sum_n_rec)) or _ZERO,
        "pct_recaudo_corriente": safe_div(tot_rec_corr, tot_fact) or _ZERO,
        "recaudo_total": q4(tot_rec_total),
        "factura_promedio_rec_total": safe_div(tot_rec_total, Decimal(sum_n_rec)) or _ZERO,
        "pct_recaudo_total": safe_div(tot_rec_total, tot_fact) or _ZERO,
        "n_facturas_recaudo_cartera": tot_n_fact_cart,
        "recaudo_cartera": q4(tot_rec_cart),
        "pct_recaudo_cartera": Decimal("1.0000") if tot_rec_cart else _ZERO,
        "factura_promedio_cartera": safe_div(tot_rec_cart, Decimal(tot_n_fact_cart)) or _ZERO,
        "n_facturacion_cartera_ordinaria": sum_n_factura - sum_n_rec,
        "pct_facturacion_cartera_ordinaria": safe_div(
            Decimal(sum_n_factura - sum_n_rec), Decimal(sum_n_factura)
        )
        or _ZERO,
        "cartera_periodo": q4(tot_fact - tot_rec_total),
        "eficiencia_con_cartera": safe_div(tot_rec_total, tot_fact) or _ZERO,
        "eficiencia_corriente": safe_div(tot_rec_corr, tot_fact) or _ZERO,
        "eficiencia_facturacion": safe_div(Decimal(sum_n_rec), Decimal(sum_n_factura)) or _ZERO,
        "n_usuarios_cartera_acumulada": sum(
            int(r["n_usuarios_cartera_acumulada"]) for r in rows_out
        ),
        "pct_n_usuarios_cartera": _ZERO,
        "cartera_acumulada": q4(sum_cartera_acum),
        "pct_cartera_valor": Decimal("1.0000") if sum_cartera_acum else _ZERO,
        "n_usuarios_cartera_recuperada": tot_n_fact_cart,
        "cartera_recuperada": q4(tot_rec_cart),
        "n_usuarios_interes_mora": sum(int(r["n_usuarios_interes_mora"]) for r in rows_out),
        "interes_mora_periodo": q4(sum((r["interes_mora_periodo"] for r in rows_out), _ZERO)),
        "n_usuarios_convenios": sum(int(r["n_usuarios_convenios"]) for r in rows_out),
        "valor_convenios_periodo": q4(tot_val_conv),
        "n_usuarios_total_convenios": sum(int(r["n_usuarios_total_convenios"]) for r in rows_out),
        "total_valor_convenios": q4(tot_val_conv),
        "usuarios_dejados_facturar": sum(int(r["usuarios_dejados_facturar"]) for r in rows_out),
        "nuevos_usuarios": sum(int(r["nuevos_usuarios"]) for r in rows_out),
        "usuarios_reintegrados": sum(int(r["usuarios_reintegrados"]) for r in rows_out),
        "n_facturas_convenios": tot_n_fact_conv,
        "valor_promedio_factura_convenio": (
            safe_div(tot_val_conv, Decimal(tot_n_fact_conv)) or _ZERO
        ),
        "n_usuarios_multiples_facturas_convenio": sum(
            int(r["n_usuarios_multiples_facturas_convenio"]) for r in rows_out
        ),
        "consumo_kwh": q4(tot_consumo_ci400),
        "n_facturados_pagaron": tot_facturados_pagaron,
        "eficiencia_usuarios": safe_div(Decimal(tot_facturados_pagaron), Decimal(sum_n_factura))
        or _ZERO,
    }
    return {"rows": rows_out, "total": total_row}


def verify_parity(
    dashboard_summary: Mapping[str, Any],
    annex_summary: Mapping[str, Any],
    report_summary: Mapping[str, Any],
    *,
    keys: Sequence[str] = (
        "n_factura",
        "facturacion",
        "recaudo_corriente",
        "recaudo_cartera",
        "recaudo_total",
        "valor_convenios_periodo",
        "nuevos_usuarios",
        "usuarios_reintegrados",
        "usuarios_dejados_facturar",
        "consumo_kwh",
    ),
) -> None:
    """Assert exact penny-and-count parity across Dashboard, Annex Excel, and PDF Report."""
    for key in keys:
        d_val = q2(dashboard_summary[key])
        a_val = q2(annex_summary[key])
        r_val = q2(report_summary[key])
        assert d_val == a_val == r_val, (
            f"Parity mismatch on {key!r}: dashboard={d_val}, annex={a_val}, report={r_val}"
        )


def deduce_celsia_periodicity(observed_periods: Sequence[str]) -> str:
    """Deduce Celsia account periodicity solely from observed billing periods."""
    ordered = sorted(set(observed_periods))
    if not ordered:
        return "no_evaluable"
    if len(ordered) == 1:
        month = int(ordered[0][4:6])
        return "bimestral_provisional_par" if month % 2 == 0 else "bimestral_provisional_impar"

    month_nums = [int(p[:4]) * 12 + int(p[4:6]) for p in ordered]
    for a, b in itertools.pairwise(month_nums):
        if b - a == 1:
            return "mensual"

    parities = {m % 2 for m in month_nums}
    if len(parities) == 1:
        return "bimestral_par" if next(iter(parities)) == 0 else "bimestral_impar"
    return "no_evaluable"


def _corresponds_to_period(periodicity: str, periodo: str) -> bool | None:
    month_parity = int(periodo[4:6]) % 2
    if periodicity == "mensual":
        return True
    if periodicity in {"bimestral_par", "bimestral_provisional_par"}:
        return month_parity == 0
    if periodicity in {"bimestral_impar", "bimestral_provisional_impar"}:
        return month_parity == 1
    return None


def classify_movements_and_absences(
    *,
    loaded_periods: Sequence[str],
    account_presence: Mapping[str, Iterable[str]],
    target_periodo: str,
    periodicities: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Classify movements and absence bands while skipping missing cuts (e.g. 202603)."""
    ordered_loaded = sorted(loaded_periods)
    if target_periodo not in ordered_loaded:
        raise ValueError(f"target_periodo {target_periodo!r} not in loaded_periods")

    idx = ordered_loaded.index(target_periodo)
    comparable = ordered_loaded[idx - 1] if idx > 0 else None
    prior_loaded = ordered_loaded[:idx]

    all_accounts = sorted(account_presence.keys())
    movements: dict[str, str] = {}
    absence_counts: dict[str, int] = {}
    bands = {"1": 0, "2": 0, "3": 0, ">3": 0}

    for acc in all_accounts:
        seen = set(account_presence[acc])
        per_type = (periodicities or {}).get(acc, "mensual")
        corresponds = _corresponds_to_period(per_type, target_periodo)

        if corresponds is None:
            movements[acc] = "No evaluable"
            continue
        if not corresponds and target_periodo not in seen:
            movements[acc] = "No le correspondía"
            continue

        # Previous comparable cut where this account should have been billed
        prev_expected = [
            p for p in prior_loaded if _corresponds_to_period(per_type, p) is True
        ]
        last_comp = prev_expected[-1] if prev_expected else comparable

        if target_periodo in seen:
            if last_comp is None or last_comp in seen:
                movements[acc] = "Facturado"
            elif any(p in seen for p in prior_loaded):
                movements[acc] = "Reintegrado"
            else:
                movements[acc] = "Nuevo"
        else:
            if last_comp is not None and last_comp in seen:
                movements[acc] = "Dejó de facturar"
            else:
                movements[acc] = "Ausente"

            # Count expected loaded periods missed since last appearance
            seen_before = [p for p in prior_loaded if p in seen]
            if seen_before:
                last_seen = max(seen_before)
                missed = sum(
                    1
                    for p in ordered_loaded
                    if p > last_seen
                    and p <= target_periodo
                    and _corresponds_to_period(per_type, p) is True
                    and p not in seen
                )
                if missed > 0:
                    absence_counts[acc] = missed
                    if missed == 1:
                        bands["1"] += 1
                    elif missed == 2:
                        bands["2"] += 1
                    elif missed == 3:
                        bands["3"] += 1
                    else:
                        bands[">3"] += 1

    return {
        "comparable": comparable,
        "skipped_missing_cut": (
            comparable is not None
            and (int(target_periodo[:4]) * 12 + int(target_periodo[4:6]))
            - (int(comparable[:4]) * 12 + int(comparable[4:6]))
            > 1
        ),
        "movements": movements,
        "absence_counts": absence_counts,
        "absence_bands": bands,
    }


def compute_maturation_bands(
    recaudo_rows: Sequence[Mapping[str, Any]],
    *,
    periodo: str,
    date_field: str = "fecha_fact_lect",
) -> dict[str, Decimal]:
    """Classify recaudo amounts into the 7 maturation bands + FECHA_FUTURA."""
    fecha_ref = _first_day_of_period(periodo)
    end_of_period = _shift_months(fecha_ref, 1) - dt.timedelta(days=1)
    b_1m = _shift_months(fecha_ref, -1)
    b_3m = _shift_months(fecha_ref, -3)
    b_6m = _shift_months(fecha_ref, -6)
    b_12m = _shift_months(fecha_ref, -12)

    bands: dict[str, Decimal] = {
        "SIN_FECHA": _ZERO,
        "FECHA_FUTURA": _ZERO,
        "DEL_MES": _ZERO,
        "UN_MES": _ZERO,
        "DOS_A_TRES_MESES": _ZERO,
        "CUATRO_A_SEIS_MESES": _ZERO,
        "SIETE_A_DOCE_MESES": _ZERO,
        "MAS_DE_UN_ANO": _ZERO,
    }
    for row in recaudo_rows:
        d = row.get(date_field)
        amt = D(row.get("importe_trans") or row.get("valor_recaudado"))
        if d is None:
            bands["SIN_FECHA"] += amt
        elif d > end_of_period:
            bands["FECHA_FUTURA"] += amt
        elif d >= fecha_ref:
            bands["DEL_MES"] += amt
        elif d >= b_1m:
            bands["UN_MES"] += amt
        elif d >= b_3m:
            bands["DOS_A_TRES_MESES"] += amt
        elif d >= b_6m:
            bands["CUATRO_A_SEIS_MESES"] += amt
        elif d >= b_12m:
            bands["SIETE_A_DOCE_MESES"] += amt
        else:
            bands["MAS_DE_UN_ANO"] += amt

    return {k: q2(v) for k, v in bands.items()}


def classify_payment_behavior(
    accounts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Classify NUNCA_PAGA/INTERMITENTE/PAGA_SIEMPRE and INSTITUCIONAL/ORDINARIA."""
    order_rank = {"NUNCA_PAGA": 0, "INTERMITENTE": 1, "PAGA_SIEMPRE": 2}
    out: list[dict[str, Any]] = []
    for acc in accounts:
        fact = int(acc.get("cortes_facturados", 0))
        rec = int(acc.get("cortes_con_recaudo", 0))
        if rec == 0:
            estado = "NUNCA_PAGA"
        elif fact > 0 and rec >= fact:
            estado = "PAGA_SIEMPRE"
        else:
            estado = "INTERMITENTE"
        nombre = str(acc.get("nombre", "")).lower()
        tarifa = str(acc.get("tarifa", "")).lower()
        tipo_gestion = (
            "INSTITUCIONAL"
            if ("municipio" in nombre or "oficial" in tarifa)
            else "ORDINARIA"
        )
        out.append(
            {
                "identificador": str(acc["identificador"]),
                "comportamiento": estado,
                "tipo_gestion": tipo_gestion,
                "cartera": q2(acc.get("cartera", 0)),
            }
        )
    out.sort(key=lambda r: (order_rank[r["comportamiento"]], -r["cartera"], r["identificador"]))
    return out


def compute_portfolio_concentration(
    debtors: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute Top 10/21/100/1000 and cuantos_suman_50_pct with deterministic tie-breaking."""
    positive = [
        {"nic": str(d["nic"]), "deuda_corriente": q2(d["deuda_corriente"])}
        for d in debtors
        if D(d.get("deuda_corriente")) > _ZERO
    ]
    positive.sort(key=lambda r: (-r["deuda_corriente"], r["nic"]))
    total_debt = sum((r["deuda_corriente"] for r in positive), _ZERO)
    half_target = total_debt * Decimal("0.5")

    cum = _ZERO
    cuantos_50 = 0
    for idx, item in enumerate(positive, start=1):
        cum += item["deuda_corriente"]
        if cuantos_50 == 0 and cum >= half_target:
            cuantos_50 = idx

    return {
        "total_cartera": q2(total_debt),
        "total_deudores": len(positive),
        "cuantos_suman_50_pct": cuantos_50,
        "top_10": q2(sum((r["deuda_corriente"] for r in positive[:10]), _ZERO)),
        "top_21": q2(sum((r["deuda_corriente"] for r in positive[:21]), _ZERO)),
        "top_100": q2(sum((r["deuda_corriente"] for r in positive[:100]), _ZERO)),
        "top_1000": q2(sum((r["deuda_corriente"] for r in positive[:1000]), _ZERO)),
        "ranking": positive[:1000],
    }


def audit_oc135_convenios(convenio_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Audit OC135 convenio agreements per (nic, sv)."""
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in convenio_rows:
        if str(row.get("cod_oper_cont")) == "OC135":
            groups[(str(row["nic"]), str(row["sv"]))].append(row)

    out: list[dict[str, Any]] = []
    for (nic, sv), rows in sorted(groups.items()):
        importe = q2(sum((D(r.get("importe_trans")) for r in rows), _ZERO))
        recibos = [q2(r.get("valor_recibo")) for r in rows]
        valor_recibo_ref = max(recibos)
        diff = q2(importe - valor_recibo_ref)
        sigs = {
            (
                str(r.get("concepto")),
                q2(r.get("importe_trans")),
                str(r.get("fecha_fact_lect")),
                str(r.get("fecha_trans")),
            )
            for r in rows
        }
        out.append(
            {
                "nic": nic,
                "sv": sv,
                "importe": importe,
                "valor_recibo_ref": valor_recibo_ref,
                "diferencia": diff,
                "conciliado": abs(diff) <= Decimal("1.00"),
                "posible_duplicado": len(rows) > len(sigs),
                "recibo_inconsistente": len(set(recibos)) > 1,
            }
        )
    return out


def detect_negative_adjustment_alert(
    recaudo_by_period: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    target_periodo: str,
) -> dict[str, Any]:
    """Flag alerta=True if negative recaudo weight exceeds max of all prior periods."""
    ordered = sorted(recaudo_by_period.keys())
    weights: dict[str, Decimal] = {}
    for p in ordered:
        rows = recaudo_by_period[p]
        neg = sum(
            (D(r.get("importe_trans")) for r in rows if D(r.get("importe_trans")) < _ZERO),
            _ZERO,
        )
        gross = sum(
            (D(r.get("importe_trans")) for r in rows if D(r.get("importe_trans")) > _ZERO),
            _ZERO,
        )
        weights[p] = safe_div(abs(neg), gross) or _ZERO

    prior_weights = [weights[p] for p in ordered if p < target_periodo]
    cur_weight = weights[target_periodo]
    max_prior = max(prior_weights, default=_ZERO)
    return {
        "periodo": target_periodo,
        "peso": cur_weight,
        "max_previo": max_prior,
        "alerta": bool(prior_weights) and cur_weight > max_prior,
    }


def detect_irregular_invoices(
    facturacion_rows: Sequence[Mapping[str, Any]],
    *,
    operator: str,
    periodo: str,
) -> dict[str, list[str]]:
    """Detect the 5 irregular invoice categories for Afinia and Celsia (>= 202605)."""
    categories: dict[str, list[str]] = {
        "LINEA_NEGATIVA": [],
        "TOTAL_NEGATIVO": [],
        "TOTAL_EN_CERO": [],
        "SIN_CONCEPTO_IMPUESTO": [],
        "IMPUESTO_AMBIGUO": [],
    }
    op = operator.lower()
    if op == "vatia" or (op == "celsia" and periodo < "202605"):
        return categories

    id_key = "nic" if op == "afinia" else "cuenta"
    amt_key = "importe_trans" if op == "afinia" else "valor_facturado"

    by_user: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in facturacion_rows:
        if str(row.get("periodo", periodo)) == periodo:
            by_user[str(row[id_key])].append(row)

    for uid, rows in sorted(by_user.items()):
        if op == "afinia":
            tax_rows = [r for r in rows if str(r.get("concepto")) in {"CI400", "CI401"}]
        else:
            tax_rows = [r for r in rows if str(r.get("tipo_concepto")) == "impuesto"]

        if not tax_rows:
            categories["SIN_CONCEPTO_IMPUESTO"].append(uid)
            continue

        amounts = [D(r.get(amt_key)) for r in tax_rows]
        if any(a < _ZERO for a in amounts):
            categories["LINEA_NEGATIVA"].append(uid)

        total_tax = sum(amounts, _ZERO)
        if total_tax < _ZERO:
            categories["TOTAL_NEGATIVO"].append(uid)
        elif total_tax == _ZERO:
            categories["TOTAL_EN_CERO"].append(uid)

        tariff_counts: dict[str, int] = defaultdict(int)
        for r in tax_rows:
            tariff_counts[str(r.get("tarifa") or "")] += 1
        if any(cnt >= 2 for cnt in tariff_counts.values()):
            categories["IMPUESTO_AMBIGUO"].append(uid)

    return categories
