"""Pruebas de integración y aislamiento para activos (EP-03) y migración (IMP-1, IMP-6)."""

import io
import math

from openpyxl import Workbook

from app.modulos.migracion import servicio as migracion_servicio
from tests.conftest import crear_usuario_db, iniciar_sesion_cliente


def _crear_xlsx_luminarias() -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Luminarias"
    ws.append(
        [
            "codigo",
            "barrio",
            "latitud",
            "longitud",
            "estado",
            "marca",
            "tecnologia",
            "potencia",
            "fecha_instalacion",
            "poste",
            "es_rural",
        ]
    )
    ws.append(
        [
            "IMP-LUM-01",
            "El Centro",
            7.9801,
            -75.4171,
            "121",
            "KÜNIX",
            "MH",
            1947,
            "01/01/1900",
            "P-01",
            False,
        ]
    )
    ws.append(
        [
            "IMP-LUM-02",
            "San Felipe",
            7.9811,
            -75.4181,
            "124",
            "SCHRÉDER",
            "Led",
            70,
            "2025-05-14",
            "P-02",
            True,
        ]
    )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_crud_luminarias_ubicacion_lote_mvt_pmtiles_y_aislamiento(cliente, db_configurado) -> None:
    crear_usuario_db(
        db_configurado,
        nombre_usuario="admin_mt",
        correo="admin_mt@sapef.local",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano"],
    )
    crear_usuario_db(
        db_configurado,
        nombre_usuario="censo_al",
        correo="censo_al@sapef.local",
        rol_codigo="CENSO",
        sede_codigos=["alcala"],
    )
    iniciar_sesion_cliente(cliente, "admin_mt")

    barrio_id = cliente.get("/api/v1/barrios", headers={"X-Sede": "montelibano"}).json()[0]["id"]
    estados = cliente.get("/api/v1/estados", params={"proceso": "luminaria"}).json()
    est_121 = next(e["id"] for e in estados if e["codigo"] == "121")
    tech_id = cliente.get("/api/v1/maestros/LUMINARIA_TECNOLOGIA").json()[0]["id"]
    pot_id = cliente.get("/api/v1/maestros/LUMINARIA_POTENCIA").json()[0]["id"]
    marca_id = cliente.get("/api/v1/maestros/LUMINARIA_MARCA").json()[0]["id"]

    creada = cliente.post(
        "/api/v1/luminarias",
        headers={"X-Sede": "montelibano"},
        json={
            "codigo": "LUM-TEST-001",
            "barrio_id": barrio_id,
            "latitud": 7.9801,
            "longitud": -75.4171,
            "estado_id": est_121,
            "tecnologia_id": tech_id,
            "potencia_id": pot_id,
            "marca_id": marca_id,
        },
    )
    assert creada.status_code == 201, creada.text
    lum_id = creada.json()["id"]
    assert creada.json()["zona_id"] is not None
    assert "google.com/maps" in (creada.json()["google_maps_url"] or "")

    # Duplicado -> 409
    dup = cliente.post(
        "/api/v1/luminarias",
        headers={"X-Sede": "montelibano"},
        json={
            "codigo": "LUM-TEST-001",
            "barrio_id": barrio_id,
            "estado_id": est_121,
        },
    )
    assert dup.status_code == 409

    # Mover ubicación y verificar historial
    movida = cliente.post(
        f"/api/v1/luminarias/{lum_id}/ubicacion",
        headers={"X-Sede": "montelibano"},
        json={"latitud": 7.9815, "longitud": -75.4165, "origen": "web"},
    )
    assert movida.status_code == 200
    hist = cliente.get(
        f"/api/v1/luminarias/{lum_id}/historial", headers={"X-Sede": "montelibano"}
    ).json()
    assert len(hist["ubicaciones"]) == 1
    assert {"alta", "cambio_ubicacion"}.issubset({e["tipo"] for e in hist["eventos"]})

    # MVT y PMTiles
    n = 2**14
    tx = int((-75.4165 + 180.0) / 360.0 * n)
    ty = int((1.0 - math.asinh(math.tan(math.radians(7.9815))) / math.pi) / 2.0 * n)
    mvt = cliente.get(
        f"/api/v1/mapa/luminarias/14/{tx}/{ty}.mvt", headers={"X-Sede": "montelibano"}
    )
    assert mvt.status_code == 200
    assert mvt.headers["content-type"].startswith("application/vnd.mapbox-vector-tile")
    assert len(mvt.content) > 0

    pm = cliente.get("/api/v1/mapa/base/montelibano.pmtiles", headers={"Range": "bytes=0-511"})
    assert pm.status_code == 206
    assert pm.content[:7] == b"PMTiles"
    assert len(pm.content) == 512
    assert int(pm.headers["content-range"].split("/")[1]) > 100_000

    # Lote por consecutivos + solapamiento 409
    lote = cliente.post(
        "/api/v1/lotes",
        headers={"X-Sede": "montelibano"},
        json={
            "consecutivo_inicial": 5001,
            "consecutivo_final": 5003,
            "cantidad": 3,
            "tecnologia_id": tech_id,
            "potencia_id": pot_id,
            "marca_id": marca_id,
            "orden_compra": "OC-100",
        },
    )
    assert lote.status_code == 201
    solapado = cliente.post(
        "/api/v1/lotes",
        headers={"X-Sede": "montelibano"},
        json={
            "consecutivo_inicial": 5002,
            "consecutivo_final": 5004,
            "cantidad": 3,
            "tecnologia_id": tech_id,
            "potencia_id": pot_id,
        },
    )
    assert solapado.status_code == 409

    # Exportar en segundo plano (202)
    exp = cliente.post(
        "/api/v1/luminarias/exportar",
        headers={"X-Sede": "montelibano"},
        json={"texto": "LUM-TEST-001"},
    )
    assert exp.status_code == 202
    assert isinstance(exp.json()["tareaId"], int)

    # Importador de luminarias idempotente
    xlsx = _crear_xlsx_luminarias()
    mime_xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    imp1 = cliente.post(
        "/api/v1/migracion/luminarias",
        headers={"X-Sede": "montelibano"},
        files={"archivo": ("lums.xlsx", xlsx, mime_xlsx)},
    )
    assert imp1.status_code == 202, imp1.text
    assert imp1.json()["estado"] == "pendiente"
    migracion_servicio.procesar_ejecucion(db_configurado, imp1.json()["ejecucion_id"])
    res1 = cliente.get(
        f"/api/v1/migracion/ejecuciones/{imp1.json()['ejecucion_id']}",
        headers={"X-Sede": "montelibano"},
    )
    assert res1.json()["estado"] == "completado", res1.text
    assert res1.json()["conciliacion"]["creadas"] == 2

    imp2 = cliente.post(
        "/api/v1/migracion/luminarias",
        headers={"X-Sede": "montelibano"},
        files={"archivo": ("lums.xlsx", xlsx, mime_xlsx)},
    )
    assert imp2.status_code == 202
    migracion_servicio.procesar_ejecucion(db_configurado, imp2.json()["ejecucion_id"])
    res2 = cliente.get(
        f"/api/v1/migracion/ejecuciones/{imp2.json()['ejecucion_id']}",
        headers={"X-Sede": "montelibano"},
    )
    assert res2.json()["conciliacion"]["creadas"] == 0
    assert res2.json()["conciliacion"]["actualizadas"] == 2

    # Aislamiento estricto: usuario de Alcalá no ve luminaria ni PMTiles de Montelíbano
    iniciar_sesion_cliente(cliente, "censo_al")
    assert (
        cliente.get(f"/api/v1/luminarias/{lum_id}", headers={"X-Sede": "alcala"}).status_code == 404
    )
    assert (
        cliente.get(f"/api/v1/luminarias/{lum_id}", headers={"X-Sede": "montelibano"}).status_code
        == 403
    )
    assert cliente.get("/api/v1/mapa/base/montelibano.pmtiles").status_code == 403
