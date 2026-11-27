"""Reglas y análisis de Afinia (puros, sobre filas normalizadas). Anexo E y §11.6.

Todas las sumas en Decimal exacto; los derivados se redondean a 4 decimales (ROUND_HALF_UP).
"""

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.modulos.comercial.dominio.comun import (
    CERO,
    UNO,
    como_fecha,
    d,
    desplazar,
    div,
    div_precisa,
    primer_dia,
    q2,
    q4,
    suma,
    sumar_meses,
)

if TYPE_CHECKING:
    from app.modulos.comercial.dominio.analisis import UsuarioCorte

TARIFAS_CANONICAS: tuple[str, ...] = (
    "AP_Comerciales_Nivel_1",
    "AP_Comerciales_Nivel_2",
    "AP_Industriales_Nivel_1",
    "AP_Industriales_Nivel_2",
    "AP_Oficiales_Nivel_1",
    "AP_Oficiales_Nivel_2",
    "AP_Residenciales_Estrato_1",
    "AP_Residenciales_Estrato_2",
    "AP_Residenciales_Estrato_3",
    "AP_Residenciales_Estrato_4",
    "AP_Residenciales_Estrato_5",
    "AP_Residenciales_Estrato_6",
)
TARIFAS_COMERCIALES = ("AP_Comerciales_Nivel_1", "AP_Comerciales_Nivel_2")
CONCEPTO_IMPUESTO = "CI400"
CONCEPTO_AJUSTE = "CI401"
CONCEPTO_REFACTURA = "CI851"
CONCEPTO_CUOTA_CONVENIO = "CI306"
CONCEPTO_MORA = "CI102"
OPERACION_CONVENIO = "OC135"
CONCEPTOS_IMPUESTO = (CONCEPTO_IMPUESTO, CONCEPTO_AJUSTE)

ESTADOS = ("CORRECTO", "POR_ENCIMA", "POR_DEBAJO", "NO_VALIDABLE", "REQUIERE_REVISION")


def sin_cuota(fila: dict[str, Any]) -> bool:
    """`concepto IS DISTINCT FROM 'CI306'`: conserva las filas con concepto vacío."""
    return fila.get("concepto") != CONCEPTO_CUOTA_CONVENIO


def segmento_de_tarifa(tarifa: str | None) -> str:
    """E.8: Afinia no trae segmento; se deduce del texto de la tarifa."""
    t = (tarifa or "").lower()
    for clave, nombre in (
        ("comercial", "Comercial"),
        ("industrial", "Industrial"),
        ("oficial", "Oficial"),
        ("residencial", "Residencial"),
    ):
        if clave in t:
            return nombre
    return "Sin clasificación"


# === Control tarifario (§11.6) ==================================================================


@dataclass(frozen=True)
class VigenciaAfinia:
    anio: int
    uvt: Decimal
    umbral_kwh: Decimal
    tolerancia: Decimal
    tarifas: dict[str, tuple[Decimal, Decimal]]  # tarifa -> (factor UVT, % costo variable)
    excepciones: dict[str, Decimal]  # NIC -> factor UVT


@dataclass
class FilaControl:
    identificador: str
    periodo: str
    tarifa: str | None
    estado: str
    motivo_revision: str | None
    regla_aplicada: str | None
    consumo_kwh: Decimal | None
    base_variable: Decimal | None
    facturado_real: Decimal
    esperado: Decimal | None
    diferencia: Decimal | None
    valor_por_encima: Decimal = CERO
    valor_por_debajo: Decimal = CERO
    senal_ci401: Decimal = CERO
    senal_ci851: Decimal = CERO
    extra: dict[str, Any] = field(default_factory=dict)

    def como_dict(self) -> dict[str, Any]:
        datos = asdict(self)
        datos.update(datos.pop("extra"))
        return datos


