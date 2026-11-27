"""Reglas y análisis de Celsia (Alcalá): control tarifario 2026 (§11.7), periodicidad, cartera por
edades y facturas irregulares."""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from functools import partial
from typing import Any

from app.modulos.comercial.dominio.afinia import ESTADOS, FilaControl
from app.modulos.comercial.dominio.analisis import UsuarioCorte
from app.modulos.comercial.dominio.celsia_ingesta import EDADES
from app.modulos.comercial.dominio.comun import (
    CERO,
    como_fecha,
    d,
    div,
    div_precisa,
    normalizar_encabezado,
    primer_dia,
    q2,
    suma,
    sumar_meses,
)

TARIFA_ESPECIAL = "SERVICIOS_ESPECIALES"
TARIFA_NO_RESIDENCIAL = "NO_RESIDENCIAL_NIVEL_1"
ETIQUETAS_EDAD = {
    "cartera_financiada": "Financiada",
    "cartera_corriente": "Corriente",
    "cartera_30": "30 días",
    "cartera_60": "60 días",
    "cartera_90": "90 días",
    "cartera_180": "180 días",
    "cartera_360": "360 días",
    "cartera_mayor_360": "Mayor a 360",
    "valor_congelado": "Valor congelado",
}


@dataclass(frozen=True)
class ReglaCelsia:
    tipo: str  # fija | mayor_porcentaje_minimo | porcentaje
    porcentaje: Decimal | None
    urbano: Decimal | None
    rural: Decimal | None


@dataclass(frozen=True)
class VigenciaCelsia:
    anio: int
    tolerancia: Decimal
    duplicar_bimestral: bool
    tarifas: dict[str, ReglaCelsia]
    excepciones: dict[str, dict[str, Any]] = field(default_factory=dict)


def tarifa_de(clase: str | None, estrato: str | None) -> tuple[str | None, str | None]:
    """(tarifa, motivo de revisión) según la clase y el estrato de la cuenta."""
    c = normalizar_encabezado(clase)
    if "especial" in c:
        return TARIFA_ESPECIAL, None
    if "residencial" in c and "no_residencial" not in c:
        if estrato in {"1", "2", "3", "4", "5", "6"}:
            return f"RESIDENCIAL_ESTRATO_{estrato}", None
        return None, "ESTRATO_SIN_REGLA"
    if any(k in c for k in ("comercial", "industrial", "no_residencial")):
        return TARIFA_NO_RESIDENCIAL, None
    return None, "CLASIFICACION_REQUIERE_EXCEPCION"


def _fila(
    estado: str,
    *,
    cuenta: str,
    periodo: str,
    consumo: Any,
    vce: Any,
    facturado: Decimal,
    extra: dict[str, Any],
    **kw: Any,
) -> FilaControl:
    return FilaControl(
        identificador=cuenta,
        periodo=periodo,
        tarifa=kw.get("tarifa"),
        estado=estado,
        motivo_revision=kw.get("motivo"),
        regla_aplicada=kw.get("tarifa"),
        consumo_kwh=consumo,
        base_variable=vce,
        facturado_real=facturado,
        esperado=kw.get("esperado"),
        diferencia=kw.get("diferencia"),
        valor_por_encima=kw.get("encima", CERO),
        valor_por_debajo=kw.get("debajo", CERO),
        extra=extra,
    )


def _moda(filas: Sequence[dict[str, Any]], campo: str) -> Any:
    """El valor más frecuente no vacío (en empate, el primero que aparece), como `mode()`."""
    conteo: dict[Any, int] = {}
    for f in filas:
        valor = f.get(campo)
        if valor is not None and str(valor).strip() != "":
            conteo[valor] = conteo.get(valor, 0) + 1
    return max(conteo, key=lambda v: conteo[v]) if conteo else None


_TIPOS_ANEXO = {
    "fija": "fija",
    "porcentaje_vce": "porcentaje",
    "mayor_entre_porcentaje_y_minimo": "mayor_porcentaje_minimo",
}


