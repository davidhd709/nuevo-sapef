"""R1: lectura de las exportaciones reales de SAPEF (CSV) y normalización para los importadores.

Los encabezados y formatos imitan los de las exportaciones de SAPEF Montelíbano (SPIKE-03), con
datos inventados.
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.modulos.migracion import dominio


def test_csv_con_bom_linea_sep_y_punto_y_coma() -> None:
    contenido = (
        "﻿sep=;\r\n"
        "codigo;barrio;fecha_instalacion;estado;latitud;longitud\r\n"
        " SN 23A;BODEGA;18/02/2019;Bodega de baja;7.98195;-75.41606\r\n"
        "\r\n"
        "100-22;LA LUCHA;12/05/2022;Activo en operación;;\r\n"
    ).encode()
    filas = dominio.leer_tabla(contenido)["csv"]
    assert len(filas) == 2
    assert filas[0]["codigo"] == "SN 23A"
    assert filas[0]["estado"] == "Bodega de baja"
    assert filas[1]["latitud"] is None


def test_csv_con_tabulador_y_encabezados_con_espacios() -> None:
    contenido = (
        b"codigo\tcodigo mantenimiento\tfotocelda\tlongitud\r\n30-150\t17068\tFalse\t75.43\r\n"
    )
    filas = dominio.leer_tabla(contenido)["csv"]
    assert filas == [
        {
            "codigo": "30-150",
            "codigo_mantenimiento": "17068",
            "fotocelda": "False",
            "longitud": "75.43",
        }
    ]


def test_csv_en_cp1252_y_rechazo_de_formulas() -> None:
    assert (
        dominio.leer_tabla("barrio;zona\nCañaveral;Sur\n".encode("cp1252"))["csv"][0]["barrio"]
        == "Cañaveral"
    )
    with pytest.raises(dominio.ErrorDominioMigracion):
        dominio.leer_tabla(b'codigo;valor\nA;=HYPERLINK("x")\n')
    # Un número negativo no es una fórmula
    assert dominio.leer_tabla(b"a;b\n1;=5\n")["csv"][0]["b"] == "=5"


def test_archivo_binario_que_no_es_excel_se_rechaza() -> None:
    with pytest.raises(dominio.ErrorDominioMigracion):
        dominio.leer_tabla(b"%PDF-1.7\x00\x00\x00")


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("29/07/2024 14:51:14", dt.datetime(2024, 7, 29, 14, 51, 14)),
        ("2/25/2019 5:38:52 AM", dt.datetime(2019, 2, 25, 5, 38, 52)),
        ("3/9/2026 1:05:00 PM", dt.datetime(2026, 3, 9, 13, 5)),
        ("12/1/2026 12:10:00 AM", dt.datetime(2026, 12, 1, 0, 10)),
        ("11/11/2026", dt.datetime(2026, 11, 11)),
        ("2026-11-19T15:53:47", dt.datetime(2026, 11, 19, 15, 53, 47)),
        ("01/01/1900 00:00:00", None),
        ("1/1/1900 12:00:00 AM", None),
        ("", None),
        (None, None),
    ],
)
def test_fechas_de_sapef(valor: object, esperado: dt.datetime | None) -> None:
    assert dominio.normalizar_fecha_hora_sapef(valor) == esperado


def test_fecha_corrida_de_columna_es_error_de_fila() -> None:
    # SAPEF a veces corre las columnas: llega una coordenada donde va la fecha.
    with pytest.raises(dominio.ErrorDominioMigracion):
        dominio.normalizar_fecha_hora_sapef("-75.412766")
    assert dominio.normalizar_fecha_sapef("18/02/2019") == dt.date(2019, 2, 18)


def test_coordenadas_corrige_longitud_sin_signo_y_rechaza_fuera_de_colombia() -> None:
    assert dominio.coordenadas_colombia("7.979938", "75.434805") == (
        7.979938,
        -75.434805,
        "Longitud sin signo negativo; se corrigió.",
    )
    assert dominio.coordenadas_colombia("7,98", "-75,41") == (7.98, -75.41, None)
    assert dominio.coordenadas_colombia(None, None) == (None, None, None)
    assert dominio.coordenadas_colombia("0", "0") == (None, None, None)
    with pytest.raises(dominio.ErrorDominioMigracion):
        dominio.coordenadas_colombia("40.4", "-3.7")


def test_prioridad_identificacion_y_potencia() -> None:
    assert dominio.normalizar_prioridad("MEDIA") == 2
    assert dominio.normalizar_prioridad("urgente") == 0
    assert dominio.normalizar_prioridad(1) == 1
    assert dominio.normalizar_prioridad(None) == 2
    with pytest.raises(dominio.ErrorDominioMigracion):
        dominio.normalizar_prioridad(7)
    assert dominio.normalizar_identificacion("50.929.069") == "50929069"
    assert dominio.normalizar_identificacion(1234567.0) == "1234567"
    assert dominio.potencia_atipica("4893")
    assert not dominio.potencia_atipica("1000")
    assert not dominio.potencia_atipica(None)


def test_columnas_de_clave_se_detectan_para_ignorarlas() -> None:
    filas = [{"nombre_usuario": "x", "password": "secreta"}, {"hash_clave": "abc"}]
    assert dominio.columnas_clave(filas) == ["hash_clave", "password"]


def test_hoja_por_nombre_o_unica_y_alias_de_columnas() -> None:
    libro = {"Luminarias": [{"codigo": "A"}], "Otra": []}
    assert dominio.hoja(libro, "luminarias") == [{"codigo": "A"}]
    assert dominio.hoja({"csv": [{"codigo": "B"}]}, "Luminarias") == [{"codigo": "B"}]
    assert dominio.hoja(libro, "Bodega") == []
    fila = {"luminaria_codigo": None, "codigo": "  30-150 ", "rowid": 17.0}
    assert dominio.texto(fila, "luminaria_codigo", "codigo") == "30-150"
    assert dominio.texto(fila, "rowid") == "17"
    assert dominio.decimal_no_negativo("25", "existencias") == Decimal("25.0")


# --- R1: endurecimiento de archivos (Tier 2) ---------------------------------------------------


def test_extension_que_contradice_el_contenido_da_415() -> None:
    from app.modulos.archivos import dominio as archivos

    with pytest.raises(archivos.ErrorDominioArchivo) as exc:
        archivos.detectar_mime_por_magic_bytes(b"%PDF-1.7\n", "foto_falsa.png")
    assert exc.value.status_code == 415
    with pytest.raises(archivos.ErrorDominioArchivo):
        archivos.detectar_mime_por_magic_bytes(b"\x89PNG\r\n\x1a\nxx", "foto.jpg")
    # Lo que envía la app de campo sigue entrando
    assert archivos.detectar_mime_por_magic_bytes(b"\xff\xd8\xff\xe0x", "foto.JPG") == "image/jpeg"
    assert archivos.detectar_mime_por_magic_bytes(b"\x89PNG\r\n\x1a\nx", "firma.png") == "image/png"
    assert (
        archivos.detectar_mime_por_magic_bytes(b"\x00\x00\x00\x20ftypM4A ", "nota_voz.m4a")
        == "audio/mp4"
    )
    assert (
        archivos.detectar_mime_por_magic_bytes(b"\x1a\x45\xdf\xa3x", "nota_voz.webm")
        == "audio/webm"
    )
    # Sin extensión se decide solo por el contenido
    assert archivos.detectar_mime_por_magic_bytes(b"%PDF-1.7\n", "documento") == "application/pdf"
