"""Análisis de Vatia (E.10): resumen del corte, tabla dinámica y cartera por edades."""

import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from app.modulos.comercial.dominio.analisis import UsuarioCorte
from app.modulos.comercial.dominio.comun import CERO, d, div, div_precisa, q2, q4, suma


def resumen(comercial: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Todos los clientes del archivo son los facturados del corte. Pagó = recaudo del mes o
    recuperación de cartera distinta de cero. Con notas, un corte negativo no se interpreta:
    eficiencia null si la facturación es cero o negativa."""
    facturacion = q4(suma(f.get("facturado_total") for f in comercial))
    recaudo = q4(suma(f.get("recaudo_mes") for f in comercial))
    pagaron = {
        f["cliente_id"]
        for f in comercial
        if d(f.get("recaudo_mes")) != 0 or d(f.get("recuperacion_cartera")) != 0
    }
    clientes = {f["cliente_id"] for f in comercial}
    return {
        "filas": len(comercial),
        "clientes": len(clientes),
        "n_facturados": len(clientes),
        "clientes_pagaron": len(pagaron),
        "n_pagaron": len(pagaron),
        "facturas": len({f.get("factura") for f in comercial if f.get("factura")}),
        "facturacion": facturacion,
        "recaudo": recaudo,
        "recaudo_total": recaudo,
        "recuperacion_cartera": q4(suma(f.get("recuperacion_cartera") for f in comercial)),
        "saldo_cartera": q4(suma(f.get("saldo_cartera") for f in comercial)),
        "cartera": q4(suma(f.get("saldo_cartera") for f in comercial)),
        "consumo_activa": q4(suma(f.get("consumo_activa_kw") for f in comercial)),
        "eficiencia": div_precisa(recaudo, facturacion) if facturacion > 0 else None,
        "eficiencia_usuarios": div(len(pagaron), len(clientes), nulo=True),
    }


def tabla_dinamica(comercial: Sequence[dict[str, Any]]) -> dict[str, Any]:
    grupos: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for f in comercial:
        clave = tuple(
            (f.get(c) or "Sin dato") for c in ("mercado", "submercado", "estrato", "nivel_tension")
        )
        grupos[clave].append(f)

    def fila(filas: Sequence[dict[str, Any]]) -> dict[str, Any]:
        facturacion = q4(suma(f.get("facturado_total") for f in filas))
        recaudo = q4(suma(f.get("recaudo_mes") for f in filas))
        consumo = q4(suma(f.get("consumo_activa_kw") for f in filas))
        facturas = len({f.get("factura") for f in filas if f.get("factura")}) or len(filas)
        return {
            "usuarios_facturados": len({f["cliente_id"] for f in filas}),
            "usuarios_con_recaudo": len(
                {f["cliente_id"] for f in filas if d(f.get("recaudo_mes")) != 0}
            ),
            "usuarios_con_cartera": len(
                {f["cliente_id"] for f in filas if d(f.get("saldo_cartera")) > 0}
            ),
            "facturas": facturas,
            "facturacion": facturacion,
            "recaudo": recaudo,
            "recuperacion_cartera": q4(suma(f.get("recuperacion_cartera") for f in filas)),
            "saldo_cartera": q4(suma(f.get("saldo_cartera") for f in filas)),
            "consumo_activa": consumo,
            "eficiencia": div_precisa(recaudo, facturacion) if facturacion > 0 else None,
            "promedio_consumo": div_precisa(consumo, facturas),
        }

    filas = [
        {"mercado": k[0], "submercado": k[1], "estrato": k[2], "nivel_tension": k[3], **fila(v)}
        for k, v in grupos.items()
    ]
    filas.sort(key=lambda r: (-r["saldo_cartera"], -r["facturacion"]))
    return {"filas": filas, "total": {"mercado": "Total", **fila(comercial)}}


def _orden_edad(etiqueta: str) -> tuple[int, int]:
    if etiqueta.strip().lower().startswith("al d"):
        return (0, 0)
    numero = re.search(r"\d+", etiqueta)
    return (1, int(numero.group())) if numero else (2, 0)


def cartera_por_edades(comercial: Sequence[dict[str, Any]]) -> dict[str, Any]:
    grupos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in comercial:
        grupos[f.get("edad_cartera") or "Sin dato"].append(f)
    total = suma(f.get("saldo_cartera") for f in comercial)
    bandas = [
        {
            "edad": edad,
            "usuarios": len({f["cliente_id"] for f in filas}),
            "valor": q2(suma(f.get("saldo_cartera") for f in filas)),
            "pct": div(suma(f.get("saldo_cartera") for f in filas), total),
        }
        for edad, filas in sorted(grupos.items(), key=lambda kv: _orden_edad(kv[0]))
    ]
    return {
        "total_cartera": q2(total),
        "usuarios": len({f["cliente_id"] for f in comercial}),
        "bandas": bandas,
    }


def usuarios_corte(familias: dict[str, Sequence[dict[str, Any]]]) -> dict[str, UsuarioCorte]:
    usuarios: dict[str, UsuarioCorte] = {}
    for f in familias.get("comercial", ()):
        clave = str(f["cliente_id"])
        u = usuarios.setdefault(clave, UsuarioCorte(identificador=clave, facturado_presente=True))
        u.facturado += d(f.get("facturado_total"))
        u.recaudo += d(f.get("recaudo_mes"))
        u.recaudo_corriente += d(f.get("recaudo_mes"))
        u.recuperacion_cartera += d(f.get("recuperacion_cartera"))
        u.recaudo_cartera += d(f.get("recuperacion_cartera"))
        u.cartera += d(f.get("saldo_cartera"))
        if f.get("consumo_activa_kw") is not None:
            u.consumo = (u.consumo or CERO) + d(f["consumo_activa_kw"])
        u.pago = u.pago or d(f.get("recaudo_mes")) != 0 or d(f.get("recuperacion_cartera")) != 0
        u.segmento = u.segmento or f.get("submercado")
        u.tarifa = u.tarifa or f.get("mercado")
        u.estrato = u.estrato or f.get("estrato")
        u.nombre = u.nombre or f.get("cliente_nombre")
        u.direccion = u.direccion or f.get("direccion_facturacion")
        u.extra.setdefault("edad_cartera", f.get("edad_cartera"))
    return usuarios


def redondear(valor: Any) -> Any:
    return q2(valor) if valor is not None else None