def regla_de_anexo(excepcion: dict[str, Any]) -> ReglaCelsia | None:
    """Regla por cuenta en el formato del anexo de la carta (el de OPainn): `tipo` y, según el
    tipo, `porcentaje_vce`, `valor_fijo_mensual` o `tope_minimo_mensual`, o `urbano`/`rural`."""
    tipo = _TIPOS_ANEXO.get(str(excepcion.get("tipo") or ""))
    if tipo is None:
        return None
    fijo = excepcion.get("valor_fijo_mensual", excepcion.get("tope_minimo_mensual"))

    def valor(clave: str) -> Decimal | None:
        crudo = fijo if fijo is not None else excepcion.get(clave)
        if crudo is None:  # sin mínimo, OPainn toma 0; una fija sin valor queda incompleta
            return CERO if tipo == "mayor_porcentaje_minimo" else None
        return d(crudo)

    porcentaje = excepcion.get("porcentaje_vce")
    return ReglaCelsia(
        tipo, None if porcentaje is None else d(porcentaje), valor("urbano"), valor("rural")
    )


def control_tarifario(
    facturacion: Sequence[dict[str, Any]],
    periodo: str,
    vigencia: VigenciaCelsia | None,
) -> list[FilaControl]:
    """Cuenta × periodo sobre las filas de impuesto, como OPainn: clase, estrato, sector y
    periodicidad son los más frecuentes de la cuenta; el VCE, el mayor (una nota de ajuste trae
    VCE negativo). Los topes fijos se duplican si la factura dice bimestral: si Celsia cobra el
    doble a una cuenta que declara mensual, eso es un hallazgo y no se esconde."""
    grupos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fila in facturacion:
        if fila.get("tipo_concepto") == "impuesto":
            grupos[str(fila["cuenta"])].append(fila)
    salida: list[FilaControl] = []
    for cuenta, filas in sorted(grupos.items()):
        primera = {c: _moda(filas, c) for c in ("clase", "segmento", "estrato", "sector")}
        primera["periodicidad"] = _moda(filas, "periodicidad")
        primera["consumo_kwh"] = max(
            (d(f["consumo_kwh"]) for f in filas if f.get("consumo_kwh") is not None), default=None
        )
        facturado = q2(suma(f.get("valor_facturado") for f in filas))
        rural = "rural" in str(primera.get("sector") or "").lower()
        bimestral = "bim" in str(primera.get("periodicidad") or "").lower()
        vce = max(
            (d(f["monto_energia"]) for f in filas if f.get("monto_energia") is not None),
            default=None,
        )
        extra = {
            "sector": "rural" if rural else "urbano",
            "periodicidad": "bimestral" if bimestral else "mensual",
            "clase": primera.get("clase"),
            "estrato": primera.get("estrato"),
        }

        fila = partial(
            _fila,
            cuenta=cuenta,
            periodo=periodo,
            consumo=primera.get("consumo_kwh"),
            vce=vce,
            facturado=facturado,
            extra=extra,
        )

        if vigencia is None:
            salida.append(fila("REQUIERE_REVISION", motivo="PERIODO_SIN_PARAMETROS"))
            continue
        excepcion = vigencia.excepciones.get(cuenta) or {}
        tarifa, motivo = tarifa_de(primera.get("clase"), primera.get("estrato"))
        if excepcion.get("pendiente_revision"):
            salida.append(fila("NO_VALIDABLE", motivo="REGLAS_CONTRADICTORIAS_EN_CARTA"))
            continue
        anexo = regla_de_anexo(excepcion)
        if excepcion.get("tarifa"):
            tarifa, motivo = str(excepcion["tarifa"]), None
        regla = vigencia.tarifas.get(tarifa) if tarifa else None
        if anexo is not None:
            # Regla individual del anexo de la carta municipal: manda sobre la general.
            regla, tarifa = anexo, excepcion.get("clasificacion_fuente") or tarifa or "ANEXO"
        elif excepcion.get("valor_fijo") is not None:
            regla = ReglaCelsia(
                "fija", None, d(excepcion["valor_fijo"]), d(excepcion["valor_fijo"])
            )
            tarifa = tarifa or "EXCEPCION"
        elif excepcion.get("porcentaje") is not None:
            regla = ReglaCelsia("porcentaje", d(excepcion["porcentaje"]), None, None)
            tarifa = tarifa or "EXCEPCION"
        if regla is None:
            salida.append(
                # La carta no fija regla para esa cuenta: no hay esperado que calcular (RN-006).
                fila("NO_VALIDABLE", tarifa=tarifa, motivo=motivo or "ESTRATO_SIN_REGLA")
            )
            continue
        multiplo = Decimal(2) if bimestral and vigencia.duplicar_bimestral else Decimal(1)
        tope = regla.rural if rural else regla.urbano
        if regla.tipo == "fija":
            if tope is None:
                salida.append(
                    fila("REQUIERE_REVISION", tarifa=tarifa, motivo="REGLA_FIJA_INCOMPLETA")
                )
                continue
            esperado = q2(tope * multiplo)
        else:
            if vce is None:
                # Falta un dato que se puede conseguir: requiere revisión (RN-006).
                salida.append(fila("REQUIERE_REVISION", tarifa=tarifa, motivo="SIN_VCE"))
                continue
            if regla.porcentaje is None or (regla.tipo != "porcentaje" and tope is None):
                salida.append(
                    fila(
                        "NO_VALIDABLE", tarifa=tarifa, motivo="REGLAS_CONTRADICTORIAS_EN_CARTA"
                    )
                )
                continue
            esperado = q2(regla.porcentaje * d(vce))
            if regla.tipo == "mayor_porcentaje_minimo" and tope is not None:
                esperado = max(esperado, q2(tope * multiplo))
        diferencia = q2(facturado - esperado)
        if abs(diferencia) <= vigencia.tolerancia:
            salida.append(fila("CORRECTO", tarifa=tarifa, esperado=esperado, diferencia=diferencia))
        elif diferencia > 0:
            salida.append(
                fila(
                    "POR_ENCIMA",
                    tarifa=tarifa,
                    esperado=esperado,
                    diferencia=diferencia,
                    encima=diferencia,
                )
            )
        else:
            salida.append(
                fila(
                    "POR_DEBAJO",
                    tarifa=tarifa,
                    esperado=esperado,
                    diferencia=diferencia,
                    debajo=-diferencia,
                )
            )
    return salida


