"""Análisis comunes a los tres comercializadores, sobre un resumen por usuario de cada corte.

Cada adaptador reduce su corte a `UsuarioCorte` (facturado, recaudo, cartera, consumo, segmento…)
y estas funciones responden igual para Afinia, Celsia y Vatia (§11.8, §11.10, E.4, E.7).
"""

import itertools
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.modulos.comercial.dominio.comun import (
    CERO,
    div,
    faltantes_entre,
    meses_entre,
    q2,
    q4,
    suma,
)


@dataclass
class UsuarioCorte:
    identificador: str
    facturado_presente: bool = False
    facturado: Decimal = CERO
    recaudo: Decimal = CERO
    recaudo_corriente: Decimal = CERO
    recaudo_cartera: Decimal = CERO
    recuperacion_cartera: Decimal = CERO
    cartera: Decimal = CERO
    consumo: Decimal | None = None
    pago: bool = False
    segmento: str | None = None
    tarifa: str | None = None
    estrato: str | None = None
    barrio: str | None = None
    nombre: str | None = None
    direccion: str | None = None
    estado_suministro: str | None = None
    periodicidad: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# === Periodicidad y movimiento de usuarios (§11.8) ==============================================

MENSUAL = "mensual"
NO_EVALUABLE = "no_evaluable"


def deducir_periodicidad(
    meses: Iterable[str], declarada: str | None = None, sector: str | None = None
) -> tuple[str, str]:
    """(periodicidad, origen). Con dos o más facturas mandan los meses facturados; con una sola,
    el archivo o el sector orientan y si no, bimestral provisional en la paridad de ese mes."""
    ordenados = sorted(set(meses))
    dec_ = (declarada or "").lower()
    if dec_ and not any(k in dec_ for k in ("mensual", "bimestral", "bim")):
        return NO_EVALUABLE, "archivo"
    if not ordenados:
        return NO_EVALUABLE, "sin_facturas"
    if len(ordenados) == 1:
        paridad = "par" if int(ordenados[0][4:6]) % 2 == 0 else "impar"
        if "mensual" in dec_:
            return MENSUAL, "archivo"
        if not dec_ and "urban" in (sector or "").lower():
            return MENSUAL, "sector"
        return f"bimestral_provisional_{paridad}", "provisional"
    indices = [int(p[:4]) * 12 + int(p[4:6]) for p in ordenados]
    if any(b - a == 1 for a, b in itertools.pairwise(indices)):
        return MENSUAL, "meses_facturados"
    paridades = {i % 2 for i in indices}
    if len(paridades) == 1:
        # índice = año*12 + mes: la paridad del índice depende del mes solamente
        mes = int(ordenados[0][4:6])
        return ("bimestral_par" if mes % 2 == 0 else "bimestral_impar"), "meses_facturados"
    return NO_EVALUABLE, "meses_facturados"


def corresponde(periodicidad: str, periodo: str) -> bool | None:
    """¿Al usuario le correspondía facturar en ese periodo? None si no es evaluable."""
    if periodicidad == MENSUAL:
        return True
    par = int(periodo[4:6]) % 2 == 0
    if periodicidad.endswith("_par"):
        return par
    if periodicidad.endswith("_impar"):
        return not par
    return None


@dataclass
class Movimiento:
    periodo: str
    comparable: str | None
    salto_corte_detectado: bool
    cortes_faltantes: list[str]
    facturados: list[str] = field(default_factory=list)
    nuevos: list[str] = field(default_factory=list)
    reintegrados: list[str] = field(default_factory=list)
    dejados_facturar: list[str] = field(default_factory=list)
    ausentes: dict[str, int] = field(default_factory=dict)  # id -> periodos esperados ausente
    ultimo_periodo: dict[str, str] = field(default_factory=dict)
    no_evaluables: list[str] = field(default_factory=list)


