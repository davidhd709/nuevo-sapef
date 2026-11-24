"""Adaptador de Celsia (Alcalá): libros Excel con hojas reconocidas por sus columnas (E.9).

Familias: facturacion y recaudo (obligatorias para publicar) y cartera (opcional). La hoja «C2M»
se excluye. Las filas sin cuenta (pies de totales) se descartan hasta un 10 % de la hoja.
"""

import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from app.modulos.comercial.dominio import archivos as lectura
from app.modulos.comercial.dominio.comun import (
    MESES_ABREVIADOS,
    MESES_ES,
    ErrorDominioComercial,
    como_fecha,
    dec,
    desplazar,
    identificador,
    meses_entre,
    normalizar_encabezado,
    periodo_de,
    primer_dia,
    q4,
    sin_tildes,
    texto,
)
from app.modulos.comercial.dominio.modelo import ResultadoAdaptador

VERSION = "celsia-1.0"
EXTENSIONES = (".xlsx", ".xlsm")
FAMILIAS = ("facturacion", "recaudo", "cartera")
OBLIGATORIAS_PUBLICAR = ("facturacion", "recaudo")
MAX_PIE_PCT = 0.10
MAX_PIE_FILAS = 20

FIRMAS: dict[str, frozenset[str]] = {
    "facturacion": frozenset(
        {"valor_del_impuesto_facturado", "valor_impuesto_del_alumbrado_publico", "monto_ap"}
    ),
    "recaudo": frozenset({"valor_del_impuesto_recaudado", "valor_recaudado", "importe_cta"}),
    "cartera": frozenset({"total_cartera", "cartera_total"}),
}

ALIAS: dict[str, tuple[str, ...]] = {
    "cuenta": ("id_cuenta", "id_de_cuenta", "id_cliente", "cuenta"),
    "factura": ("id_factura", "numero_de_factura", "numero_factura"),
    "nombre": ("nombre", "nombre_cliente", "entity_name_upr"),
    "direccion": ("direccion", "direccion_predio"),
    "clase": ("clase_cliente", "clase_de_cliente", "desc_clase", "tipo_cliente"),
    "tarifa": ("tarifa", "tarifa_ap", "tarifa_cliente"),
    "estrato": ("estrato", "estrato_socioeconomico"),
    "sector": ("sector",),
    "municipio": ("municipio", "municipio2"),
    "barrio": ("barrio_vereda_corregimiento",),
    "mercado": ("mercado", "mercado_1"),
    "periodicidad": ("periodicidad", "ciclo_facturacion"),
    "concepto": (
        "descripcion",
        "descripcion_cobro_impuesto_del_alumbrado_publico",
        "descripcion_as",
        "sa_type_cd",
    ),
    "fecha_factura": ("fecha_factura", "fecha_generacion", "fecha_facturacion"),
    "fecha_vencimiento": ("fecha_vcto", "fecha_vencimiento"),
    "fecha_pago": ("fecha_de_pago", "fecha_pago", "fecha_contable"),
    "fecha_aplicacion": ("fecha_aplicacion",),
    "valor_facturado": (
        "valor_del_impuesto_facturado",
        "valor_impuesto_del_alumbrado_publico",
        "monto_ap",
    ),
    "valor_recaudado": ("valor_del_impuesto_recaudado", "valor_recaudado", "importe_cta"),
    "consumo_kwh": ("consumo_de_energia_del_periodo_facturado_al_usuario_kwh", "consumo_kwh"),
    "monto_energia": (
        "valor_del_consumo_de_energia_antes_de_subsidios_o_contribuciones_pesos",
        "monto_kwh",
    ),
    "grupo_cartera": ("grupo_cartera",),
    "cartera_financiada": ("financiada", "cartera_financiada"),
    "cartera_corriente": ("corriente", "cartera_corriente"),
    "cartera_30": ("mora_30", "cartera_30", "cartera_30_dias"),
    "cartera_60": ("mora_60", "cartera_60", "cartera_60_dias"),
    "cartera_90": ("mora_90", "cartera_90", "cartera_90_dias"),
    "cartera_180": ("mora_180", "cartera_180", "cartera_180_dias"),
    "cartera_360": ("mora_360", "cartera_360", "cartera_360_dias"),
    "cartera_mayor_360": ("mayor_a_360", "cartera_mayor_360", "cartera_mayor_a_360_dias"),
    "valor_congelado": ("valor_congelado",),
    "cartera_total": ("total_cartera", "cartera_total"),
}
_DESDE_ENCABEZADO = {alias: columna for columna, lista in ALIAS.items() for alias in lista}

