"""Reglas puras de la Fase 2: inventario (EP-06), atención (EP-04) y trabajos (EP-05)."""

import io
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook

from app.modulos.atencion import dominio as atencion
from app.modulos.inventario import dominio as inventario
from app.modulos.trabajos import dominio as trabajos


def _xlsx(filas: list[list[object]]) -> bytes:
    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    for fila in filas:
        hoja.append(fila)
    buf = io.BytesIO()
    libro.save(buf)
    return buf.getvalue()


# === Inventario =================================================================================


@pytest.mark.parametrize(
    ("tipo", "cantidad", "delta"),
    [("entrada", "5", "5"), ("salida", "5", "-5"), ("ajuste", "-2", "-2"), ("ajuste", "3", "3")],
)
def test_delta_por_tipo(tipo: str, cantidad: str, delta: str) -> None:
    assert inventario.calcular_delta(tipo, Decimal(cantidad)) == Decimal(delta)


@pytest.mark.parametrize(
    ("tipo", "cantidad"), [("entrada", "0"), ("salida", "-1"), ("ajuste", "0")]
)
def test_delta_invalido(tipo: str, cantidad: str) -> None:
    with pytest.raises(inventario.ErrorDominioInventario) as exc:
        inventario.calcular_delta(tipo, Decimal(cantidad))
    assert exc.value.status_code == 422


def test_existencias_nunca_negativas_rn017() -> None:
    assert inventario.aplicar_delta(Decimal(5), Decimal(-5), "M1") == 0
    with pytest.raises(inventario.ErrorDominioInventario) as exc:
        inventario.aplicar_delta(Decimal(5), Decimal("-5.001"), "M1")
    assert exc.value.status_code == 409


def test_bajo_minimo() -> None:
    assert inventario.esta_bajo_minimo(Decimal(4), Decimal(10))
    assert not inventario.esta_bajo_minimo(Decimal(10), Decimal(10))


@pytest.mark.parametrize(
    ("actual", "destino"),
    [("126", "124"), ("124", "121"), ("121", "124"), ("124", "124")],
)
def test_transicion_bodega_invalida(actual: str, destino: str) -> None:
    with pytest.raises(inventario.ErrorDominioInventario) as exc:
        inventario.validar_transicion_bodega(actual, destino)
    assert exc.value.status_code == 422


def test_transicion_bodega_valida() -> None:
    inventario.validar_transicion_bodega("124", "123")
    inventario.validar_transicion_bodega("112", "126")


def test_leer_cargue_bodega() -> None:
    contenido = _xlsx(
        [
            ["luminaria_codigo", "estado_codigo", "observacion"],
            ["L-1", 125, "a garantía"],
            [None, None, None],
            ["L-2", None, None],
        ]
    )
    filas, errores = inventario.leer_cargue_bodega(contenido)
    assert [(f.fila, f.luminaria_codigo, f.estado_codigo) for f in filas] == [(2, "L-1", "125")]
    assert errores == [{"fila": 4, "error": "luminaria_codigo y estado_codigo son obligatorios"}]
    with pytest.raises(inventario.ErrorDominioInventario):
        inventario.leer_cargue_bodega(_xlsx([["codigo", "estado"]]))
    with pytest.raises(inventario.ErrorDominioInventario):
        inventario.leer_cargue_bodega(b"no es excel")


# === Atención ===================================================================================


@pytest.mark.parametrize(
    ("dias", "color"), [(0, "verde"), (3, "verde"), (4, "amarillo"), (7, "amarillo"), (8, "rojo")]
)
def test_semaforo_rn015(dias: int, color: str) -> None:
    assert atencion.color_semaforo(dias, 3, 7) == color


def test_umbrales_y_dias() -> None:
    assert atencion.umbrales({"verde_max_dias": 4, "amarillo_max_dias": 8}) == (4, 8)
    assert atencion.umbrales(None) == (3, 7)
    assert atencion.umbrales({"otro": 1}) == (3, 7)
    assert atencion.dias_abierta(date(2026, 11, 1), date(2026, 11, 23)) == 22
    assert atencion.dias_abierta(date(2026, 11, 24), date(2026, 11, 23)) == 0


@pytest.mark.parametrize("estado", ["303", "304"])
def test_pqrs_cerrada_no_se_modifica(estado: str) -> None:
    with pytest.raises(atencion.ErrorDominioAtencion) as exc:
        atencion.validar_abierta(estado)
    assert exc.value.status_code == 409


def test_quitar_luminaria() -> None:
    atencion.validar_quitar_luminaria(2, False)
    for total, reparada in ((1, False), (3, True)):
        with pytest.raises(atencion.ErrorDominioAtencion) as exc:
            atencion.validar_quitar_luminaria(total, reparada)
        assert exc.value.status_code == 409


def test_luminaria_reportable() -> None:
    for estado in ("121", "122", "110"):
        atencion.validar_luminaria_reportable("L", estado)
    with pytest.raises(atencion.ErrorDominioAtencion) as exc:
        atencion.validar_luminaria_reportable("L", "124")
    assert exc.value.status_code == 422