GRUPOS_CONSUMO = {
    "todos": None,
    "minima": ("fija",),
    "variable": ("mayor_porcentaje_minimo", "porcentaje"),
    "especial": ("especial",),
    "revision": (),
}


def filtrar_grupo(
    filas: list[FilaControl], grupo: str, vigencia: VigenciaCelsia | None
) -> list[FilaControl]:
    if grupo not in GRUPOS_CONSUMO or GRUPOS_CONSUMO[grupo] is None:
        return filas
    if grupo == "revision":
        return [f for f in filas if f.estado in ("REQUIERE_REVISION", "NO_VALIDABLE")]
    if grupo == "especial":
        return [f for f in filas if f.tarifa in (TARIFA_ESPECIAL, "EXCEPCION")]
    tipos = GRUPOS_CONSUMO[grupo] or ()
    tarifas = vigencia.tarifas if vigencia else {}
    return [f for f in filas if f.tarifa in tarifas and tarifas[f.tarifa].tipo in tipos]


def estados_vacios() -> dict[str, int]:
    return dict.fromkeys(ESTADOS, 0)


# === Facturas irregulares (desde mayo de 2026) ==================================================


def facturas_irregulares(
    facturacion: Sequence[dict[str, Any]], periodo: str
) -> dict[str, list[dict[str, Any]]]:
    categorias: dict[str, list[dict[str, Any]]] = {
        c: []
        for c in (
            "LINEA_NEGATIVA",
            "TOTAL_NEGATIVO",
            "TOTAL_EN_CERO",
            "SIN_CONCEPTO_IMPUESTO",
            "IMPUESTO_AMBIGUO",
        )
    }
    if periodo < "202605":
        return categorias  # los cortes anteriores no desglosan el concepto
    por_cuenta: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in facturacion:
        por_cuenta[str(f["cuenta"])].append(f)
    for cuenta, filas in sorted(por_cuenta.items()):
        impuesto = [f for f in filas if f.get("tipo_concepto") == "impuesto"]
        base = {
            "identificador": cuenta,
            "cuenta": cuenta,
            "facturas": sorted({str(f.get("factura") or "") for f in filas}),
        }
        if not impuesto:
            categorias["SIN_CONCEPTO_IMPUESTO"].append(
                {**base, "valor_otros_conceptos": q2(suma(f.get("valor_facturado") for f in filas))}
            )
            continue
        montos = [d(f.get("valor_facturado")) for f in impuesto]
        total = q2(suma(montos))
        fila = {**base, "total_impuesto": total}
        if any(m < 0 for m in montos):
            categorias["LINEA_NEGATIVA"].append(fila)
        if total < 0:
            categorias["TOTAL_NEGATIVO"].append(fila)
        elif total == 0:
            categorias["TOTAL_EN_CERO"].append(fila)
        por_tarifa: dict[str, int] = defaultdict(int)
        for f in impuesto:
            por_tarifa[str(f.get("tarifa") or "")] += 1
        if any(n >= 2 for n in por_tarifa.values()):
            categorias["IMPUESTO_AMBIGUO"].append(fila)
    return categorias


