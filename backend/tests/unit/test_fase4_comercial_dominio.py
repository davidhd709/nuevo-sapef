"""Reglas puras del módulo comercial (Anexo E, §11.6 a §11.11)."""

import datetime as dt
from decimal import Decimal

import pytest

from app.modulos.comercial.dominio import (
    afinia,
    afinia_ingesta,
    analisis,
    catalogo,
    celsia,
    celsia_ingesta,
    vatia,
)
from app.modulos.comercial.dominio.archivos import (
    ArchivoEntrada,
    descomprimir_z,
    validar_contenido,
)
from app.modulos.comercial.dominio.comun import (
    ErrorDominioComercial,
    dec,
    div,
    faltantes_entre,
    normalizar_encabezado,
    validar_periodo,
)

# «He110\n» comprimido con Unix compress (16 bits, modo bloque): referencia de unlzw.
HELLO_Z = bytes.fromhex("1f9d90480a4c18f0000a")


def test_descomprimir_z_y_validaciones_de_contenido() -> None:
    assert descomprimir_z(b"\x1f\x9d\x90") == b""
    with pytest.raises(ErrorDominioComercial):
        descomprimir_z(b"no es z")
    with pytest.raises(ErrorDominioComercial) as exc:
        validar_contenido("x.exe", b"MZ", (".txt", ".xlsx"))
    assert exc.value.status_code == 415
    with pytest.raises(ErrorDominioComercial):
        validar_contenido("libro.xlsx", b"MZ\x90", (".xlsx",))
    with pytest.raises(ErrorDominioComercial):
        validar_contenido("plano.txt", b"abc\x00def", (".txt",))
    validar_contenido("FACT_SV500_ZONA_1_20260715.txt.Z", b"\x1f\x9d\x90", (".z",))


def test_utilidades_numericas_y_periodos() -> None:
    assert dec("1.234,56") == Decimal("1234.56")
    assert dec("1,234.56") == Decimal("1234.56")
    assert dec("") is None
    with pytest.raises(ValueError):
        dec("N/A")
    assert div(1, 0) == 0 and div(1, 0, nulo=True) is None
    assert faltantes_entre("202602", "202605") == ["202603", "202604"]
    assert normalizar_encabezado("Número de Factura") == "numero_de_factura"
    with pytest.raises(ErrorDominioComercial):
        validar_periodo("202613")


def test_reconocimiento_de_archivos_afinia() -> None:
    assert afinia_ingesta.reconocer("FACT_SV500_ZONA_3_20260715.txt.Z") == (
        "facturacion",
        "202607",
        "3",
    )
    assert afinia_ingesta.reconocer("CATASTRO_USUARIOS_SV500_1_20260731.txt") == (
        "catastro",
        "202607",
        "1",
    )
    assert afinia_ingesta.reconocer("REFACTURACION_MONTELIBANO_SETIEMBRE_2026.xlsx") == (
        "refactura",
        "202609",
        None,
    )
    assert afinia_ingesta.reconocer("NOVEDADES_20260715.txt") == (None, None, None)
    with pytest.raises(ErrorDominioComercial):
        afinia_ingesta.reconocer("OTRO_ARCHIVO.txt")


def test_normalizacion_afinia_plano_con_duplicados() -> None:
    dia = "2026-07-15"
    fila = [
        dia,
        "OC100",
        "7",
        "8",
        "1",
        "1",
        "2026-05-01",
        "Res",
        "AP_Residenciales_Estrato_1",
        "1",
        "CI400",
        "100.5",
        dia,
        "100.5",
        "23",
        "466",
        "0",
        "23",
        "SV1",
    ]
    plano = ("\n".join("\t".join(fila) for _ in range(2)) + "\n").encode("cp1252")
    resultado = afinia_ingesta.procesar(
        [ArchivoEntrada("RECA_SV500_ZONA_1_20260715.txt", plano)], "202607"
    )
    assert not resultado.errores
    assert resultado.familias["recaudo"][0]["tipo_recaudo"] == "CARTERA"  # factura de mayo
    assert resultado.familias["recaudo"][0]["importe_trans"] == Decimal("100.5000")
    assert any("duplicadas" in a for a in resultado.advertencias)
    assert resultado.publicable is False  # sin facturación