EDADES = (
    "cartera_financiada",
    "cartera_corriente",
    "cartera_30",
    "cartera_60",
    "cartera_90",
    "cartera_180",
    "cartera_360",
    "cartera_mayor_360",
    "valor_congelado",
)
COMUNES = (
    "periodo",
    "cuenta",
    "nombre",
    "direccion",
    "clase",
    "tarifa",
    "segmento",
    "estrato",
    "sector",
    "municipio",
)
COLUMNAS: dict[str, tuple[str, ...]] = {
    "facturacion": (
        *COMUNES[:2],
        "factura",
        "fecha_factura",
        *COMUNES[2:],
        "barrio",
        "periodicidad",
        "mercado",
        "concepto",
        "tipo_concepto",
        "valor_facturado",
        "consumo_kwh",
        "monto_energia",
    ),
    "recaudo": (
        *COMUNES[:2],
        "factura",
        "fecha_vencimiento",
        "fecha_pago",
        "fecha_aplicacion",
        *COMUNES[2:],
        "mercado",
        "concepto",
        "tipo_concepto",
        "tipo_recaudo",
        "valor_recaudado",
    ),
    "cartera": (
        *COMUNES,
        "mercado",
        "concepto",
        "tipo_concepto",
        "grupo_cartera",
        *EDADES[:8],
        "valor_congelado",
        "cartera_total",
    ),
}
FECHAS = frozenset({"fecha_factura", "fecha_vencimiento", "fecha_pago", "fecha_aplicacion"})
DECIMALES = frozenset(
    {"valor_facturado", "valor_recaudado", "consumo_kwh", "monto_energia", "cartera_total", *EDADES}
)


def esquema(familia: str) -> dict[str, str]:
    columnas = {
        c: "fecha" if c in FECHAS else "decimal" if c in DECIMALES else "texto"
        for c in COLUMNAS[familia]
    }
    columnas.update({"archivo": "texto", "hoja": "texto", "fila_origen": "entero"})
    return columnas


# --- Reglas de clasificación ------------------------------------------------------------------


def tipo_concepto(concepto: str | None) -> str:
    """E.9, con la descripción larga de Celsia («Impuesto Alumbrado Público»)."""
    c = normalizar_encabezado(concepto)
    if not c:
        return "agregado_sin_detalle"
    if "interes" in c or c.startswith("int_finan"):
        return "interes"
    if "cuota" in c or "financiacion" in c or c == "finatap":
        return "financiacion"
    if c.startswith("a_te") or "ajuste" in c or c.startswith("desc_"):
        return "ajuste"
    if (
        "impuesto_a_publico" in c
        or "tasa_de_alumbrado" in c
        or c == "ap"
        or ("impuesto" in c and "alumbrado" in c)
    ):
        return "impuesto"
    return "otro"


def segmento(clase: str | None) -> str | None:
    """Texto de la clase sin el número inicial, en formato título («2 Comercial» → Comercial)."""
    if not clase:
        return None
    limpio = re.sub(r"^\s*\d+\s*[-.]?\s*", "", clase).strip()
    return limpio.title() if limpio else None


def estrato(valor: Any, seg: str | None) -> str | None:
    """Solo el número («Estrato 2» → 2); si no hay dígito, el segmento (§11.4)."""
    crudo = texto(valor)
    if crudo:
        digito = re.search(r"\d+", crudo)
        if digito:
            return str(int(digito.group()))
    return seg


def tipo_recaudo(fecha_vencimiento: Any, periodo: str) -> str:
    if fecha_vencimiento is None:
        return "NO_CLASIFICADO"
    return "CORRIENTE" if fecha_vencimiento >= desplazar(primer_dia(periodo), -1) else "CARTERA"


# --- Periodo del nombre -----------------------------------------------------------------------


