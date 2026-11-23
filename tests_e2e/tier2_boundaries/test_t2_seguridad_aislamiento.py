"""Tier 2 boundary, error, and security E2E tests for EP-01 Seguridad y Sedes."""

from __future__ import annotations

import json
import sys
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fixtures.media_builder import make_png
from fixtures.operational_builder import generate_coordinates
from harness.browser import BrowserDriver
from harness.client import SapefClient, assert_problem_json
from harness.config import E2EConfig

pytestmark = [pytest.mark.tier2, pytest.mark.isolation]


def _admin_creds(e2e_config: E2EConfig) -> tuple[str, str]:
    assert e2e_config.admin_password, (
        "SAPEF_E2E_ADMIN_PASSWORD must be configured to run authenticated E2E tests"
    )
    return e2e_config.admin_user, e2e_config.admin_password


def _unique_secret() -> str:
    return f"SapefT2!{uuid.uuid4().hex[:10]}9Z"


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


def _create_user(
    admin: SapefClient,
    *,
    run_id: str,
    tag: str,
    role_codigo: str,
    sede_codigos: list[str],
    debe_cambiar_clave: bool = False,
    activo: bool = True,
) -> dict[str, Any]:
    sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    sede_map = {s["codigo"]: s["id"] for s in sedes}
    roles = _extract_items(admin.get("/api/v1/roles", omit_sede=True).json())
    role = next(r for r in roles if str(r["codigo"]).upper() == role_codigo.upper())

    suffix = uuid.uuid4().hex[:6].lower()
    username = f"{run_id.lower()}_{tag}_{suffix}"
    secret = _unique_secret()
    resp = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": username,
            "nombre_completo": f"Usuario T2 {tag} {suffix}",
            "identificacion": f"71{int(suffix, 16) % 10000000:07d}",
            "correo": f"{username}@example.test",
            "clave": secret,
            "rol_id": role["id"],
            "sedes": [sede_map[c] for c in sede_codigos],
            "activo": activo,
            "debe_cambiar_clave": debe_cambiar_clave,
        },
    )
    assert resp.status_code == 201, f"Create user failed: {resp.status_code} {resp.text}"
    user_dto = dict(resp.json())
    user_dto["_secret"] = secret
    return user_dto


def _deactivate_user(admin: SapefClient, user_id: Any) -> None:
    admin.patch(
        f"/api/v1/usuarios/{user_id}",
        omit_sede=True,
        json_body={"activo": False},
    )


def test_unauthenticated_and_invalid_credentials_return_401_rfc9457_never_500(
    e2e_config: E2EConfig,
    inprocess_or_live_client: SapefClient,
) -> None:
    """Unauthenticated protected endpoints & bad logins return 401 RFC 9457 with requestId."""
    admin_user, _ = _admin_creds(e2e_config)

    for method, path in (
        ("GET", "/api/v1/yo"),
        ("GET", "/api/v1/usuarios"),
        ("GET", "/api/v1/luminarias"),
        ("GET", "/api/v1/pqrs"),
        ("GET", "/api/v1/ordenes"),
        ("POST", "/api/v1/auth/salir"),
        ("POST", "/api/v1/auth/renovar"),
    ):
        rid = f"t2-401-{uuid.uuid4().hex[:6]}"
        resp = inprocess_or_live_client.request(
            method,
            path,
            sede="montelibano",
            request_id=rid,
        )
        assert resp.status_code < 500, f"{method} {path} returned 5xx: {resp.text}"
        body = assert_problem_json(resp, expected_status=401, require_request_id=True)
        assert body["requestId"] == rid

    for bad_user, bad_secret in (
        (admin_user, _unique_secret()),
        (f"no_existe_{uuid.uuid4().hex[:8]}", _unique_secret()),
    ):
        rid = f"t2-badlogin-{uuid.uuid4().hex[:6]}"
        resp = inprocess_or_live_client.post(
            "/api/v1/auth/ingresar",
            omit_sede=True,
            request_id=rid,
            json_body={"usuario": bad_user, "clave": bad_secret, "tipo_cliente": "web"},
        )
        assert resp.status_code < 500, f"Login returned 5xx: {resp.text}"
        body = assert_problem_json(resp, expected_status=401, require_request_id=True)
        assert body["requestId"] == rid


