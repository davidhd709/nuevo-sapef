"""Reglas puras de configuración (EP-02) y coherencia de los datos semilla."""

from decimal import Decimal

import pytest

from app.modulos.configuracion import datos_semilla, dominio
from app.modulos.configuracion.dominio import (
    AcuerdoDatos,
    ErrorDominioConfiguracion,
    ExcepcionDatos,
    TarifaDatos,
)
from app.modulos.seguridad import datos_semilla as semilla_seguridad


def _estado(exc: pytest.ExceptionInfo[ErrorDominioConfiguracion]) -> int:
    return exc.value.status_code


# --- Códigos ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [("Künix", "KUNIX"), ("led solar", "LED_SOLAR"), ("Schréder", "SCHREDER"), ("ok-1", "OK_1")],
)
def test_codigo_maestro_se_normaliza(entrada: str, esperado: str) -> None:
    assert dominio.normalizar_codigo_maestro(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "¿?", "_X", "A" * 61])
def test_codigo_maestro_invalido(entrada: str) -> None:
    with pytest.raises(ErrorDominioConfiguracion) as exc:
        dominio.normalizar_codigo_maestro(entrada)
    assert _estado(exc) == 422


def test_codigo_sede() -> None:
    assert dominio.normalizar_codigo_sede(" Montelibano ") == "montelibano"
    with pytest.raises(ErrorDominioConfiguracion):
        dominio.normalizar_codigo_sede("a")
    with pytest.raises(ErrorDominioConfiguracion):
        dominio.normalizar_codigo_sede("con espacio")


def test_asignaciones_repetidas() -> None:
    with pytest.raises(ErrorDominioConfiguracion) as exc:
        dominio.validar_asignaciones_unicas(["afinia", "Afinia "])
    assert _estado(exc) == 422


# --- Parámetros ------------------------------------------------------------------------------


def test_semaforo_valido() -> None:
    dominio.validar_valor_parametro(
        "semaforo_pqrs_umbrales", {"verde_max_dias": 0, "amarillo_max_dias": 1}
    )


@pytest.mark.parametrize(
    "valor",
    [
        {"verde_max_dias": -5, "amarillo_max_dias": 1},
        {"verde_max_dias": 5, "amarillo_max_dias": 5},
        {"verde_max_dias": True, "amarillo_max_dias": 7},
        {"verde_max_dias": 3.5, "amarillo_max_dias": 7},
        {"verde_max_dias": 3, "amarillo_max_dias": 7, "rojo": 1},
        {"verde_max_dias": 3},
        [3, 7],
        None,
    ],
)
def test_semaforo_invalido(valor: object) -> None:
    with pytest.raises(ErrorDominioConfiguracion) as exc:
        dominio.validar_valor_parametro("semaforo_pqrs_umbrales", valor)
    assert _estado(exc) == 422


def test_parametro_sin_validador_acepta_json() -> None:
    dominio.validar_valor_parametro("otro", {"x": [1, 2]})


# --- Plantillas ------------------------------------------------------------------------------


def test_plantilla_valida_y_renderizado_escapa_html() -> None:
    dominio.validar_plantilla(
        "Solicitud {{numero}}", "<p>Hola {{ nombre }}</p>", ["numero", "nombre"]
    )
    cuerpo = dominio.renderizar_texto(
        "<p>{{nombre}} {{oculta}}</p>", {"nombre"}, {"nombre": "<b>Ana</b>", "oculta": "x"},
        escapar_html=True,
    )
    assert cuerpo == "<p>&lt;b&gt;Ana&lt;/b&gt; </p>"


@pytest.mark.parametrize(
    ("asunto", "cuerpo"),
    [
        ("Hola {{clave}}", "<p>x</p>"),
        ("Hola", "<script>alert(1)</script>"),
        ("Hola", '<img src=x onerror="alert(1)">'),
        ("Hola", '<a href="javascript:alert(1)">x</a>'),
        ("Hola\nBcc: otro@x.co", "<p>x</p>"),
        ("   ", "<p>x</p>"),
    ],
)
def test_plantilla_invalida(asunto: str, cuerpo: str) -> None:
    with pytest.raises(ErrorDominioConfiguracion) as exc:
        dominio.validar_plantilla(asunto, cuerpo, ["nombre"])
    assert _estado(exc) == 422