def periodo_del_nombre(nombre: str) -> str | None:
    """Mes abreviado o completo + año de 2 o 4 dígitos (…_ABR_26, …_JULIO_2026)."""
    tallo = sin_tildes(nombre.rsplit(".", 1)[0]).upper()
    partes = re.split(r"[^A-Z0-9]+", tallo)
    for i, parte in enumerate(partes[:-1]):
        mes = MESES_ES.get(parte) or MESES_ABREVIADOS.get(parte)
        if mes is None:
            continue
        anio = partes[i + 1]
        if re.fullmatch(r"\d{4}", anio):
            return f"{anio}{mes:02d}"
        if re.fullmatch(r"\d{2}", anio):
            return f"20{anio}{mes:02d}"
    return None


# --- Normalización ----------------------------------------------------------------------------


def _clasificar_hoja(encabezados: list[str]) -> str | None:
    coincidencias = [f for f, firma in FIRMAS.items() if firma & set(encabezados)]
    if len(coincidencias) > 1:
        raise ErrorDominioComercial(
            422,
            "La hoja tiene columnas de varias familias a la vez "
            f"({', '.join(coincidencias)}); no se puede reconocer.",
        )
    return coincidencias[0] if coincidencias else None


def _convertir(columna: str, valor: Any) -> Any:
    if columna in FECHAS:
        return como_fecha(valor)
    if columna in DECIMALES:
        numero = dec(valor)
        return q4(numero) if numero is not None else None
    if columna == "cuenta":
        return identificador(valor)
    return texto(valor)


def _normalizar_hoja(
    filas: list[list[Any]],
    familia: str,
    *,
    periodo: str,
    nombre: str,
    hoja: str,
    errores: list[str],
) -> tuple[list[dict[str, Any]], int]:
    encabezados = [normalizar_encabezado(c) for c in filas[0]]
    columnas = [_DESDE_ENCABEZADO.get(e) for e in encabezados]
    if "cuenta" not in columnas:
        raise ErrorDominioComercial(422, f"«{nombre}», hoja «{hoja}»: falta la columna de cuenta.")
    salida: list[dict[str, Any]] = []
    descartadas = 0
    for i, fila in enumerate(filas[1:], start=2):
        crudo: dict[str, Any] = {}
        for columna, valor in zip(columnas, fila, strict=False):
            if columna is not None and columna not in crudo:
                crudo[columna] = valor
        if identificador(crudo.get("cuenta")) is None:
            descartadas += 1
            continue
        registro: dict[str, Any] = {"periodo": periodo}
        try:
            for columna in COLUMNAS[familia]:
                if columna in ("periodo", "segmento", "tipo_concepto", "tipo_recaudo"):
                    continue
                registro[columna] = _convertir(columna, crudo.get(columna))
        except ValueError as exc:
            errores.append(f"«{nombre}», hoja «{hoja}», fila {i}: valor inválido «{exc}».")
            continue
        registro["segmento"] = segmento(registro.get("clase"))
        registro["estrato"] = estrato(crudo.get("estrato"), registro["segmento"])
        registro["tipo_concepto"] = tipo_concepto(registro.get("concepto"))
        if familia == "recaudo":
            registro["tipo_recaudo"] = tipo_recaudo(registro.get("fecha_vencimiento"), periodo)
        registro.update({"archivo": nombre, "hoja": hoja, "fila_origen": i})
        salida.append(registro)
    total = len(filas) - 1
    if descartadas > MAX_PIE_FILAS and descartadas > MAX_PIE_PCT * total:
        raise ErrorDominioComercial(
            422,
            f"«{nombre}», hoja «{hoja}»: {descartadas} de {total} filas no tienen cuenta (más de "
            f"{MAX_PIE_FILAS} y del {MAX_PIE_PCT:.0%}); el archivo parece mal formado.",
        )
    return salida, descartadas


def _fechas_internas(registros: list[dict[str, Any]], familia: str) -> list[str]:
    campo = "fecha_factura" if familia == "facturacion" else "fecha_pago"
    return [periodo_de(r[campo]) for r in registros if r.get(campo) is not None]


def _cartera_repetida(actual: list[dict[str, Any]], anterior: list[dict[str, Any]]) -> bool:
    def huella(filas: list[dict[str, Any]]) -> Counter[tuple[Any, ...]]:
        return Counter(
            (r.get("cuenta"), *(str(r.get(c)) for c in (*EDADES, "cartera_total"))) for r in filas
        )

    return bool(actual) and bool(anterior) and huella(actual) == huella(anterior)