VIGENCIA = afinia.VigenciaAfinia(
    anio=2026,
    uvt=Decimal(52374),
    umbral_kwh=Decimal(173),
    tolerancia=Decimal("1.00"),
    tarifas={"E1": (Decimal("0.04"), Decimal("0.02")), "C1": (Decimal("0.30"), Decimal("0.12"))},
    excepciones={"900": Decimal(5)},
)


def _ci400(nic: str, tarifa: str, importe: str, consumo: str | None, base: str | None) -> dict:
    return {
        "nic": nic,
        "tarifa": tarifa,
        "concepto": "CI400",
        "importe_trans": Decimal(importe),
        "consumo_kwh": None if consumo is None else Decimal(consumo),
        "valor_consumo_antes": None if base is None else Decimal(base),
    }


def test_control_tarifario_afinia_tolerancia_de_un_peso() -> None:
    filas = [
        _ci400("1", "E1", "2095.96", "50", "1"),  # +1,00 → correcto
        _ci400("2", "E1", "2095.97", "50", "1"),  # +1,01 → por encima
        _ci400("3", "E1", "2093.95", "50", "1"),  # -1,01 → por debajo
        _ci400("4", "C1", "120000", "500", "1000000"),  # 12 % del consumo antes del impuesto
        _ci400("900", "E1", "261870", None, None),  # contribuyente especial: 5 UVT
        _ci400("5", "XX", "10", "10", "10"),
    ]
    resultado = {f.identificador: f for f in afinia.control_tarifario(filas, "202607", VIGENCIA)}
    assert resultado["1"].estado == "CORRECTO"
    assert (resultado["2"].estado, resultado["2"].valor_por_encima) == (
        "POR_ENCIMA",
        Decimal("1.01"),
    )
    assert (resultado["3"].estado, resultado["3"].valor_por_debajo) == (
        "POR_DEBAJO",
        Decimal("1.01"),
    )
    assert resultado["4"].regla_aplicada == "COSTO_VARIABLE" and resultado["4"].estado == "CORRECTO"
    assert resultado["900"].regla_aplicada == "COBRO_ESPECIAL_UVT"
    assert resultado["5"].motivo_revision == "TARIFA_SIN_PARAMETROS"
    sin_vigencia = afinia.control_tarifario(filas[:1], "202207", None)
    assert sin_vigencia[0].motivo_revision == "PERIODO_SIN_PARAMETROS"


def test_facturas_irregulares_afinia() -> None:
    def fila(nic: str, concepto: str, importe: str, tarifa: str = "E1") -> dict:
        return {
            "nic": nic,
            "concepto": concepto,
            "importe_trans": Decimal(importe),
            "tarifa": tarifa,
            "sv": f"S{nic}",
        }

    categorias = afinia.facturas_irregulares(
        [
            fila("1", "CI400", "500"),
            fila("1", "CI401", "-500"),
            fila("2", "CI400", "-200"),
            fila("3", "CI306", "1200"),
            fila("4", "CI400", "10"),
            fila("4", "CI400", "10"),
            fila("5", "CI400", "10"),
            fila("5", "CI400", "10", "C1"),
        ]
    )
    ids = {k: [x["identificador"] for x in v] for k, v in categorias.items()}
    assert ids == {
        "LINEA_NEGATIVA": ["1", "2"],
        "TOTAL_NEGATIVO": ["2"],
        "TOTAL_EN_CERO": ["1"],
        "SIN_CONCEPTO_IMPUESTO": ["3"],
        "IMPUESTO_AMBIGUO": ["4"],
    }


