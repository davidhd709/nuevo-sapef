"""Reglas llevadas desde OPainn para la paridad de la Fase 4 (sin datos privados)."""

from decimal import Decimal
from pathlib import Path

from app.modulos.comercial.dominio import afinia, celsia
from app.modulos.comercial.repositorio import almacen


def test_clasificacion_td_celsia_une_estrato_viejo_y_nuevo() -> None:
    assert celsia.clasificacion_td({"segmento": "Residencial", "estrato": "Estrato 2"}) == (
        "Residencial · Estrato 2"
    )
    assert celsia.clasificacion_td({"segmento": "Residencial", "estrato": "2"}) == (
        "Residencial · Estrato 2"
    )
    assert celsia.clasificacion_td({"segmento": "Residencial", "estrato": "N/A"}) == "Residencial"
    assert celsia.clasificacion_td({"segmento": "", "clase": "Oficial"}) == "Oficial"
    assert celsia.clasificacion_td({}) == "Sin clasificación"


def test_recaudo_celsia_corriente_cartera_y_sin_vencimiento() -> None:
    assert celsia.tipo_recaudo_td({"fecha_vencimiento": "2026-05-20"}, "202606") == "CORRIENTE"
    assert celsia.tipo_recaudo_td({"fecha_vencimiento": "2026-04-30"}, "202606") == "CARTERA"
    assert celsia.tipo_recaudo_td({}, "202606") == "NO_CLASIFICADO"


def test_movimiento_celsia_respeta_el_ciclo_de_cada_cuenta() -> None:
    cortes = {
        "202604": [("U1", "MENSUAL", "Urbano"), ("R1", "", "Rural"), ("V1", "MENSUAL", "Urbano")],
        "202605": [("U1", "MENSUAL", "Urbano")],
        "202606": [("R1", "", "Rural"), ("V1", "MENSUAL", "Urbano"), ("N1", "MENSUAL", "Urbano")],
    }
    mov = celsia.clasificar_movimientos(cortes, "202606")
    # U1 (mensual) no está en junio: baja. R1 (rural, bimestral par) vuelve en su mes: normal.
    # V1 faltó en mayo y vuelve: reintegrado. N1 aparece por primera vez: nuevo.
    assert mov.dejados == {"U1"}
    assert mov.reintegrados == {"V1"}
    assert mov.nuevos == {"N1"}
    assert mov.evaluables["R1"] == "202604"
    # Mayo no le toca al rural: no es ausencia ni se evalúa.
    assert "R1" not in celsia.clasificar_movimientos(cortes, "202605").evaluables
    # Primer corte: nada contra qué medir.
    assert not celsia.clasificar_movimientos(cortes, "202604").evaluables


def test_td_afinia_movimiento_por_nic_y_razones_sin_redondear() -> None:
    fila = {
        "periodo": "202606",
        "concepto": "CI400",
        "importe_trans": 1000,
        "consumo_kwh": 3,
        "tarifa": "AP_Residenciales_Estrato_1",
    }
    facturacion = [
        {**fila, "nic": "1"},
        {**fila, "nic": "2"},
        {**fila, "nic": "3", "tarifa": "AP_Residenciales_Estrato_2"},
    ]
    td = afinia.tabla_dinamica(
        "202606",
        facturacion=facturacion,
        recaudo=[],
        catastro=[],
        # NIC 3 cambió de tarifa: no es baja ni alta. NIC 9 dejó de facturarse.
        pares_anteriores={
            ("1", "AP_Residenciales_Estrato_1"),
            ("3", "AP_Residenciales_Estrato_1"),
            ("9", "AP_Residenciales_Estrato_1"),
        },
        pares_historicos=set(),
    )
    e1 = td["filas"][6]
    assert e1["estrato_uso"] == "AP_Residenciales_Estrato_1"
    assert e1["estrato_uso_catastro"] == "AP Residenciales Estrato 1"
    assert e1["usuarios_dejados_facturar"] == 1  # solo el 9
    assert e1["nuevos_usuarios"] == 1  # el 2
    assert td["filas"][7]["nuevos_usuarios"] == 0  # el 3 ya estaba
    assert td["filas"][6]["pct_n_factura"] == Decimal("0.6666666667")
    # Sin corte comparable el movimiento va en cero (como OPainn), no «todos nuevos».
    primero = afinia.tabla_dinamica("202606", facturacion=facturacion, recaudo=[], catastro=[])
    assert primero["total"]["nuevos_usuarios"] == 0


def test_paquete_de_opainn_sin_manifiesto_o_con_el_suyo_se_infiere(almacen_temporal: Path) -> None:
    tmp_path = almacen_temporal
    import pyarrow as pa
    import pyarrow.parquet as pq

    esquemas = {"comercial": {"cliente_id": "texto"}}
    pq.write_table(pa.table({"cliente_id": ["A"]}), tmp_path / "comercial.parquet")
    inferido = almacen.manifiesto_efectivo(tmp_path, esquemas)
    assert inferido is not None and inferido["inferido"] is True
    assert almacen.aviso_manifiesto(tmp_path) == almacen.SIN_MANIFIESTO
    # Manifiesto propio de OPainn: huellas de los archivos fuente, no de los Parquet.
    (tmp_path / "manifest.json").write_text(
        '{"proveedor": "VATIA", "periodo": "202606", "huellas_sha256": {"x.xlsx": "ab"}}',
        encoding="utf-8",
    )
    inferido = almacen.manifiesto_efectivo(tmp_path, esquemas)
    assert inferido is not None and inferido["periodo"] == "202606"
    assert inferido["origen"]["proveedor"] == "VATIA"
    assert almacen.aviso_manifiesto(tmp_path) == almacen.MANIFIESTO_OPAINN
    familias, errores = almacen.leer_paquete(tmp_path, esquemas)
    assert errores == [] and familias["comercial"] == [{"cliente_id": "A"}]