def movimiento(
    presencia: dict[str, set[str]],
    cargados: Sequence[str],
    objetivo: str,
    periodicidades: dict[str, str] | None = None,
) -> Movimiento:
    """Una sola definición para todas las vistas. Los meses sin archivo no cuentan como ausencia;
    quien reaparece es reintegrado, nunca nuevo; a un bimestral fuera de su mes no se le cuenta
    ni se le lista."""
    previos = sorted(p for p in cargados if p < objetivo)
    comparable = previos[-1] if previos else None
    salto = comparable is not None and meses_entre(comparable, objetivo) > 1
    resultado = Movimiento(
        periodo=objetivo,
        comparable=comparable,
        salto_corte_detectado=salto,
        cortes_faltantes=faltantes_entre(comparable, objetivo) if comparable else [],
    )
    hasta = [*previos, objetivo]
    for usuario in sorted(presencia):
        vistos = {p for p in presencia[usuario] if p <= objetivo}
        if not vistos:
            continue
        tipo = (periodicidades or {}).get(usuario, MENSUAL)
        toca = corresponde(tipo, objetivo)
        presente = objetivo in vistos
        if toca is None:
            resultado.no_evaluables.append(usuario)
            continue
        if not toca and not presente:
            continue  # no le correspondía: no se cuenta ni se lista
        esperados = [p for p in previos if corresponde(tipo, p)]
        ultimo_comparable = esperados[-1] if esperados else None
        if presente:
            if ultimo_comparable is None or ultimo_comparable in vistos:
                resultado.facturados.append(usuario)
            elif any(p in vistos for p in previos):
                resultado.reintegrados.append(usuario)
            else:
                resultado.nuevos.append(usuario)
            continue
        if ultimo_comparable is not None and ultimo_comparable in vistos:
            resultado.dejados_facturar.append(usuario)
        anteriores = [p for p in previos if p in vistos]
        if anteriores:
            ultimo = max(anteriores)
            perdidos = sum(
                1 for p in hasta if p > ultimo and corresponde(tipo, p) and p not in vistos
            )
            if perdidos:
                resultado.ausentes[usuario] = perdidos
                resultado.ultimo_periodo[usuario] = ultimo
    return resultado


def tramo(periodos: int) -> str:
    return str(periodos) if periodos <= 3 else ">3"


def tramos_ausencia(ausentes: dict[str, int]) -> dict[str, int]:
    conteo = {"1": 0, "2": 0, "3": 0, ">3": 0}
    for n in ausentes.values():
        conteo[tramo(n)] += 1
    return conteo


# === Totales del corte y eficiencia (§11.10) ====================================================


def totales(
    usuarios: Iterable[UsuarioCorte], *, eficiencia_nula_si_no_positivo: bool = False
) -> dict[str, Any]:
    lista = list(usuarios)
    facturados = [u for u in lista if u.facturado_presente]
    facturacion = q4(suma(u.facturado for u in lista))
    recaudo = q4(suma(u.recaudo for u in lista))
    pagaron = sum(1 for u in facturados if u.pago)
    consumos = [u.consumo for u in facturados if u.consumo is not None]
    eficiencia = (
        None
        if eficiencia_nula_si_no_positivo and facturacion <= 0
        else div(recaudo, facturacion, nulo=True)
    )
    return {
        "n_facturados": len(facturados),
        "facturacion": facturacion,
        "recaudo": recaudo,
        "recaudo_total": recaudo,
        "recaudo_corriente": q4(suma(u.recaudo_corriente for u in lista)),
        "recaudo_cartera": q4(suma(u.recaudo_cartera for u in lista)),
        "recuperacion_cartera": q4(suma(u.recuperacion_cartera for u in lista)),
        "cartera": q4(suma(u.cartera for u in lista)),
        "n_con_cartera": sum(1 for u in lista if u.cartera > 0),
        "consumo": q4(suma(consumos)),
        "n_pagaron": pagaron,
        "eficiencia": eficiencia,
        "eficiencia_usuarios": div(pagaron, len(facturados), nulo=True),
    }


