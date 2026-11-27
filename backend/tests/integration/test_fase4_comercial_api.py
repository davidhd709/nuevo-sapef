"""Integración de la Fase 4 contra PostgreSQL: cargues comerciales, almacén Parquet, análisis con
las reglas de OPainn, entregables y permisos nominales."""

import datetime as dt
import io
import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import obtener_configuracion
from app.main import crear_app
from app.modulos.comercial import servicio as comercial
from tests.conftest import crear_usuario_db, iniciar_sesion_cliente

MT = {"X-Sede": "montelibano"}
AL = {"X-Sede": "alcala"}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def almacen_comercial(almacen_temporal, monkeypatch):
    ruta = almacen_temporal / "comercial"
    monkeypatch.setenv("SAPEF_COMERCIAL_DIR", str(ruta))
    obtener_configuracion.cache_clear()
    yield ruta
    obtener_configuracion.cache_clear()


@pytest.fixture
def analista(cliente: TestClient, db_configurado: Session, almacen_comercial) -> TestClient:
    crear_usuario_db(
        db_configurado,
        nombre_usuario="admin_f4",
        correo="admin_f4@sapef.test",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano", "alcala"],
    )
    iniciar_sesion_cliente(cliente, "admin_f4")
    return cliente


# --- Archivos de prueba ---------------------------------------------------------------------------


def _tx(
    nic: int,
    tarifa: str,
    concepto: str,
    importe: str,
    fecha: dt.date,
    sv: str,
    extra: list[Any] | None = None,
    oper: str = "OC100",
) -> list[Any]:
    fila = [
        fecha,
        oper,
        nic,
        nic + 100000,
        1,
        1,
        fecha,
        "Residencial",
        tarifa,
        1,
        concepto,
        importe,
        fecha,
        importe,
        23,
        466,
        0,
        23,
        sv,
    ]
    return fila + (extra or [])


def _plano(filas: list[list[Any]], sep: str = "\t") -> bytes:
    def celda(v: Any) -> str:
        return "" if v is None else v.isoformat() if isinstance(v, dt.date) else str(v)

    return ("\n".join(sep.join(celda(c) for c in f) for f in filas) + "\n").encode("cp1252")


E1, E2, C1 = "AP_Residenciales_Estrato_1", "AP_Residenciales_Estrato_2", "AP_Comerciales_Nivel_1"


def _corte_afinia(
    periodo: str, *, nics_extra: tuple[int, ...] = ()
) -> list[tuple[str, bytes, str]]:
    anio, mes = int(periodo[:4]), int(periodo[4:])
    dia = dt.date(anio, mes, 15)
    viejo = dt.date(anio - 1, 1, 10)
    stamp = f"{periodo}15"
    fact = [
        _tx(9001, E1, "CI400", "2094.96", dia, "S1", [120, 350000]),  # mínimo correcto
        _tx(9002, E1, "CI400", "2595.96", dia, "S2", [100, 90000]),  # +501 por encima
        _tx(9002, E1, "CI401", "-100", dia, "S2", [0, 0]),
        _tx(9003, E2, "CI400", "2742.44", dia, "S3", [90, 90000]),  # -400 por debajo
        _tx(9003, E2, "CI851", "-50", dia, "S3", [0, 0]),
        _tx(9004, C1, "CI400", "120000", dia, "S4", [500, 1000000]),  # 12 % de 1.000.000
        _tx(9005, E1, "CI400", "10000", dia, "S5", [400, None]),  # sin base: no validable
        _tx(9006, E2, "CI400", "3142.44", dia, "S6", [80, 80000]),  # dos CI400: revisión
        _tx(9006, E2, "CI400", "3142.44", dia, "S6", [80, 80000]),
        _tx(9007, E1, "CI306", "1500", dia, "S7", [0, 0]),  # sin impuesto
        *[_tx(n, E1, "CI400", "2094.96", dia, f"X{n}", [100, 50000]) for n in nics_extra],
    ]
    reca = [
        _tx(9001, E1, "CI400", "2094.96", dia, "S1"),
        _tx(9002, E1, "CI400", "2595.96", viejo, "OLD"),  # cartera
        _tx(9002, E1, "CI400", "2595.96", viejo, "OLD"),  # duplicado exacto
        _tx(9002, E1, "CI102", "125.50", viejo, "MORA"),
        _tx(9003, E2, "CI400", "-350", dia, "ADJ"),
    ]
    catastro = [
        [
            "SV500",
            "Alumbrado",
            "T1",
            "AP Residenciales Estrato 1",
            n,
            n + 100000,
            f"Usuario {n}",
            f"Calle {n}",
            100,
            "MONTELIBANO",
            "El Centro",
            deuda,
            0,
            "ACTIVO",
        ]
        for n, deuda in ((9001, 1000), (9002, 5000), (9007, 0))
    ]
    conv = [_tx(9007, E1, "CI300", "15000", dia, "CONV", oper="OC135")]
    return [
        (f"FACT_SV500_ZONA_1_{stamp}.txt", _plano(fact), "text/plain"),
        (f"RECA_SV500_ZONA_1_{stamp}.txt", _plano(reca), "text/plain"),
        (f"CATASTRO_USUARIOS_SV500_ZONA_1_{stamp}.txt", _plano(catastro, "|"), "text/plain"),
        (f"CONV_SV500_ZONA_1_{stamp}.txt", _plano(conv), "text/plain"),
        (
            f"REFA_SV500_ZONA_1_{stamp}.txt",
            _plano([_tx(9002, E1, "CI400", "320", dia, "R1", [100000])]),
            "text/plain",
        ),
    ]


