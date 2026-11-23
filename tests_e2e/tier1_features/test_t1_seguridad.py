"""Tier 1 E2E tests for EP-01 Seguridad y Sedes (F1-1..F1-7) & apps/web auth shell."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from harness.browser import BrowserDriver
from harness.client import SapefClient, assert_problem_json
from harness.config import E2EConfig
from harness.db import DbHelper


def _admin_creds(e2e_config: E2EConfig) -> tuple[str, str]:
    assert e2e_config.admin_password, (
        "SAPEF_E2E_ADMIN_PASSWORD must be configured to run authenticated E2E tests"
    )
    return e2e_config.admin_user, e2e_config.admin_password


def _unique_secret() -> str:
    return f"SapefE2e!{uuid.uuid4().hex[:10]}9Z"


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [dict(item) for item in payload["items"]]
    raise AssertionError(f"Unexpected list/paginated payload: {payload!r}")


def _perm_code(perm: Any) -> str:
    if isinstance(perm, str):
        return perm
    if isinstance(perm, dict):
        return str(perm.get("codigo", ""))
    return str(perm)


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
def test_login_argon2id_cookies_and_profile_without_hash(
    e2e_config: E2EConfig,
    inprocess_or_live_client: SapefClient,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)

    bad_resp = inprocess_or_live_client.login(
        admin_user,
        _unique_secret(),
        expect_ok=False,
    )
    assert_problem_json(bad_resp, expected_status=401)

    ok_resp = inprocess_or_live_client.login(admin_user, admin_pw, tipo_cliente="web")
    assert ok_resp.status_code == 200
    assert "hash_clave" not in ok_resp.text.lower()
    assert "clave" not in {k.lower() for k in ok_resp.json()}

    body = ok_resp.json()
    perfil = body.get("usuario", body)
    assert perfil.get("nombre_usuario") == admin_user
    assert isinstance(perfil.get("sedes", body.get("sedes")), list)

    set_cookie_hdr = ok_resp.header("set-cookie", "") or ""
    assert "httponly" in set_cookie_hdr.lower(), (
        f"Expected HttpOnly cookie attribute, got Set-Cookie={set_cookie_hdr!r}"
    )
    assert "samesite=" in set_cookie_hdr.lower(), (
        f"Expected SameSite cookie attribute, got Set-Cookie={set_cookie_hdr!r}"
    )
    assert len(inprocess_or_live_client.cookie_names()) >= 1


@pytest.mark.tier1
def test_refresh_rotation_yo_and_logout(
    e2e_config: E2EConfig,
    inprocess_or_live_client: SapefClient,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    inprocess_or_live_client.login(admin_user, admin_pw, tipo_cliente="web")

    yo_resp = inprocess_or_live_client.get("/api/v1/yo", omit_sede=True)
    assert yo_resp.status_code == 200
    assert "hash_clave" not in yo_resp.text.lower()
    yo = yo_resp.json()
    assert yo["nombre_usuario"] == admin_user
    assert yo.get("rol")
    assert isinstance(yo.get("permisos"), list) and len(yo["permisos"]) >= 1
    assert isinstance(yo.get("sedes"), list) and len(yo["sedes"]) >= 1
    assert "debe_cambiar_clave" in yo
    assert "acepto_condiciones_en" in yo

    renovar_resp = inprocess_or_live_client.post("/api/v1/auth/renovar", omit_sede=True)
    assert renovar_resp.status_code in {200, 204}

    yo_after_refresh = inprocess_or_live_client.get("/api/v1/yo", omit_sede=True)
    assert yo_after_refresh.status_code == 200
    assert yo_after_refresh.json()["nombre_usuario"] == admin_user

    salir_resp = inprocess_or_live_client.logout()
    assert salir_resp.status_code in {200, 204}

    yo_after_logout = inprocess_or_live_client.get("/api/v1/yo", omit_sede=True)
    assert_problem_json(yo_after_logout, expected_status=401)


@pytest.mark.tier1
def test_password_recovery_procrastinate_ids_only_and_forced_change_terms(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    db_helper: DbHelper,
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    roles = _extract_items(admin.get("/api/v1/roles", omit_sede=True).json())
    mtl = next(s for s in sedes if s["codigo"] == "montelibano")
    role = next(r for r in roles if r["codigo"] in {"COORDINACION", "INTERVENTORIA", "ADMIN"})

    suffix = uuid.uuid4().hex[:6].lower()
    username = f"{run_id.lower()}_rec_{suffix}"
    email = f"{username}@example.test"
    initial_pw = _unique_secret()
    new_pw = _unique_secret()

    create_resp = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": username,
            "nombre_completo": f"Usuario Recuperación {suffix}",
            "identificacion": f"88{int(suffix, 16) % 10000000:07d}",
            "correo": email,
            "clave": initial_pw,
            "rol_id": role["id"],
            "sedes": [mtl["id"]],
            "activo": True,
            "debe_cambiar_clave": True,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created_user = create_resp.json()
    user_id = created_user["id"]

    try:
        anon = admin.clone()
        anon.clear_cookies()

        max_job_id = int(
            db_helper.scalar("SELECT COALESCE(MAX(id), 0) FROM procrastinate_jobs") or 0
        )
        rec_resp = anon.post(
            "/api/v1/auth/recuperar",
            omit_sede=True,
            json_body={"correo": email},
        )
        assert rec_resp.status_code in {200, 202}, rec_resp.text

        unknown_resp = anon.post(
            "/api/v1/auth/recuperar",
            omit_sede=True,
            json_body={"correo": f"noexiste_{suffix}@example.test"},
        )
        assert unknown_resp.status_code in {200, 202}, unknown_resp.text

        jobs = db_helper.fetch_all(
            """
            SELECT id, task_name, args
            FROM procrastinate_jobs
            WHERE id > %s
            ORDER BY id DESC
            """,
            (max_job_id,),
        )
        assert len(jobs) >= 1, "Expected Procrastinate recovery job to be enqueued"
        job_args_str = json.dumps(jobs[0].get("args", {})).lower()
        assert email.lower() not in job_args_str
        assert "hash_clave" not in job_args_str
        assert initial_pw.lower() not in job_args_str
        assert str(user_id) in job_args_str or "usuario_id" in job_args_str

        user_client = anon.clone()
        login_resp = user_client.login(username, initial_pw)
        assert login_resp.json().get("debe_cambiar_clave") is True

        change_resp = user_client.post(
            "/api/v1/auth/cambiar-clave",
            omit_sede=True,
            json_body={"clave_actual": initial_pw, "clave_nueva": new_pw},
        )
        assert change_resp.status_code in {200, 204}, change_resp.text

        terms_resp = user_client.post(
            "/api/v1/yo/aceptar-condiciones",
            omit_sede=True,
            json_body={},
        )
        assert terms_resp.status_code == 200, terms_resp.text

        yo_updated = user_client.get("/api/v1/yo", omit_sede=True)
        assert yo_updated.status_code == 200
        assert yo_updated.json()["debe_cambiar_clave"] is False
        assert yo_updated.json()["acepto_condiciones_en"] is not None

        relogin = anon.clone()
        relogin.login(username, new_pw)
        relogin.close()
        user_client.close()
        anon.close()
    finally:
        admin.patch(
            f"/api/v1/usuarios/{user_id}",
            omit_sede=True,
            json_body={"activo": False},
        )


@pytest.mark.tier1
def test_users_crud_single_role_multisede_no_hash_leak(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    roles = _extract_items(admin.get("/api/v1/roles", omit_sede=True).json())
    mtl = next(s for s in sedes if s["codigo"] == "montelibano")
    alc = next(s for s in sedes if s["codigo"] == "alcala")
    role = next(r for r in roles if r["codigo"] == "INTERVENTORIA")

    suffix = uuid.uuid4().hex[:6].lower()
    username = f"{run_id.lower()}_usr_{suffix}"
    pw = _unique_secret()

    create_resp = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": username,
            "nombre_completo": f"Interventor MultiSede {suffix}",
            "identificacion": f"77{int(suffix, 16) % 10000000:07d}",
            "correo": f"{username}@example.test",
            "clave": pw,
            "rol_id": role["id"],
            "sedes": [mtl["id"], alc["id"]],
            "activo": True,
            "debe_cambiar_clave": False,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    assert "hash_clave" not in create_resp.text.lower()
    created = create_resp.json()
    user_id = created["id"]

    list_resp = admin.get(
        "/api/v1/usuarios",
        omit_sede=True,
        params={"buscar": username, "page": 1, "size": 20},
    )
    assert list_resp.status_code == 200
    assert "hash_clave" not in list_resp.text.lower()
    list_body = list_resp.json()
    assert list_body["total"] >= 1
    assert any(u["id"] == user_id for u in list_body["items"])

    detail_resp = admin.get(f"/api/v1/usuarios/{user_id}", omit_sede=True)
    assert detail_resp.status_code == 200
    assert "hash_clave" not in detail_resp.text.lower()
    detail = detail_resp.json()
    assert len(detail["sedes"]) == 2

    patch_resp = admin.patch(
        f"/api/v1/usuarios/{user_id}",
        omit_sede=True,
        json_body={
            "nombre_completo": f"Interventor Editado {suffix}",
            "activo": False,
        },
    )
    assert patch_resp.status_code == 200
    assert "hash_clave" not in patch_resp.text.lower()
    patched = patch_resp.json()
    assert patched["nombre_completo"] == f"Interventor Editado {suffix}"
    assert patched["activo"] is False


@pytest.mark.tier1
def test_granular_rbac_roles_and_permisos_catalog(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    perms_resp = admin.get("/api/v1/permisos", omit_sede=True)
    assert perms_resp.status_code == 200
    perms = _extract_items(perms_resp.json())
    perm_codes = {_perm_code(p) for p in perms}
    assert len(perm_codes) >= 52, f"Expected >= 52 seeded permissions, got {len(perm_codes)}"

    required_sample = {
        "seguridad.usuario.ver",
        "configuracion.acuerdo.aprobar",
        "activos.luminaria.mover",
        "atencion.datos_personales.ver",
        "trabajos.orden.cerrar",
        "inventario.movimiento.ajustar",
        "comercial.nominal.ver",
        "tablero.consolidado.ver",
        "campo.app.usar",
    }
    assert required_sample.issubset(perm_codes)

    roles_resp = admin.get("/api/v1/roles", omit_sede=True)
    assert roles_resp.status_code == 200
    roles = _extract_items(roles_resp.json())
    role_codes = {r["codigo"] for r in roles}
    assert {"ADMIN", "COORDINACION", "TECNICO", "GERENTE", "ANALISTA_COMERCIAL"}.issubset(
        role_codes
    )

    suffix = uuid.uuid4().hex[:6].upper()
    role_code = f"{run_id}_ROL_{suffix}"
    create_role = admin.post(
        "/api/v1/roles",
        omit_sede=True,
        json_body={
            "codigo": role_code,
            "nombre": f"Rol E2E {suffix}",
            "permisos": ["activos.luminaria.ver", "activos.mapa.ver"],
        },
    )
    assert create_role.status_code == 201, create_role.text
    created_role = create_role.json()
    role_id = created_role["id"]
    initial_perms = {_perm_code(p) for p in created_role["permisos"]}
    assert initial_perms == {"activos.luminaria.ver", "activos.mapa.ver"}

    patch_role = admin.patch(
        f"/api/v1/roles/{role_id}",
        omit_sede=True,
        json_body={
            "nombre": f"Rol E2E Actualizado {suffix}",
            "permisos": [
                "activos.luminaria.ver",
                "activos.mapa.ver",
                "atencion.pqrs.ver",
            ],
        },
    )
    assert patch_role.status_code == 200, patch_role.text
    updated_perms = {_perm_code(p) for p in patch_role.json()["permisos"]}
    assert updated_perms == {
        "activos.luminaria.ver",
        "activos.mapa.ver",
        "atencion.pqrs.ver",
    }


@pytest.mark.tier1
def test_multisede_context_switching_and_auditoria(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    db_helper: DbHelper,
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    roles = _extract_items(admin.get("/api/v1/roles", omit_sede=True).json())
    mtl = next(s for s in sedes if s["codigo"] == "montelibano")
    alc = next(s for s in sedes if s["codigo"] == "alcala")
    coord = next(r for r in roles if r["codigo"] == "COORDINACION")

    suffix = uuid.uuid4().hex[:6].lower()
    username = f"{run_id.lower()}_ms_{suffix}"
    pw = _unique_secret()

    user_resp = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": username,
            "nombre_completo": f"MultiSede Coord {suffix}",
            "identificacion": f"66{int(suffix, 16) % 10000000:07d}",
            "correo": f"{username}@example.test",
            "clave": pw,
            "rol_id": coord["id"],
            "sedes": [mtl["id"], alc["id"]],
            "activo": True,
            "debe_cambiar_clave": False,
        },
    )
    assert user_resp.status_code == 201, user_resp.text
    user_id = user_resp.json()["id"]

    try:
        ms_client = auth_session_factory(username, pw, sede="montelibano")
        mtl_zonas_resp = ms_client.get("/api/v1/zonas", sede="montelibano")
        assert mtl_zonas_resp.status_code == 200
        mtl_zonas = {z["nombre"] for z in _extract_items(mtl_zonas_resp.json())}
        assert "Centro" in mtl_zonas

        alc_zonas_resp = ms_client.get("/api/v1/zonas", sede="alcala")
        assert alc_zonas_resp.status_code == 200
        alc_zonas = {z["nombre"] for z in _extract_items(alc_zonas_resp.json())}
        assert "Ciudadelas Cerro Matoso" not in alc_zonas

        audit_resp = admin.get(
            "/api/v1/auditoria",
            omit_sede=True,
            params={"page": 1, "size": 20},
        )
        assert audit_resp.status_code == 200, audit_resp.text
        audit_items = _extract_items(audit_resp.json())
        assert len(audit_items) >= 1
        assert db_helper.count_audit_logs() >= 1
    finally:
        admin.patch(
            f"/api/v1/usuarios/{user_id}",
            omit_sede=True,
            json_body={"activo": False},
        )


@pytest.mark.tier1
@pytest.mark.browser
def test_web_browser_ingresar_redirect_sede_switcher_and_seguridad(
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
    assert "/ingresar" not in browser_driver.current_url(), (
        f"Expected redirect away from /ingresar, still at {browser_driver.current_url()}"
    )

    cookies = browser_driver.get_cookies()
    assert len(cookies) >= 1, "Expected browser session cookie after login"

    sede_selector_found = browser_driver.eval_js(
        "(() => {"
        "  const el = document.querySelector("
        "    \"[data-testid*='sede' i], [aria-label*='sede' i], select[name*='sede' i]\""
        "  );"
        "  return el !== null || /montel[ií]bano|alcal[aá]/i.test(document.body.innerText);"
        "})()"
    )
    assert sede_selector_found, "Expected sede selector or active sede indicator in shell"

    browser_driver.navigate(f"{web_url}/seguridad/usuarios")
    browser_driver.wait_for_selector("main, table, [role='table'], h1, h2")
    body_text = str(browser_driver.eval_js("document.body.innerText") or "")
    assert len(body_text.strip()) > 0
    assert not _browser_errors(browser_driver), (
        f"Browser reported JS errors: {_browser_errors(browser_driver)}"
    )