# === Cartera por edades ==========================================================================


def cartera_por_edades(cartera: Sequence[dict[str, Any]]) -> dict[str, Any]:
    total = suma(f.get("cartera_total") for f in cartera)
    bandas = []
    for campo in EDADES:
        valor = q2(suma(f.get(campo) for f in cartera))
        usuarios = len({f["cuenta"] for f in cartera if d(f.get(campo)) > 0})
        bandas.append(
            {
                "edad": ETIQUETAS_EDAD[campo],
                "campo": campo,
                "usuarios": usuarios,
                "valor": valor,
                "pct": div(valor, total),
            }
        )
    return {
        "total_cartera": q2(total),
        "usuarios": len({f["cuenta"] for f in cartera}),
        "bandas": bandas,
    }


# === Resumen por usuario =========================================================================


def usuarios_corte(familias: dict[str, Sequence[dict[str, Any]]]) -> dict[str, UsuarioCorte]:
    usuarios: dict[str, UsuarioCorte] = {}

    def usuario(cuenta: str) -> UsuarioCorte:
        if cuenta not in usuarios:
            usuarios[cuenta] = UsuarioCorte(identificador=cuenta)
        return usuarios[cuenta]

    for f in familias.get("facturacion", ()):
        u = usuario(str(f["cuenta"]))
        u.facturado_presente = True
        u.facturado += d(f.get("valor_facturado"))
        if (
            f.get("tipo_concepto") in ("impuesto", "agregado_sin_detalle")
            and f.get("consumo_kwh") is not None
        ):
            u.consumo = (u.consumo or CERO) + d(f["consumo_kwh"])
        u.segmento = u.segmento or f.get("segmento")
        u.estrato = u.estrato or f.get("estrato")
        u.tarifa = u.tarifa or f.get("tarifa")
        u.barrio = u.barrio or f.get("barrio")
        u.nombre = u.nombre or f.get("nombre")
        u.direccion = u.direccion or f.get("direccion")
        u.periodicidad = u.periodicidad or f.get("periodicidad")
        u.extra.setdefault("sector", f.get("sector"))
        u.extra.setdefault("clase", f.get("clase"))
    for f in familias.get("recaudo", ()):
        u = usuario(str(f["cuenta"]))
        valor = d(f.get("valor_recaudado"))
        u.recaudo += valor
        if f.get("tipo_recaudo") == "CORRIENTE":
            u.recaudo_corriente += valor
        elif f.get("tipo_recaudo") == "CARTERA":
            u.recaudo_cartera += valor
        u.pago = True
        u.nombre = u.nombre or f.get("nombre")
        u.segmento = u.segmento or f.get("segmento")
    for f in familias.get("cartera", ()):
        u = usuario(str(f["cuenta"]))
        u.cartera += d(f.get("cartera_total"))
        u.nombre = u.nombre or f.get("nombre")
        u.segmento = u.segmento or f.get("segmento")
        u.estrato = u.estrato or f.get("estrato")
    return usuarios


# === Tabla dinámica Celsia (paridad con `td_celsia` de OPainn) ==================================
# Equivalente de la TD de Afinia: los residenciales se abren por estrato y los demás segmentos se
# conservan como los reporta Celsia.