def _libro(hojas: dict[str, list[list[Any]]]) -> bytes:
    libro = Workbook()
    libro.remove(libro.active)
    for nombre, filas in hojas.items():
        hoja = libro.create_sheet(nombre)
        for fila in filas:
            hoja.append(fila)
    buf = io.BytesIO()
    libro.save(buf)
    return buf.getvalue()


def _celsia(periodo: str, *, con_bimestral: bool = True, pies: int = 1) -> tuple[str, bytes, str]:
    anio, mes = int(periodo[:4]), int(periodo[4:])
    dia, vence = dt.date(anio, mes, 15), dt.date(anio, mes, 28)
    encabezados = [
        "Cuenta",
        "Número de Factura",
        "Fecha Factura",
        "Nombre",
        "Clase de Cliente",
        "Estrato",
        "Sector",
        "Periodicidad",
        "Descripción",
        "Valor del Impuesto Facturado",
        "Consumo kWh",
        "Valor del Consumo de Energía Antes de Subsidios o Contribuciones Pesos",
    ]
    fact = [
        encabezados,
        [
            "C1",
            "F1",
            dia,
            "Ana",
            "1 Residencial",
            "Estrato 1",
            "Urbano",
            "Mensual",
            "Impuesto Alumbrado Público",
            3994.50,
            120,
            85000,
        ],
        [
            "C2",
            "F2",
            dia,
            "Luis",
            "1 Residencial",
            "2",
            "Urbano",
            "Mensual",
            "Impuesto Alumbrado Público",
            8489.00,
            150,
            110000,
        ],
        [
            "C4",
            "F4",
            dia,
            "Tienda",
            "2 Comercial",
            "",
            "Urbano",
            "Mensual",
            "Impuesto Alumbrado Público",
            25000,
            600,
            250000,
        ],
        [
            "C5",
            "F5",
            dia,
            "Sin VCE",
            "1 Residencial",
            "4",
            "Urbano",
            "Mensual",
            "Impuesto Alumbrado Público",
            20417.51,
            200,
            None,
        ],
    ]
    if con_bimestral:
        fact.append(
            [
                "C3",
                "F3",
                dia,
                "Finca",
                "1 Residencial",
                "Estrato 3",
                "Rural",
                "Bimestral",
                "Impuesto Alumbrado Público",
                21129.98,
                300,
                150000,
            ]
        )
    fact += [[None, None, None, "TOTAL", None, None, None, None, None, 0, 0, 0]] * pies
    reca = [
        [
            "Cuenta",
            "Número de Factura",
            "Fecha Vencimiento",
            "Fecha de Pago",
            "Descripción",
            "Valor del Impuesto Recaudado",
        ],
        ["C1", "F1", vence, dia, "Impuesto Alumbrado Público", 3994.50],
        [
            "C4",
            "F4",
            dt.date(anio, mes, 1) - dt.timedelta(days=60),
            dia,
            "Impuesto Alumbrado Público",
            25000,
        ],
    ]
    cartera = [
        ["Cuenta", "Nombre", "Clase de Cliente", "Corriente", "Mora 30", "Total Cartera"],
        ["C2", "Luis", "1 Residencial", 8489, 5000, 13489],
    ]
    nombres = {4: "ABRIL", 5: "MAYO", 6: "JUNIO"}
    contenido = _libro(
        {
            "Facturacion": fact,
            "Recaudo": reca,
            "Cartera": cartera,
            "C2M": [["Nota", "Valor del Impuesto Facturado"], ["x", 9999999]],
        }
    )
    return (f"CELSIA_ALCALA_{nombres[mes]}_{anio % 100}.xlsx", contenido, XLSX)