def eficiencia_detalle(usuarios: Iterable[UsuarioCorte]) -> dict[str, Any]:
    lista = [u for u in usuarios if u.facturado_presente]
    sin_pago = sorted(
        (u for u in lista if not u.pago), key=lambda u: (-u.facturado, u.identificador)
    )
    por_segmento: dict[str, dict[str, int]] = defaultdict(lambda: {"facturados": 0, "pagaron": 0})
    for u in lista:
        clave = u.segmento or "Sin dato"
        por_segmento[clave]["facturados"] += 1
        por_segmento[clave]["pagaron"] += int(u.pago)
    return {
        "por_segmento": [
            {"segmento": k, **v, "eficiencia_usuarios": div(v["pagaron"], v["facturados"])}
            for k, v in sorted(por_segmento.items())
        ],
        "sin_pago": [
            {"identificador": u.identificador, "segmento": u.segmento, "facturado": q2(u.facturado)}
            for u in sin_pago
        ],
    }


# === Gestión de cobro (E.4) ======================================================================


def concentracion(deudas: dict[str, Decimal]) -> dict[str, Any]:
    positivos = sorted(
        ((k, q2(v)) for k, v in deudas.items() if v > 0), key=lambda kv: (-kv[1], kv[0])
    )
    total = suma(v for _, v in positivos)
    mitad = total * Decimal("0.5")
    acumulado, cuantos = CERO, 0
    for i, (_, v) in enumerate(positivos, start=1):
        acumulado += v
        if cuantos == 0 and acumulado >= mitad:
            cuantos = i

    def tramo_top(n: int) -> dict[str, Any]:
        valor = q2(suma(v for _, v in positivos[:n]))
        return valor

    resultado: dict[str, Any] = {
        "total_cartera": q2(total),
        "total_deudores": len(positivos),
        "cuantos_suman_50_pct": cuantos,
    }
    for n in (10, 21, 100, 1000):
        resultado[f"top_{n}"] = tramo_top(n)
        resultado[f"top_{n}_pct_cartera"] = div(tramo_top(n), total)
        resultado[f"top_{n}_pct_deudores"] = div(min(n, len(positivos)), len(positivos))
    resultado["ranking"] = [{"identificador": k, "cartera": v} for k, v in positivos[:1000]]
    return resultado


ORDEN_PAGO = {"NUNCA_PAGA": 0, "INTERMITENTE": 1, "PAGA_SIEMPRE": 2}


def comportamiento_pago(
    facturados: dict[str, set[str]],
    pagaron: dict[str, set[str]],
    ultimos: dict[str, UsuarioCorte],
    limite: int = 1000,
) -> dict[str, Any]:
    """Sobre todos los cortes cargados. Señal operativa, no prueba de mora jurídica."""
    cortes_fact: dict[str, int] = defaultdict(int)
    cortes_pago: dict[str, int] = defaultdict(int)
    for periodo, ids in facturados.items():
        pagos = pagaron.get(periodo, set())
        for usuario in ids:
            cortes_fact[usuario] += 1
            if usuario in pagos:
                cortes_pago[usuario] += 1
    filas = []
    for usuario, n in cortes_fact.items():
        m = cortes_pago.get(usuario, 0)
        estado = "NUNCA_PAGA" if m == 0 else "PAGA_SIEMPRE" if m >= n else "INTERMITENTE"
        u = ultimos.get(usuario)
        nombre = (u.nombre if u else None) or ""
        tarifa = (u.tarifa if u else None) or ""
        filas.append(
            {
                "identificador": usuario,
                "comportamiento": estado,
                "tipo_gestion": (
                    "INSTITUCIONAL"
                    if "municipio" in nombre.lower() or "oficial" in tarifa.lower()
                    else "ORDINARIA"
                ),
                "cortes_facturados": n,
                "cortes_con_recaudo": m,
                "nombre": u.nombre if u else None,
                "tarifa": u.tarifa if u else None,
                "barrio": u.barrio if u else None,
                "direccion": u.direccion if u else None,
                "estado_suministro": u.estado_suministro if u else None,
                "cartera": q2(u.cartera if u else CERO),
            }
        )
    filas.sort(key=lambda r: (ORDEN_PAGO[r["comportamiento"]], -r["cartera"], r["identificador"]))
    resumen: dict[str, dict[str, Any]] = {k: {"usuarios": 0, "cartera": CERO} for k in ORDEN_PAGO}
    for f in filas:
        resumen[f["comportamiento"]]["usuarios"] += 1
        resumen[f["comportamiento"]]["cartera"] = q2(
            resumen[f["comportamiento"]]["cartera"] + f["cartera"]
        )
    return {"resumen": resumen, "total": len(filas), "items": filas[:limite]}