def test_bruteforce_lockout_after_five_failed_attempts(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Five consecutive failed logins lock the account with HTTP 423 or 429 RFC 9457."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    user = _create_user(
        admin,
        run_id=run_id,
        tag="lock",
        role_codigo="INTERVENTORIA",
        sede_codigos=["montelibano"],
    )
    try:
        probe = admin.clone()
        probe.clear_cookies()
        for attempt in range(5):
            fail_resp = probe.login(
                user["nombre_usuario"],
                _unique_secret(),
                expect_ok=False,
            )
            assert fail_resp.status_code < 500
            if attempt < 4:
                assert_problem_json(fail_resp, expected_status=401)
            else:
                assert_problem_json(fail_resp, expected_status=(401, 423, 429))

        locked_wrong = probe.login(user["nombre_usuario"], _unique_secret(), expect_ok=False)
        assert_problem_json(locked_wrong, expected_status=(423, 429))

        locked_valid = probe.login(user["nombre_usuario"], user["_secret"], expect_ok=False)
        assert_problem_json(locked_valid, expected_status=(423, 429))
        probe.close()
    finally:
        _deactivate_user(admin, user["id"])


def test_refresh_token_reuse_detection_revokes_entire_session_family(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Replaying a pre-rotation refresh token returns 401 and revokes the active session family."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    user = _create_user(
        admin,
        run_id=run_id,
        tag="reuse",
        role_codigo="COORDINACION",
        sede_codigos=["montelibano"],
    )
    try:
        client = admin.clone()
        client.clear_cookies()
        client.login(user["nombre_usuario"], user["_secret"], tipo_cliente="web")

        stale_cookie_header = "; ".join(
            f"{name}={client.get_cookie(name)}"
            for name in client.cookie_names()
            if client.get_cookie(name) is not None
        )
        assert stale_cookie_header, "Expected session cookies after login"

        rot_resp = client.post("/api/v1/auth/renovar", omit_sede=True)
        assert rot_resp.status_code in {200, 204}, rot_resp.text

        yo_ok = client.get("/api/v1/yo", omit_sede=True)
        assert yo_ok.status_code == 200

        attacker = admin.clone()
        attacker.clear_cookies()
        replay_resp = attacker.post(
            "/api/v1/auth/renovar",
            omit_sede=True,
            headers={"Cookie": stale_cookie_header},
        )
        assert_problem_json(replay_resp, expected_status=401)

        victim_refresh = client.post("/api/v1/auth/renovar", omit_sede=True)
        assert_problem_json(victim_refresh, expected_status=401)

        attacker.close()
        client.close()
    finally:
        _deactivate_user(admin, user["id"])