def _vatia(periodo: str, filas: list[list[Any]]) -> tuple[str, bytes, str]:
    encabezados = [
        "CICLO",
        "CLIENTE ID",
        "CLIENTE NOMBRE",
        "SUBMERCADO",
        "FECHA ELAB FACTURA",
        "FACTURADO TOTAL INCLUYE NOTAS",
        "RECAUDO MES",
        "RECUPERACION CARTERA",
        "SALDO EN CARTERA",
        "EDAD CIERRE MES CICLO",
    ]
    return (f"VATIA_{periodo}.xlsx", _libro({"Comercial": [encabezados, *filas]}), XLSX)


def _subir(
    c: TestClient,
    sede: dict,
    op: str,
    periodo: str,
    archivos: list[tuple[str, bytes, str]],
    clave: str | None = None,
) -> Any:
    headers = {**sede, **({"Idempotency-Key": clave} if clave else {})}
    return c.post(
        f"/api/v1/comercial/{op}/cargues",
        headers=headers,
        data={"periodo": periodo},
        files=[("files", a) for a in archivos],
    )


def _procesar(db: Session, respuesta: Any) -> dict[str, Any]:
    assert respuesta.status_code in (200, 202), respuesta.text
    cargue_id = respuesta.json()["cargue_id"]
    comercial.procesar_cargue(db, cargue_id)
    return {"id": cargue_id}


def _cargar(c: TestClient, db: Session, sede: dict, op: str, periodo: str, archivos: list) -> dict:
    info = _procesar(db, _subir(c, sede, op, periodo, archivos))
    detalle = c.get(f"/api/v1/comercial/{op}/cargues/{info['id']}", headers=sede).json()
    assert detalle["estado"] == "publicado", detalle
    return detalle


# --- Cargues, almacén y límites ------------------------------------------------------------