# === Disminuciones (E.7) =========================================================================

VARIABLES_DISMINUCION = ("consumo", "facturado", "recaudo", "recaudo_corriente")


def disminuciones(
    actual: dict[str, UsuarioCorte],
    anterior: dict[str, UsuarioCorte],
    *,
    variable: str = "facturado",
    minimo_pct: Decimal | None = None,
    maximo_pct: Decimal | None = None,
    segmento: str | None = None,
    barrio: str | None = None,
    limite: int = 1000,
) -> dict[str, Any]:
    dejaron = sorted(
        k
        for k, u in anterior.items()
        if u.facturado_presente and not (k in actual and actual[k].facturado_presente)
    )
    filas = []
    for k, u in actual.items():
        previo = anterior.get(k)
        if not (u.facturado_presente and previo and previo.facturado_presente):
            continue
        if segmento and (u.segmento or "") != segmento and (u.tarifa or "") != segmento:
            continue
        if barrio and (u.barrio or "").lower() != barrio.lower():
            continue
        antes, ahora = getattr(previo, variable), getattr(u, variable)
        if antes is None or ahora is None or antes <= 0 or ahora >= antes:
            continue
        caida = q4((antes - ahora) / antes * 100)
        if minimo_pct is not None and caida < minimo_pct:
            continue
        if maximo_pct is not None and caida > maximo_pct:
            continue
        filas.append(
            {
                "identificador": k,
                "segmento": u.segmento,
                "tarifa": u.tarifa,
                "barrio": u.barrio,
                "anterior": q2(antes),
                "actual": q2(ahora),
                "disminucion": q2(antes - ahora),
                "disminucion_pct": caida,
            }
        )
    filas.sort(key=lambda r: (-r["disminucion"], r["identificador"]))
    return {
        "variable": variable,
        "total": len(filas),
        "items": filas[:limite],
        "dejo_de_facturar": dejaron,
    }


# === Segmentación, barrios y comparativos ========================================================


def agrupar(usuarios: Iterable[UsuarioCorte], clave: str) -> list[dict[str, Any]]:
    grupos: dict[str, list[UsuarioCorte]] = defaultdict(list)
    for u in usuarios:
        grupos[getattr(u, clave) or "Sin dato"].append(u)
    total_fact = suma(u.facturado for g in grupos.values() for u in g)
    salida = []
    for nombre, lista in grupos.items():
        t = totales(lista)
        salida.append(
            {
                clave: nombre,
                "usuarios": len({u.identificador for u in lista}),
                "facturados": t["n_facturados"],
                "facturacion": t["facturacion"],
                "participacion": div(t["facturacion"], total_fact),
                "recaudo": t["recaudo"],
                "cartera": t["cartera"],
                "consumo": t["consumo"],
                "eficiencia": t["eficiencia"],
            }
        )
    return sorted(salida, key=lambda r: (-r["facturacion"], r[clave]))


