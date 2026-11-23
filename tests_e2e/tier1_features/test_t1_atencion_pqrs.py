"""Tier 1 E2E tests for EP-04 Atencion PQRS (F4-1..F4-5)."""

from __future__ import annotations

import datetime as dt
import json
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
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


def _resolve_pqrs_prereqs(admin: SapefClient) -> dict[str, Any]:
    barrios = _extract_items(admin.get("/api/v1/barrios", sede="montelibano").json())
    barrio = next((b for b in barrios if b["nombre"] == "El Centro"), barrios[0])

    estados_lum = _extract_items(
        admin.get("/api/v1/estados", omit_sede=True, params={"proceso": "luminaria"}).json()
    )
    est_121 = next(e for e in estados_lum if str(e["codigo"]) == "121")

    techs = _extract_items(admin.get("/api/v1/maestros/LUMINARIA_TECNOLOGIA", omit_sede=True).json())
    tech_led = next(t for t in techs if t["codigo"] == "LED")

    pots = _extract_items(admin.get("/api/v1/maestros/LUMINARIA_POTENCIA", omit_sede=True).json())
    pot_70 = next((p for p in pots if str(p["codigo"]) == "70"), pots[0])

    marcas = _extract_items(admin.get("/api/v1/maestros/LUMINARIA_MARCA", omit_sede=True).json())
    marca_philips = next((m for m in marcas if m["codigo"] == "PHILIPS"), marcas[0])

    canales = _extract_items(admin.get("/api/v1/maestros/CANAL_PQRS", omit_sede=True).json())
    canal_wa = next(c for c in canales if c["codigo"] == "WHATSAPP")

    return {
        "barrio": barrio,
        "estado_121": est_121,
        "tech_led": tech_led,
        "pot_70": pot_70,
        "marca_philips": marca_philips,
        "canal_wa": canal_wa,
    }