def test_cargue_afinia_publica_parquet_idempotencia_y_reemplazo(
    analista: TestClient, db_configurado: Session, almacen_comercial
) -> None:
    clave = str(uuid.uuid4())
    archivos = _corte_afinia("202607")
    primera = _subir(analista, MT, "afinia", "202607", archivos, clave)
    assert primera.status_code == 202, primera.text
    assert primera.json()["tareaId"] is not None
    comercial.procesar_cargue(db_configurado, primera.json()["cargue_id"])
    detalle = analista.get(f"/api/v1/comercial/cargues/{primera.json()['id']}", headers=MT).json()
    assert detalle["estado"] == "publicado" and detalle["completo"] is True
    assert any("duplic" in a for a in detalle["advertencias"])
    assert detalle["familias"]["recaudo"] == 5  # el duplicado se conserva
    manifiesto = almacen_comercial / "montelibano" / "afinia" / "202607" / "manifest.json"
    assert manifiesto.is_file()

    repetida = _subir(analista, MT, "afinia", "202607", archivos, clave)
    assert repetida.status_code == 200 and repetida.json()["id"] == primera.json()["id"]
    otra = _subir(analista, MT, "afinia", "202607", _corte_afinia("202607", nics_extra=(1,)), clave)
    assert otra.status_code == 409

    # Reemplazo: el corte nuevo sustituye al anterior (uno publicado por periodo).
    segundo = _cargar(
        analista,
        db_configurado,
        MT,
        "afinia",
        "202607",
        _corte_afinia("202607", nics_extra=(9100,)),
    )
    estados = dict(
        db_configurado.execute(text("SELECT id, estado FROM cargue_comercial ORDER BY id")).all()
    )
    assert estados[primera.json()["id"]] == "reemplazado"
    assert estados[segundo["id"]] == "publicado"
    cortes = analista.get("/api/v1/comercial/afinia/cortes", headers=MT).json()
    assert [c["periodo"] for c in cortes] == ["202607"]

    datos = analista.get(
        "/api/v1/comercial/afinia/cortes/202607/datos",
        headers=MT,
        params={"familia": "recaudo", "buscar": "9002", "size": 10},
    ).json()
    assert datos["total"] == 3
    assert {r["tipo_recaudo"] for r in datos["items"]} == {"CARTERA"}
    refactura = analista.get(
        "/api/v1/comercial/afinia/cortes/202607/datos", headers=MT, params={"familia": "refactura"}
    ).json()["items"]
    assert "consumo_kwh" not in refactura[0]

    borrado = analista.delete(f"/api/v1/comercial/afinia/cargues/{segundo['id']}", headers=MT)
    assert borrado.status_code == 204
    assert analista.get("/api/v1/comercial/afinia/cortes", headers=MT).json() == []
    assert not (almacen_comercial / "montelibano" / "afinia" / "202607").exists()


def test_limites_extension_contenido_y_sede(analista: TestClient, db_configurado: Session) -> None:
    muchos = [
        ("files", (f"FACT_SV500_ZONA_{i}_20260815.txt", b"", "text/plain")) for i in range(65)
    ]
    r = analista.post(
        "/api/v1/comercial/afinia/cargues", headers=MT, data={"periodo": "202608"}, files=muchos
    )
    assert r.status_code == 413
    r = _subir(analista, MT, "afinia", "202608", [("x.exe", b"MZ\x90\x00" + b"\0" * 20, "a/b")])
    assert r.status_code == 415
    r = _subir(
        analista,
        MT,
        "afinia",
        "202608",
        [("FACTURACION_MONTELIBANO_AGOSTO_2026.xlsx", b"MZ" + b"\0" * 40, XLSX)],
    )
    assert r.status_code == 415
    assert _subir(analista, AL, "afinia", "202608", _corte_afinia("202608")).status_code == 404
    assert analista.get("/api/v1/comercial/celsia/cortes", headers=MT).status_code == 404
    assert analista.get("/api/v1/comercial/afinia/cortes").status_code == 400


def test_errores_de_validacion_no_publican_nada(
    analista: TestClient, db_configurado: Session
) -> None:
    libro = _libro({"facturacion": [["NIC", "IMPORTE TRANS.", "COLUMNA_EXTRA"], [1, 2, 3]]})
    _procesar(
        db_configurado,
        _subir(
            analista,
            MT,
            "afinia",
            "202503",
            [("FACTURACION_MONTELIBANO_MARZO_2025.xlsx", libro, XLSX)],
        ),
    )
    sin_fact = [a for a in _corte_afinia("202504") if not a[0].startswith("FACT_")]
    _procesar(db_configurado, _subir(analista, MT, "afinia", "202504", sin_fact))
    estados = [
        c["estado"] for c in analista.get("/api/v1/comercial/afinia/cargues", headers=MT).json()
    ]
    assert sorted(estados) == ["con_errores", "no_publicable"]
    assert analista.get("/api/v1/comercial/afinia/cortes", headers=MT).json() == []

    malo = _vatia(
        "202506", [["202506", "V1", "X", "Ind", dt.date(2025, 6, 18), "N/A", 0, 0, 0, ""]]
    )
    info = _procesar(db_configurado, _subir(analista, AL, "vatia", "202506", [malo]))
    detalle = analista.get(f"/api/v1/comercial/vatia/cargues/{info['id']}", headers=AL).json()
    assert detalle["estado"] == "con_errores"
    assert "facturado_total" in detalle["errores"][0] and "1 valor" in detalle["errores"][0]


