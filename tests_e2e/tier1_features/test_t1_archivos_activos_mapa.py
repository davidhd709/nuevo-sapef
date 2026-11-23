"""Tier 1 E2E tests for EP-03 Archivos, Activos y Mapa + F0-5 (F3-1..F3-6)."""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fixtures.media_builder import make_jpeg, make_pdf, make_png
from fixtures.operational_builder import generate_coordinates
from harness.browser import BrowserDriver
from harness.client import SapefClient
from harness.config import E2EConfig
from harness.db import DbHelper


def _admin_creds(e2e_config: E2EConfig) -> tuple[str, str]:
    assert e2e_config.admin_password, (
        "SAPEF_E2E_ADMIN_PASSWORD must be configured to run authenticated E2E tests"
    )
    return e2e_config.admin_user, e2e_config.admin_password


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [dict(item) for item in payload["items"]]
    raise AssertionError(f"Unexpected list/paginated payload: {payload!r}")


def _latlng_to_tile(lat: float, lng: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    x = int((lng + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _resolve_mtl_catalogs(admin: SapefClient) -> dict[str, Any]:
    barrios = _extract_items(admin.get("/api/v1/barrios", sede="montelibano").json())
    barrio = next((b for b in barrios if b["nombre"] == "El Centro"), barrios[0])

    estados = _extract_items(
        admin.get("/api/v1/estados", omit_sede=True, params={"proceso": "luminaria"}).json()
    )
    est_121 = next(e for e in estados if str(e["codigo"]) == "121")
    est_124 = next(e for e in estados if str(e["codigo"]) == "124")

    techs = _extract_items(admin.get("/api/v1/maestros/LUMINARIA_TECNOLOGIA", omit_sede=True).json())
    tech_led = next(t for t in techs if t["codigo"] == "LED")

    pots = _extract_items(admin.get("/api/v1/maestros/LUMINARIA_POTENCIA", omit_sede=True).json())
    pot_70 = next((p for p in pots if str(p["codigo"]) == "70"), pots[0])

    marcas = _extract_items(admin.get("/api/v1/maestros/LUMINARIA_MARCA", omit_sede=True).json())
    marca_philips = next((m for m in marcas if m["codigo"] == "PHILIPS"), marcas[0])

    return {
        "barrio": barrio,
        "estado_121": est_121,
        "estado_124": est_124,
        "tech_led": tech_led,
        "pot_70": pot_70,
        "marca_philips": marca_philips,
    }


def _browser_errors(driver: BrowserDriver) -> list[str]:
    errs: list[str] = []
    for ev in driver.events:
        method = ev.get("method")
        params = ev.get("params", {})
        if method == "Runtime.exceptionThrown":
            errs.append(f"JS exception: {json.dumps(params)}")
        elif method == "Runtime.consoleAPICalled" and params.get("type") == "error":
            errs.append(f"Console error: {json.dumps(params)}")
    return errs


@pytest.mark.tier1
def test_archivos_upload_png_jpeg_pdf_idempotency_and_download(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    samples = [
        ("evidencia.png", make_png(8, 8), "image/png"),
        ("evidencia.jpg", make_jpeg(), "image/jpeg"),
        ("acta.pdf", make_pdf("SAPEF Archivo E2E"), "application/pdf"),
    ]

    png_idem_key = str(uuid.uuid4())
    png_file_id: str | None = None

    for idx, (fname, raw_bytes, mime) in enumerate(samples):
        idem_key = png_idem_key if idx == 0 else str(uuid.uuid4())
        expected_sha = hashlib.sha256(raw_bytes).hexdigest()

        up_resp = admin.post(
            "/api/v1/archivos",
            sede="montelibano",
            idempotency_key=idem_key,
            files={"archivo": (fname, raw_bytes, mime)},
        )
        assert up_resp.status_code in {200, 201}, up_resp.text
        meta = up_resp.json()
        assert meta["id"]
        assert meta["sha256"] == expected_sha
        assert int(meta["tamano"]) == len(raw_bytes)
        if idx == 0:
            png_file_id = str(meta["id"])

        dl_resp = admin.get(f"/api/v1/archivos/{meta['id']}", sede="montelibano")
        assert dl_resp.status_code == 200
        assert dl_resp.content == raw_bytes

    replay_resp = admin.post(
        "/api/v1/archivos",
        sede="montelibano",
        idempotency_key=png_idem_key,
        files={"archivo": ("evidencia.png", samples[0][1], "image/png")},
    )
    assert replay_resp.status_code in {200, 201}, replay_resp.text
    assert str(replay_resp.json()["id"]) == png_file_id
    assert replay_resp.json()["sha256"] == hashlib.sha256(samples[0][1]).hexdigest()


@pytest.mark.tier1
def test_luminaria_postgis_crud_derived_zona_and_evento_alta(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    cat = _resolve_mtl_catalogs(admin)

    lat, lng = generate_coordinates("montelibano", 1, seed=11)[0]
    suffix = uuid.uuid4().hex[:6].upper()
    codigo = f"{run_id}-LUM-{suffix}"

    create_resp = admin.post(
        "/api/v1/luminarias",
        sede="montelibano",
        json_body={
            "codigo": codigo,
            "barrio_id": cat["barrio"]["id"],
            "latitud": lat,
            "longitud": lng,
            "estado_id": cat["estado_121"]["id"],
            "tecnologia_id": cat["tech_led"]["id"],
            "potencia_id": cat["pot_70"]["id"],
            "marca_id": cat["marca_philips"]["id"],
            "poste": f"P-{suffix}",
            "es_rural": False,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    lum = create_resp.json()
    lum_id = lum["id"]
    assert lum["codigo"] == codigo
    assert float(lum["latitud"]) == pytest.approx(lat, abs=1e-4)
    assert float(lum["longitud"]) == pytest.approx(lng, abs=1e-4)
    expected_zona_id = cat["barrio"]["zona_id"]
    if "zona_id" in lum:
        assert lum["zona_id"] == expected_zona_id
    elif isinstance(lum.get("zona"), dict):
        assert lum["zona"]["id"] == expected_zona_id

    get_resp = admin.get(f"/api/v1/luminarias/{lum_id}", sede="montelibano")
    assert get_resp.status_code == 200
    assert get_resp.json()["codigo"] == codigo

    patch_resp = admin.patch(
        f"/api/v1/luminarias/{lum_id}",
        sede="montelibano",
        json_body={"poste": f"P-{suffix}-UPD", "observaciones": f"Actualizada {run_id}"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["poste"] == f"P-{suffix}-UPD"

    hist_resp = admin.get(f"/api/v1/luminarias/{lum_id}/historial", sede="montelibano")
    assert hist_resp.status_code == 200
    hist = hist_resp.json()
    event_types = {str(e.get("tipo", e.get("evento_tipo", ""))).lower() for e in hist["eventos"]}
    assert "alta" in event_types


@pytest.mark.tier1
def test_luminaria_relocation_logs_ubicacion_and_evento_cambio_ubicacion(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    cat = _resolve_mtl_catalogs(admin)

    (lat1, lng1), (lat2, lng2) = generate_coordinates("montelibano", 2, seed=22)
    suffix = uuid.uuid4().hex[:6].upper()
    create_resp = admin.post(
        "/api/v1/luminarias",
        sede="montelibano",
        json_body={
            "codigo": f"{run_id}-MOV-{suffix}",
            "barrio_id": cat["barrio"]["id"],
            "latitud": lat1,
            "longitud": lng1,
            "estado_id": cat["estado_121"]["id"],
            "tecnologia_id": cat["tech_led"]["id"],
            "potencia_id": cat["pot_70"]["id"],
            "marca_id": cat["marca_philips"]["id"],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    lum_id = create_resp.json()["id"]

    move_resp = admin.post(
        f"/api/v1/luminarias/{lum_id}/ubicacion",
        sede="montelibano",
        json_body={"latitud": lat2, "longitud": lng2, "origen": "web"},
    )
    assert move_resp.status_code == 200, move_resp.text

    detail = admin.get(f"/api/v1/luminarias/{lum_id}", sede="montelibano").json()
    assert float(detail["latitud"]) == pytest.approx(lat2, abs=1e-4)
    assert float(detail["longitud"]) == pytest.approx(lng2, abs=1e-4)

    hist = admin.get(f"/api/v1/luminarias/{lum_id}/historial", sede="montelibano").json()
    assert len(hist.get("ubicaciones", [])) >= 1
    event_types = {str(e.get("tipo", e.get("evento_tipo", ""))).lower() for e in hist["eventos"]}
    assert "cambio_ubicacion" in event_types


@pytest.mark.tier1
def test_luminaria_search_paginated_list_and_excel_export(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    db_helper: DbHelper,
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    cat = _resolve_mtl_catalogs(admin)

    lat, lng = generate_coordinates("montelibano", 1, seed=33)[0]
    suffix = uuid.uuid4().hex[:6].upper()
    codigo = f"{run_id}-SRCH-{suffix}"

    create_resp = admin.post(
        "/api/v1/luminarias",
        sede="montelibano",
        json_body={
            "codigo": codigo,
            "barrio_id": cat["barrio"]["id"],
            "latitud": lat,
            "longitud": lng,
            "estado_id": cat["estado_121"]["id"],
            "tecnologia_id": cat["tech_led"]["id"],
            "potencia_id": cat["pot_70"]["id"],
            "marca_id": cat["marca_philips"]["id"],
            "poste": f"P-SRCH-{suffix}",
        },
    )
    assert create_resp.status_code == 201, create_resp.text

    buscar_resp = admin.get(
        "/api/v1/luminarias/buscar",
        sede="montelibano",
        params={"q": suffix},
    )
    assert buscar_resp.status_code == 200, buscar_resp.text
    buscar_items = _extract_items(buscar_resp.json())
    assert any(item["codigo"] == codigo for item in buscar_items)
    assert len(buscar_items) <= 100

    list_resp = admin.get(
        "/api/v1/luminarias",
        sede="montelibano",
        params={"page": 1, "size": 25, "texto": codigo},
    )
    assert list_resp.status_code == 200, list_resp.text
    list_body = list_resp.json()
    assert list_body["total"] >= 1
    assert list_body["size"] == 25
    assert any(item["codigo"] == codigo for item in list_body["items"])

    export_resp = admin.post(
        "/api/v1/luminarias/exportar",
        sede="montelibano",
        json_body={"texto": codigo},
    )
    assert export_resp.status_code == 202, export_resp.text
    export_body = export_resp.json()
    tarea_id = int(export_body.get("tareaId", export_body.get("id")))
    job = db_helper.wait_for_procrastinate_job(tarea_id, timeout=30.0)
    assert job["status"] == "succeeded"


@pytest.mark.tier1
def test_luminaria_dossier_lifecycle_and_google_maps_metadata(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    cat = _resolve_mtl_catalogs(admin)

    lat, lng = generate_coordinates("montelibano", 1, seed=44)[0]
    suffix = uuid.uuid4().hex[:6].upper()
    codigo = f"{run_id}-DOS-{suffix}"

    create_resp = admin.post(
        "/api/v1/luminarias",
        sede="montelibano",
        json_body={
            "codigo": codigo,
            "codigo_externo": f"EXT-{suffix}",
            "barrio_id": cat["barrio"]["id"],
            "latitud": lat,
            "longitud": lng,
            "estado_id": cat["estado_121"]["id"],
            "tecnologia_id": cat["tech_led"]["id"],
            "potencia_id": cat["pot_70"]["id"],
            "marca_id": cat["marca_philips"]["id"],
            "fecha_instalacion": "2026-03-15",
            "fecha_mision": "2026-03-15",
            "observaciones": f"Hoja de vida {run_id}",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    lum_id = create_resp.json()["id"]

    dossier = admin.get(f"/api/v1/luminarias/{lum_id}", sede="montelibano").json()
    assert dossier["codigo_externo"] == f"EXT-{suffix}"
    assert dossier["fecha_instalacion"] is not None
    assert dossier["fecha_mision"] is not None
    assert float(dossier["latitud"]) == pytest.approx(lat, abs=1e-4)
    assert float(dossier["longitud"]) == pytest.approx(lng, abs=1e-4)
    if "google_maps_url" in dossier:
        assert "maps.google.com" in dossier["google_maps_url"] or "google.com/maps" in dossier[
            "google_maps_url"
        ]

    hist_resp = admin.get(f"/api/v1/luminarias/{lum_id}/historial", sede="montelibano")
    assert hist_resp.status_code == 200
    hist = hist_resp.json()
    assert {"eventos", "ubicaciones", "pqrs", "ordenes"}.issubset(hist.keys())


@pytest.mark.tier1
def test_lotes_consecutive_batch_creates_luminaires_in_124(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    cat = _resolve_mtl_catalogs(admin)

    base_num = (int(uuid.uuid4().hex[:6], 16) % 900000) + 100000
    c_ini = base_num
    c_fin = base_num + 2

    lote_resp = admin.post(
        "/api/v1/lotes",
        sede="montelibano",
        json_body={
            "consecutivo_inicial": c_ini,
            "consecutivo_final": c_fin,
            "cantidad": 3,
            "tecnologia_id": cat["tech_led"]["id"],
            "potencia_id": cat["pot_70"]["id"],
            "marca_id": cat["marca_philips"]["id"],
            "es_rural": False,
            "orden_compra": f"OC-{run_id}-{base_num}",
            "fecha_orden_compra": "2026-04-01",
            "entrada_almacen": f"EA-{run_id}-{base_num}",
            "fecha_entrada_almacen": "2026-04-05",
        },
    )
    assert lote_resp.status_code == 201, lote_resp.text
    lote = lote_resp.json()
    assert int(lote["cantidad"]) == 3

    lotes_list = _extract_items(admin.get("/api/v1/lotes", sede="montelibano").json())
    assert any(item["id"] == lote["id"] for item in lotes_list)

    for num in range(c_ini, c_fin + 1):
        found = _extract_items(
            admin.get(
                "/api/v1/luminarias",
                sede="montelibano",
                params={"texto": str(num), "estado_id": cat["estado_124"]["id"], "size": 20},
            ).json()
        )
        matched = [item for item in found if str(num) in str(item["codigo"])]
        assert len(matched) >= 1, f"Expected luminaire for consecutive {num} in state 124"
        hist = admin.get(
            f"/api/v1/luminarias/{matched[0]['id']}/historial",
            sede="montelibano",
        ).json()
        assert len(hist["eventos"]) >= 1


@pytest.mark.tier1
def test_mapa_mvt_tiles_and_pmtiles_range(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    cat = _resolve_mtl_catalogs(admin)

    lat, lng = 7.9801, -75.4171
    suffix = uuid.uuid4().hex[:6].upper()
    create_resp = admin.post(
        "/api/v1/luminarias",
        sede="montelibano",
        json_body={
            "codigo": f"{run_id}-MAP-{suffix}",
            "barrio_id": cat["barrio"]["id"],
            "latitud": lat,
            "longitud": lng,
            "estado_id": cat["estado_121"]["id"],
            "tecnologia_id": cat["tech_led"]["id"],
            "potencia_id": cat["pot_70"]["id"],
            "marca_id": cat["marca_philips"]["id"],
        },
    )
    assert create_resp.status_code == 201, create_resp.text

    tx, ty = _latlng_to_tile(lat, lng, 14)
    mvt_resp = admin.get(f"/api/v1/mapa/luminarias/14/{tx}/{ty}.mvt", sede="montelibano")
    assert mvt_resp.status_code == 200, mvt_resp.text
    assert mvt_resp.content_type.lower().startswith("application/vnd.mapbox-vector-tile")
    assert len(mvt_resp.content) > 0, "Expected non-empty MVT protobuf payload"

    tx_low, ty_low = _latlng_to_tile(lat, lng, 10)
    mvt_low = admin.get(f"/api/v1/mapa/luminarias/10/{tx_low}/{ty_low}.mvt", sede="montelibano")
    assert mvt_low.status_code == 200
    assert mvt_low.content_type.lower().startswith("application/vnd.mapbox-vector-tile")

    pm_resp = admin.get(
        "/api/v1/mapa/base/montelibano.pmtiles",
        omit_sede=True,
        byte_range="bytes=0-511",
    )
    assert pm_resp.status_code == 206, pm_resp.text
    assert pm_resp.header("accept-ranges", "").lower() == "bytes"
    assert pm_resp.header("content-range")
    assert len(pm_resp.content) == 512
    assert pm_resp.content[:7] == b"PMTiles"


@pytest.mark.tier1
@pytest.mark.browser
def test_web_browser_mapa_renders_canvas_without_errors(
    e2e_config: E2EConfig,
    browser_driver: BrowserDriver,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    web_url = e2e_config.web_url

    browser_driver.navigate(f"{web_url}/ingresar")
    browser_driver.wait_for_selector("input[type='password']")
    browser_driver.fill(
        "input[name='usuario'], input[autocomplete='username'], input[type='text']",
        admin_user,
    )
    browser_driver.fill("input[name='clave'], input[type='password']", admin_pw)
    browser_driver.click("button[type='submit']")

    deadline = time.monotonic() + e2e_config.timeout_seconds
    while time.monotonic() < deadline:
        if "/ingresar" not in browser_driver.current_url():
            break
        time.sleep(0.2)
    assert "/ingresar" not in browser_driver.current_url()

    browser_driver.navigate(f"{web_url}/mapa")
    browser_driver.wait_for_selector("canvas")
    counts = browser_driver.has_canvas_or_svg()
    assert counts["canvas"] >= 1, f"Expected MapLibre <canvas> on /mapa, got {counts}"
    assert not _browser_errors(browser_driver), (
        f"Browser reported JS errors on /mapa: {_browser_errors(browser_driver)}"
    )