def control_tarifario(
    facturacion: Sequence[dict[str, Any]], periodo: str, vigencia: VigenciaAfinia | None
) -> list[FilaControl]:
    """Granularidad NIC × periodo × tarifa. Orden de las razones de revisión como en OPainn."""
    grupos: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    todos: set[str] = set()
    con_ci400: set[str] = set()
    senales: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"CI401": CERO, "CI851": CERO})
    for fila in facturacion:
        nic = str(fila["nic"])
        todos.add(nic)
        concepto = fila.get("concepto")
        if concepto == CONCEPTO_IMPUESTO:
            con_ci400.add(nic)
            grupos[(nic, fila.get("tarifa") or "")].append(fila)
        elif concepto in (CONCEPTO_AJUSTE, CONCEPTO_REFACTURA):
            senales[nic][concepto] += d(fila.get("importe_trans"))

    def base(
        nic: str, tarifa: str | None, facturado: Decimal, estado: str, **kw: Any
    ) -> FilaControl:
        return FilaControl(
            identificador=nic,
            periodo=periodo,
            tarifa=tarifa,
            estado=estado,
            motivo_revision=kw.get("motivo"),
            regla_aplicada=kw.get("regla"),
            consumo_kwh=kw.get("consumo"),
            base_variable=kw.get("base"),
            facturado_real=facturado,
            esperado=kw.get("esperado"),
            diferencia=kw.get("diferencia"),
            valor_por_encima=kw.get("encima", CERO),
            valor_por_debajo=kw.get("debajo", CERO),
            senal_ci401=q2(senales[nic]["CI401"]),
            senal_ci851=q2(senales[nic]["CI851"]),
        )

    salida: list[FilaControl] = []
    for nic in sorted(todos - con_ci400):
        salida.append(base(nic, None, CERO, "REQUIERE_REVISION", motivo="SIN_CI400"))

    for (nic, tarifa), filas in sorted(grupos.items()):
        facturado = q2(suma(f.get("importe_trans") for f in filas))
        fila = filas[0]
        consumo = fila.get("consumo_kwh")
        base_var = fila.get("valor_consumo_antes")
        if vigencia is None:
            salida.append(
                base(
                    nic,
                    tarifa,
                    facturado,
                    "REQUIERE_REVISION",
                    motivo="PERIODO_SIN_PARAMETROS",
                    consumo=consumo,
                )
            )
            continue
        if len(filas) > 1:
            salida.append(
                base(
                    nic,
                    tarifa,
                    facturado,
                    "REQUIERE_REVISION",
                    motivo="MULTIPLES_CI400",
                    consumo=consumo,
                )
            )
            continue
        especial = nic in vigencia.excepciones
        if not especial and tarifa not in vigencia.tarifas:
            salida.append(
                base(
                    nic,
                    tarifa,
                    facturado,
                    "REQUIERE_REVISION",
                    motivo="TARIFA_SIN_PARAMETROS",
                    consumo=consumo,
                )
            )
            continue
        if not especial and consumo is None:
            salida.append(
                base(nic, tarifa, facturado, "REQUIERE_REVISION", motivo="CONSUMO_CI400_NULO")
            )
            continue
        if especial:
            regla = "COBRO_ESPECIAL_UVT"
            esperado = q2(vigencia.excepciones[nic] * vigencia.uvt)
        else:
            factor, pct = vigencia.tarifas[tarifa]
            if d(consumo) <= vigencia.umbral_kwh:
                regla = "FACTURACION_MINIMA"
                esperado = q2(factor * vigencia.uvt)
            else:
                regla = "COSTO_VARIABLE"
                if base_var is None:
                    salida.append(
                        base(nic, tarifa, facturado, "NO_VALIDABLE", regla=regla, consumo=consumo)
                    )
                    continue
                esperado = q2(pct * d(base_var))
        diferencia = q2(facturado - esperado)
        if abs(diferencia) <= vigencia.tolerancia:
            estado, encima, debajo = "CORRECTO", CERO, CERO
        elif diferencia > 0:
            estado, encima, debajo = "POR_ENCIMA", diferencia, CERO
        else:
            estado, encima, debajo = "POR_DEBAJO", CERO, -diferencia
        salida.append(
            base(
                nic,
                tarifa,
                facturado,
                estado,
                regla=regla,
                consumo=consumo,
                base=base_var,
                esperado=esperado,
                diferencia=diferencia,
                encima=q2(encima),
                debajo=q2(debajo),
            )
        )
    return salida


GRUPOS_CONSUMO: dict[str, tuple[str, ...] | None] = {
    "todos": None,
    "minima": ("FACTURACION_MINIMA",),
    "variable": ("COSTO_VARIABLE",),
    "especial": ("COBRO_ESPECIAL_UVT",),
    "revision": (),
}


def filtrar_grupo(filas: list[FilaControl], grupo: str) -> list[FilaControl]:
    reglas = GRUPOS_CONSUMO.get(grupo)
    if reglas is None:
        return filas
    if grupo == "revision":
        return [f for f in filas if f.estado in ("REQUIERE_REVISION", "NO_VALIDABLE")]
    return [f for f in filas if f.regla_aplicada in reglas]


def resumir_control(filas: Iterable[FilaControl]) -> dict[str, Any]:
    por_estado = dict.fromkeys(ESTADOS, 0)
    encima = debajo = CERO
    for f in filas:
        por_estado[f.estado] += 1
        encima += f.valor_por_encima
        debajo += f.valor_por_debajo
    return {
        "por_estado": por_estado,
        "valor_por_encima": q2(encima),
        "valor_por_debajo": q2(debajo),
    }


# === Tabla dinámica (E.1) ========================================================================

