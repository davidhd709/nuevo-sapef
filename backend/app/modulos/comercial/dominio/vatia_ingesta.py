"""Adaptador de Vatia (Alcalá): libros Excel consolidados en una tabla comercial (E.10).

Sin control tarifario, sin estrato (usa submercado) y sin barrio. Incluye notas: un corte puede
quedar negativo. Las monetarias obligatorias rechazan la carga si traen texto («N/A»); un cero
válido es cero.
"""

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from app.modulos.comercial.dominio import archivos as lectura
from app.modulos.comercial.dominio.comun import (
    ErrorDominioComercial,
    como_fecha,
    dec,
    identificador,
    normalizar_encabezado,
    periodo_de,
    q4,
    texto,
)
from app.modulos.comercial.dominio.modelo import ResultadoAdaptador

VERSION = "vatia-1.0"
EXTENSIONES = (".xlsx", ".xlsm")
FAMILIAS = ("comercial",)
OBLIGATORIAS_PUBLICAR = ("comercial",)

ALIAS: dict[str, str] = {
    "ciclo": "ciclo",
    "numero_de_factura": "factura",
    "cliente_nit": "cliente_nit",
    "cliente_id": "cliente_id",
    "cliente_nombre": "cliente_nombre",
    "dir_facturacion": "direccion_facturacion",
    "direccion_de_correspondencia": "direccion_correspondencia",
    "nivel_de_tension": "nivel_tension",
    "operador_de_red": "operador_red",
    "mercado": "mercado",
    "submercado": "submercado",
    "estrato": "estrato",
    "depto_facturacion": "departamento",
    "muni_facturacion": "municipio",
    "fecha_elab_factura": "fecha_factura",
    "fecha_limite1": "fecha_limite1",
    "fecha_limite2": "fecha_limite2",
    "concepto": "concepto",
    "facturado_cartera_ciclo": "facturado_cartera_ciclo",
    "vr_facturado_concepto": "valor_facturado_concepto",
    "tipo_nota": "tipo_nota",
    "vlr_nota": "valor_nota",
    "facturado_total_incluye_notas": "facturado_total",
    "recaudo_mes": "recaudo_mes",
    "recuperacion_cartera": "recuperacion_cartera",
    "fecha_pago": "fecha_pago",
    "saldo_en_cartera": "saldo_cartera",
    "edad_cierre_mes_ciclo": "edad_cartera",
    "consumo_activa_kw": "consumo_activa_kw",
    "consumo_reactiva_kw": "consumo_reactiva_kw",
    "valor_consumo_sin_contribucion": "valor_consumo_sin_contribucion",
    "fecha_iniper": "fecha_inicio_periodo",
    "fecha_finper": "fecha_fin_periodo",
}
OBLIGATORIAS = (
    "ciclo",
    "cliente_id",
    "fecha_factura",
    "facturado_total",
    "recaudo_mes",
    "saldo_cartera",
)
MONETARIAS_OBLIGATORIAS = ("facturado_total", "recaudo_mes", "saldo_cartera")
DECIMALES = frozenset(
    {
        "facturado_cartera_ciclo",
        "valor_facturado_concepto",
        "valor_nota",
        "facturado_total",
        "recaudo_mes",
        "recuperacion_cartera",
        "saldo_cartera",
        "consumo_activa_kw",
        "consumo_reactiva_kw",
        "valor_consumo_sin_contribucion",
    }
)
FECHAS = frozenset(
    {
        "fecha_factura",
        "fecha_limite1",
        "fecha_limite2",
        "fecha_pago",
        "fecha_inicio_periodo",
        "fecha_fin_periodo",
    }
)
COLUMNAS = ("periodo", *dict.fromkeys(ALIAS.values()))


def esquema(familia: str) -> dict[str, str]:
    columnas = {
        c: "fecha" if c in FECHAS else "decimal" if c in DECIMALES else "texto" for c in COLUMNAS
    }
    columnas.update({"archivo": "texto", "hoja": "texto", "fila_origen": "entero"})
    return columnas


