"""Pruebas unitarias de reglas puras del dominio de archivos (magic bytes, XSS, nombres)."""

import io
import zipfile
from datetime import UTC, datetime

import pytest

from app.modulos.archivos import dominio


def _xlsx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", "<workbook/>")
    return buf.getvalue()


def test_sanitizar_nombre_evita_path_traversal_y_control():
    assert dominio.sanitizar_nombre_archivo("../../../../etc/passwd") == "passwd"
    assert dominio.sanitizar_nombre_archivo("..\\..\\Windows\\cmd.exe") == "cmd.exe"
    assert dominio.sanitizar_nombre_archivo("foto\x00\nposte.jpg") == "fotoposte.jpg"
    assert dominio.sanitizar_nombre_archivo("...") == "archivo"
    largo = "a" * 300 + ".jpeg"
    sanitizado = dominio.sanitizar_nombre_archivo(largo)
    assert len(sanitizado) <= 255
    assert sanitizado.endswith(".jpeg")


def test_detectar_mime_formatos_validos():
    assert dominio.detectar_mime_por_magic_bytes(b"\xff\xd8\xff\xe0jpg", "f.jpg") == "image/jpeg"
    assert (
        dominio.detectar_mime_por_magic_bytes(b"\x89PNG\r\n\x1a\npng", "f.png") == "image/png"
    )
    assert (
        dominio.detectar_mime_por_magic_bytes(b"RIFF1234WEBPdata", "f.webp") == "image/webp"
    )
    assert dominio.detectar_mime_por_magic_bytes(b"%PDF-1.7\n", "doc.pdf") == "application/pdf"
    assert (
        dominio.detectar_mime_por_magic_bytes(b"\x1f\x9d\x90datos", "F123.Z")
        == "application/x-compress"
    )
    assert (
        dominio.detectar_mime_por_magic_bytes(_xlsx_bytes(), "carga.xlsx")
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert dominio.detectar_mime_por_magic_bytes(b"OggS\x00\x02", "nota.ogg") == "audio/ogg"
    assert (
        dominio.detectar_mime_por_magic_bytes(b"\x00\x00\x00\x20ftypM4A ", "v.m4a")
        == "audio/mp4"
    )
    assert dominio.detectar_mime_por_magic_bytes(b"RIFF1234WAVEfmt ", "a.wav") == "audio/wav"
    assert dominio.detectar_mime_por_magic_bytes(b"nic;valor\n1;2\n", "datos.csv") == "text/csv"


def test_rechaza_ejecutables_svg_html_y_spoofing():
    for payload, nombre in [
        (b"", "vacio.jpg"),
        (b"MZ\x90\x00exe", "foto.jpg"),
        (b"\x7fELF\x02\x01", "binario.png"),
        (b"#!/bin/sh\nrm -rf /", "script.txt"),
        (b"<svg onload=alert(1)></svg>", "icono.jpg"),
        (b"<?xml version='1.0'?><svg><script>alert(1)</script></svg>", "vector.png"),
        (b"<!DOCTYPE html><html><script>1</script></html>", "pagina.csv"),
        (b"\x00\x01\x02\x03random", "raro.bin"),
    ]:
        with pytest.raises(dominio.ErrorDominioArchivo) as exc:
            dominio.detectar_mime_por_magic_bytes(payload, nombre)
        assert exc.value.status_code in (400, 415)


def test_rechaza_zip_sin_estructura_ooxml_como_xlsx():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("malicioso.exe", b"MZ")
    with pytest.raises(dominio.ErrorDominioArchivo) as exc:
        dominio.detectar_mime_por_magic_bytes(buf.getvalue(), "falso.xlsx")
    assert exc.value.status_code == 415


def test_validacion_categoria_y_cabeceras_descarga():
    dominio.validar_mime_para_categoria("image/jpeg", "evidencia")
    dominio.validar_mime_para_categoria("application/x-compress", "cargue")

    with pytest.raises(dominio.ErrorDominioArchivo):
        dominio.validar_mime_para_categoria("application/x-compress", "evidencia")
    with pytest.raises(dominio.ErrorDominioArchivo):
        dominio.validar_mime_para_categoria("image/jpeg", "cargue")

    ruta = dominio.construir_ruta_relativa(1, "abcdef123456", datetime(2026, 11, 23, tzinfo=UTC))
    assert ruta == "sede_1/2026/11/ab/abcdef123456"

    disp_img = dominio.construir_content_disposition("foto poste.jpg", "image/jpeg", False)
    assert disp_img.startswith("inline;")
    disp_forzado = dominio.construir_content_disposition("foto poste.jpg", "image/jpeg", True)
    assert disp_forzado.startswith("attachment;")
    mime_xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    disp_xlsx = dominio.construir_content_disposition("reporte.xlsx", mime_xlsx, False)
    assert disp_xlsx.startswith("attachment;")