COLUMNAS_TD: tuple[str, ...] = (
    "estrato_uso",
    "estrato_uso_catastro",
    "n_factura",
    "pct_n_factura",
    "promedio_consumo_kwh",
    "facturacion",
    "tarifa_promedio",
    "refacturacion",
    "total_facturacion",
    "n_rec",
    "pct_n_rec",
    "recaudo_corriente",
    "factura_promedio_rec_corriente",
    "pct_recaudo_corriente",
    "recaudo_total",
    "factura_promedio_rec_total",
    "pct_recaudo_total",
    "n_facturas_recaudo_cartera",
    "recaudo_cartera",
    "pct_recaudo_cartera",
    "factura_promedio_cartera",
    "n_facturacion_cartera_ordinaria",
    "pct_facturacion_cartera_ordinaria",
    "cartera_periodo",
    "eficiencia_con_cartera",
    "eficiencia_corriente",
    "eficiencia_facturacion",
    "n_usuarios_cartera_acumulada",
    "pct_n_usuarios_cartera",
    "cartera_acumulada",
    "pct_cartera_valor",
    "n_usuarios_cartera_recuperada",
    "cartera_recuperada",
    "n_usuarios_interes_mora",
    "interes_mora_periodo",
    "n_usuarios_convenios",
    "valor_convenios_periodo",
    "n_usuarios_total_convenios",
    "total_valor_convenios",
    "usuarios_dejados_facturar",
    "nuevos_usuarios",
    "usuarios_reintegrados",
    "n_facturas_convenios",
    "valor_promedio_factura_convenio",
    "n_usuarios_multiples_facturas_convenio",
)
COLUMNAS_TD_EXTRA = ("consumo_kwh", "n_facturados_pagaron", "eficiencia_usuarios")


def tipo_recaudo(fila: dict[str, Any], periodo: str) -> str:
    """CORRIENTE si la factura pagada es del mes anterior al periodo o posterior (E.1)."""
    fecha = como_fecha(fila.get("fecha_fact_lect"))
    if fecha is None:
        return "NO_CLASIFICADO"
    return "CORRIENTE" if fecha >= desplazar(primer_dia(periodo), -1) else "CARTERA"