def test_ajustes_negativos_alertan_solo_si_superan_el_maximo_previo() -> None:
    def recaudo(*montos: int) -> list[dict]:
        return [{"importe_trans": Decimal(m)} for m in montos]

    salida = afinia.ajustes_negativos(
        {
            "202510": recaudo(10000, -100),
            "202511": recaudo(10000, -100),
            "202512": recaudo(10000, -2500),
        }
    )
    assert [a["alerta"] for a in salida] == [False, False, True]


def test_celsia_reglas_y_tope_bimestral() -> None:
    regla = celsia.ReglaCelsia
    vigencia = celsia.VigenciaCelsia(
        anio=2026,
        tolerancia=Decimal(100),
        duplicar_bimestral=True,
        tarifas={
            "RESIDENCIAL_ESTRATO_1": regla("fija", None, Decimal("3994.50"), Decimal("2349.20")),
            "RESIDENCIAL_ESTRATO_3": regla(
                "mayor_porcentaje_minimo", Decimal("0.10"), Decimal("13205.16"), Decimal("10564.99")
            ),
        },
    )

    def factura(
        cuenta: str,
        clase: str,
        estrato: str,
        sector: str,
        valor: str,
        vce: str | None,
        periodicidad: str = "Mensual",
    ) -> dict:
        return {
            "cuenta": cuenta,
            "clase": clase,
            "estrato": estrato,
            "sector": sector,
            "periodicidad": periodicidad,
            "tipo_concepto": "impuesto",
            "valor_facturado": Decimal(valor),
            "monto_energia": None if vce is None else Decimal(vce),
        }

    filas = {
        f.identificador: f
        for f in celsia.control_tarifario(
            [
                factura("A", "1 Residencial", "1", "Urbano", "4094.50", "1"),
                factura("B", "1 Residencial", "1", "Urbano", "4094.51", "1"),
                factura("C", "1 Residencial", "3", "Rural", "21129.98", "150000", "Bimestral"),
                factura("D", "1 Residencial", "3", "Urbano", "1", None),
                factura("E", "3 Oficial Exenta", "", "Urbano", "1", "1"),
                factura("F", "1 Residencial", "9", "Urbano", "1", "1"),
            ],
            "202610",
            vigencia,
        )
    }
    assert filas["A"].estado == "CORRECTO" and filas["B"].estado == "POR_ENCIMA"
    assert filas["C"].esperado == Decimal("21129.98") and filas["C"].estado == "CORRECTO"
    assert filas["D"].estado == "REQUIERE_REVISION"  # sin VCE: falta un dato (RN-006)
    # Sin regla en la carta: no hay esperado que calcular (RN-006) -> NO_VALIDABLE.
    assert filas["E"].motivo_revision == "CLASIFICACION_REQUIERE_EXCEPCION"
    assert filas["F"].motivo_revision == "ESTRATO_SIN_REGLA"
    assert filas["E"].estado == filas["F"].estado == "NO_VALIDABLE"
    assert celsia_ingesta.tipo_concepto("Impuesto Alumbrado Público") == "impuesto"
    assert celsia_ingesta.tipo_concepto("") == "agregado_sin_detalle"
    assert celsia_ingesta.tipo_concepto("Interés de financiación") == "interes"
    assert celsia_ingesta.estrato("Estrato 2", "Residencial") == "2"
    assert celsia_ingesta.estrato("", "Comercial") == "Comercial"
    assert celsia_ingesta.periodo_del_nombre("CELSIA_ALCALA_ABR_26.xlsx") == "202604"
    assert celsia_ingesta.periodo_del_nombre("X_JULIO_2026.xlsx") == "202607"