# --- Análisis de Afinia --------------------------------------------------------------------------


def test_control_tarifario_afinia_estados_y_senales(
    analista: TestClient, db_configurado: Session
) -> None:
    _cargar(analista, db_configurado, MT, "afinia", "202607", _corte_afinia("202607"))
    r = analista.get(
        "/api/v1/comercial/afinia/analisis/control-tarifario/202607",
        headers=MT,
        params={"size": 100},
    )
    assert r.status_code == 200, r.text
    tc = r.json()
    por = {f["identificador"]: f for f in tc["items"]}
    assert tc["totales"]["por_estado"] == {
        "CORRECTO": 2,
        "POR_ENCIMA": 1,
        "POR_DEBAJO": 1,
        "NO_VALIDABLE": 1,
        "REQUIERE_REVISION": 2,
    }
    assert Decimal(tc["totales"]["valor_por_encima"]) == Decimal("501.00")
    assert Decimal(tc["totales"]["valor_por_debajo"]) == Decimal("400.00")
    assert por["9002"]["estado"] == "POR_ENCIMA" and Decimal(por["9002"]["senal_ci401"]) == -100
    assert por["9003"]["estado"] == "POR_DEBAJO" and Decimal(por["9003"]["senal_ci851"]) == -50
    assert por["9004"]["regla_aplicada"] == "COSTO_VARIABLE"
    assert por["9005"]["estado"] == "NO_VALIDABLE"
    assert por["9006"]["motivo_revision"] == "MULTIPLES_CI400"
    assert por["9007"]["motivo_revision"] == "SIN_CI400"
    assert por["9001"]["nombre"] == "Usuario 9001"
    solo_minima = analista.get(
        "/api/v1/comercial/afinia/analisis/control-tarifario/202607",
        headers=MT,
        params={"grupo_consumo": "minima"},
    ).json()
    assert {f["regla_aplicada"] for f in solo_minima["items"]} == {"FACTURACION_MINIMA"}
    auditadas = db_configurado.execute(
        text("SELECT count(*) FROM auditoria_consulta WHERE recurso LIKE 'comercial.afinia.%'")
    ).scalar_one()
    assert auditadas >= 2


def test_tabla_dinamica_indicadores_movimiento_y_paridad(
    analista: TestClient, db_configurado: Session
) -> None:
    _cargar(
        analista,
        db_configurado,
        MT,
        "afinia",
        "202602",
        _corte_afinia("202602", nics_extra=(9500,)),
    )
    _cargar(analista, db_configurado, MT, "afinia", "202604", _corte_afinia("202604"))
    td = analista.get("/api/v1/comercial/afinia/analisis/tabla-dinamica/202604", headers=MT).json()
    assert len(td["filas"]) == 12 and len(td["columnas"]) == 45
    total = td["total"]
    # Facturación sin CI306: 2094.96 + 2595.96 - 100 + 2742.44 - 50 + 120000 + 10000 + 2*3142.44
    assert Decimal(total["facturacion"]) == Decimal("143568.2400")
    assert Decimal(total["recaudo_cartera"]) == Decimal("5317.4200")
    assert Decimal(total["recaudo_corriente"]) == Decimal("1744.9600")
    assert total["usuarios_dejados_facturar"] == 1  # 9500 estaba en febrero
    assert Decimal(total["consumo_kwh"]) == Decimal("1370.0000")
    assert td["comparable"] == "202602" and td["salto_corte_detectado"] is True

    kpi = analista.get("/api/v1/comercial/afinia/analisis/indicadores/202604", headers=MT).json()
    for clave in (
        "n_factura",
        "facturacion",
        "recaudo_total",
        "consumo_kwh",
        "usuarios_dejados_facturar",
        "valor_convenios_periodo",
    ):
        assert kpi[clave] == total[clave], clave
    assert kpi["anterior"]["n_factura"] == 8

    mov = analista.get("/api/v1/comercial/afinia/analisis/movimientos/202604", headers=MT).json()
    assert mov["comparable"] == "202602" and mov["cortes_faltantes"] == ["202603"]
    assert [x["identificador"] for x in mov["dejados_facturar"]] == ["9500"]
    aus = analista.get("/api/v1/comercial/afinia/analisis/ausencias/202604", headers=MT).json()
    assert aus["tramos"] == {"1": 1, "2": 0, "3": 0, ">3": 0}

    serie = analista.get("/api/v1/comercial/afinia/analisis/serie", headers=MT).json()["serie"]
    assert [p["periodo"] for p in serie] == ["202602", "202604"]
    anual = analista.get(
        "/api/v1/comercial/afinia/analisis/consolidado-anual", headers=MT, params={"anio": 2026}
    ).json()
    assert anual["cobertura_meses"] == 2 and "202603" in anual["meses_faltantes"]