# --- Acuerdo tarifario -------------------------------------------------------------------------

# Tabla de §11.6: valor mínimo 2026 = UVT (52.374) × factor, redondeado a centavos.
MINIMOS_2026 = {
    "AP_Comerciales_Nivel_1": "15712.20",
    "AP_Residenciales_Estrato_1": "2094.96",
    "AP_Residenciales_Estrato_2": "3142.44",
    "AP_Residenciales_Estrato_3": "3666.18",
    "AP_Residenciales_Estrato_4": "4713.66",
    "AP_Residenciales_Estrato_5": "6284.88",
    "AP_Residenciales_Estrato_6": "7332.36",
}


def test_valor_minimo_coincide_con_la_tabla_de_opainn() -> None:
    factores = {t: f for t, f, _ in datos_semilla.TARIFAS_AFINIA_2026}
    for tarifa, esperado in MINIMOS_2026.items():
        assert dominio.valor_minimo(Decimal("52374"), factores[tarifa]) == Decimal(esperado)
    assert dominio.valor_minimo(None, Decimal("0.3")) is None


def test_valor_minimo_redondea_mitad_hacia_arriba() -> None:
    assert dominio.valor_minimo(Decimal("0.125"), Decimal("1")) == Decimal("0.13")


def _afinia_completo(**cambios: object) -> AcuerdoDatos:
    base = {
        "uvt": Decimal("52374"),
        "umbral_kwh": Decimal("173"),
        "tolerancia": Decimal("1"),
        "base_costo_variable": "valor_consumo_antes",
        "tarifas": [TarifaDatos("AP_Residenciales_Estrato_1", None, Decimal("0.04"),
                                Decimal("0.02"))],
        "excepciones": [ExcepcionDatos("123", Decimal("5"))],
    }
    base.update(cambios)
    return AcuerdoDatos(**base)


def test_afinia_completo_es_aprobable() -> None:
    assert dominio.faltantes_para_aprobar(dominio.REGLA_AFINIA, _afinia_completo()) == []
    dominio.validar_aprobable("borrador", dominio.REGLA_AFINIA, _afinia_completo())


def test_afinia_incompleto_lista_lo_que_falta() -> None:
    faltan = dominio.faltantes_para_aprobar(
        dominio.REGLA_AFINIA,
        _afinia_completo(uvt=None, tarifas=[TarifaDatos("X")], excepciones=[ExcepcionDatos("9")]),
    )
    assert "uvt" in faltan
    assert "X: factor_uvt_minimo" in faltan
    assert "excepción 9: factor_uvt o regla" in faltan
    with pytest.raises(ErrorDominioConfiguracion) as exc:
        dominio.validar_aprobable("borrador", dominio.REGLA_AFINIA, _afinia_completo(tarifas=[]))
    assert _estado(exc) == 422


def test_celsia_reglas_por_tipo() -> None:
    datos = AcuerdoDatos(
        uvt=None, umbral_kwh=None, tolerancia=Decimal("100"), base_costo_variable="vce",
        tarifas=[
            TarifaDatos("E1", "fija", valor_urbano=Decimal("1"), valor_rural=None),
            TarifaDatos("E3", "mayor_porcentaje_minimo", porcentaje_costo_variable=Decimal("0.1"),
                        valor_urbano=Decimal("1"), valor_rural=Decimal("1")),
            TarifaDatos("SE", "porcentaje", porcentaje_costo_variable=Decimal("0.15")),
            TarifaDatos("SIN"),
        ],
    )
    assert dominio.faltantes_para_aprobar(dominio.REGLA_CELSIA, datos) == [
        "E1: valor_rural",
        "SIN: tipo_regla",
    ]