def test_mandatory_password_change_blocks_operations_and_revokes_other_sessions(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """debe_cambiar_clave=true blocks operational routes (403) and revokes peer sessions."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    user = _create_user(
        admin,
        run_id=run_id,
        tag="chgpwd",
        role_codigo="COORDINACION",
        sede_codigos=["montelibano"],
        debe_cambiar_clave=True,
    )
    try:
        sess1 = admin.clone()
        sess1.clear_cookies()
        login1 = sess1.login(user["nombre_usuario"], user["_secret"], tipo_cliente="web")
        assert login1.json().get("debe_cambiar_clave") is True

        sess2 = admin.clone()
        sess2.clear_cookies()
        sess2.login(user["nombre_usuario"], user["_secret"], tipo_cliente="web")

        for blocked_path in ("/api/v1/luminarias", "/api/v1/zonas", "/api/v1/pqrs"):
            blocked = sess1.get(blocked_path, sede="montelibano")
            assert_problem_json(blocked, expected_status=403)

        bad_change = sess1.post(
            "/api/v1/auth/cambiar-clave",
            omit_sede=True,
            json_body={"clave_actual": _unique_secret(), "clave_nueva": _unique_secret()},
        )
        assert_problem_json(bad_change, expected_status=(400, 401, 403))

        new_secret = _unique_secret()
        ok_change = sess1.post(
            "/api/v1/auth/cambiar-clave",
            omit_sede=True,
            json_body={"clave_actual": user["_secret"], "clave_nueva": new_secret},
        )
        assert ok_change.status_code in {200, 204}, ok_change.text

        unblocked = sess1.get("/api/v1/zonas", sede="montelibano")
        assert unblocked.status_code == 200, unblocked.text

        peer_refresh = sess2.post("/api/v1/auth/renovar", omit_sede=True)
        assert_problem_json(peer_refresh, expected_status=401)
        peer_yo = sess2.get("/api/v1/yo", omit_sede=True)
        assert_problem_json(peer_yo, expected_status=401)

        sess1.close()
        sess2.close()
    finally:
        _deactivate_user(admin, user["id"])


def test_password_reset_invalid_token_and_weak_password_rejected(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Invalid/expired reset token and weak passwords return 400/422 RFC 9457."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    anon = admin.clone()
    anon.clear_cookies()

    bad_email_rec = anon.post(
        "/api/v1/auth/recuperar",
        omit_sede=True,
        json_body={"correo": "correo-no-valido"},
    )
    assert_problem_json(bad_email_rec, expected_status=422)

    bad_token_reset = anon.post(
        "/api/v1/auth/restablecer",
        omit_sede=True,
        json_body={"token": f"expired-invalid-{uuid.uuid4().hex}", "clave_nueva": _unique_secret()},
    )
    assert_problem_json(bad_token_reset, expected_status=(400, 422))

    weak_reset = anon.post(
        "/api/v1/auth/restablecer",
        omit_sede=True,
        json_body={"token": uuid.uuid4().hex, "clave_nueva": "123"},
    )
    assert_problem_json(weak_reset, expected_status=(400, 422))

    user = _create_user(
        admin,
        run_id=run_id,
        tag="weakpw",
        role_codigo="INTERVENTORIA",
        sede_codigos=["montelibano"],
    )
    try:
        uclient = auth_session_factory(user["nombre_usuario"], user["_secret"], sede="montelibano")
        weak_change = uclient.post(
            "/api/v1/auth/cambiar-clave",
            omit_sede=True,
            json_body={"clave_actual": user["_secret"], "clave_nueva": "abc"},
        )
        assert_problem_json(weak_change, expected_status=(400, 422))
    finally:
        anon.close()
        _deactivate_user(admin, user["id"])


def test_missing_x_sede_header_returns_400_rfc9457(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
) -> None:
    """Omitting X-Sede on sede-scoped endpoints returns HTTP 400 RFC 9457."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    for path in (
        "/api/v1/zonas",
        "/api/v1/barrios",
        "/api/v1/luminarias",
        "/api/v1/pqrs",
        "/api/v1/ordenes",
        "/api/v1/materiales",
        "/api/v1/acuerdos",
    ):
        resp = admin.get(path, omit_sede=True)
        assert_problem_json(resp, expected_status=400)


def test_cross_sede_header_rejected_with_403(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Montelíbano-only user sending X-Sede: alcala receives 403 RFC 9457."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    mtl_only = _create_user(
        admin,
        run_id=run_id,
        tag="mtlonly",
        role_codigo="COORDINACION",
        sede_codigos=["montelibano"],
    )
    try:
        client = auth_session_factory(
            mtl_only["nombre_usuario"],
            mtl_only["_secret"],
            sede="montelibano",
        )
        assert client.get("/api/v1/zonas", sede="montelibano").status_code == 200

        for path in (
            "/api/v1/zonas",
            "/api/v1/barrios",
            "/api/v1/luminarias",
            "/api/v1/pqrs",
            "/api/v1/ordenes",
            "/api/v1/materiales",
            "/api/v1/acuerdos",
        ):
            resp = client.get(path, sede="alcala")
            assert_problem_json(resp, expected_status=403)
    finally:
        _deactivate_user(admin, mtl_only["id"])