def test_estado_de_la_pqrs_sigue_a_la_orden() -> None:
    assert atencion.siguiente_estado_por_orden("301", "orden_creada") == "302"
    assert atencion.siguiente_estado_por_orden("302", "orden_creada") is None
    assert atencion.siguiente_estado_por_orden("302", "orden_asignada") == "305"
    assert atencion.siguiente_estado_por_orden("303", "orden_asignada") is None


def test_enmascarado_no_deja_salir_el_dato_completo() -> None:
    datos = {
        "nombre_completo": "Sofía Álvarez",
        "identificacion": "1067123456",
        "telefono": "7729988",
        "celular": "3159876543",
        "correo": "sofia.alvarez@example.test",
    }
    masc = atencion.enmascarar_ciudadano(datos)
    assert masc["enmascarado"] is True
    for campo, valor in datos.items():
        assert valor not in str(masc[campo]), campo
    assert masc["identificacion"].endswith("456")
    assert masc["correo"] == "s•••@example.test"
    assert masc["nombre_completo"] == "S•••• Á••••••"


# === Trabajos ===================================================================================


@pytest.mark.parametrize(
    ("tipo", "roles"),
    [
        ("mantenimiento", ["intervenida", "intervenida"]),
        ("expansion", ["instalada"]),
        ("modernizacion", ["instalada", "desmontada"]),
        ("reubicacion", ["desmontada", "instalada"]),
    ],
)
def test_luminarias_validas_por_tipo(tipo: str, roles: list[str]) -> None:
    trabajos.validar_luminarias(tipo, roles)


@pytest.mark.parametrize(
    ("tipo", "roles"),
    [
        ("mantenimiento", ["instalada"]),
        ("expansion", ["desmontada"]),
        ("modernizacion", ["instalada"]),
        ("reubicacion", ["desmontada"]),
        ("modernizacion", ["instalada", "instalada", "desmontada"]),
        ("mantenimiento", []),
    ],
)
def test_luminarias_invalidas_rn013(tipo: str, roles: list[str]) -> None:
    with pytest.raises(trabajos.ErrorDominioTrabajos) as exc:
        trabajos.validar_luminarias(tipo, roles)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("estado", ["203", "204"])
def test_orden_cerrada_o_anulada_409(estado: str) -> None:
    with pytest.raises(trabajos.ErrorDominioTrabajos) as exc:
        trabajos.validar_abierta(estado)
    assert exc.value.status_code == 409


def test_checklist_de_12_componentes() -> None:
    completo = dict.fromkeys(trabajos.COMPONENTES, True)
    assert len(trabajos.validar_componentes(completo)) == 12
    for malo in (
        None,
        {k: v for k, v in completo.items() if k != "fotocelda"},
        {**completo, "extra": True},
        {**completo, "tubo": "si"},
    ):
        with pytest.raises(trabajos.ErrorDominioTrabajos) as exc:
            trabajos.validar_componentes(malo)
        assert exc.value.status_code == 422


def test_destino_y_mantenimiento() -> None:
    assert trabajos.validar_destino(None) == "112"
    assert trabajos.validar_destino("124") == "124"
    with pytest.raises(trabajos.ErrorDominioTrabajos):
        trabajos.validar_destino("121")
    trabajos.validar_mantenimiento(False, None, None)
    trabajos.validar_mantenimiento(True, "Quemada", 7)
    with pytest.raises(trabajos.ErrorDominioTrabajos):
        trabajos.validar_mantenimiento(False, None, 7)
    with pytest.raises(trabajos.ErrorDominioTrabajos):
        trabajos.validar_mantenimiento(True, " ", None)


@pytest.mark.parametrize("tipo", ["expansion", "modernizacion", "reubicacion"])
def test_plantilla_y_lectura_del_cargue(tipo: str) -> None:
    plantilla = trabajos.generar_plantilla(tipo)
    libro = load_workbook(io.BytesIO(plantilla))
    encabezado = [c.value for c in libro.worksheets[0][1]]
    assert tuple(encabezado) == trabajos.COLUMNAS_CARGUE[tipo]
    fila_valida = {
        "expansion": ["L-1", "COMPLEMENTARIA", "El Centro", "P-1", 7.98, -75.41],
        "modernizacion": ["L-1", "L-2", "PRIORITARIA", "El Centro", "P-1", "124"],
        "reubicacion": ["L-1", "L-2", "", "El Centro", "P-1", "124"],
    }[tipo]
    filas, errores = trabajos.leer_cargue(
        tipo, _xlsx([list(encabezado), fila_valida, [None] * 6, ["", "", "", "", "", ""]])
    )
    assert len(filas) == 1 and errores == []
    _, errores = trabajos.leer_cargue(tipo, _xlsx([list(encabezado), [""] * 6, ["X"]]))
    assert errores and errores[0]["fila"] == 3


def test_coordenadas_de_fila() -> None:
    assert trabajos.coordenadas_de_fila({"latitud": "7,98", "longitud": "-75.4"}) == (7.98, -75.4)
    with pytest.raises(trabajos.ErrorDominioTrabajos):
        trabajos.coordenadas_de_fila({"latitud": "norte", "longitud": "1"})