def test_estructura_invalida() -> None:
    repetidas = _afinia_completo(tarifas=[TarifaDatos("A"), TarifaDatos("A")])
    with pytest.raises(ErrorDominioConfiguracion):
        dominio.validar_estructura_acuerdo(dominio.REGLA_AFINIA, repetidas)
    con_tipo = _afinia_completo(tarifas=[TarifaDatos("A", "fija")])
    with pytest.raises(ErrorDominioConfiguracion):
        dominio.validar_estructura_acuerdo(dominio.REGLA_AFINIA, con_tipo)
    tipo_raro = _afinia_completo(tarifas=[TarifaDatos("A", "otra")])
    with pytest.raises(ErrorDominioConfiguracion):
        dominio.validar_estructura_acuerdo(dominio.REGLA_CELSIA, tipo_raro)


def test_ciclo_de_vida_del_acuerdo() -> None:
    dominio.validar_editable("borrador")
    for estado in ("aprobado", "reemplazado"):
        with pytest.raises(ErrorDominioConfiguracion) as exc:
            dominio.validar_editable(estado)
        assert _estado(exc) == 409
        with pytest.raises(ErrorDominioConfiguracion) as exc:
            dominio.validar_aprobable(estado, dominio.REGLA_AFINIA, _afinia_completo())
        assert _estado(exc) == 409


def test_vatia_no_admite_acuerdo() -> None:
    with pytest.raises(ErrorDominioConfiguracion) as exc:
        dominio.validar_regla_admite_acuerdo(None, "vatia")
    assert _estado(exc) == 422


# --- Datos semilla -----------------------------------------------------------------------------


def test_maestros_sin_codigos_repetidos_y_normalizados() -> None:
    for clase, (_, valores) in datos_semilla.MAESTROS.items():
        codigos = [c for c, _ in valores]
        assert len(codigos) == len(set(codigos)), clase
        for c in codigos:
            assert dominio.normalizar_codigo_maestro(c) == c, (clase, c)
    assert len(datos_semilla.MAESTROS["COMPONENTE_MANTENIMIENTO"][1]) == 12
    assert len(datos_semilla.MAESTROS["LUMINARIA_POTENCIA"][1]) == 39


def test_zonas_y_barrios_de_montelibano() -> None:
    zonas = datos_semilla.ZONAS_BARRIOS["montelibano"]
    assert len(zonas) == 11
    assert sum(len(b) for b in zonas.values()) == 101
    for zona, barrios in zonas.items():
        assert len({b.lower() for b in barrios}) == len(barrios), zona


def test_acuerdos_semilla_son_aprobables() -> None:
    for acuerdo in datos_semilla.ACUERDOS_2026:
        regla = datos_semilla.COMERCIALIZADORES[str(acuerdo["comercializador"])][2]
        datos = AcuerdoDatos(
            uvt=acuerdo["uvt"],
            umbral_kwh=acuerdo["umbral_kwh"],
            tolerancia=acuerdo["tolerancia"],
            base_costo_variable=str(acuerdo["base_costo_variable"]),
            tarifas=[TarifaDatos(**t) for t in acuerdo["tarifas"]],
        )
        assert regla is not None
        dominio.validar_estructura_acuerdo(regla, datos)
        assert dominio.faltantes_para_aprobar(regla, datos) == []


def test_catalogos_comerciales() -> None:
    assert len(datos_semilla.CONCEPTOS_AFINIA) == 64
    assert len(datos_semilla.OPERACIONES_AFINIA) == 33
    assert set(datos_semilla.CONCEPTOS_AFINIA) >= datos_semilla.CONCEPTOS_AFINIA_EN_CALCULO


def test_roles_semilla_solo_usan_permisos_del_catalogo() -> None:
    catalogo = {c for c, _, _ in semilla_seguridad.PERMISOS}
    assert len(catalogo) == len(semilla_seguridad.PERMISOS)
    for rol, (_, _, permisos) in semilla_seguridad.ROLES.items():
        assert set(permisos) <= catalogo, rol
    analista = set(semilla_seguridad.ROLES["ANALISTA_COMERCIAL"][2])
    assert "configuracion.acuerdo.editar" in analista
    assert "configuracion.acuerdo.aprobar" not in analista
    assert "configuracion.parametro.editar" not in semilla_seguridad.ROLES["INTERVENTORIA"][2]