def test_irregulares_convenios_ajustes_y_gestion(
    analista: TestClient, db_configurado: Session
) -> None:
    _cargar(analista, db_configurado, MT, "afinia", "202607", _corte_afinia("202607"))
    irr = analista.get("/api/v1/comercial/afinia/analisis/facturas-revision/202607", headers=MT)
    assert irr.status_code == 200, irr.text
    ids = {k: [x["identificador"] for x in v] for k, v in irr.json()["por_categoria"].items()}
    assert ids["SIN_CONCEPTO_IMPUESTO"] == ["9007"]
    assert ids["IMPUESTO_AMBIGUO"] == ["9006"]  # CI400 + CI401 en la misma tarifa no es ambiguo
    conv = analista.get("/api/v1/comercial/afinia/analisis/convenios/202607", headers=MT).json()
    assert conv["resumen"]["facturas"] == 1 and conv["facturas"][0]["conciliado"] is True
    ajustes = analista.get("/api/v1/comercial/afinia/analisis/convenios-ajustes", headers=MT).json()
    assert ajustes["ajustes_negativos"][0]["monto"] == "-350.00"
    for ruta in (
        "maduracion/202607",
        "concentracion/202607",
        "comportamiento-pago",
        "rutas-campo/202607",
        "segmentacion/202607",
        "barrios/202607",
        "historico-comerciales",
        "disminuciones/202607",
        "eficiencia/202607",
        "detalle/202607?indicador=eficiencia_usuarios",
        "trazabilidad/9002",
    ):
        r = analista.get(f"/api/v1/comercial/afinia/analisis/{ruta}", headers=MT)
        assert r.status_code == 200, (ruta, r.text)
    conc = analista.get("/api/v1/comercial/afinia/analisis/concentracion/202607", headers=MT).json()
    assert conc["cuantos_suman_50_pct"] == 1 and conc["top_10"] == "6000.00"
    edades = analista.get("/api/v1/comercial/afinia/analisis/cartera-edades/202607", headers=MT)
    assert edades.status_code == 422  # Afinia no entrega edades de cartera


# --- Celsia y Vatia ----------------------------------------------------------------------------