TOTALES_TD = "TOTALES"
_SIN_CLASIFICACION = "Sin clasificación"
_PRIMER_NUMERO = re.compile(r"(\d+)")


def clasificacion_td(fila: dict[str, Any]) -> str:
    """Segmento (o clase); los residenciales con el número del estrato. Celsia escribió
    «Estrato 2» hasta abril de 2026 y «2» desde mayo: se toma solo el número."""
    base = next(
        (str(fila[c]).strip() for c in ("segmento", "clase") if str(fila.get(c) or "").strip()),
        _SIN_CLASIFICACION,
    )
    numero = _PRIMER_NUMERO.search(str(fila.get("estrato") or "").strip())
    if "residencial" in base.lower() and numero:
        return f"Residencial · Estrato {numero.group(1)}"
    return base


def tipo_recaudo_td(fila: dict[str, Any], periodo: str) -> str:
    """Corriente si la factura vence en el mes del recaudo o en el anterior; sin vencimiento, no
    clasificado. Es una clasificación analítica, no un campo certificado por Celsia."""
    vence = como_fecha(fila.get("fecha_vencimiento"))
    if vence is None:
        return "NO_CLASIFICADO"
    return "CORRIENTE" if vence >= primer_dia(sumar_meses(periodo, -1)) else "CARTERA"


def _razon(num: Any, den: Any) -> Decimal | None:
    return None if den is None or d(den) == CERO else div_precisa(num, den)


def _vacia(clas: str) -> dict[str, Any]:
    return {
        "clasificacion": clas,
        "_cuentas_f": set(),
        "_facturas": set(),
        "_fin_f": set(),
        "_consumo": {},
        "_cuentas_r": set(),
        "_fin_r": set(),
        "_cuentas_c": set(),
        "facturacion": CERO,
        "financiacion_facturada": CERO,
        "recaudo_total": CERO,
        "financiacion_recaudada": CERO,
        "recaudo_corriente": CERO,
        "recaudo_cartera": CERO,
        "recaudo_no_clasificado": CERO,
        "cartera_acumulada": CERO,
        "cartera_financiada": CERO,
    }


_SUMABLES = (
    "usuarios_facturados",
    "facturas",
    "consumo_kwh",
    "facturacion",
    "usuarios_financiacion_facturada",
    "financiacion_facturada",
    "usuarios_recaudo",
    "usuarios_financiacion_recaudada",
    "financiacion_recaudada",
    "recaudo_corriente",
    "recaudo_cartera",
    "recaudo_no_clasificado",
    "recaudo_total",
)