def _por_tarifa(filas: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    salida: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in filas:
        salida[str(f.get("tarifa") or "")].append(f)
    return salida


def tabla_dinamica(
    periodo: str,
    *,
    facturacion: Sequence[dict[str, Any]],
    recaudo: Sequence[dict[str, Any]],
    catastro: Sequence[dict[str, Any]],
    refactura: Sequence[dict[str, Any]] = (),
    convenio: Sequence[dict[str, Any]] = (),
    pares_anteriores: set[tuple[str, str]] | None = None,
    pares_historicos: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """12 filas (tarifas canónicas, en su orden) + fila de totales. `pares_*`: (NIC, tarifa) del
    corte comparable y de todos los cortes previos a él, para el movimiento de usuarios."""
    anteriores = pares_anteriores or set()
    historicos = pares_historicos or set()
    fact_t = _por_tarifa(facturacion)
    rec_t = _por_tarifa(recaudo)
    cat_t = _por_tarifa(catastro)
    refa_t = _por_tarifa(f for f in refactura if sin_cuota(f))
    conv_t = _por_tarifa(f for f in convenio if f.get("cod_oper_cont") == OPERACION_CONVENIO)
    nics_recaudo = {str(f["nic"]) for f in recaudo}
    # Movimiento de usuarios como OPainn: por NIC (cambiar de tarifa no es dejar de facturarse
    # ni ser nuevo); sin corte comparable, en cero.
    nics_actuales = {str(f["nic"]) for f in facturacion}
    nics_previos = {nic for nic, _ in anteriores}
    nics_historicos = {nic for nic, _ in historicos}
    hay_comparable = bool(anteriores)

    def tipo(f: dict[str, Any]) -> str:
        return f.get("tipo_recaudo") or tipo_recaudo(f, periodo)

    sum_n_factura = sum(len({str(f["nic"]) for f in fact_t.get(t, [])}) for t in TARIFAS_CANONICAS)
    sum_n_rec = sum(len({str(f["nic"]) for f in rec_t.get(t, [])}) for t in TARIFAS_CANONICAS)
    sum_rec_cartera = suma(
        f.get("importe_trans")
        for t in TARIFAS_CANONICAS
        for f in rec_t.get(t, [])
        if tipo(f) == "CARTERA"
    )
    sum_cartera = suma(
        f.get("deuda_corriente") for t in TARIFAS_CANONICAS for f in cat_t.get(t, [])
    )

    filas: list[dict[str, Any]] = []
    consumo_num, consumo_cnt = CERO, 0
    for tarifa in TARIFAS_CANONICAS:
        f_rows = fact_t.get(tarifa, [])
        f_sin = [f for f in f_rows if sin_cuota(f)]
        r_rows = rec_t.get(tarifa, [])
        c_rows = cat_t.get(tarifa, [])
        nics_f = {str(f["nic"]) for f in f_rows}
        n_factura, n_rec = len(nics_f), len({str(f["nic"]) for f in r_rows})
        consumos = [d(f["consumo_kwh"]) for f in f_sin if f.get("consumo_kwh") is not None]
        consumo_num += suma(consumos)
        consumo_cnt += len(consumos)
        promedio_exacto = suma(consumos) / Decimal(len(consumos)) if consumos else CERO
        promedio = q4(promedio_exacto)
        consumo_ci400 = q4(
            suma(f.get("consumo_kwh") for f in f_rows if f.get("concepto") == CONCEPTO_IMPUESTO)
        )
        facturacion_v = q4(suma(f.get("importe_trans") for f in f_sin))
        refacturacion_v = q4(suma(f.get("importe_trans") for f in refa_t.get(tarifa, [])))
        total_fact = q4(facturacion_v + refacturacion_v)
        corriente = [f for f in r_rows if tipo(f) == "CORRIENTE"]
        cartera = [f for f in r_rows if tipo(f) == "CARTERA"]
        rec_corr = q4(suma(f.get("importe_trans") for f in corriente))
        rec_cart = q4(suma(f.get("importe_trans") for f in cartera))
        rec_total = q4(suma(f.get("importe_trans") for f in r_rows))
        n_cart = len({str(f["nic"]) for f in cartera})
        deudores = {str(f["nic"]) for f in c_rows if d(f.get("deuda_corriente")) > CERO}
        cartera_acum = q4(suma(f.get("deuda_corriente") for f in c_rows))
        con_cartera = len(nics_f & deudores)
        mora = [f for f in r_rows if f.get("concepto") == CONCEPTO_MORA]
        conv = conv_t.get(tarifa, [])
        por_factura: dict[tuple[str, str], Decimal] = defaultdict(lambda: CERO)
        for f in conv:
            por_factura[(str(f["nic"]), str(f.get("sv") or ""))] += d(f.get("importe_trans"))
        facturas_por_nic: dict[str, int] = defaultdict(int)
        for nic, _sv in por_factura:
            facturas_por_nic[nic] += 1
        val_conv = q4(suma(por_factura.values()))
        n_fact_conv = len(por_factura)
        altas = [nic for nic in nics_f if nic not in nics_previos] if hay_comparable else []
        pagaron = len(nics_f & nics_recaudo)
        filas.append(
            {
                "estrato_uso": tarifa,
                "estrato_uso_catastro": tarifa.replace("_", " "),
                "n_factura": n_factura,
                "pct_n_factura": div_precisa(n_factura, sum_n_factura),
                "promedio_consumo_kwh": promedio,
                "facturacion": facturacion_v,
                "tarifa_promedio": div_precisa(total_fact, promedio_exacto),
                "refacturacion": refacturacion_v,
                "total_facturacion": total_fact,
                "n_rec": n_rec,
                "pct_n_rec": div_precisa(n_rec, sum_n_rec),
                "recaudo_corriente": rec_corr,
                "factura_promedio_rec_corriente": div_precisa(rec_corr, n_rec),
                "pct_recaudo_corriente": div_precisa(rec_corr, facturacion_v),
                "recaudo_total": rec_total,
                "factura_promedio_rec_total": div_precisa(rec_total, n_rec),
                "pct_recaudo_total": div_precisa(rec_total, facturacion_v),
                "n_facturas_recaudo_cartera": n_cart,
                "recaudo_cartera": rec_cart,
                "pct_recaudo_cartera": div_precisa(rec_cart, sum_rec_cartera),
                "factura_promedio_cartera": div_precisa(rec_cart, n_cart),
                "n_facturacion_cartera_ordinaria": n_factura - n_rec,
                "pct_facturacion_cartera_ordinaria": div_precisa(n_factura - n_rec, n_factura),
                "cartera_periodo": q4(facturacion_v - rec_total),
                "eficiencia_con_cartera": div_precisa(rec_total, facturacion_v),
                "eficiencia_corriente": div_precisa(rec_corr, facturacion_v),
                "eficiencia_facturacion": div_precisa(n_rec, n_factura),
                "n_usuarios_cartera_acumulada": len(deudores),
                "pct_n_usuarios_cartera": div_precisa(con_cartera, n_factura),
                "cartera_acumulada": cartera_acum,
                "pct_cartera_valor": div_precisa(cartera_acum, sum_cartera),
                "n_usuarios_cartera_recuperada": n_cart,
                "cartera_recuperada": rec_cart,
                "n_usuarios_interes_mora": len({str(f["nic"]) for f in mora}),
                "interes_mora_periodo": q4(suma(f.get("importe_trans") for f in mora)),
                "n_usuarios_convenios": len(facturas_por_nic),
                "valor_convenios_periodo": val_conv,
                # [PENDIENTE §E.1] acumulados de convenios: por ahora, los del periodo.
                "n_usuarios_total_convenios": len(facturas_por_nic),
                "total_valor_convenios": val_conv,
                "usuarios_dejados_facturar": len(
                    {n for n, t in anteriores if t == tarifa and n not in nics_actuales}
                ),
                "nuevos_usuarios": sum(1 for n in altas if n not in nics_historicos),
                "usuarios_reintegrados": sum(1 for n in altas if n in nics_historicos),
                "n_facturas_convenios": n_fact_conv,
                "valor_promedio_factura_convenio": div_precisa(val_conv, n_fact_conv),
                "n_usuarios_multiples_facturas_convenio": sum(
                    1 for n in facturas_por_nic.values() if n > 1
                ),
                "consumo_kwh": consumo_ci400,
                "n_facturados_pagaron": pagaron,
                "eficiencia_usuarios": div_precisa(pagaron, n_factura),
                "_facturados_con_cartera": con_cartera,
            }
        )

    def total_de(clave: str) -> Any:
        return sum((f[clave] for f in filas), CERO if isinstance(filas[0][clave], Decimal) else 0)

    fact, rec_total = total_de("facturacion"), total_de("recaudo_total")
    rec_corr, rec_cart = total_de("recaudo_corriente"), total_de("recaudo_cartera")
    total_fact = q4(fact + total_de("refacturacion"))
    promedio_total_exacto = consumo_num / Decimal(consumo_cnt) if consumo_cnt else CERO
    promedio_total = q4(promedio_total_exacto)
    n_cart = total_de("n_facturas_recaudo_cartera")
    val_conv = total_de("valor_convenios_periodo")
    n_fact_conv = total_de("n_facturas_convenios")
    pagaron = total_de("n_facturados_pagaron")
    total = {
        "estrato_uso": "Total",
        "estrato_uso_catastro": "Total",
        "n_factura": sum_n_factura,
        "pct_n_factura": q4(UNO) if sum_n_factura else CERO,
        "promedio_consumo_kwh": promedio_total,
        "facturacion": q4(fact),
        "tarifa_promedio": div_precisa(total_fact, promedio_total_exacto),
        "refacturacion": q4(total_de("refacturacion")),
        "total_facturacion": total_fact,
        "n_rec": sum_n_rec,
        "pct_n_rec": q4(UNO) if sum_n_rec else CERO,
        "recaudo_corriente": q4(rec_corr),
        "factura_promedio_rec_corriente": div_precisa(rec_corr, sum_n_rec),
        "pct_recaudo_corriente": div_precisa(rec_corr, fact),
        "recaudo_total": q4(rec_total),
        "factura_promedio_rec_total": div_precisa(rec_total, sum_n_rec),
        "pct_recaudo_total": div_precisa(rec_total, fact),
        "n_facturas_recaudo_cartera": n_cart,
        "recaudo_cartera": q4(rec_cart),
        "pct_recaudo_cartera": q4(UNO) if rec_cart else CERO,
        "factura_promedio_cartera": div_precisa(rec_cart, n_cart),
        "n_facturacion_cartera_ordinaria": sum_n_factura - sum_n_rec,
        "pct_facturacion_cartera_ordinaria": div_precisa(sum_n_factura - sum_n_rec, sum_n_factura),
        "cartera_periodo": q4(fact - rec_total),
        "eficiencia_con_cartera": div_precisa(rec_total, fact),
        "eficiencia_corriente": div_precisa(rec_corr, fact),
        "eficiencia_facturacion": div_precisa(sum_n_rec, sum_n_factura),
        "n_usuarios_cartera_acumulada": total_de("n_usuarios_cartera_acumulada"),
        "pct_n_usuarios_cartera": div_precisa(total_de("_facturados_con_cartera"), sum_n_factura),
        "cartera_acumulada": q4(sum_cartera),
        "pct_cartera_valor": q4(UNO) if sum_cartera else CERO,
        "n_usuarios_cartera_recuperada": n_cart,
        "cartera_recuperada": q4(rec_cart),
        "n_usuarios_interes_mora": total_de("n_usuarios_interes_mora"),
        "interes_mora_periodo": q4(total_de("interes_mora_periodo")),
        "n_usuarios_convenios": total_de("n_usuarios_convenios"),
        "valor_convenios_periodo": q4(val_conv),
        "n_usuarios_total_convenios": total_de("n_usuarios_total_convenios"),
        "total_valor_convenios": q4(total_de("total_valor_convenios")),
        "usuarios_dejados_facturar": total_de("usuarios_dejados_facturar"),
        "nuevos_usuarios": total_de("nuevos_usuarios"),
        "usuarios_reintegrados": total_de("usuarios_reintegrados"),
        "n_facturas_convenios": n_fact_conv,
        "valor_promedio_factura_convenio": div_precisa(val_conv, n_fact_conv),
        "n_usuarios_multiples_facturas_convenio": total_de(
            "n_usuarios_multiples_facturas_convenio"
        ),
        "consumo_kwh": q4(total_de("consumo_kwh")),
        "n_facturados_pagaron": pagaron,
        "eficiencia_usuarios": div_precisa(pagaron, sum_n_factura),
    }
    for f in filas:
        f.pop("_facturados_con_cartera")
    return {"filas": filas, "total": total}


# === Facturas irregulares (§11.9) ================================================================

CATEGORIAS_IRREGULARES = (
    "LINEA_NEGATIVA",
    "TOTAL_NEGATIVO",
    "TOTAL_EN_CERO",
    "SIN_CONCEPTO_IMPUESTO",
    "IMPUESTO_AMBIGUO",
)


def facturas_irregulares(facturacion: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Solo cuentan los conceptos del impuesto (CI400 y CI401). Nivel usuario y factura."""
    por_nic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in facturacion:
        por_nic[str(f["nic"])].append(f)
    salida: dict[str, list[dict[str, Any]]] = {c: [] for c in CATEGORIAS_IRREGULARES}
    for nic, filas in sorted(por_nic.items()):
        impuesto = [f for f in filas if f.get("concepto") in CONCEPTOS_IMPUESTO]
        facturas = sorted({str(f.get("sv") or "") for f in filas})
        if not impuesto:
            salida["SIN_CONCEPTO_IMPUESTO"].append(
                {
                    "identificador": nic,
                    "nic": nic,
                    "facturas": facturas,
                    "valor_otros_conceptos": q2(suma(f.get("importe_trans") for f in filas)),
                }
            )
            continue
        montos = [d(f.get("importe_trans")) for f in impuesto]
        total = q2(suma(montos))
        fila = {"identificador": nic, "nic": nic, "facturas": facturas, "total_impuesto": total}
        if any(m < CERO for m in montos):
            salida["LINEA_NEGATIVA"].append(
                {**fila, "lineas_negativas": sum(1 for m in montos if m < CERO)}
            )
        if total < CERO:
            salida["TOTAL_NEGATIVO"].append(fila)
        elif total == CERO:
            salida["TOTAL_EN_CERO"].append(fila)
        # Ambiguo: dos líneas CI400 con la misma tarifa (el CI401 es un ajuste, no otra línea).
        por_tarifa: dict[str, int] = defaultdict(int)
        for f in impuesto:
            if f.get("concepto") == CONCEPTO_IMPUESTO:
                por_tarifa[str(f.get("tarifa") or "")] += 1
        repetidas = [t for t, n in por_tarifa.items() if n >= 2]
        if repetidas:
            salida["IMPUESTO_AMBIGUO"].append({**fila, "tarifas": repetidas})
    return salida


# === Convenios y ajustes (E.6) ==================================================================


def auditoria_convenios(convenio: Sequence[dict[str, Any]]) -> dict[str, Any]:
    grupos: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for f in convenio:
        if f.get("cod_oper_cont") == OPERACION_CONVENIO:
            grupos[(str(f["nic"]), str(f.get("sv") or ""))].append(f)
    facturas = []
    for (nic, sv), filas in sorted(grupos.items()):
        importe = q2(suma(f.get("importe_trans") for f in filas))
        recibos = [q2(f.get("valor_recibo")) for f in filas]
        recibo = max(recibos) if recibos else CERO
        diferencia = q2(importe - recibo)
        firmas = {
            (
                str(f.get("concepto")),
                q2(f.get("importe_trans")),
                str(f.get("fecha_fact_lect")),
                str(f.get("fecha_trans")),
            )
            for f in filas
        }
        facturas.append(
            {
                "nic": nic,
                "sv": sv,
                "lineas": len(filas),
                "importe": importe,
                "valor_recibo": recibo,
                "diferencia": diferencia,
                "conciliado": abs(diferencia) <= Decimal("1.00"),
                "posible_duplicado": len(filas) > len(firmas),
                "recibo_inconsistente": len(set(recibos)) > 1,
            }
        )
    usuarios = {f["nic"] for f in facturas}
    por_nic: dict[str, int] = defaultdict(int)
    for f in facturas:
        por_nic[f["nic"]] += 1
    importe_total = q2(suma(f["importe"] for f in facturas))
    alertas = [
        f
        for f in facturas
        if not f["conciliado"] or f["posible_duplicado"] or f["recibo_inconsistente"]
    ][:500]
    return {
        "resumen": {
            "facturas": len(facturas),
            "usuarios": len(usuarios),
            "importe": importe_total,
            "valor_promedio_factura": div(importe_total, len(facturas)),
            "usuarios_varias_facturas": sum(1 for n in por_nic.values() if n > 1),
            "no_conciliadas": sum(1 for f in facturas if not f["conciliado"]),
            "posibles_duplicados": sum(1 for f in facturas if f["posible_duplicado"]),
            "recibos_inconsistentes": sum(1 for f in facturas if f["recibo_inconsistente"]),
        },
        "alertas": alertas,
        "facturas": facturas,
    }


def ajustes_negativos(
    recaudo_por_periodo: dict[str, Sequence[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Por corte: monto negativo, recaudo bruto y peso; alerta si supera el de todo corte previo."""
    salida = []
    maximo_previo: Decimal | None = None
    for periodo in sorted(recaudo_por_periodo):
        filas = recaudo_por_periodo[periodo]
        negativo = suma(f.get("importe_trans") for f in filas if d(f.get("importe_trans")) < 0)
        bruto = suma(f.get("importe_trans") for f in filas if d(f.get("importe_trans")) > 0)
        peso = div(abs(negativo), bruto) or CERO
        salida.append(
            {
                "periodo": periodo,
                "filas_negativas": sum(1 for f in filas if d(f.get("importe_trans")) < 0),
                "monto": q2(negativo),
                "recaudo_bruto": q2(bruto),
                "peso": peso,
                "max_previo": maximo_previo if maximo_previo is not None else CERO,
                "alerta": maximo_previo is not None and peso > maximo_previo,
            }
        )
        maximo_previo = peso if maximo_previo is None else max(maximo_previo, peso)
    return salida


def cohortes_convenio(
    convenios: dict[str, Sequence[dict[str, Any]]],
    facturacion: dict[str, set[str]],
    cuotas: dict[str, dict[str, Decimal]],
    pagos: dict[str, dict[str, Decimal]],
    cartera: dict[str, dict[str, Decimal]],
) -> list[dict[str, Any]]:
    """Cohorte = corte con OC135. Descriptivo: no prueba cumplimiento ni abandono."""
    periodos = sorted(facturacion)
    salida = []
    for cohorte in sorted(convenios):
        firmantes = {
            str(f["nic"])
            for f in convenios[cohorte]
            if f.get("cod_oper_cont") == OPERACION_CONVENIO
        }
        if not firmantes:
            continue
        seguimiento = []
        for periodo in (p for p in periodos if p > cohorte):
            cuota = cuotas.get(periodo, {})
            pago = pagos.get(periodo, {})
            saldo = cartera.get(periodo, {})
            seguimiento.append(
                {
                    "periodo": periodo,
                    "con_cuota": len(firmantes & set(cuota)),
                    "pagaron": len(firmantes & set(pago)),
                    "cuota_esperada": q2(suma(cuota[n] for n in firmantes if n in cuota)),
                    "recaudo_observado": q2(suma(pago[n] for n in firmantes if n in pago)),
                    "cartera": q2(suma(saldo[n] for n in firmantes if n in saldo)),
                }
            )
        salida.append({"cohorte": cohorte, "firmantes": len(firmantes), "seguimiento": seguimiento})
    return salida


# === Maduración del recaudo (E.3) ================================================================

BANDAS = (
    "SIN_FECHA",
    "FECHA_FUTURA",
    "DEL_MES",
    "UN_MES",
    "DOS_A_TRES_MESES",
    "CUATRO_A_SEIS_MESES",
    "SIETE_A_DOCE_MESES",
    "MAS_DE_UN_ANO",
)


def banda_de(fecha: dt.date | None, periodo: str) -> str:
    referencia = primer_dia(periodo)
    if fecha is None:
        return "SIN_FECHA"
    if fecha >= desplazar(referencia, 1):
        return "FECHA_FUTURA"
    for banda, meses in (
        ("DEL_MES", 0),
        ("UN_MES", -1),
        ("DOS_A_TRES_MESES", -3),
        ("CUATRO_A_SEIS_MESES", -6),
        ("SIETE_A_DOCE_MESES", -12),
    ):
        if fecha >= desplazar(referencia, meses):
            return banda
    return "MAS_DE_UN_ANO"


def maduracion(recaudo: Sequence[dict[str, Any]], periodo: str) -> dict[str, Any]:
    montos: dict[str, Decimal] = dict.fromkeys(BANDAS, CERO)
    usuarios: dict[str, set[str]] = {b: set() for b in BANDAS}
    for f in recaudo:
        banda = banda_de(como_fecha(f.get("fecha_fact_lect")), periodo)
        montos[banda] += d(f.get("importe_trans"))
        usuarios[banda].add(str(f["nic"]))
    total = suma(montos.values())
    return {
        b: {"usuarios": len(usuarios[b]), "monto": q2(montos[b]), "pct": div(montos[b], total)}
        for b in BANDAS
    }


def curva_cohortes(
    facturacion: Sequence[dict[str, Any]],
    recaudo: Sequence[dict[str, Any]],
    periodos_cargados: Sequence[str],
) -> list[dict[str, Any]]:
    facturado: dict[str, Decimal] = defaultdict(lambda: CERO)
    for f in facturacion:
        fecha = como_fecha(f.get("fecha_fact_lect"))
        if fecha is not None and sin_cuota(f):
            facturado[f"{fecha.year:04d}{fecha.month:02d}"] += d(f.get("importe_trans"))
    recuperado: dict[str, dict[int, Decimal]] = defaultdict(
        lambda: dict.fromkeys((30, 60, 90), CERO)
    )
    ultimo: dict[str, dt.date] = {}
    for f in recaudo:
        factura = como_fecha(f.get("fecha_fact_lect"))
        pago = como_fecha(f.get("fecha_trans"))
        if factura is None or pago is None:
            continue
        cohorte = f"{factura.year:04d}{factura.month:02d}"
        dias = (pago - factura).days
        for limite in (30, 60, 90):
            if 0 <= dias <= limite:
                recuperado[cohorte][limite] += d(f.get("importe_trans"))
        ultimo[cohorte] = max(ultimo.get(cohorte, pago), pago)
    cargados = set(periodos_cargados)
    salida = []
    for cohorte in sorted(facturado):
        base = facturado[cohorte]
        rec = recuperado[cohorte]
        siguientes = [sumar_meses(cohorte, k) for k in range(1, 4)]
        salida.append(
            {
                "cohorte": cohorte,
                "facturado": q2(base),
                "recuperado_30": q2(rec[30]),
                "recuperado_60": q2(rec[60]),
                "recuperado_90": q2(rec[90]),
                "pct_30": div(rec[30], base),
                "pct_60": div(rec[60], base),
                "pct_90": div(rec[90], base),
                "ultimo_recaudo": ultimo.get(cohorte),
                "meses_ausentes": [p for p in siguientes if p not in cargados],
            }
        )
    return salida


# === Rutas y controles de campo (E.5) ============================================================


def anomalias_consumo(
    actual: dict[str, tuple[Decimal, Decimal]], anterior: dict[str, tuple[Decimal, Decimal]]
) -> list[dict[str, Any]]:
    """NIC cuyo consumo CI400 cae 50 % o más y su facturación varía como máximo 10 %.
    Entradas: NIC -> (consumo CI400, facturación sin CI306)."""
    salida = []
    for nic, (consumo, factura) in actual.items():
        if nic not in anterior:
            continue
        consumo_ant, factura_ant = anterior[nic]
        if consumo_ant <= 0:
            continue
        caida = (consumo_ant - consumo) / consumo_ant
        variacion = abs(factura - factura_ant) / abs(factura_ant) if factura_ant else None
        if caida >= Decimal("0.5") and variacion is not None and variacion <= Decimal("0.10"):
            salida.append(
                {
                    "nic": nic,
                    "consumo_anterior": q2(consumo_ant),
                    "consumo": q2(consumo),
                    "caida_pct": q4(caida),
                    "facturacion_anterior": q2(factura_ant),
                    "facturacion": q2(factura),
                }
            )
    return sorted(salida, key=lambda r: (-r["caida_pct"], r["nic"]))


def movimientos_repetidos(presencia: dict[str, list[bool]]) -> list[dict[str, Any]]:
    """NIC con dos o más transiciones presencia ↔ ausencia en facturación."""
    salida = []
    for nic, serie in presencia.items():
        cambios = sum(1 for a, b in zip(serie, serie[1:], strict=False) if a != b)
        if cambios >= 2:
            salida.append({"nic": nic, "transiciones": cambios})
    return sorted(salida, key=lambda r: (-r["transiciones"], r["nic"]))


# === Resumen por usuario (para los análisis comunes) =============================================


def usuarios_corte(familias: dict[str, Sequence[dict[str, Any]]]) -> dict[str, "UsuarioCorte"]:
    """NIC → facturado (sin CI306), consumo CI400, recaudo (corriente/cartera), cartera del
    catastro y datos del catastro (nombre, dirección, barrio, estado del suministro)."""
    from app.modulos.comercial.dominio.analisis import UsuarioCorte

    usuarios: dict[str, UsuarioCorte] = {}

    def usuario(nic: Any) -> UsuarioCorte:
        clave = str(nic)
        if clave not in usuarios:
            usuarios[clave] = UsuarioCorte(identificador=clave)
        return usuarios[clave]

    for f in familias.get("facturacion", ()):
        u = usuario(f["nic"])
        u.facturado_presente = True
        if sin_cuota(f):
            u.facturado += d(f.get("importe_trans"))
        if f.get("concepto") == CONCEPTO_IMPUESTO:
            u.consumo = (u.consumo or CERO) + d(f.get("consumo_kwh"))
            u.tarifa = u.tarifa or f.get("tarifa")
        u.extra.setdefault("tarifa_factura", f.get("tarifa"))
    for f in familias.get("recaudo", ()):
        u = usuario(f["nic"])
        valor = d(f.get("importe_trans"))
        u.recaudo += valor
        if f.get("tipo_recaudo") == "CORRIENTE":
            u.recaudo_corriente += valor
        elif f.get("tipo_recaudo") == "CARTERA":
            u.recaudo_cartera += valor
        u.pago = True
    for f in familias.get("catastro", ()):
        u = usuario(f["nic"])
        u.cartera += d(f.get("deuda_corriente"))
        u.nombre = u.nombre or f.get("nombre")
        u.direccion = u.direccion or f.get("direccion")
        u.barrio = u.barrio or f.get("barrio")
        u.estado_suministro = u.estado_suministro or f.get("estado_suministro")
        u.tarifa = u.tarifa or f.get("tarifa")
        u.extra.setdefault("deuda_cuota", f.get("deuda_cuota"))
    for u in usuarios.values():
        u.tarifa = u.tarifa or u.extra.get("tarifa_factura")
        u.segmento = segmento_de_tarifa(u.tarifa)
        u.estrato = u.tarifa
    return usuarios
