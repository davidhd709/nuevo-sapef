"""Reglas puras del tablero (Fase 5)."""

from app.modulos.tablero import dominio
from app.modulos.tablero.dominio import FilaDimension


def test_serie_mensual_completa_los_doce_meses_y_acumula() -> None:
    serie = dominio.serie_mensual([(2026, 1, 3), (2026, 3, 2), (2025, 3, 9), (2026, 3, 1)], 2026)
    assert [m["cantidad"] for m in serie[:4]] == [3, 0, 3, 0]
    assert serie[-1] == {"mes": 12, "cantidad": 0, "acumulado": 6}


def test_consolidado_suma_tipos_y_separa_barrios_por_sede() -> None:
    filas = {
        "Montelíbano": [
            FilaDimension("tecnologia", "LED", "Led", None, 10),
            FilaDimension("barrio", "1", "El Centro", "Urbana", 4),
        ],
        "Alcalá": [
            FilaDimension("tecnologia", "LED", "Led", None, 5),
            FilaDimension("barrio", "9", "El Centro", "Zona A", 2),
        ],
    }
    salida = dominio.consolidar_dimensiones(filas)
    assert salida["tecnologia"] == [{"etiqueta": "Led", "grupo": None, "cantidad": 15}]
    assert {b["grupo"] for b in salida["barrio"]} == {"Montelíbano · Urbana", "Alcalá · Zona A"}
    # Una sola sede conserva el grupo tal cual.
    una = dominio.consolidar_dimensiones({"Montelíbano": filas["Montelíbano"]})
    assert una["barrio"][0]["grupo"] == "Urbana"


def test_suma_de_operacion_pondera_el_tiempo_de_atencion() -> None:
    total = dominio.sumar_operacion(
        [
            {"pqrs_abiertas": 2, "pqrs_atendidas_anio": 1, "tiempo_promedio_atencion_horas": 10},
            {"pqrs_abiertas": 3, "pqrs_atendidas_anio": 3, "tiempo_promedio_atencion_horas": 2},
        ]
    )
    assert total["pqrs_abiertas"] == 5
    assert total["tiempo_promedio_atencion_horas"] == 4.0  # (10·1 + 2·3) / 4, no (10+2)/2
    assert dominio.sumar_operacion([{}])["tiempo_promedio_atencion_horas"] is None


def test_variacion_y_estado_comercial() -> None:
    assert dominio.variacion(110, 100) == 10.0
    assert dominio.variacion(5, 0) is None and dominio.variacion(None, 3) is None
    assert dominio.variacion(-50, -100) == 50.0
    assert dominio.estado_comercial(False, []) == dominio.SIN_CORTES
    assert dominio.estado_comercial(True, []) == dominio.PENDIENTE
    assert dominio.estado_comercial(True, [{"x": 1}]) == dominio.CON_DATOS