def procesar(
    archivos: list[lectura.ArchivoEntrada],
    periodo: str,
    *,
    corte_anterior: Callable[[str], list[dict[str, Any]]] | None = None,
) -> ResultadoAdaptador:
    resultado = ResultadoAdaptador(familias={f: [] for f in FAMILIAS})
    for archivo in archivos:
        try:
            if lectura.tiene_formulas(archivo.datos):
                resultado.advertencias.append(
                    f"«{archivo.nombre}» trae fórmulas; se tomaron los valores calculados."
                )
            periodo_nombre = periodo_del_nombre(archivo.nombre)
            if periodo_nombre is not None and periodo_nombre != periodo:
                raise ErrorDominioComercial(
                    422, f"«{archivo.nombre}» es del periodo {periodo_nombre}, no de {periodo}."
                )
            reconocidas = 0
            for hoja, filas in lectura.leer_libro(archivo.datos).items():
                if normalizar_encabezado(hoja) == "c2m":
                    resultado.advertencias.append(
                        f"«{archivo.nombre}»: la hoja «{hoja}» (C2M) se excluye."
                    )
                    continue
                if not filas:
                    continue
                encabezados = [normalizar_encabezado(c) for c in filas[0]]
                try:
                    familia = _clasificar_hoja(encabezados)
                except ErrorDominioComercial as exc:
                    raise ErrorDominioComercial(
                        422, f"«{archivo.nombre}», hoja «{hoja}»: {exc.detail}"
                    ) from exc
                if familia is None:
                    resultado.advertencias.append(
                        f"«{archivo.nombre}»: la hoja «{hoja}» no se reconoce y se omite."
                    )
                    continue
                errores: list[str] = []
                registros, descartadas = _normalizar_hoja(
                    filas,
                    familia,
                    periodo=periodo,
                    nombre=archivo.nombre,
                    hoja=hoja,
                    errores=errores,
                )
                resultado.errores.extend(errores)
                if descartadas:
                    resultado.advertencias.append(
                        f"«{archivo.nombre}», hoja «{hoja}»: {descartadas} fila(s) sin cuenta "
                        "(pies de totales) descartadas."
                    )
                internos = _fechas_internas(registros, familia)
                if internos:
                    dominante = Counter(internos).most_common(1)[0][0]
                    if abs(meses_entre(periodo, dominante)) > 1:
                        raise ErrorDominioComercial(
                            422,
                            f"«{archivo.nombre}»: las fechas internas son de {dominante} y el "
                            f"corte es {periodo} (más de un mes de diferencia); el archivo "
                            "parece mal nombrado.",
                        )
                resultado.familias[familia].extend(registros)
                resultado.presentes.add(familia)
                reconocidas += 1
                resultado.archivos.append(
                    {
                        "nombre": archivo.nombre,
                        "hoja": hoja,
                        "familia": familia,
                        "filas": len(registros),
                    }
                )
            if reconocidas == 0:
                raise ErrorDominioComercial(
                    422,
                    f"«{archivo.nombre}»: ninguna hoja se reconoce como facturación, "
                    "recaudo o cartera.",
                )
        except ErrorDominioComercial as exc:
            resultado.errores.append(exc.detail)

    if corte_anterior is not None and resultado.familias["cartera"]:
        anterior = corte_anterior("cartera")
        if _cartera_repetida(resultado.familias["cartera"], anterior):
            resultado.advertencias.append(
                "Cartera repetida: es igual a la del corte anterior (saldos e importes "
                "repetidos fila por fila); se conserva hasta que el operador lo confirme."
            )
    faltan = [f for f in FAMILIAS if f not in resultado.presentes]
    resultado.completo = not faltan
    resultado.publicable = all(f in resultado.presentes for f in OBLIGATORIAS_PUBLICAR)
    if not resultado.publicable:
        resultado.motivo_no_publicable = (
            "Celsia exige facturación y recaudo para publicar el corte."
        )
    elif faltan:
        resultado.advertencias.append(f"Corte incompleto: falta {', '.join(faltan)}.")
    if periodo < "202605" and any(
        r["tipo_concepto"] == "agregado_sin_detalle" for r in resultado.familias["facturacion"]
    ):
        resultado.advertencias.append(
            "Corte anterior a mayo de 2026 sin desglose del concepto: no se evalúan "
            "irregularidades."
        )
    return resultado