def _create_luminaire(
    admin: SapefClient,
    prereqs: dict[str, Any],
    codigo: str,
    seed: int = 1,
) -> dict[str, Any]:
    lat, lng = generate_coordinates("montelibano", 1, seed=seed)[0]
    resp = admin.post(
        "/api/v1/luminarias",
        sede="montelibano",
        json_body={
            "codigo": codigo,
            "barrio_id": prereqs["barrio"]["id"],
            "latitud": lat,
            "longitud": lng,
            "estado_id": prereqs["estado_121"]["id"],
            "tecnologia_id": prereqs["tech_led"]["id"],
            "potencia_id": prereqs["pot_70"]["id"],
            "marca_id": prereqs["marca_philips"]["id"],
        },
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


def _create_citizen(
    admin: SapefClient,
    prereqs: dict[str, Any],
    *,
    nombre: str,
    identificacion: str,
    correo: str,
) -> dict[str, Any]:
    resp = admin.post(
        "/api/v1/ciudadanos",
        sede="montelibano",
        json_body={
            "identificacion": identificacion,
            "nombre_completo": nombre,
            "barrio_id": prereqs["barrio"]["id"],
            "sector": "Centro",
            "telefono": "7720001",
            "celular": "3005551234",
            "correo": correo,
        },
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


@pytest.mark.tier1
def test_ciudadanos_search_pg_trgm_unaccent_and_auditoria_consulta(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    db_helper: DbHelper,
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    prereqs = _resolve_pqrs_prereqs(admin)

    suffix = uuid.uuid4().hex[:6].upper()
    ident = f"1067{int(suffix, 16) % 1000000:06d}"
    email = f"sofia.{suffix.lower()}@example.test"
    citizen = _create_citizen(
        admin,
        prereqs,
        nombre=f"Sofía Álvarez {suffix}",
        identificacion=ident,
        correo=email,
    )

    before_logs = db_helper.count_nominal_consult_logs()

    search_resp = admin.get(
        "/api/v1/ciudadanos",
        sede="montelibano",
        params={"buscar": f"Sofia Alvarez {suffix}", "page": 1, "size": 20},
    )
    assert search_resp.status_code == 200, search_resp.text
    items = _extract_items(search_resp.json())
    matched = next((c for c in items if c["id"] == citizen["id"]), None)
    assert matched is not None, f"Expected unaccent/pg_trgm match for {suffix}, got {items}"
    assert matched["identificacion"] == ident
    assert matched["celular"] == "3005551234"
    assert matched["correo"] == email

    after_logs = db_helper.count_nominal_consult_logs()
    assert after_logs > before_logs, (
        "Expected nominal search with atencion.datos_personales.ver to log auditoria_consulta"
    )


@pytest.mark.tier1
def test_pqrs_creation_multi_luminaire_and_sin_identificar_wildcard(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    prereqs = _resolve_pqrs_prereqs(admin)

    suffix = uuid.uuid4().hex[:6].upper()
    lum1 = _create_luminaire(admin, prereqs, f"{run_id}-PQ1-{suffix}", seed=51)
    lum2 = _create_luminaire(admin, prereqs, f"{run_id}-PQ2-{suffix}", seed=52)
    citizen = _create_citizen(
        admin,
        prereqs,
        nombre=f"Carlos PQRS {suffix}",
        identificacion=f"1068{int(suffix, 16) % 1000000:06d}",
        correo=f"carlos.{suffix.lower()}@example.test",
    )

    pqrs_resp = admin.post(
        "/api/v1/pqrs",
        sede="montelibano",
        json_body={
            "canal_id": prereqs["canal_wa"]["id"],
            "ciudadano_id": citizen["id"],
            "prioridad": 1,
            "observacion_solicitante": f"Dos luminarias apagadas {run_id}",
            "notificar_cliente": False,
            "luminarias": [
                {"luminaria_id": lum1["id"], "observacion_solicitante": "Apagada 1"},
                {"luminaria_id": lum2["id"], "observacion_solicitante": "Apagada 2"},
            ],
        },
    )
    assert pqrs_resp.status_code == 201, pqrs_resp.text
    pqrs = pqrs_resp.json()
    assert pqrs.get("numero") is not None
    assert len(pqrs.get("luminarias", [])) == 2

    for lum in (lum1, lum2):
        lum_after = admin.get(f"/api/v1/luminarias/{lum['id']}", sede="montelibano").json()
        estado_cod = str(
            lum_after.get("estado_codigo")
            or (lum_after.get("estado") or {}).get("codigo", "")
        )
        assert estado_cod == "122", f"Expected luminaire {lum['codigo']} in state 122, got {lum_after}"

    wildcard_candidates = _extract_items(
        admin.get(
            "/api/v1/luminarias/buscar",
            sede="montelibano",
            params={"q": "SIN-IDENTIFICAR"},
        ).json()
    )
    wildcard = next(
        (item for item in wildcard_candidates if item["codigo"] == "SIN-IDENTIFICAR"),
        None,
    )
    assert wildcard is not None, "Expected seeded SIN-IDENTIFICAR wildcard luminaire"

    wildcard_pqrs = admin.post(
        "/api/v1/pqrs",
        sede="montelibano",
        json_body={
            "canal_id": prereqs["canal_wa"]["id"],
            "ciudadano_id": citizen["id"],
            "prioridad": 2,
            "observacion_solicitante": f"Poste sin placa {run_id}",
            "notificar_cliente": False,
            "luminarias": [
                {"luminaria_id": wildcard["id"], "observacion_solicitante": "Sin identificar"},
            ],
        },
    )
    assert wildcard_pqrs.status_code == 201, wildcard_pqrs.text

    wildcard_after = admin.get(f"/api/v1/luminarias/{wildcard['id']}", sede="montelibano").json()
    wc_estado = str(
        wildcard_after.get("estado_codigo")
        or (wildcard_after.get("estado") or {}).get("codigo", "")
    )
    assert wc_estado == "110", f"Wildcard SIN-IDENTIFICAR must remain in state 110, got {wildcard_after}"


@pytest.mark.tier1
def test_pqrs_query_filter_detail_cancel_304_and_export_202(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    db_helper: DbHelper,
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    prereqs = _resolve_pqrs_prereqs(admin)

    suffix = uuid.uuid4().hex[:6].upper()
    lum = _create_luminaire(admin, prereqs, f"{run_id}-PQC-{suffix}", seed=61)
    citizen = _create_citizen(
        admin,
        prereqs,
        nombre=f"Marta Anula {suffix}",
        identificacion=f"1069{int(suffix, 16) % 1000000:06d}",
        correo=f"marta.{suffix.lower()}@example.test",
    )

    create_resp = admin.post(
        "/api/v1/pqrs",
        sede="montelibano",
        json_body={
            "canal_id": prereqs["canal_wa"]["id"],
            "ciudadano_id": citizen["id"],
            "prioridad": 0,
            "observacion_solicitante": f"Urgente anulable {run_id}",
            "notificar_cliente": False,
            "luminarias": [{"luminaria_id": lum["id"]}],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    pqrs_id = create_resp.json()["id"]

    today = dt.date.today()
    list_resp = admin.get(
        "/api/v1/pqrs",
        sede="montelibano",
        params={
            "prioridad": 0,
            "desde": (today - dt.timedelta(days=1)).isoformat(),
            "hasta": (today + dt.timedelta(days=1)).isoformat(),
            "page": 1,
            "size": 50,
        },
    )
    assert list_resp.status_code == 200, list_resp.text
    list_items = _extract_items(list_resp.json())
    assert any(item["id"] == pqrs_id for item in list_items)

    detail_resp = admin.get(f"/api/v1/pqrs/{pqrs_id}", sede="montelibano")
    assert detail_resp.status_code == 200
    assert len(detail_resp.json().get("luminarias", [])) == 1

    cancel_resp = admin.post(
        f"/api/v1/pqrs/{pqrs_id}/anular",
        sede="montelibano",
        json_body={"motivo": f"Duplicada {run_id}"},
    )
    assert cancel_resp.status_code == 200, cancel_resp.text
    canceled = cancel_resp.json()
    cancel_state = str(
        canceled.get("estado_codigo") or (canceled.get("estado") or {}).get("codigo", "")
    )
    assert cancel_state == "304"

    export_resp = admin.post(
        "/api/v1/pqrs/exportar",
        sede="montelibano",
        json_body={"prioridad": 0},
    )
    assert export_resp.status_code == 202, export_resp.text
    export_body = export_resp.json()
    tarea_id = int(export_body.get("tareaId", export_body.get("id")))
    job = db_helper.wait_for_procrastinate_job(tarea_id, timeout=30.0)
    assert job["status"] == "succeeded"


@pytest.mark.tier1
def test_pqrs_pendientes_semaphore_matches_sede_thresholds(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    prereqs = _resolve_pqrs_prereqs(admin)

    params_items = _extract_items(admin.get("/api/v1/parametros", sede="montelibano").json())
    semaforo_param = next(p for p in params_items if p["codigo"] == "semaforo_pqrs_umbrales")
    thresholds = semaforo_param["valor"]
    verde_max = int(thresholds["verde_max_dias"])
    amarillo_max = int(thresholds["amarillo_max_dias"])

    suffix = uuid.uuid4().hex[:6].upper()
    lum = _create_luminaire(admin, prereqs, f"{run_id}-SEM-{suffix}", seed=71)
    citizen = _create_citizen(
        admin,
        prereqs,
        nombre=f"Luis Semaforo {suffix}",
        identificacion=f"1070{int(suffix, 16) % 1000000:06d}",
        correo=f"luis.{suffix.lower()}@example.test",
    )

    create_resp = admin.post(
        "/api/v1/pqrs",
        sede="montelibano",
        json_body={
            "canal_id": prereqs["canal_wa"]["id"],
            "ciudadano_id": citizen["id"],
            "prioridad": 1,
            "observacion_solicitante": f"Pendiente semáforo {run_id}",
            "notificar_cliente": False,
            "luminarias": [{"luminaria_id": lum["id"]}],
        },
    )
    assert create_resp.status_code == 201, create_resp.text

    pend_resp = admin.get(
        "/api/v1/pqrs/pendientes",
        sede="montelibano",
        params={"semaforo": "verde", "page": 1, "size": 100},
    )
    assert pend_resp.status_code == 200, pend_resp.text
    pend_items = _extract_items(pend_resp.json())
    our_row = next(
        (
            item
            for item in pend_items
            if item.get("luminaria_id") == lum["id"]
            or item.get("luminaria_codigo") == lum["codigo"]
            or (item.get("luminaria") or {}).get("id") == lum["id"]
        ),
        None,
    )
    assert our_row is not None, "Expected newly created pending PQRS luminaire in verde board"
    assert our_row["semaforo"] == "verde"

    all_pend = _extract_items(
        admin.get("/api/v1/pqrs/pendientes", sede="montelibano", params={"size": 100}).json()
    )
    for row in all_pend:
        days = int(row["dias_abierta"])
        expected_color = (
            "verde" if days <= verde_max else ("amarillo" if days <= amarillo_max else "rojo")
        )
        assert row["semaforo"] == expected_color, (
            f"Row {row} has dias_abierta={days}, expected {expected_color} per {thresholds}"
        )


@pytest.mark.tier1
def test_pqrs_add_and_remove_luminaire(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    prereqs = _resolve_pqrs_prereqs(admin)

    suffix = uuid.uuid4().hex[:6].upper()
    lum1 = _create_luminaire(admin, prereqs, f"{run_id}-ADD1-{suffix}", seed=81)
    lum2 = _create_luminaire(admin, prereqs, f"{run_id}-ADD2-{suffix}", seed=82)
    citizen = _create_citizen(
        admin,
        prereqs,
        nombre=f"Elena Multi {suffix}",
        identificacion=f"1071{int(suffix, 16) % 1000000:06d}",
        correo=f"elena.{suffix.lower()}@example.test",
    )

    create_resp = admin.post(
        "/api/v1/pqrs",
        sede="montelibano",
        json_body={
            "canal_id": prereqs["canal_wa"]["id"],
            "ciudadano_id": citizen["id"],
            "prioridad": 2,
            "observacion_solicitante": f"Add/Remove luminarias {run_id}",
            "notificar_cliente": False,
            "luminarias": [{"luminaria_id": lum1["id"]}],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    pqrs_id = create_resp.json()["id"]

    add_resp = admin.post(
        f"/api/v1/pqrs/{pqrs_id}/luminarias",
        sede="montelibano",
        json_body={"luminaria_id": lum2["id"], "observacion_solicitante": "Agregada luego"},
    )
    assert add_resp.status_code == 201, add_resp.text

    detail_2 = admin.get(f"/api/v1/pqrs/{pqrs_id}", sede="montelibano").json()
    assert len(detail_2["luminarias"]) == 2

    del_resp = admin.delete(
        f"/api/v1/pqrs/{pqrs_id}/luminarias/{lum2['id']}",
        sede="montelibano",
    )
    assert del_resp.status_code == 204, del_resp.text

    detail_1 = admin.get(f"/api/v1/pqrs/{pqrs_id}", sede="montelibano").json()
    assert len(detail_1["luminarias"]) == 1


@pytest.mark.tier1
@pytest.mark.browser
def test_web_browser_atencion_pendientes_renders_semaphore_rows(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    browser_driver: BrowserDriver,
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    prereqs = _resolve_pqrs_prereqs(admin)

    suffix = uuid.uuid4().hex[:6].upper()
    lum = _create_luminaire(admin, prereqs, f"{run_id}-BRW-{suffix}", seed=91)
    citizen = _create_citizen(
        admin,
        prereqs,
        nombre=f"Pedro Browser {suffix}",
        identificacion=f"1072{int(suffix, 16) % 1000000:06d}",
        correo=f"pedro.{suffix.lower()}@example.test",
    )
    create_resp = admin.post(
        "/api/v1/pqrs",
        sede="montelibano",
        json_body={
            "canal_id": prereqs["canal_wa"]["id"],
            "ciudadano_id": citizen["id"],
            "prioridad": 1,
            "observacion_solicitante": f"Browser pendientes {run_id}",
            "notificar_cliente": False,
            "luminarias": [{"luminaria_id": lum["id"]}],
        },
    )
    assert create_resp.status_code == 201, create_resp.text

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

    browser_driver.navigate(f"{web_url}/atencion/pendientes")
    browser_driver.wait_for_selector("table tbody tr, [role='row']")
    body_text = str(browser_driver.eval_js("document.body.innerText") or "")
    assert "verde" in body_text.lower() or "amarillo" in body_text.lower() or "rojo" in body_text.lower()
    assert not _browser_errors(browser_driver), (
        f"Browser reported JS errors on /atencion/pendientes: {_browser_errors(browser_driver)}"
    )