def tabla_dinamica(
    periodo: str,
    *,
    facturacion: Sequence[dict[str, Any]],
    recaudo: Sequence[dict[str, Any]],
    cartera: Sequence[dict[str, Any]] | None,
    nuevos: set[str] | None = None,
    reintegrados: set[str] | None = None,
    dejados: dict[str, set[str]] | None = None,
    previo: dict[str, dict[str, Decimal]] | None = None,
) -> dict[str, Any]:
    """Filas por clasificación (de mayor a menor facturación) y totales.

    `nuevos` y `reintegrados`: cuentas del corte (se cuentan en su clasificación actual).
    `dejados`: cuenta → clasificaciones en el corte donde se le facturó por última vez.
    Sin movimiento evaluable (`nuevos is None`) esas columnas van en None.
    `previo`: {clasificación: {facturacion, recaudo}} del corte comparable (variación).
    """
    grupos: dict[str, dict[str, Any]] = {}

    def grupo(clas: str) -> dict[str, Any]:
        return grupos.setdefault(clas, _vacia(clas))

    for f in facturacion:
        x = grupo(clasificacion_td(f))
        cuenta = str(f.get("cuenta"))
        x["_cuentas_f"].add(cuenta)
        if f.get("factura") is not None:
            x["_facturas"].add(str(f["factura"]))
        valor = d(f.get("valor_facturado"))
        x["facturacion"] += valor
        if f.get("tipo_concepto") == "financiacion":
            x["_fin_f"].add(cuenta)
            x["financiacion_facturada"] += valor
        if f.get("consumo_kwh") is not None:
            clave = (cuenta, str(f.get("factura")))
            previo_consumo = x["_consumo"].get(clave)
            consumo = d(f["consumo_kwh"])
            x["_consumo"][clave] = (
                consumo if previo_consumo is None else max(previo_consumo, consumo)
            )
    for f in recaudo:
        x = grupo(clasificacion_td(f))
        cuenta = str(f.get("cuenta"))
        valor = d(f.get("valor_recaudado"))
        x["_cuentas_r"].add(cuenta)
        x["recaudo_total"] += valor
        if f.get("tipo_concepto") == "financiacion":
            x["_fin_r"].add(cuenta)
            x["financiacion_recaudada"] += valor
        x[f"recaudo_{tipo_recaudo_td(f, periodo).lower()}"] += valor
    hay_cartera = bool(cartera)
    for f in cartera or ():
        x = grupo(clasificacion_td(f))
        if d(f.get("cartera_total")) > CERO:
            x["_cuentas_c"].add(str(f.get("cuenta")))
        x["cartera_acumulada"] += d(f.get("cartera_total"))
        x["cartera_financiada"] += d(f.get("cartera_financiada"))

    hay_movimiento = nuevos is not None
    bajas: dict[str, int] = defaultdict(int)
    for clases in (dejados or {}).values():
        for clas in clases:
            bajas[clas] += 1
            grupo(clas)

    total_facturados = sum(len(x["_cuentas_f"]) for x in grupos.values())
    filas: list[dict[str, Any]] = []
    for x in grupos.values():
        r: dict[str, Any] = {
            "clasificacion": x["clasificacion"],
            "usuarios_facturados": len(x["_cuentas_f"]),
            "facturas": len(x["_facturas"]),
            "consumo_kwh": suma(x["_consumo"].values()),
            "facturacion": x["facturacion"],
            "usuarios_financiacion_facturada": len(x["_fin_f"]),
            "financiacion_facturada": x["financiacion_facturada"],
            "usuarios_recaudo": len(x["_cuentas_r"]),
            "usuarios_financiacion_recaudada": len(x["_fin_r"]),
            "recaudo_total": x["recaudo_total"],
            "financiacion_recaudada": x["financiacion_recaudada"],
            "recaudo_corriente": x["recaudo_corriente"],
            "recaudo_cartera": x["recaudo_cartera"],
            "recaudo_no_clasificado": x["recaudo_no_clasificado"],
            "usuarios_cartera": len(x["_cuentas_c"]) if hay_cartera else None,
            "cartera_acumulada": x["cartera_acumulada"] if hay_cartera else None,
            "cartera_financiada": x["cartera_financiada"] if hay_cartera else None,
            "nuevos_usuarios": (
                len(x["_cuentas_f"] & (nuevos or set())) if hay_movimiento else None
            ),
            "usuarios_dejados_facturar": bajas.get(x["clasificacion"], 0)
            if hay_movimiento
            else None,
            "usuarios_reintegrados": (
                len(x["_cuentas_f"] & (reintegrados or set())) if hay_movimiento else None
            ),
        }
        _derivados(r, total_facturados, hay_cartera)
        anterior = (previo or {}).get(x["clasificacion"]) or {}
        fact_prev, rec_prev = anterior.get("facturacion"), anterior.get("recaudo")
        r["variacion_facturacion"] = (
            _razon(r["facturacion"] - fact_prev, abs(fact_prev)) if fact_prev else None
        )
        r["variacion_recaudo"] = (
            _razon(r["recaudo_total"] - rec_prev, abs(rec_prev)) if rec_prev else None
        )
        filas.append(r)
    filas.sort(key=lambda r: r["facturacion"], reverse=True)

    def total_de(clave: str) -> Any:
        valores = [r[clave] for r in filas if r[clave] is not None]
        return sum(valores, CERO if valores and isinstance(valores[0], Decimal) else 0)

    totales: dict[str, Any] = {"clasificacion": TOTALES_TD}
    for clave in _SUMABLES:
        totales[clave] = total_de(clave)
    for clave in ("usuarios_cartera", "cartera_acumulada", "cartera_financiada"):
        totales[clave] = total_de(clave) if hay_cartera else None
    for clave in ("nuevos_usuarios", "usuarios_dejados_facturar", "usuarios_reintegrados"):
        totales[clave] = total_de(clave) if hay_movimiento else None
    _derivados(totales, totales["usuarios_facturados"], hay_cartera)
    totales["pct_usuarios_facturados"] = Decimal(1) if totales["usuarios_facturados"] else None
    return {"filas": filas, "totales": totales, "cartera_disponible": hay_cartera}