def test_celsia_control_periodicidad_y_movimiento(
    analista: TestClient, db_configurado: Session
) -> None:
    for periodo, bim in (("202604", True), ("202605", False), ("202606", True)):
        _cargar(
            analista, db_configurado, AL, "celsia", periodo, [_celsia(periodo, con_bimestral=bim)]
        )
    datos = analista.get(
        "/api/v1/comercial/celsia/cortes/202606/datos",
        headers=AL,
        params={"familia": "facturacion"},
    ).json()
    assert datos["total"] == 5
    por = {r["cuenta"]: r for r in datos["items"]}
    assert por["C1"]["estrato"] == "1" and por["C4"]["estrato"] == "Comercial"
    assert por["C1"]["tipo_concepto"] == "impuesto"
    tc = analista.get(
        "/api/v1/comercial/celsia/analisis/control-tarifario/202606", headers=AL
    ).json()
    estados = {f["identificador"]: f for f in tc["items"]}
    assert tc["totales"]["por_estado"]["CORRECTO"] == 3
    assert estados["C2"]["estado"] == "POR_ENCIMA"
    assert estados["C5"]["estado"] == "REQUIERE_REVISION"  # sin VCE: falta un dato (RN-006)
    assert estados["C3"]["esperado"] == "21129.98"  # tope rural duplicado por ser bimestral
    mov = analista.get("/api/v1/comercial/celsia/analisis/movimientos/202605", headers=AL)
    assert "C3" not in mov.text  # bimestral fuera de su mes: no se cuenta ni se lista
    per = analista.get("/api/v1/comercial/celsia/analisis/periodicidad/202606", headers=AL).json()
    ciclo = {i["identificador"]: i["periodicidad"] for i in per["items"]}
    assert ciclo["C3"] == "bimestral_par" and ciclo["C1"] == "mensual"
    edades = analista.get(
        "/api/v1/comercial/celsia/analisis/cartera-edades/202606", headers=AL
    ).json()
    assert edades["total_cartera"] == "13489.00"
    ids = analista.post(
        "/api/v1/comercial/celsia/exportaciones/promedios-ids",
        headers=AL,
        files={"archivo": ("ids.txt", b"C1\nC2\n", "text/plain")},
    )
    assert ids.status_code == 200 and ids.content[:2] == b"PK"
    muchos = ("\n".join(str(i) for i in range(50001))).encode()
    assert (
        analista.post(
            "/api/v1/comercial/celsia/exportaciones/promedios-ids",
            headers=AL,
            files={"archivo": ("x.txt", muchos, "text/plain")},
        ).status_code
        == 422
    )
    cartera = analista.post(
        "/api/v1/comercial/celsia/exportaciones/cartera", headers=AL, json={"periodo": "202606"}
    )
    assert cartera.status_code == 200 and cartera.content[:2] == b"PK"


def test_vatia_indicadores_eficiencia_nula_y_notas(
    analista: TestClient, db_configurado: Session
) -> None:
    dia = dt.date(2026, 6, 18)
    _cargar(
        analista,
        db_configurado,
        AL,
        "vatia",
        "202606",
        [
            _vatia(
                "202606",
                [
                    [
                        "202606",
                        "V1",
                        "Industria",
                        "Industrial",
                        dia,
                        180000,
                        180000,
                        0,
                        0,
                        "Al día",
                    ],
                    ["202606", "V2", "Cero", "Comercial", dia, 0, 0, 0, 45000, "30 días"],
                    ["202606", "V3", "Notas", "Comercial", dia, -200000, 0, 0, 120000, "60 días"],
                ],
            )
        ],
    )
    kpi = analista.get("/api/v1/comercial/vatia/analisis/indicadores/202606", headers=AL).json()
    assert kpi["facturacion"] == "-20000.0000" and kpi["recaudo"] == "180000.0000"
    assert kpi["eficiencia"] is None
    edades = analista.get(
        "/api/v1/comercial/vatia/analisis/cartera-edades/202606", headers=AL
    ).json()
    assert [b["edad"] for b in edades["bandas"]] == ["Al día", "30 días", "60 días"]
    catalogo = analista.get("/api/v1/comercial/vatia/catalogo", headers=AL).json()
    assert len(catalogo) == 29
    assert {c["id"]: c["estado"] for c in catalogo}["control-tarifario"] == "no_aplica"
    assert (
        analista.get(
            "/api/v1/comercial/vatia/analisis/control-tarifario/202606", headers=AL
        ).status_code
        == 422
    )


# --- Entregables, hallazgos y permisos -----------------------------------------------------------