def _periodo_fila(registro: dict[str, Any], defecto: str) -> str:
    ciclo = (registro.get("ciclo") or "").strip()
    if len(ciclo) == 6 and ciclo.isdigit():
        return ciclo
    fecha = registro.get("fecha_factura")
    return periodo_de(fecha) if fecha else defecto


def _normalizar(
    filas: list[list[Any]], *, periodo: str, nombre: str, hoja: str, errores: list[str]
) -> list[dict[str, Any]]:
    encabezados = [ALIAS.get(normalizar_encabezado(c)) for c in filas[0]]
    faltan = [c for c in OBLIGATORIAS if c not in encabezados]
    if faltan:
        raise ErrorDominioComercial(
            422, f"«{nombre}», hoja «{hoja}»: faltan columnas obligatorias: {', '.join(faltan)}."
        )
    invalidos: dict[str, int] = defaultdict(int)
    salida: list[dict[str, Any]] = []
    for i, fila in enumerate(filas[1:], start=2):
        crudo = {c: v for c, v in zip(encabezados, fila, strict=False) if c is not None}
        if identificador(crudo.get("cliente_id")) is None:
            continue
        registro: dict[str, Any] = {}
        valida = True
        for columna in COLUMNAS:
            if columna == "periodo":
                continue
            valor = crudo.get(columna)
            try:
                if columna in DECIMALES:
                    numero = dec(valor)
                    if numero is None and columna in MONETARIAS_OBLIGATORIAS:
                        numero = None
                    registro[columna] = q4(numero) if numero is not None else None
                elif columna in FECHAS:
                    registro[columna] = como_fecha(valor)
                elif columna in ("cliente_id", "ciclo"):
                    registro[columna] = identificador(valor)
                else:
                    registro[columna] = texto(valor)
            except ValueError:
                if columna in MONETARIAS_OBLIGATORIAS:
                    invalidos[columna] += 1
                    valida = False
                else:
                    registro[columna] = None
        if not valida:
            continue
        registro["periodo"] = _periodo_fila(registro, periodo)
        registro.update({"archivo": nombre, "hoja": hoja, "fila_origen": i})
        salida.append(registro)
    for columna, cantidad in invalidos.items():
        errores.append(
            f"«{nombre}»: la columna {columna} tiene {cantidad} valor(es) no numérico(s) "
            "(p. ej., «N/A»); corrija el archivo."
        )
    return salida


def procesar(
    archivos: list[lectura.ArchivoEntrada],
    periodo: str,
    *,
    corte_anterior: Callable[[str], list[dict[str, Any]]] | None = None,
) -> ResultadoAdaptador:
    resultado = ResultadoAdaptador(familias={"comercial": []})
    for archivo in archivos:
        try:
            reconocida = False
            for hoja, filas in lectura.leer_libro(archivo.datos).items():
                if not filas:
                    continue
                encabezados = {normalizar_encabezado(c) for c in filas[0]}
                if "cliente_id" not in encabezados:
                    continue
                errores: list[str] = []
                registros = _normalizar(
                    filas, periodo=periodo, nombre=archivo.nombre, hoja=hoja, errores=errores
                )
                resultado.errores.extend(errores)
                otros = sorted({r["periodo"] for r in registros} - {periodo})
                if otros:
                    raise ErrorDominioComercial(
                        422,
                        f"«{archivo.nombre}»: trae filas de {', '.join(otros)}; el corte es "
                        f"{periodo}.",
                    )
                resultado.familias["comercial"].extend(registros)
                resultado.presentes.add("comercial")
                resultado.archivos.append(
                    {
                        "nombre": archivo.nombre,
                        "hoja": hoja,
                        "familia": "comercial",
                        "filas": len(registros),
                    }
                )
                reconocida = True
            if not reconocida:
                raise ErrorDominioComercial(
                    422, f"«{archivo.nombre}»: ninguna hoja tiene la columna CLIENTE ID."
                )
        except ErrorDominioComercial as exc:
            resultado.errores.append(exc.detail)
    resultado.completo = "comercial" in resultado.presentes
    resultado.publicable = resultado.completo
    if not resultado.publicable:
        resultado.motivo_no_publicable = "Vatia exige la tabla comercial."
    return resultado