def _derivados(r: dict[str, Any], total_facturados: int, hay_cartera: bool) -> None:
    facturados = r["usuarios_facturados"]
    r["pct_usuarios_facturados"] = _razon(facturados, total_facturados)
    r["pct_usuarios_recaudo"] = _razon(r["usuarios_recaudo"], facturados)
    r["promedio_consumo_kwh"] = _razon(r["consumo_kwh"], facturados)
    r["factura_promedio"] = _razon(r["facturacion"], facturados)
    r["eficiencia_recaudo"] = _razon(r["recaudo_total"], r["facturacion"])
    r["eficiencia_corriente"] = _razon(r["recaudo_corriente"], r["facturacion"])
    r["pct_usuarios_cartera"] = _razon(r["usuarios_cartera"], facturados) if hay_cartera else None
    r["cartera_promedio"] = (
        _razon(r["cartera_acumulada"], r["usuarios_cartera"]) if hay_cartera else None
    )


# === Periodicidad y movimiento de Celsia (paridad con `opainn.celsia.periodicidad`) ==============
# El sector es la fuente de verdad: urbano, mensual; rural, bimestral en meses pares. Si el sector
# y lo declarado chocan, mandan los meses facturados; sin patrón, bimestral provisional en la
# paridad en que apareció (no inventa bajas). Un mes en que no le toca facturar no es ausencia.

SALTO_DE_PERIODICIDAD = {"MENSUAL": 1, "BIMESTRAL": 2}