def comparar_grupos(
    actual: list[dict[str, Any]], anterior: list[dict[str, Any]], clave: str
) -> list[dict[str, Any]]:
    previo = {r[clave]: r for r in anterior}
    salida = []
    for r in actual:
        p = previo.get(r[clave], {})
        fila = {clave: r[clave]}
        for campo in ("usuarios", "facturacion", "recaudo", "cartera"):
            ahora, antes = r[campo], p.get(campo, 0)
            fila[campo] = ahora
            fila[f"{campo}_anterior"] = antes
            fila[f"{campo}_variacion"] = q4(Decimal(ahora) - Decimal(antes))
            fila[f"{campo}_variacion_pct"] = div(Decimal(ahora) - Decimal(antes), antes, nulo=True)
        salida.append(fila)
    return salida


def variaciones(actual: dict[str, Any], anterior: dict[str, Any] | None) -> dict[str, Any]:
    if not anterior:
        return {}
    salida = {}
    for clave, valor in actual.items():
        previo = anterior.get(clave)
        if (
            isinstance(valor, (int, Decimal))
            and not isinstance(valor, bool)
            and isinstance(previo, (int, Decimal))
        ):
            salida[clave] = {
                "anterior": previo,
                "diferencia": q4(Decimal(valor) - Decimal(previo)),
                "pct": div(Decimal(valor) - Decimal(previo), previo, nulo=True),
            }
    return salida


# === Consolidado anual (E.1) =====================================================================

INDICADORES_ANUALES: dict[str, tuple[str, str]] = {
    "facturacion": ("flujo", "mayor"),
    "refacturacion": ("flujo", "mayor"),
    "total_facturacion": ("flujo", "mayor"),
    "recaudo_corriente": ("flujo", "mayor"),
    "recaudo_cartera": ("flujo", "mayor"),
    "recaudo_total": ("flujo", "mayor"),
    "cartera_recuperada": ("flujo", "mayor"),
    "valor_convenios_periodo": ("flujo", "mayor"),
    "cartera_acumulada": ("saldo", "menor"),
    "cartera": ("saldo", "menor"),
    "interes_mora_periodo": ("flujo", "menor"),
    "n_factura": ("usuarios", "mayor"),
    "n_facturados": ("usuarios", "mayor"),
    "n_rec": ("usuarios", "mayor"),
    "n_usuarios_cartera_acumulada": ("usuarios", "menor"),
    "consumo_kwh": ("flujo", "mayor"),
    "consumo": ("flujo", "mayor"),
    "eficiencia_corriente": ("eficiencia", "mayor"),
    "eficiencia_con_cartera": ("eficiencia", "mayor"),
    "eficiencia": ("eficiencia", "mayor"),
}


def consolidado_anual(anio: int, series: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Flujos se suman en el año; saldos toman el último corte; usuarios y eficiencias, el
    promedio de los cortes (se informa la cobertura de meses cargados)."""
    meses = sorted(p for p in series if p.startswith(str(anio)))
    indicadores: dict[str, Any] = {}
    for clave, (tipo, mejor) in INDICADORES_ANUALES.items():
        valores = [series[p][clave] for p in meses if series[p].get(clave) is not None]
        if not valores:
            continue
        if tipo == "flujo":
            valor: Any = q4(suma(valores))
        elif tipo == "saldo":
            valor = series[meses[-1]].get(clave)
        else:
            valor = q4(suma(valores) / Decimal(len(valores)))
        indicadores[clave] = {"tipo": tipo, "mejor_si": mejor, "valor": valor}
    faltan = [f"{anio}{m:02d}" for m in range(1, 13) if f"{anio}{m:02d}" not in meses]
    return {
        "anio": anio,
        "cobertura_meses": len(meses),
        "meses_cargados": meses,
        "meses_faltantes": faltan,
        "indicadores": indicadores,
    }