def test_entregables_anexo_con_tope_y_hallazgos(
    analista: TestClient, db_configurado: Session
) -> None:
    _cargar(analista, db_configurado, MT, "afinia", "202607", _corte_afinia("202607"))
    cuerpo = {"periodo": "202607"}
    req = analista.post(
        "/api/v1/comercial/afinia/entregables/requerimiento", headers=MT, json=cuerpo
    )
    assert req.status_code == 200 and req.content[:2] == b"PK"
    html = analista.post("/api/v1/comercial/afinia/entregables/analisis", headers=MT, json=cuerpo)
    assert "<html" in html.text
    pdf = analista.post(
        "/api/v1/comercial/afinia/entregables/informe-gerencial", headers=MT, json=cuerpo
    )
    assert pdf.content.startswith(b"%PDF-") and len(pdf.content) > 1000
    anexo = analista.post(
        "/api/v1/comercial/afinia/entregables/anexo-nominal", headers=MT, json=cuerpo
    )
    assert anexo.status_code == 200
    hojas = load_workbook(io.BytesIO(anexo.content)).sheetnames
    assert "Cobros por encima" in hojas
    recortado = analista.post(
        "/api/v1/comercial/afinia/entregables/anexo-nominal",
        headers=MT,
        json={**cuerpo, "max_filas": 1},
    )
    assert recortado.status_code == 409

    falta = analista.post(
        "/api/v1/comercial/afinia/hallazgos",
        headers=MT,
        json={"tipo": "ANOMALIA", "estado": "ABIERTO", "decision": "x y"},
    )
    assert falta.status_code == 422
    creado = analista.post(
        "/api/v1/comercial/afinia/hallazgos",
        headers=MT,
        json={"tipo": "RUTA", "responsable": "Analista", "decision": "Visitar", "nic": "9002"},
    )
    assert creado.status_code == 201, creado.text
    assert creado.json()["identificador"] == "9002"
    editado = analista.patch(
        f"/api/v1/comercial/afinia/hallazgos/{creado.json()['id']}",
        headers=MT,
        json={"estado": "RESUELTO", "decision": "Confirmado"},
    )
    assert editado.json()["estado"] == "RESUELTO"
    cruzado = analista.patch(
        f"/api/v1/comercial/celsia/hallazgos/{creado.json()['id']}",
        headers=AL,
        json={"estado": "ABIERTO"},
    )
    assert cruzado.status_code == 404


def test_sin_permiso_nominal_no_ve_datos_de_usuarios(
    analista: TestClient, db_configurado: Session
) -> None:
    _cargar(analista, db_configurado, MT, "afinia", "202607", _corte_afinia("202607"))
    db_configurado.execute(
        text("INSERT INTO rol (codigo, nombre, activo) VALUES ('SIN_NOMINAL', 'Sin nominal', true)")
    )
    db_configurado.execute(
        text(
            "INSERT INTO rol_permiso (rol_id, permiso_id) SELECT r.id, p.id FROM rol r, permiso p "
            "WHERE r.codigo = 'SIN_NOMINAL' AND p.codigo IN ('comercial.analisis.ver', "
            "'comercial.entregable.generar')"
        )
    )
    db_configurado.commit()
    crear_usuario_db(
        db_configurado,
        nombre_usuario="sin_nominal",
        correo="sn@sapef.test",
        rol_codigo="SIN_NOMINAL",
        sede_codigos=["montelibano"],
    )
    limitado = TestClient(crear_app())
    iniciar_sesion_cliente(limitado, "sin_nominal")
    assert (
        limitado.get("/api/v1/comercial/afinia/analisis/indicadores/202607", headers=MT).status_code
        == 200
    )
    for metodo, ruta in (
        ("GET", "/api/v1/comercial/afinia/analisis/trazabilidad/9001"),
        ("GET", "/api/v1/comercial/afinia/analisis/control-tarifario/202607"),
        ("GET", "/api/v1/comercial/afinia/cortes/202607/datos?familia=catastro"),
        ("GET", "/api/v1/comercial/afinia/hallazgos"),
    ):
        assert limitado.request(metodo, ruta, headers=MT).status_code == 403, ruta
    anexo = limitado.post(
        "/api/v1/comercial/afinia/entregables/anexo-nominal", headers=MT, json={"periodo": "202607"}
    )
    assert anexo.status_code == 403