def _rotulo(valor: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_")


def _regla_sector(valor: Any) -> tuple[str, int | None] | None:
    sector = _rotulo(valor)
    if "rural" in sector:
        return "BIMESTRAL", 0
    if "urbano" in sector:
        return "MENSUAL", None
    return None


def sectores_estables(cortes: dict[str, list[tuple[str, Any, Any]]]) -> dict[str, set[str]]:
    """Sectores explícitos por cuenta en todos los cortes, también los posteriores: el sector es
    un atributo de la cuenta, no del corte. `cortes`: periodo → [(cuenta, periodicidad, sector)].
    """
    por_cuenta: dict[str, set[str]] = {}
    for filas in cortes.values():
        for cuenta, _, sector in filas:
            if _regla_sector(sector) is not None:
                por_cuenta.setdefault(cuenta, set()).add(_rotulo(sector).upper())
    return por_cuenta


def _indice_mes(periodo: str) -> int:
    return int(periodo[:4]) * 12 + int(periodo[4:])


def _ciclo_observado(periodos: set[str]) -> tuple[str, int | None] | None:
    if len(periodos) < 2:
        return None
    meses = sorted(_indice_mes(p) for p in periodos)
    if any(b - a == 1 for a, b in zip(meses, meses[1:], strict=False)):
        return "MENSUAL", None
    paridades = {int(p[4:]) % 2 for p in periodos}
    if len(paridades) == 1:
        return "BIMESTRAL", paridades.pop()
    return None


def perfil_de_usuarios(
    cortes: dict[str, list[tuple[str, Any, Any]]], hasta_periodo: str | None = None
) -> dict[str, dict[str, Any]]:
    """Periodicidad, ciclo, salto y cortes vistos de cada cuenta (hasta `hasta_periodo`)."""
    sectores = sectores_estables(cortes)
    perfil: dict[str, dict[str, Any]] = {}
    for periodo in sorted(cortes):
        if hasta_periodo is not None and periodo > hasta_periodo:
            continue
        paridad = int(periodo[4:]) % 2
        for cuenta, periodicidad, _sector in dict.fromkeys(cortes[periodo]):
            conocidos = sectores.get(cuenta, set())
            conflicto = len(conocidos) > 1
            estable = next(iter(conocidos)) if len(conocidos) == 1 else None
            entrada = perfil.setdefault(
                cuenta,
                {
                    "periodicidad": None,
                    "sector": estable,
                    "conflicto_sector": conflicto,
                    "declaradas": set(),
                    "paridades": set(),
                    "periodos": set(),
                },
            )
            regla = _regla_sector(estable)
            if regla is not None and not conflicto:
                entrada["periodicidad"] = regla[0]
            declarada = str(periodicidad or "").strip().upper()
            if not conflicto and regla is None and declarada:
                entrada["periodicidad"] = declarada
            if declarada:
                entrada["declaradas"].add(declarada)
            entrada["paridades"].add(paridad)
            entrada["periodos"].add(periodo)

    for entrada in perfil.values():
        paridades = entrada.pop("paridades")
        con_sector = entrada["sector"] is not None and not entrada["conflicto_sector"]
        if entrada["sector"] == "RURAL" and not entrada["conflicto_sector"]:
            entrada["ciclo"] = 0
        elif entrada["sector"] is None and not entrada["conflicto_sector"] and len(paridades) == 1:
            entrada["ciclo"] = next(iter(paridades))
        else:
            entrada["ciclo"] = None
        declaradas = entrada.pop("declaradas")
        entrada["discrepancia_periodicidad"] = con_sector and bool(
            declaradas - {entrada["periodicidad"]}
        )
        if entrada["discrepancia_periodicidad"] or entrada["conflicto_sector"]:
            observado = _ciclo_observado(entrada["periodos"])
            if observado is not None:
                entrada["periodicidad"], entrada["ciclo"] = observado
            else:
                vistas = {int(p[4:]) % 2 for p in entrada["periodos"]}
                entrada["periodicidad"] = "BIMESTRAL"
                entrada["ciclo"] = vistas.pop() if len(vistas) == 1 else None
            entrada["discrepancia_periodicidad"] = False
        entrada["salto"] = (
            None
            if entrada["discrepancia_periodicidad"]
            else SALTO_DE_PERIODICIDAD.get(entrada["periodicidad"])
        )
    return perfil


def le_corresponde(entrada: dict[str, Any], periodo: str) -> bool:
    salto = entrada.get("salto")
    if salto is None:
        return False
    if salto == 1:
        return True
    ciclo = entrada.get("ciclo")
    return ciclo is not None and int(periodo[4:]) % 2 == ciclo


def comparable_de_usuario(entrada: dict[str, Any], periodo: str) -> str | None:
    salto = entrada.get("salto")
    if salto is None:
        return None
    anio, mes = int(periodo[:4]), int(periodo[4:]) - salto
    while mes <= 0:
        anio, mes = anio - 1, mes + 12
    return f"{anio:04d}{mes:02d}"


@dataclass
class MovimientoCelsia:
    """Quién entra, sale o vuelve, cada uno contra su propio ciclo. `evaluables`: cuenta → su
    corte comparable (vacío si no hay contra qué medir)."""

    evaluables: dict[str, str] = field(default_factory=dict)
    nuevos: set[str] = field(default_factory=set)
    reintegrados: set[str] = field(default_factory=set)
    dejados: set[str] = field(default_factory=set)


def clasificar_movimientos(
    cortes: dict[str, list[tuple[str, Any, Any]]], periodo: str
) -> MovimientoCelsia:
    cargados = set(cortes)
    perfil = perfil_de_usuarios(cortes, periodo)
    mov = MovimientoCelsia()
    for cuenta, entrada in perfil.items():
        if not le_corresponde(entrada, periodo):
            continue
        comparable = comparable_de_usuario(entrada, periodo)
        if comparable is None or comparable not in cargados:
            continue  # sin el corte contra el que medir no se afirma nada
        mov.evaluables[cuenta] = comparable
    altas: set[str] = set()
    for cuenta, comparable in mov.evaluables.items():
        vistos = perfil[cuenta]["periodos"]
        aqui, antes = periodo in vistos, comparable in vistos
        if antes and not aqui:
            mov.dejados.add(cuenta)
        elif aqui and not antes:
            altas.add(cuenta)
            if any(p < comparable for p in vistos):
                mov.reintegrados.add(cuenta)
    mov.nuevos = altas - mov.reintegrados
    return mov
