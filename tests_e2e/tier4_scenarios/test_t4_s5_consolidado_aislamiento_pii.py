"""Tier 4 Scenario 5: Multi-Sede Executive Consolidation & Strict Tenant Isolation Audit."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fixtures import build_vatia_xlsx, generate_coordinates, make_png
from harness.browser import BrowserDriver
from harness.client import SapefClient, assert_problem_json
from harness.config import E2EConfig
from harness.db import DbHelper

pytestmark = [pytest.mark.tier4, pytest.mark.isolation, pytest.mark.browser]


def _admin_client(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    sede: str = "montelibano",
) -> SapefClient:
    assert e2e_config.admin_password, (
        "SAPEF_E2E_ADMIN_PASSWORD must be configured to run Tier 4 E2E scenarios"
    )
    return auth_session_factory(e2e_config.admin_user, e2e_config.admin_password, sede=sede)


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    if isinstance(payload, dict):
        for key in ("items", "resultados", "datos", "luminarias", "ordenes", "materiales"):
            val = payload.get(key)
            if isinstance(val, list):
                return [dict(item) for item in val]
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


def _create_user(
    admin: SapefClient,
    *,
    run_id: str,
    tag: str,
    role_codigo: str,
    sede_codigos: list[str],
) -> dict[str, Any]:
    sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    sede_ids = [next(s["id"] for s in sedes if s["codigo"] == c) for c in sede_codigos]
    roles = _extract_items(admin.get("/api/v1/roles", omit_sede=True).json())
    role_id = next(r["id"] for r in roles if str(r["codigo"]).upper() == role_codigo.upper())

    suffix = uuid.uuid4().hex[:6].lower()
    username = f"{run_id.lower()}_{tag}_{suffix}"
    secret = f"S5Iso!{uuid.uuid4().hex[:10]}9Z"
    resp = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": username,
            "nombre_completo": f"Usuario S5 {tag} {suffix}",
            "identificacion": f"75{int(suffix, 16) % 10000000:07d}",
            "correo": f"{username}@example.test",
            "clave": secret,
            "rol_id": role_id,
            "sedes": sede_ids,
            "activo": True,
            "debe_cambiar_clave": False,
        },
    )
    assert resp.status_code == 201, resp.text
    dto = dict(resp.json())
    dto["_secret"] = secret
    return dto


def test_consolidado_multi_sede_isolation_pii_masking_and_audit_logs(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    db_helper: DbHelper,
    browser_driver: BrowserDriver,
    run_id: str,
) -> None:
    """Scenario 5: GERENTE ?sede=todas + browser /tablero vs single-sede leak probes & PII masking."""
    admin_mtl = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    admin_alc = _admin_client(auth_session_factory, e2e_config, sede="alcala")
    tag = uuid.uuid4().hex[:6].upper()

    # ------------------------------------------------------------------
    # Phase 1: Seed distinct Montelíbano & Alcalá resources + commercial cut
    # ------------------------------------------------------------------
    alc_barrio = _extract_items(admin_alc.get("/api/v1/barrios", sede="alcala").json())[0]
    mtl_barrio = _extract_items(admin_mtl.get("/api/v1/barrios", sede="montelibano").json())[0]
    est_121 = next(
        e["id"]
        for e in _extract_items(
            admin_alc.get("/api/v1/estados", omit_sede=True, params={"proceso": "luminaria"}).json()
        )
        if str(e["codigo"]) == "121"
    )
    tech_led = _extract_items(
        admin_alc.get("/api/v1/maestros/LUMINARIA_TECNOLOGIA", omit_sede=True).json()
    )[0]["id"]
    pot_id = _extract_items(
        admin_alc.get("/api/v1/maestros/LUMINARIA_POTENCIA", omit_sede=True).json()
    )[0]["id"]
    canal_wa = next(
        c
        for c in _extract_items(admin_alc.get("/api/v1/maestros/CANAL_PQRS", omit_sede=True).json())
        if c["codigo"] == "WHATSAPP"
    )

    alc_lat, alc_lng = generate_coordinates("alcala", 1, seed=505)[0]
    alc_lum_secret = f"{run_id}-ALC-CONFIDENTIAL-{tag}"
    alc_lum = admin_alc.post(
        "/api/v1/luminarias",
        sede="alcala",
        json_body={
            "codigo": alc_lum_secret,
            "barrio_id": alc_barrio["id"],
            "latitud": alc_lat,
            "longitud": alc_lng,
            "estado_id": est_121,
            "tecnologia_id": tech_led,
            "potencia_id": pot_id,
        },
    )
    assert alc_lum.status_code == 201, alc_lum.text
    alc_lum_id = alc_lum.json()["id"]

    alc_cit_ident = f"ALC99{int(tag, 16) % 100000:05d}"
    alc_cit = admin_alc.post(
        "/api/v1/ciudadanos",
        sede="alcala",
        json_body={
            "identificacion": alc_cit_ident,
            "nombre_completo": f"Ciudadano Privado Alcala {tag}",
            "telefono": "3129998877",
            "correo": f"priv.alc.{tag.lower()}@example.test",
        },
    )
    assert alc_cit.status_code == 201, alc_cit.text

    alc_pqrs_secret = f"Falla confidencial Alcala {tag}"
    alc_pqrs = admin_alc.post(
        "/api/v1/pqrs",
        sede="alcala",
        json_body={
            "canal_id": canal_wa["id"],
            "ciudadano_id": alc_cit.json()["id"],
            "prioridad": 1,
            "observacion_solicitante": alc_pqrs_secret,
            "notificar_cliente": False,
            "luminarias": [{"luminaria_id": alc_lum_id}],
        },
    )
    assert alc_pqrs.status_code == 201, alc_pqrs.text
    alc_pqrs_id = alc_pqrs.json()["id"]

    alc_ot = admin_alc.post(
        "/api/v1/ordenes",
        sede="alcala",
        json_body={
            "tipo": "mantenimiento",
            "prioridad": 1,
            "observaciones": f"Orden privada Alcala {tag}",
            "luminarias": [{"luminaria_id": alc_lum_id, "rol": "intervenida"}],
        },
    )
    assert alc_ot.status_code == 201, alc_ot.text
    alc_ot_id = alc_ot.json()["id"]

    alc_mat_secret = f"{run_id}-ALCMAT-{tag}"
    alc_mat = admin_alc.post(
        "/api/v1/materiales",
        sede="alcala",
        json_body={
            "categoria": "CABLE",
            "codigo": alc_mat_secret,
            "descripcion": f"Material secreto Alcala {tag}",
            "unidad": "MTS",
            "existencias": 10,
            "existencias_minimas": 2,
        },
    )
    assert alc_mat.status_code == 201, alc_mat.text
    alc_mat_id = alc_mat.json()["id"]

    alc_file = admin_alc.post(
        "/api/v1/archivos",
        sede="alcala",
        idempotency_key=str(uuid.uuid4()),
        files={"archivo": ("alc_secret.png", make_png(4, 4), "image/png")},
    )
    assert alc_file.status_code in (200, 201), alc_file.text
    alc_file_id = alc_file.json()["id"]

    vatia_f = build_vatia_xlsx("202606")
    cargue_up = admin_alc.post(
        "/api/v1/comercial/vatia/cargues",
        sede="alcala",
        idempotency_key=str(uuid.uuid4()),
        data={"periodo": "202606"},
        files=[("files", vatia_f.filename, vatia_f.content, vatia_f.content_type)],
    )
    assert cargue_up.status_code == 202, cargue_up.text
    alc_cargue_id = (
        cargue_up.json().get("cargue_id")
        or cargue_up.json().get("cargueId")
        or cargue_up.json().get("id")
    )
    if isinstance(cargue_up.json().get("tarea_id"), int):
        db_helper.wait_for_procrastinate_job(
            cargue_up.json()["tarea_id"], timeout=e2e_config.timeout_seconds
        )

    # Montelíbano citizen & luminaire for PII masking + nominal audit tests
    mtl_lat, mtl_lng = generate_coordinates("montelibano", 1, seed=506)[0]
    mtl_lum = admin_mtl.post(
        "/api/v1/luminarias",
        sede="montelibano",
        json_body={
            "codigo": f"{run_id}-MTL-PII-{tag}",
            "barrio_id": mtl_barrio["id"],
            "latitud": mtl_lat,
            "longitud": mtl_lng,
            "estado_id": est_121,
            "tecnologia_id": tech_led,
            "potencia_id": pot_id,
        },
    )
    assert mtl_lum.status_code == 201, mtl_lum.text

    pii_ident = f"1067{int(tag, 16) % 1000000:06d}"
    pii_phone = "3157776655"
    pii_email = f"ciudadano.pii.{tag.lower()}@example.test"
    mtl_cit = admin_mtl.post(
        "/api/v1/ciudadanos",
        sede="montelibano",
        json_body={
            "identificacion": pii_ident,
            "nombre_completo": f"Marta PII {tag}",
            "barrio_id": mtl_barrio["id"],
            "telefono": pii_phone,
            "celular": pii_phone,
            "correo": pii_email,
        },
    )
    assert mtl_cit.status_code == 201, mtl_cit.text
    mtl_pqrs = admin_mtl.post(
        "/api/v1/pqrs",
        sede="montelibano",
        json_body={
            "canal_id": canal_wa["id"],
            "ciudadano_id": mtl_cit.json()["id"],
            "prioridad": 1,
            "observacion_solicitante": f"Prueba enmascaramiento {tag}",
            "notificar_cliente": False,
            "luminarias": [{"luminaria_id": mtl_lum.json()["id"]}],
        },
    )
    assert mtl_pqrs.status_code == 201, mtl_pqrs.text
    mtl_pqrs_id = mtl_pqrs.json()["id"]

    recalc = admin_mtl.post("/api/v1/tablero/recalcular", omit_sede=True, json_body={})
    assert recalc.status_code == 202, recalc.text
    r_job = recalc.json().get("tareaId") or recalc.json().get("tarea_id")
    if isinstance(r_job, int):
        db_helper.wait_for_procrastinate_job(r_job, timeout=e2e_config.timeout_seconds)

    # ------------------------------------------------------------------
    # Phase 2: GERENTE (both sedes + tablero.consolidado.ver) -> API & Chromium /tablero
    # ------------------------------------------------------------------
    gerente = _create_user(
        admin_mtl,
        run_id=run_id,
        tag="ger",
        role_codigo="GERENTE",
        sede_codigos=["montelibano", "alcala"],
    )
    mtl_only_user = _create_user(
        admin_mtl,
        run_id=run_id,
        tag="mtl",
        role_codigo="COORDINACION",
        sede_codigos=["montelibano"],
    )
    # Role without atencion.datos_personales.ver and without comercial.nominal.ver
    masked_role = admin_mtl.post(
        "/api/v1/roles",
        omit_sede=True,
        json_body={
            "codigo": f"{run_id}_MASK_{tag}",
            "nombre": f"Consulta Sin Nominal {tag}",
            "permisos": [
                "atencion.pqrs.ver",
                "comercial.analisis.ver",
                "tablero.ver",
            ],
        },
    )
    assert masked_role.status_code == 201, masked_role.text
    masked_user = _create_user(
        admin_mtl,
        run_id=run_id,
        tag="msk",
        role_codigo=masked_role.json()["codigo"],
        sede_codigos=["montelibano"],
    )

    try:
        ger_client = auth_session_factory(
            gerente["nombre_usuario"], gerente["_secret"], sede="montelibano"
        )
        t0 = time.perf_counter()
        cons_resp = ger_client.get(
            "/api/v1/tablero/resumen",
            params={"sede": "todas"},
            omit_sede=True,
        )
        assert cons_resp.status_code == 200, cons_resp.text
        assert (time.perf_counter() - t0) < 2.0
        cons_text = json.dumps(cons_resp.json()).lower()
        assert "montelibano" in cons_text and "alcala" in cons_text

        # GERENTE opens apps/web /tablero Consolidado in Chromium
        browser_driver.navigate(f"{e2e_config.web_url}/ingresar")
        browser_driver.wait_for_selector("input[type='password']", timeout=e2e_config.timeout_seconds)
        browser_driver.fill(
            "input[name='usuario'], input[autocomplete='username'], input[type='text']",
            gerente["nombre_usuario"],
        )
        browser_driver.fill("input[name='clave'], input[type='password']", gerente["_secret"])
        browser_driver.click("button[type='submit"]')
        deadline = time.monotonic() + e2e_config.timeout_seconds
        while time.monotonic() < deadline and "/ingresar" in browser_driver.current_url():
            time.sleep(0.2)

        browser_driver.navigate(f"{e2e_config.web_url}/tablero?sede=todas")
        chart_deadline = time.monotonic() + e2e_config.timeout_seconds
        counts = {"canvas": 0, "svg": 0}
        while time.monotonic() < chart_deadline:
            counts = browser_driver.has_canvas_or_svg()
            if counts["canvas"] > 0 or counts["svg"] > 0:
                break
            time.sleep(0.25)
        assert counts["canvas"] > 0 or counts["svg"] > 0, (
            f"Expected ECharts <canvas>/<svg> on /tablero Consolidado, got {counts}"
        )
        assert not _browser_errors(browser_driver), _browser_errors(browser_driver)

        # ------------------------------------------------------------------
        # Phase 3: Single-sede Montelíbano user cross-sede & ?sede=todas probes
        # ------------------------------------------------------------------
        mtl_client = auth_session_factory(
            mtl_only_user["nombre_usuario"], mtl_only_user["_secret"], sede="montelibano"
        )
        for path in ("/api/v1/luminarias", "/api/v1/pqrs", "/api/v1/ordenes", "/api/v1/materiales"):
            assert_problem_json(mtl_client.get(path, sede="alcala"), expected_status=403)

        assert_problem_json(
            mtl_client.get("/api/v1/tablero/resumen", params={"sede": "todas"}, omit_sede=True),
            expected_status=403,
        )

        cross_probes = [
            f"/api/v1/luminarias/{alc_lum_id}",
            f"/api/v1/pqrs/{alc_pqrs_id}",
            f"/api/v1/ordenes/{alc_ot_id}",
            f"/api/v1/materiales/{alc_mat_id}",
            f"/api/v1/archivos/{alc_file_id}",
            f"/api/v1/comercial/vatia/cargues/{alc_cargue_id}",
            f"/api/v1/comercial/cargues/{alc_cargue_id}",
        ]
        for probe in cross_probes:
            resp = mtl_client.get(probe, sede="montelibano")
            assert_problem_json(resp, expected_status=(403, 404))
            assert alc_lum_secret not in resp.text
            assert alc_pqrs_secret not in resp.text
            assert alc_mat_secret not in resp.text
            assert alc_cit_ident not in resp.text

        # ------------------------------------------------------------------
        # Phase 4: PII masking & nominal commercial 403 + DB audit verification
        # ------------------------------------------------------------------
        msk_client = auth_session_factory(
            masked_user["nombre_usuario"], masked_user["_secret"], sede="montelibano"
        )
        cit_search = msk_client.get(
            "/api/v1/ciudadanos",
            sede="montelibano",
            params={"buscar": f"Marta PII {tag}", "page": 1, "size": 10},
        )
        assert cit_search.status_code == 200, cit_search.text
        assert pii_ident not in cit_search.text
        assert pii_phone not in cit_search.text
        assert pii_email not in cit_search.text

        pqrs_detail = msk_client.get(f"/api/v1/pqrs/{mtl_pqrs_id}", sede="montelibano")
        assert pqrs_detail.status_code == 200, pqrs_detail.text
        assert pii_ident not in pqrs_detail.text
        assert pii_phone not in pqrs_detail.text
        assert pii_email not in pqrs_detail.text

        for nom_path in (
            "/api/v1/comercial/afinia/analisis/trazabilidad/7000001",
            "/api/v1/comercial/afinia/analisis/detalle/202605",
        ):
            assert_problem_json(msk_client.get(nom_path, sede="montelibano"), expected_status=403)
        assert_problem_json(
            msk_client.post(
                "/api/v1/comercial/afinia/entregables/anexo-nominal",
                sede="montelibano",
                json_body={"periodo": "202605"},
            ),
            expected_status=403,
        )

        # Authorized nominal query & mutation -> verify auditoria & auditoria_consulta rows
        audit_before = db_helper.count_audit_logs()
        nominal_before = db_helper.count_nominal_consult_logs()

        auth_cit = admin_mtl.get(
            "/api/v1/ciudadanos",
            sede="montelibano",
            params={"buscar": f"Marta PII {tag}", "page": 1, "size": 10},
        )
        assert auth_cit.status_code == 200, auth_cit.text
        assert pii_ident in auth_cit.text

        patch_cit = admin_mtl.patch(
            f"/api/v1/ciudadanos/{mtl_cit.json()['id']}",
            sede="montelibano",
            json_body={"sector": f"Sector Audit {tag}"},
        )
        assert patch_cit.status_code == 200, patch_cit.text

        assert db_helper.count_nominal_consult_logs() > nominal_before
        assert db_helper.count_audit_logs() > audit_before
    finally:
        for uid in (gerente["id"], mtl_only_user["id"], masked_user["id"]):
            admin_mtl.patch(f"/api/v1/usuarios/{uid}", omit_sede=True, json_body={"activo": False})