def test_periodicidad_y_movimiento_por_periodo_esperado() -> None:
    assert analisis.deducir_periodicidad(["202604", "202606"]) == (
        "bimestral_par",
        "meses_facturados",
    )
    assert analisis.deducir_periodicidad(["202604", "202605"])[0] == "mensual"
    assert analisis.deducir_periodicidad(["202604"], "Bimestral")[0] == "bimestral_provisional_par"
    assert analisis.deducir_periodicidad(["202604"], "Mensual") == ("mensual", "archivo")
    assert analisis.deducir_periodicidad(["202604", "202606"], "Trimestral")[0] == "no_evaluable"

    presencia = {
        "M": {"202604", "202605", "202606"},
        "B": {"202604", "202606"},
        "D": {"202604"},
        "R": {"202604", "202606"},
    }
    mov = analisis.movimiento(
        presencia,
        ["202604", "202605", "202606"],
        "202605",
        {"M": "mensual", "B": "bimestral_par", "D": "mensual", "R": "mensual"},
    )
    assert mov.facturados == ["M"] and "B" not in mov.dejados_facturar
    assert sorted(mov.dejados_facturar) == ["D", "R"]
    salto = analisis.movimiento(
        {"X": {"202602", "202604"}, "Y": {"202602"}}, ["202602", "202604"], "202604"
    )
    assert salto.comparable == "202602" and salto.salto_corte_detectado
    assert salto.cortes_faltantes == ["202603"]
    assert salto.facturados == ["X"] and salto.ausentes == {"Y": 1}
    reintegro = analisis.movimiento(
        {"Z": {"202601", "202603"}}, ["202601", "202602", "202603"], "202603"
    )
    assert reintegro.reintegrados == ["Z"] and reintegro.nuevos == []


def test_concentracion_y_comportamiento_de_pago() -> None:
    conc = analisis.concentracion({"a": Decimal(100), "b": Decimal(50), "c": Decimal(50)})
    assert conc["cuantos_suman_50_pct"] == 1 and conc["top_10"] == Decimal("200.00")
    pago = analisis.comportamiento_pago(
        {"1": {"a", "b", "c"}, "2": {"a", "b", "c"}}, {"1": {"a"}, "2": {"a", "b"}}, {}
    )
    assert {r["identificador"]: r["comportamiento"] for r in pago["items"]} == {
        "a": "PAGA_SIEMPRE",
        "b": "INTERMITENTE",
        "c": "NUNCA_PAGA",
    }


def test_vatia_eficiencia_nula_y_orden_de_edades() -> None:
    filas = [
        {
            "cliente_id": "1",
            "facturado_total": Decimal(0),
            "recaudo_mes": Decimal(0),
            "recuperacion_cartera": Decimal(0),
            "saldo_cartera": Decimal(10),
            "edad_cartera": "60 días",
        },
        {
            "cliente_id": "2",
            "facturado_total": Decimal(0),
            "recaudo_mes": Decimal(0),
            "recuperacion_cartera": Decimal(0),
            "saldo_cartera": Decimal(5),
            "edad_cartera": "Al día",
        },
    ]
    assert vatia.resumen(filas)["eficiencia"] is None
    assert [b["edad"] for b in vatia.cartera_por_edades(filas)["bandas"]] == ["Al día", "60 días"]


def test_catalogo_de_29_analisis_con_notas() -> None:
    for operador in ("afinia", "celsia", "vatia"):
        entradas = catalogo.catalogo(operador)
        assert len(entradas) == 29
        assert all(e["nota"] for e in entradas if e["estado"] == "no_aplica")
    with pytest.raises(ErrorDominioComercial):
        catalogo.exigir_disponible("vatia", "control-tarifario")


def test_maduracion_por_bandas() -> None:
    bandas = afinia.maduracion(
        [
            {"nic": 1, "importe_trans": Decimal(10), "fecha_fact_lect": dt.date(2026, 7, 2)},
            {"nic": 2, "importe_trans": Decimal(20), "fecha_fact_lect": dt.date(2026, 6, 2)},
            {"nic": 3, "importe_trans": Decimal(30), "fecha_fact_lect": dt.date(2025, 1, 2)},
            {"nic": 4, "importe_trans": Decimal(40), "fecha_fact_lect": None},
        ],
        "202607",
    )
    assert bandas["DEL_MES"]["monto"] == Decimal("10.00")
    assert bandas["UN_MES"]["monto"] == Decimal("20.00")
    assert bandas["MAS_DE_UN_ANO"]["monto"] == Decimal("30.00")
    assert bandas["SIN_FECHA"]["usuarios"] == 1
