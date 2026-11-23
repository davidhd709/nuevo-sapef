"""Fase 0 live & ASGI contract verification (/salud, /sistema/tareas, RFC 9457, OpenAPI)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from harness.client import SapefClient, assert_problem_json
from harness.config import E2EConfig
from harness.db import DbHelper


@pytest.mark.fase0
def test_salud_ok_and_request_id(
    e2e_config: E2EConfig,
    inprocess_or_live_client: SapefClient,
    db_helper: DbHelper,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if e2e_config.inprocess and not db_helper.is_ready():
        backend_dir = str(e2e_config.backend_dir)
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        from app.core import salud as salud_mod  # type: ignore[import-not-found]

        monkeypatch.setattr(
            salud_mod,
            "comprobar_base_de_datos",
            lambda: {"postgres": "17.2", "postgis": "3.5.0"},
        )

    resp = inprocess_or_live_client.get(
        "/api/v1/salud",
        request_id="e2e-salud-001",
        omit_sede=True,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["estado"] == "ok"
    assert body["base_de_datos"] == "ok"
    assert body["postgres"]
    assert body["postgis"]
    assert resp.request_id == "e2e-salud-001"


@pytest.mark.fase0
def test_salud_degraded_returns_503_without_leaking_secrets(
    e2e_config: E2EConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not e2e_config.inprocess:
        pytest.skip("Degraded DB injection test requires SAPEF_E2E_INPROCESS=1")

    backend_dir = str(e2e_config.backend_dir)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from app.core import salud as salud_mod  # type: ignore[import-not-found]
    from app.main import crear_app  # type: ignore[import-not-found]

    def _boom() -> dict[str, str]:
        raise ConnectionError("password=super_secret_token host=db.internal")

    monkeypatch.setattr(salud_mod, "comprobar_base_de_datos", _boom)
    with SapefClient(inprocess=True, app=crear_app()) as client:
        resp = client.get("/api/v1/salud", omit_sede=True)
    assert resp.status_code == 503
    body = resp.json()
    assert body["estado"] == "degradado"
    assert body["base_de_datos"] == "no disponible"
    assert "super_secret_token" not in resp.text
    assert "db.internal" not in resp.text


@pytest.mark.fase0
def test_sistema_tareas_validation_422_rfc9457(
    inprocess_or_live_client: SapefClient,
) -> None:
    resp = inprocess_or_live_client.get(
        "/api/v1/sistema/tareas/no-es-entero",
        request_id="e2e-422-001",
        omit_sede=True,
    )
    body = assert_problem_json(resp, expected_status=422)
    assert body["requestId"] == "e2e-422-001"
    assert isinstance(body.get("errors"), list) and len(body["errors"]) >= 1


@pytest.mark.fase0
def test_not_found_404_rfc9457_and_request_id(
    inprocess_or_live_client: SapefClient,
) -> None:
    resp = inprocess_or_live_client.get(
        "/api/v1/ruta-inexistente-e2e",
        request_id="e2e-404-001",
        omit_sede=True,
    )
    body = assert_problem_json(resp, expected_status=404)
    assert body["requestId"] == "e2e-404-001"


@pytest.mark.fase0
def test_sistema_tareas_prueba_live_roundtrip(
    e2e_config: E2EConfig,
    inprocess_or_live_client: SapefClient,
    db_helper: DbHelper,
) -> None:
    if e2e_config.inprocess or not db_helper.is_ready():
        pytest.skip("Requires live backend and PostgreSQL/Procrastinate tables")

    resp = inprocess_or_live_client.post("/api/v1/sistema/tareas/prueba", omit_sede=True)
    assert resp.status_code == 202
    job_id = int(resp.json()["id"])

    status_resp = inprocess_or_live_client.get(f"/api/v1/sistema/tareas/{job_id}", omit_sede=True)
    assert status_resp.status_code == 200
    assert status_resp.json()["id"] == job_id


@pytest.mark.fase0
def test_production_mode_hides_docs_openapi_and_sistema(
    e2e_config: E2EConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not e2e_config.inprocess:
        pytest.skip(
            "Production toggle check runs against ASGI crear_app() with SAPEF_E2E_INPROCESS=1"
        )

    backend_dir = str(e2e_config.backend_dir)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from app.core.config import obtener_configuracion  # type: ignore[import-not-found]
    from app.main import crear_app  # type: ignore[import-not-found]

    monkeypatch.setenv("SAPEF_ENTORNO", "produccion")
    monkeypatch.setenv(
        "SAPEF_SECRET_KEY",
        "e2e-test-prod-toggle-key-0123456789abcdef-xYz!",
    )
    obtener_configuracion.cache_clear()
    try:
        prod_app = crear_app()
        with SapefClient(inprocess=True, app=prod_app) as prod_client:
            for method, path in (
                ("GET", "/api/docs"),
                ("GET", "/api/openapi.json"),
                ("POST", "/api/v1/sistema/tareas/prueba"),
            ):
                resp = prod_client.request(method, path, omit_sede=True)
                assert_problem_json(resp, expected_status=404)
    finally:
        monkeypatch.delenv("SAPEF_ENTORNO", raising=False)
        monkeypatch.delenv("SAPEF_SECRET_KEY", raising=False)
        obtener_configuracion.cache_clear()


@pytest.mark.fase0
def test_openapi_json_synced_with_frontend_api_package(
    e2e_config: E2EConfig,
    inprocess_or_live_client: SapefClient,
) -> None:
    frontend_openapi_path: Path = e2e_config.frontend_dir / "packages" / "api" / "openapi.json"
    assert frontend_openapi_path.is_file(), f"Missing {frontend_openapi_path}"
    committed = json.loads(frontend_openapi_path.read_text(encoding="utf-8"))

    if e2e_config.inprocess:
        backend_dir = str(e2e_config.backend_dir)
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        from app.main import crear_app  # type: ignore[import-not-found]

        live_schema = crear_app().openapi()
    else:
        resp = inprocess_or_live_client.get("/api/openapi.json", omit_sede=True)
        assert resp.status_code == 200
        live_schema = resp.json()

    assert committed.get("info", {}).get("title") == live_schema.get("info", {}).get("title")
    fase0_paths = {
        "/api/v1/salud",
        "/api/v1/sistema/tareas/prueba",
        "/api/v1/sistema/tareas/{job_id}",
    }
    assert fase0_paths.issubset(set(committed.get("paths", {}).keys()))
    assert fase0_paths.issubset(set(live_schema.get("paths", {}).keys()))
    for p in fase0_paths:
        assert committed["paths"][p] == live_schema["paths"][p]