def test_cross_sede_resource_ids_do_not_leak_existence(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Requesting Alcalá resource IDs with X-Sede: montelibano returns 404/403 without leak."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="alcala")

    barrios = _extract_items(admin.get("/api/v1/barrios", sede="alcala").json())
    estados = _extract_items(
        admin.get("/api/v1/estados", omit_sede=True, params={"proceso": "luminaria"}).json()
    )
    est_121 = next(e["id"] for e in estados if str(e["codigo"]) == "121")
    tech_id = _extract_items(
        admin.get("/api/v1/maestros/LUMINARIA_TECNOLOGIA", omit_sede=True).json()
    )[0]["id"]
    pot_id = _extract_items(
        admin.get("/api/v1/maestros/LUMINARIA_POTENCIA", omit_sede=True).json()
    )[0]["id"]
    canal_id = _extract_items(
        admin.get("/api/v1/maestros/CANAL_PQRS", omit_sede=True).json()
    )[0]["id"]

    suffix = uuid.uuid4().hex[:6].upper()
    lat, lng = generate_coordinates("alcala", 1, seed=91)[0]
    lum_secret_code = f"{run_id}-ALC-SEC-{suffix}"
    lum_resp = admin.post(
        "/api/v1/luminarias",
        sede="alcala",
        json_body={
            "codigo": lum_secret_code,
            "barrio_id": barrios[0]["id"],
            "latitud": lat,
            "longitud": lng,
            "estado_id": est_121,
            "tecnologia_id": tech_id,
            "potencia_id": pot_id,
        },
    )
    assert lum_resp.status_code == 201, lum_resp.text
    alc_lum_id = lum_resp.json()["id"]

    cit_resp = admin.post(
        "/api/v1/ciudadanos",
        sede="alcala",
        json_body={
            "identificacion": f"ALC-{suffix}",
            "nombre_completo": f"Ciudadano Alcala {suffix}",
            "correo": f"alc.{suffix.lower()}@example.test",
        },
    )
    assert cit_resp.status_code == 201, cit_resp.text
    pqrs_resp = admin.post(
        "/api/v1/pqrs",
        sede="alcala",
        json_body={
            "canal_id": canal_id,
            "ciudadano_id": cit_resp.json()["id"],
            "prioridad": 1,
            "observacion_solicitante": f"Secreto Alcala {suffix}",
            "notificar_cliente": False,
            "luminarias": [{"luminaria_id": alc_lum_id}],
        },
    )
    assert pqrs_resp.status_code == 201, pqrs_resp.text
    alc_pqrs_id = pqrs_resp.json()["id"]

    ot_resp = admin.post(
        "/api/v1/ordenes",
        sede="alcala",
        json_body={
            "tipo": "mantenimiento",
            "prioridad": 1,
            "observaciones": f"Orden Alcala {suffix}",
            "luminarias": [{"luminaria_id": alc_lum_id, "rol": "intervenida"}],
        },
    )
    assert ot_resp.status_code == 201, ot_resp.text
    alc_ot_id = ot_resp.json()["id"]

    mat_secret_code = f"{run_id}-ALCMAT-{suffix}"
    mat_resp = admin.post(
        "/api/v1/materiales",
        sede="alcala",
        json_body={
            "categoria": "CABLE",
            "codigo": mat_secret_code,
            "descripcion": f"Material Alcala {suffix}",
            "unidad": "MTS",
            "existencias": 10,
            "existencias_minimas": 2,
        },
    )
    assert mat_resp.status_code == 201, mat_resp.text
    alc_mat_id = mat_resp.json()["id"]

    arch_resp = admin.post(
        "/api/v1/archivos",
        sede="alcala",
        idempotency_key=str(uuid.uuid4()),
        files={"archivo": ("alcala.png", make_png(3, 3), "image/png")},
    )
    assert arch_resp.status_code in {200, 201}, arch_resp.text
    alc_arch_id = arch_resp.json()["id"]

    mtl_user = _create_user(
        admin,
        run_id=run_id,
        tag="probe",
        role_codigo="COORDINACION",
        sede_codigos=["montelibano"],
    )
    try:
        mtl_client = auth_session_factory(
            mtl_user["nombre_usuario"],
            mtl_user["_secret"],
            sede="montelibano",
        )
        probes = [
            f"/api/v1/luminarias/{alc_lum_id}",
            f"/api/v1/pqrs/{alc_pqrs_id}",
            f"/api/v1/ordenes/{alc_ot_id}",
            f"/api/v1/materiales/{alc_mat_id}",
            f"/api/v1/archivos/{alc_arch_id}",
        ]
        for probe_path in probes:
            resp = mtl_client.get(probe_path, sede="montelibano")
            assert_problem_json(resp, expected_status=(403, 404))
            assert lum_secret_code not in resp.text
            assert mat_secret_code not in resp.text
            assert f"Secreto Alcala {suffix}" not in resp.text
    finally:
        _deactivate_user(admin, mtl_user["id"])


def test_missing_rbac_permission_in_own_sede_returns_403_rfc9457(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """User lacking modulo.recurso.accion permission in own sede receives 403 RFC 9457."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    suffix = uuid.uuid4().hex[:6].upper()
    role_resp = admin.post(
        "/api/v1/roles",
        omit_sede=True,
        json_body={
            "codigo": f"{run_id}_READONLY_{suffix}",
            "nombre": f"Solo Lectura Activos {suffix}",
            "permisos": ["activos.luminaria.ver", "activos.mapa.ver"],
        },
    )
    assert role_resp.status_code == 201, role_resp.text
    role_code = role_resp.json()["codigo"]

    user = _create_user(
        admin,
        run_id=run_id,
        tag="rbac",
        role_codigo=role_code,
        sede_codigos=["montelibano"],
    )
    try:
        client = auth_session_factory(
            user["nombre_usuario"],
            user["_secret"],
            sede="montelibano",
        )
        assert client.get("/api/v1/luminarias", sede="montelibano").status_code == 200

        forbidden_calls = [
            ("GET", "/api/v1/usuarios", True, None),
            ("POST", "/api/v1/luminarias", False, {"codigo": f"X-{suffix}"}),
            ("POST", "/api/v1/ordenes", False, {"tipo": "mantenimiento", "prioridad": 1}),
            ("POST", "/api/v1/materiales", False, {"codigo": f"M-{suffix}"}),
            ("GET", "/api/v1/tablero/resumen", True, None),
        ]
        for method, path, omit_sede, payload in forbidden_calls:
            resp = client.request(
                method,
                path,
                omit_sede=omit_sede,
                sede=None if omit_sede else "montelibano",
                json_body=payload,
                params={"sede": "todas"} if path.endswith("/resumen") else None,
            )
            assert_problem_json(resp, expected_status=403)
    finally:
        _deactivate_user(admin, user["id"])


def test_duplicate_username_and_role_codigo_409_invalid_permission_422(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Duplicate nombre_usuario or role codigo -> 409; unknown permission code -> 422."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    user = _create_user(
        admin,
        run_id=run_id,
        tag="dup",
        role_codigo="INTERVENTORIA",
        sede_codigos=["montelibano"],
    )
    try:
        sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
        mtl_id = next(s["id"] for s in sedes if s["codigo"] == "montelibano")
        roles = _extract_items(admin.get("/api/v1/roles", omit_sede=True).json())
        role_id = roles[0]["id"]

        dup_user = admin.post(
            "/api/v1/usuarios",
            omit_sede=True,
            json_body={
                "nombre_usuario": user["nombre_usuario"],
                "nombre_completo": "Duplicado E2E",
                "identificacion": f"72{uuid.uuid4().hex[:7]}",
                "correo": f"dup.{uuid.uuid4().hex[:6]}@example.test",
                "clave": _unique_secret(),
                "rol_id": role_id,
                "sedes": [mtl_id],
                "activo": True,
            },
        )
        assert_problem_json(dup_user, expected_status=409)
    finally:
        _deactivate_user(admin, user["id"])

    role_code = f"{run_id}_DUPROL_{uuid.uuid4().hex[:5].upper()}"
    ok_role = admin.post(
        "/api/v1/roles",
        omit_sede=True,
        json_body={
            "codigo": role_code,
            "nombre": "Rol Unico",
            "permisos": ["activos.luminaria.ver"],
        },
    )
    assert ok_role.status_code == 201, ok_role.text

    dup_role = admin.post(
        "/api/v1/roles",
        omit_sede=True,
        json_body={
            "codigo": role_code,
            "nombre": "Rol Duplicado",
            "permisos": ["activos.luminaria.ver"],
        },
    )
    assert_problem_json(dup_role, expected_status=409)

    bad_perm_role = admin.post(
        "/api/v1/roles",
        omit_sede=True,
        json_body={
            "codigo": f"{role_code}_BAD",
            "nombre": "Rol Permiso Invalido",
            "permisos": ["modulo.inexistente.accion"],
        },
    )
    assert_problem_json(bad_perm_role, expected_status=422)


def test_zero_leakage_of_hashes_secrets_or_stack_traces(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
) -> None:
    """API responses and error bodies must never expose hash_clave, SMTP/VAPID secrets, or traces."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    responses = [
        admin.get("/api/v1/yo", omit_sede=True),
        admin.get("/api/v1/usuarios", omit_sede=True, params={"page": 1, "size": 20}),
        admin.get("/api/v1/parametros", sede="montelibano"),
        admin.get("/api/v1/auditoria", omit_sede=True, params={"page": 1, "size": 10}),
        admin.get("/api/v1/ruta-inexistente-t2", omit_sede=True),
        admin.get("/api/v1/luminarias", omit_sede=True),
    ]
    forbidden_markers = (
        "hash_clave",
        "$argon2",
        "mailpasswd",
        "mailuser",
        "smtp_password",
        "vapid_private_key",
        "secret_key",
        "traceback (most recent call last)",
        "sqlalchemy.exc.",
        "psycopg.",
    )
    for resp in responses:
        lowered = resp.text.lower()
        for marker in forbidden_markers:
            assert marker not in lowered, (
                f"Sensitive marker {marker!r} leaked in {resp.url}: {resp.text[:300]}"
            )


def test_production_mode_hides_docs_openapi_and_sistema_prueba(
    e2e_config: E2EConfig,
    inprocess_or_live_client: SapefClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SAPEF_ENTORNO=produccion hides /api/docs, /api/openapi.json, /sistema/tareas/prueba (404)."""
    if not e2e_config.inprocess:
        openapi_probe = inprocess_or_live_client.get("/api/openapi.json", omit_sede=True)
        if openapi_probe.status_code == 404:
            for method, path in (
                ("GET", "/api/docs"),
                ("GET", "/api/openapi.json"),
                ("POST", "/api/v1/sistema/tareas/prueba"),
            ):
                assert_problem_json(
                    inprocess_or_live_client.request(method, path, omit_sede=True),
                    expected_status=404,
                )
            return

    backend_dir = str(e2e_config.backend_dir)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from app.core.config import obtener_configuracion  # type: ignore[import-not-found]
    from app.main import crear_app  # type: ignore[import-not-found]

    monkeypatch.setenv("SAPEF_ENTORNO", "produccion")
    monkeypatch.setenv("SAPEF_SECRET_KEY", f"e2e-prod-secret-{uuid.uuid4().hex}-xYz!")
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


@pytest.mark.browser
def test_browser_unauthenticated_mapa_redirects_to_ingresar(
    e2e_config: E2EConfig,
    browser_driver: BrowserDriver,
) -> None:
    """Unauthenticated visit to apps/web /mapa redirects to /ingresar."""
    web_url = e2e_config.web_url
    browser_driver.navigate(f"{web_url}/mapa")

    deadline = time.monotonic() + e2e_config.timeout_seconds
    while time.monotonic() < deadline:
        if "/ingresar" in browser_driver.current_url():
            break
        time.sleep(0.15)

    assert "/ingresar" in browser_driver.current_url(), (
        f"Expected redirect to /ingresar, got {browser_driver.current_url()}"
    )
    browser_driver.wait_for_selector("input[type='password']")
    assert not _browser_errors(browser_driver), _browser_errors(browser_driver)


@pytest.mark.browser
def test_browser_unauthorized_route_displays_visual_403(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    browser_driver: BrowserDriver,
    run_id: str,
) -> None:
    """User lacking seguridad.usuario.ver navigating to /seguridad/usuarios sees visual 403."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    user = _create_user(
        admin,
        run_id=run_id,
        tag="web403",
        role_codigo="CENSO",
        sede_codigos=["montelibano"],
    )
    try:
        web_url = e2e_config.web_url
        browser_driver.navigate(f"{web_url}/ingresar")
        browser_driver.wait_for_selector("input[type='password']")
        browser_driver.fill(
            "input[name='usuario'], input[autocomplete='username'], input[type='text']",
            user["nombre_usuario"],
        )
        browser_driver.fill("input[name='clave'], input[type='password']", user["_secret"])
        browser_driver.click("button[type='submit']")

        deadline = time.monotonic() + e2e_config.timeout_seconds
        while time.monotonic() < deadline:
            if "/ingresar" not in browser_driver.current_url():
                break
            time.sleep(0.15)
        assert "/ingresar" not in browser_driver.current_url()

        browser_driver.navigate(f"{web_url}/seguridad/usuarios")
        browser_driver.wait_for_selector("main, [role='alert'], h1, h2, p")
        time.sleep(0.4)
        body_text = str(browser_driver.eval_js("document.body.innerText") or "").lower()
        assert any(
            token in body_text
            for token in ("403", "no autorizado", "acceso denegado", "sin permiso", "prohibido")
        ), f"Expected visual 403 error message on unauthorized route, got: {body_text[:400]}"
    finally:
        _deactivate_user(admin, user["id"])
