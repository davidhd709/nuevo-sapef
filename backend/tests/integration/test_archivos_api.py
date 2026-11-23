"""Pruebas de integración reales para el módulo transversal de archivos y evidencias (F3-1)."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.config import obtener_configuracion
from app.modulos.archivos import servicio as archivos_servicio
from tests.conftest import construir_xlsx_minimo_bytes, crear_usuario_db, iniciar_sesion_cliente

PNG_MINIMO = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
JPEG_MINIMO = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01"


def test_subida_descarga_metadatos_e_idempotencia(cliente: TestClient, db, almacen_temporal):
    crear_usuario_db(
        db,
        nombre_usuario="tecnico1",
        correo="tec1@sapef.com",
        rol_codigo="TECNICO",
        sede_codigos=["montelibano"],
    )
    iniciar_sesion_cliente(cliente, "tecnico1")

    headers = {"X-Sede": "montelibano", "Idempotency-Key": "op-uuid-001"}
    r1 = cliente.post(
        "/api/v1/archivos",
        headers=headers,
        files={"archivo": ("../../../../etc/poste.png", PNG_MINIMO, "image/png")},
        data={"categoria": "evidencia"},
    )
    assert r1.status_code == 201
    meta = r1.json()
    assert meta["nombre_original"] == "poste.png"
    assert meta["tipo_mime"] == "image/png"
    assert meta["tamano"] == len(PNG_MINIMO)
    assert "ruta" not in meta

    # Replay idempotente con mismo contenido -> 200 con mismo UUID
    r_replay = cliente.post(
        "/api/v1/archivos",
        headers=headers,
        files={"archivo": ("poste.png", PNG_MINIMO, "image/png")},
        data={"categoria": "evidencia"},
    )
    assert r_replay.status_code == 200
    assert r_replay.json()["id"] == meta["id"]

    # Misma Idempotency-Key con contenido distinto -> 409 Conflict
    r_conflicto = cliente.post(
        "/api/v1/archivos",
        headers=headers,
        files={"archivo": ("otro.jpg", JPEG_MINIMO, "image/jpeg")},
        data={"categoria": "evidencia"},
    )
    assert r_conflicto.status_code == 409

    # Metadatos y descarga con cabeceras seguras
    r_meta = cliente.get(
        f"/api/v1/archivos/{meta['id']}/metadatos",
        headers={"X-Sede": "montelibano"},
    )
    assert r_meta.status_code == 200
    assert "ruta" not in r_meta.json()

    r_dl = cliente.get(
        f"/api/v1/archivos/{meta['id']}",
        headers={"X-Sede": "montelibano"},
    )
    assert r_dl.status_code == 200
    assert r_dl.content == PNG_MINIMO
    assert r_dl.headers["x-content-type-options"] == "nosniff"
    assert r_dl.headers["content-type"].startswith("image/png")
    assert r_dl.headers["content-disposition"].startswith("inline;")
    assert r_dl.headers["etag"] == f'"{meta["sha256"]}"'

    r_dl_att = cliente.get(
        f"/api/v1/archivos/{meta['id']}?descargar=true",
        headers={"X-Sede": "montelibano"},
    )
    assert r_dl_att.status_code == 200
    assert r_dl_att.headers["content-disposition"].startswith("attachment;")


def test_rechaza_vacio_tamano_excedido_y_magic_bytes_falsos(
    cliente: TestClient, db, almacen_temporal, monkeypatch
):
    crear_usuario_db(
        db,
        nombre_usuario="cargador",
        correo="carg@sapef.com",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano"],
    )
    iniciar_sesion_cliente(cliente, "cargador")

    # Archivo vacío -> 400
    r_vacio = cliente.post(
        "/api/v1/archivos",
        headers={"X-Sede": "montelibano"},
        files={"archivo": ("vacio.png", b"", "image/png")},
    )
    assert r_vacio.status_code == 400

    # Spoofing XSS / EXE disfrazados como JPEG -> 415
    for payload in (b"<svg><script>alert(1)</script></svg>", b"MZ\x90\x00exe"):
        r_bad = cliente.post(
            "/api/v1/archivos",
            headers={"X-Sede": "montelibano"},
            files={"archivo": ("falso.jpg", payload, "image/jpeg")},
        )
        assert r_bad.status_code == 415

    # Límite de tamaño excedido -> 413 sin dejar basura en disco
    monkeypatch.setenv("SAPEF_ARCHIVO_MAX_EVIDENCIA_MB", "1")
    obtener_configuracion.cache_clear()
    excedido = b"\x89PNG\r\n\x1a\n" + (b"A" * (1024 * 1024 + 10))
    r_big = cliente.post(
        "/api/v1/archivos",
        headers={"X-Sede": "montelibano"},
        files={"archivo": ("grande.png", excedido, "image/png")},
    )
    assert r_big.status_code == 413
    assert list(almacen_temporal.rglob("*")) == []

    # Categoría cargue acepta XLSX real
    r_xlsx = cliente.post(
        "/api/v1/archivos",
        headers={"X-Sede": "montelibano"},
        files={
            "archivo": (
                "cargue.xlsx",
                construir_xlsx_minimo_bytes(),
                "application/octet-stream",
            )
        },
        data={"categoria": "cargue"},
    )
    assert r_xlsx.status_code == 201


def test_registrar_evidencia_con_geometria_postgis(db, almacen_temporal):
    u = crear_usuario_db(
        db,
        nombre_usuario="geo_tec",
        correo="geo@sapef.com",
        rol_codigo="TECNICO",
        sede_codigos=["montelibano"],
    )
    archivo, _ = archivos_servicio.guardar_archivo(
        db,
        sede_id=1,
        archivo_bytes=JPEG_MINIMO,
        nombre="poste_gps.jpg",
        categoria="evidencia",
        idempotency_key="ev-gps-1",
        subido_por_id=u.id,
    )
    ev = archivos_servicio.registrar_evidencia(
        db,
        sede_id=1,
        entidad="orden",
        entidad_id="1001",
        tipo="foto",
        archivo_id=archivo.id,
        creado_por=u.id,
        latitud=7.9801,
        longitud=-75.4172,
    )
    assert ev.sede_id == 1
    assert ev.archivo_id == archivo.id
    assert ev.latitud == 7.9801


def test_registrar_evidencia_rechaza_gps_parcial_con_422(db, almacen_temporal):
    u = crear_usuario_db(
        db,
        nombre_usuario="geo_parcial",
        correo="geoparcial@sapef.co",
        rol_codigo="TECNICO",
        sede_codigos=["montelibano"],
    )
    archivo, _ = archivos_servicio.guardar_archivo(
        db,
        sede_id=1,
        archivo_bytes=JPEG_MINIMO,
        nombre="poste_parcial.jpg",
        categoria="evidencia",
        idempotency_key="ev-gps-parcial",
        subido_por_id=u.id,
    )

    with pytest.raises(HTTPException) as exc_solo_lat:
        archivos_servicio.registrar_evidencia(
            db,
            sede_id=1,
            entidad="orden",
            entidad_id="1002",
            tipo="foto",
            archivo_id=archivo.id,
            creado_por=u.id,
            latitud=7.9801,
            longitud=None,
        )
    assert exc_solo_lat.value.status_code == 422

    with pytest.raises(HTTPException) as exc_solo_lon:
        archivos_servicio.registrar_evidencia(
            db,
            sede_id=1,
            entidad="orden",
            entidad_id="1002",
            tipo="foto",
            archivo_id=archivo.id,
            creado_por=u.id,
            latitud=None,
            longitud=-75.4172,
        )
    assert exc_solo_lon.value.status_code == 422

    ev_sin_gps = archivos_servicio.registrar_evidencia(
        db,
        sede_id=1,
        entidad="orden",
        entidad_id="1002",
        tipo="foto",
        archivo_id=archivo.id,
        creado_por=u.id,
        latitud=None,
        longitud=None,
    )
    assert ev_sin_gps.latitud is None
    assert ev_sin_gps.longitud is None
