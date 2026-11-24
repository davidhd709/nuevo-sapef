"""Reglas y análisis de Celsia (Alcalá): control tarifario 2026 (§11.7), periodicidad, cartera por
edades y facturas irregulares."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from functools import partial
from typing import Any

from app.modulos.comercial.dominio.afinia import ESTADOS, FilaControl
from app.modulos.comercial.dominio.analisis import UsuarioCorte
from app.modulos.comercial.dominio.celsia_ingesta import EDADES
from app.modulos.comercial.dominio.comun import CERO, d, div, normalizar_encabezado, q2, suma

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


def control_tarifario(
    facturacion: Sequence[dict[str, Any]],
    periodo: str,
    vigencia: VigenciaCelsia | None,
    bimestrales: set[str],
) -> list[FilaControl]:
    """Cuenta × periodo sobre las filas de impuesto. Los topes fijos se duplican en bimestral."""
    grupos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fila in facturacion:
        if fila.get("tipo_concepto") == "impuesto":
            grupos[str(fila["cuenta"])].append(fila)
    salida: list[FilaControl] = []
    for cuenta, filas in sorted(grupos.items()):
        primera = filas[0]
        facturado = q2(suma(f.get("valor_facturado") for f in filas))
        rural = "rural" in (primera.get("sector") or "").lower()
        bimestral = cuenta in bimestrales or "bim" in (primera.get("periodicidad") or "").lower()
        vce = primera.get("monto_energia")
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
        if excepcion.get("tarifa"):
            tarifa, motivo = str(excepcion["tarifa"]), None
        regla = vigencia.tarifas.get(tarifa) if tarifa else None
        if excepcion.get("valor_fijo") is not None:
            regla = ReglaCelsia(
                "fija", None, d(excepcion["valor_fijo"]), d(excepcion["valor_fijo"])
            )
            tarifa = tarifa or "EXCEPCION"
        elif excepcion.get("porcentaje") is not None:
            regla = ReglaCelsia("porcentaje", d(excepcion["porcentaje"]), None, None)
            tarifa = tarifa or "EXCEPCION"
        if regla is None:
            salida.append(
                fila("REQUIERE_REVISION", tarifa=tarifa, motivo=motivo or "ESTRATO_SIN_REGLA")
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
                salida.append(fila("NO_VALIDABLE", tarifa=tarifa, motivo="SIN_VCE"))
                continue
            if regla.porcentaje is None or (regla.tipo != "porcentaje" and tope is None):
                salida.append(
                    fila(
                        "REQUIERE_REVISION", tarifa=tarifa, motivo="REGLAS_CONTRADICTORIAS_EN_CARTA"
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
