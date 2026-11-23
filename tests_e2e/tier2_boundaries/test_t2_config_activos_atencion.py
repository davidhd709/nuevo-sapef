"""Tier 2 boundary and error E2E tests for EP-02 Config, EP-03 Activos/Mapa, EP-04 PQRS."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fixtures.media_builder import (
    make_forged_file,
    make_jpeg,
    make_oversized_payload,
    make_png,
)
from fixtures.operational_builder import (
    build_maintenance_components,
    generate_coordinates,
)
from harness.client import SapefClient, assert_problem_json
from harness.config import E2EConfig

pytestmark = pytest.mark.tier2


def _admin_creds(e2e_config: E2EConfig) -> tuple[str, str]:
    assert e2e_config.admin_password, (
        "SAPEF_E2E_ADMIN_PASSWORD must be configured to run authenticated E2E tests"
    )
    return e2e_config.admin_user, e2e_config.admin_password


def _unique_secret() -> str:
    return f"SapefCfg!{uuid.uuid4().hex[:10]}9Z"


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


def _resolve_sede_catalogs(admin: SapefClient, sede: str = "montelibano") -> dict[str, Any]:
    barrios = _extract_items(admin.get("/api/v1/barrios", sede=sede).json())
    estados_lum = _extract_items(
        admin.get("/api/v1/estados", omit_sede=True, params={"proceso": "luminaria"}).json()
    )
    est_121 = next(e for e in estados_lum if str(e["codigo"]) == "121")
    est_124 = next(e for e in estados_lum if str(e["codigo"]) == "124")
    tech_led = _extract_items(
        admin.get("/api/v1/maestros/LUMINARIA_TECNOLOGIA", omit_sede=True).json()
    )[0]
    pot_70 = _extract_items(
        admin.get("/api/v1/maestros/LUMINARIA_POTENCIA", omit_sede=True).json()
    )[0]
    marca = _extract_items(
        admin.get("/api/v1/maestros/LUMINARIA_MARCA", omit_sede=True).json()
    )[0]
    canal = _extract_items(admin.get("/api/v1/maestros/CANAL_PQRS", omit_sede=True).json())[0]
    return {
        "barrio": barrios[0],
        "estado_121": est_121,
        "estado_124": est_124,
        "tech": tech_led,
        "pot": pot_70,
        "marca": marca,
        "canal": canal,
    }


def _create_user(
    admin: SapefClient,
    *,
    run_id: str,
    tag: str,
    role_codigo: str,
    sedes: list[str],
) -> dict[str, Any]:
    sedes_list = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    sede_ids = [next(s["id"] for s in sedes_list if s["codigo"] == c) for c in sedes]
    roles = _extract_items(admin.get("/api/v1/roles", omit_sede=True).json())
    role_id = next(r["id"] for r in roles if str(r["codigo"]).upper() == role_codigo.upper())
    suffix = uuid.uuid4().hex[:6].lower()
    username = f"{run_id.lower()}_{tag}_{suffix}"
    secret = _unique_secret()
    resp = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": username,
            "nombre_completo": f"User {tag} {suffix}",
            "identificacion": f"73{int(suffix, 16) % 10000000:07d}",
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


def _create_luminaire(
    admin: SapefClient,
    cat: dict[str, Any],
    codigo: str,
    *,
    sede: str = "montelibano",
    estado_key: str = "estado_121",
    seed: int = 1,
) -> dict[str, Any]:
    lat, lng = generate_coordinates(sede, 1, seed=seed)[0]
    resp = admin.post(
        "/api/v1/luminarias",
        sede=sede,
        json_body={
            "codigo": codigo,
            "barrio_id": cat["barrio"]["id"],
            "latitud": lat,
            "longitud": lng,
            "estado_id": cat[estado_key]["id"],
            "tecnologia_id": cat["tech"]["id"],
            "potencia_id": cat["pot"]["id"],
            "marca_id": cat["marca"]["id"],
        },
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


def test_config_duplicate_sede_maestro_and_barrio_return_409(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Duplicate sede, (clase_id, codigo) maestro, and barrio return 409 RFC 9457."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    dup_sede = admin.post(
        "/api/v1/sedes",
        omit_sede=True,
        json_body={
            "codigo": "montelibano",
            "nombre": "Montelibano Duplicado",
            "municipio": "Montelibano",
            "departamento": "Córdoba",
            "activa": True,
        },
    )
    assert_problem_json(dup_sede, expected_status=409)

    suffix = uuid.uuid4().hex[:6].upper()
    maestro_code = f"{run_id}_DUPM_{suffix}"
    ok_maestro = admin.post(
        "/api/v1/maestros/LUMINARIA_MARCA",
        omit_sede=True,
        json_body={"codigo": maestro_code, "nombre": f"Marca {suffix}", "orden": 900},
    )
    assert ok_maestro.status_code == 201, ok_maestro.text
    dup_maestro = admin.post(
        "/api/v1/maestros/LUMINARIA_MARCA",
        omit_sede=True,
        json_body={"codigo": maestro_code, "nombre": f"Marca Dup {suffix}", "orden": 901},
    )
    assert_problem_json(dup_maestro, expected_status=409)

    zona_resp = admin.post(
        "/api/v1/zonas",
        sede="montelibano",
        json_body={"nombre": f"{run_id}_ZONA_{suffix}"},
    )
    assert zona_resp.status_code == 201, zona_resp.text
    zona_id = zona_resp.json()["id"]

    barrio_name = f"{run_id}_BARRIO_{suffix}"
    ok_barrio = admin.post(
        "/api/v1/barrios",
        sede="montelibano",
        json_body={"zona_id": zona_id, "nombre": barrio_name, "activo": True},
    )
    assert ok_barrio.status_code == 201, ok_barrio.text
    dup_barrio = admin.post(
        "/api/v1/barrios",
        sede="montelibano",
        json_body={"zona_id": zona_id, "nombre": barrio_name, "activo": True},
    )
    assert_problem_json(dup_barrio, expected_status=409)


def test_config_barrio_with_cross_sede_zona_id_returns_404(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Creating a barrio in montelibano using a zona_id from alcala returns 404 RFC 9457."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    alc_zonas = _extract_items(admin.get("/api/v1/zonas", sede="alcala").json())
    assert alc_zonas, "Expected seeded zonas in alcala"
    alc_zona_id = alc_zonas[0]["id"]

    resp = admin.post(
        "/api/v1/barrios",
        sede="montelibano",
        json_body={
            "zona_id": alc_zona_id,
            "nombre": f"{run_id}_CROSS_ZONA_{uuid.uuid4().hex[:5]}",
            "activo": True,
        },
    )
    assert_problem_json(resp, expected_status=404)

    alc_barrios = _extract_items(admin.get("/api/v1/barrios", sede="alcala").json())
    patch_cross = admin.patch(
        f"/api/v1/barrios/{alc_barrios[0]['id']}",
        sede="montelibano",
        json_body={"nombre": "No Debe Cambiar"},
    )
    assert_problem_json(patch_cross, expected_status=404)


def test_config_non_editable_parametro_403_and_invalid_value_422(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Editing non-editable parametro returns 403; lacking permission returns 403; bad val 422."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    params = _extract_items(admin.get("/api/v1/parametros", sede="montelibano").json())
    non_editable = [p for p in params if p.get("editable") is False]
    if non_editable:
        target = non_editable[0]
        resp = admin.patch(
            f"/api/v1/parametros/{target['id']}",
            sede="montelibano",
            json_body={"valor": target["valor"]},
        )
        assert_problem_json(resp, expected_status=403)

    semaforo = next(p for p in params if p["codigo"] == "semaforo_pqrs_umbrales")
    bad_val = admin.patch(
        f"/api/v1/parametros/{semaforo['id']}",
        sede="montelibano",
        json_body={"valor": {"verde_max_dias": -5, "amarillo_max_dias": 1}},
    )
    assert_problem_json(bad_val, expected_status=422)

    no_perm_user = _create_user(
        admin,
        run_id=run_id,
        tag="noparam",
        role_codigo="INTERVENTORIA",
        sedes=["montelibano"],
    )
    try:
        uclient = auth_session_factory(
            no_perm_user["nombre_usuario"],
            no_perm_user["_secret"],
            sede="montelibano",
        )
        denied = uclient.patch(
            f"/api/v1/parametros/{semaforo['id']}",
            sede="montelibano",
            json_body={"valor": semaforo["valor"]},
        )
        assert_problem_json(denied, expected_status=403)
    finally:
        admin.patch(
            f"/api/v1/usuarios/{no_perm_user['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )


def test_config_patching_aprobado_tariff_agreement_returns_409(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
) -> None:
    """Approved tariff agreements are immutable; PATCH returns 409 RFC 9457."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    acuerdos = _extract_items(
        admin.get(
            "/api/v1/acuerdos",
            sede="montelibano",
            params={"comercializador": "afinia", "anio": 2026},
        ).json()
    )
    approved = next(a for a in acuerdos if a["estado"] == "aprobado")

    patch_resp = admin.patch(
        f"/api/v1/acuerdos/{approved['id']}",
        sede="montelibano",
        json_body={"tolerancia": 999.0, "fuente": "Mutacion Ilegal"},
    )
    assert_problem_json(patch_resp, expected_status=409)


def test_config_acuerdo_approve_incomplete_422_and_missing_perm_403(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Approving incomplete agreement -> 422; approving without .aprobar perm -> 403."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    existing_years = {
        int(a["anio"])
        for a in _extract_items(admin.get("/api/v1/acuerdos", sede="montelibano").json())
    }
    incomplete_year = max(existing_years | {2095}) + 1
    draft_year = incomplete_year + 1

    incomplete_resp = admin.post(
        "/api/v1/acuerdos",
        sede="montelibano",
        json_body={
            "comercializador_codigo": "afinia",
            "anio": incomplete_year,
            "uvt": 52374,
            "umbral_kwh": 173,
            "tolerancia": 1.0,
            "base_costo_variable": "valor_consumo_antes",
            "fuente": f"Incompleto {run_id}",
            "tarifas": [],
            "excepciones": [],
        },
    )
    if incomplete_resp.status_code == 201:
        draft_id = incomplete_resp.json()["id"]
        approve_inc = admin.post(
            f"/api/v1/acuerdos/{draft_id}/aprobar",
            sede="montelibano",
            json_body={},
        )
        assert_problem_json(approve_inc, expected_status=422)
    else:
        assert_problem_json(incomplete_resp, expected_status=422)

    analista = _create_user(
        admin,
        run_id=run_id,
        tag="ana",
        role_codigo="ANALISTA_COMERCIAL",
        sedes=["montelibano"],
    )
    try:
        ana_client = auth_session_factory(
            analista["nombre_usuario"],
            analista["_secret"],
            sede="montelibano",
        )
        afinia_2026 = next(
            a
            for a in _extract_items(
                admin.get(
                    "/api/v1/acuerdos",
                    sede="montelibano",
                    params={"comercializador": "afinia", "anio": 2026},
                ).json()
            )
            if a["estado"] == "aprobado"
        )
        copy_resp = ana_client.post(
            f"/api/v1/acuerdos/{afinia_2026['id']}/copiar",
            sede="montelibano",
            json_body={"anio_destino": draft_year},
        )
        assert copy_resp.status_code == 201, copy_resp.text
        copied_id = copy_resp.json()["id"]

        no_approve = ana_client.post(
            f"/api/v1/acuerdos/{copied_id}/aprobar",
            sede="montelibano",
            json_body={},
        )
        assert_problem_json(no_approve, expected_status=403)
    finally:
        admin.patch(
            f"/api/v1/usuarios/{analista['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )


def test_archivos_forged_mime_magic_bytes_returns_415(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
) -> None:
    """Uploading forged magic bytes (EXE/ELF/PDF disguised as image) returns 415 RFC 9457."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    for kind, fname, claimed_mime in (
        ("exe", "evidencia.jpg", "image/jpeg"),
        ("elf", "evidencia.png", "image/png"),
        ("pdf", "foto_falsa.png", "image/png"),
    ):
        forged_tuple = make_forged_file(fname, actual_kind=kind, claimed_mime=claimed_mime)
        resp = admin.post(
            "/api/v1/archivos",
            sede="montelibano",
            idempotency_key=str(uuid.uuid4()),
            files={"archivo": forged_tuple},
        )
        assert_problem_json(resp, expected_status=415)


def test_archivos_oversized_upload_returns_413(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
) -> None:
    """Uploading evidence exceeding archivo_tamano_max_evidencia_mb returns 413 RFC 9457."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    params = _extract_items(admin.get("/api/v1/parametros", sede="montelibano").json())
    max_param = next(p for p in params if p["codigo"] == "archivo_tamano_max_evidencia_mb")
    val = max_param["valor"]
    max_mb = int(val["valor"] if isinstance(val, dict) else val)

    oversized_bytes = make_oversized_payload((max_mb * 1024 * 1024) + 4096)
    resp = admin.post(
        "/api/v1/archivos",
        sede="montelibano",
        idempotency_key=str(uuid.uuid4()),
        files={"archivo": ("grande.png", oversized_bytes, "image/png")},
    )
    assert_problem_json(resp, expected_status=413)


def test_archivos_idempotency_collision_and_cross_sede_download(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
) -> None:
    """Idempotency-Key reuse with mismatched bytes -> 409/422; cross-sede GET -> 403/404."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    idem_key = str(uuid.uuid4())
    up1 = admin.post(
        "/api/v1/archivos",
        sede="montelibano",
        idempotency_key=idem_key,
        files={"archivo": ("a.png", make_png(4, 4), "image/png")},
    )
    assert up1.status_code in {200, 201}, up1.text
    file_id = up1.json()["id"]

    mismatch = admin.post(
        "/api/v1/archivos",
        sede="montelibano",
        idempotency_key=idem_key,
        files={"archivo": ("b.jpg", make_jpeg(), "image/jpeg")},
    )
    assert_problem_json(mismatch, expected_status=(409, 422))

    cross_dl = admin.get(f"/api/v1/archivos/{file_id}", sede="alcala")
    assert_problem_json(cross_dl, expected_status=(403, 404))


def test_luminarias_duplicate_codigo_409_and_out_of_range_coords_422(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Duplicate (sede_id, codigo) -> 409; out-of-range lat/lng -> 422."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    cat = _resolve_sede_catalogs(admin, "montelibano")

    code = f"{run_id}-DUP-{uuid.uuid4().hex[:6].upper()}"
    lum = _create_luminaire(admin, cat, code, sede="montelibano", seed=12)

    dup_resp = admin.post(
        "/api/v1/luminarias",
        sede="montelibano",
        json_body={
            "codigo": code,
            "barrio_id": cat["barrio"]["id"],
            "latitud": 7.98,
            "longitud": -75.41,
            "estado_id": cat["estado_121"]["id"],
            "tecnologia_id": cat["tech"]["id"],
            "potencia_id": cat["pot"]["id"],
            "marca_id": cat["marca"]["id"],
        },
    )
    assert_problem_json(dup_resp, expected_status=409)

    for bad_lat, bad_lng in ((95.0, -75.41), (-91.0, -75.41), (7.98, -185.0), (7.98, 181.0)):
        bad_create = admin.post(
            "/api/v1/luminarias",
            sede="montelibano",
            json_body={
                "codigo": f"{code}-BAD-{uuid.uuid4().hex[:4]}",
                "barrio_id": cat["barrio"]["id"],
                "latitud": bad_lat,
                "longitud": bad_lng,
                "estado_id": cat["estado_121"]["id"],
                "tecnologia_id": cat["tech"]["id"],
                "potencia_id": cat["pot"]["id"],
            },
        )
        assert_problem_json(bad_create, expected_status=422)

        bad_move = admin.post(
            f"/api/v1/luminarias/{lum['id']}/ubicacion",
            sede="montelibano",
            json_body={"latitud": bad_lat, "longitud": bad_lng, "origen": "web"},
        )
        assert_problem_json(bad_move, expected_status=422)


def test_luminarias_mover_without_perm_403_and_pagination_search_422(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """POST /luminarias/{id}/ubicacion without .mover -> 403; size>100 or short q -> 422."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    cat = _resolve_sede_catalogs(admin, "montelibano")
    lum = _create_luminaire(
        admin,
        cat,
        f"{run_id}-MOVP-{uuid.uuid4().hex[:6].upper()}",
        sede="montelibano",
        seed=15,
    )

    no_move = _create_user(
        admin,
        run_id=run_id,
        tag="nomov",
        role_codigo="INTERVENTORIA",
        sedes=["montelibano"],
    )
    try:
        uclient = auth_session_factory(
            no_move["nombre_usuario"],
            no_move["_secret"],
            sede="montelibano",
        )
        denied = uclient.post(
            f"/api/v1/luminarias/{lum['id']}/ubicacion",
            sede="montelibano",
            json_body={"latitud": 7.981, "longitud": -75.415, "origen": "web"},
        )
        assert_problem_json(denied, expected_status=403)
    finally:
        admin.patch(
            f"/api/v1/usuarios/{no_move['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )

    bad_size = admin.get("/api/v1/luminarias", sede="montelibano", params={"page": 1, "size": 101})
    assert_problem_json(bad_size, expected_status=422)

    bad_page = admin.get("/api/v1/luminarias", sede="montelibano", params={"page": 0, "size": 20})
    assert_problem_json(bad_page, expected_status=422)

    short_q = admin.get("/api/v1/luminarias/buscar", sede="montelibano", params={"q": "a"})
    assert_problem_json(short_q, expected_status=422)


def test_lotes_quantity_mismatch_422_and_consecutive_collision_409(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Lote cantidad != final - inicial + 1 -> 422; overlapping consecutives in sede -> 409."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    cat = _resolve_sede_catalogs(admin, "montelibano")

    base = (int(uuid.uuid4().hex[:6], 16) % 700000) + 200000

    mismatch = admin.post(
        "/api/v1/lotes",
        sede="montelibano",
        json_body={
            "consecutivo_inicial": base,
            "consecutivo_final": base + 4,
            "cantidad": 3,
            "tecnologia_id": cat["tech"]["id"],
            "potencia_id": cat["pot"]["id"],
            "marca_id": cat["marca"]["id"],
            "es_rural": False,
            "orden_compra": f"OC-BAD-{run_id}",
            "fecha_orden_compra": "2026-04-01",
            "entrada_almacen": f"EA-BAD-{run_id}",
            "fecha_entrada_almacen": "2026-04-02",
        },
    )
    assert_problem_json(mismatch, expected_status=422)

    inverted = admin.post(
        "/api/v1/lotes",
        sede="montelibano",
        json_body={
            "consecutivo_inicial": base + 5,
            "consecutivo_final": base,
            "cantidad": 1,
            "tecnologia_id": cat["tech"]["id"],
            "potencia_id": cat["pot"]["id"],
            "marca_id": cat["marca"]["id"],
            "es_rural": False,
            "orden_compra": f"OC-INV-{run_id}",
            "fecha_orden_compra": "2026-04-01",
            "entrada_almacen": f"EA-INV-{run_id}",
            "fecha_entrada_almacen": "2026-04-02",
        },
    )
    assert_problem_json(inverted, expected_status=422)

    ok_lote = admin.post(
        "/api/v1/lotes",
        sede="montelibano",
        json_body={
            "consecutivo_inicial": base,
            "consecutivo_final": base + 2,
            "cantidad": 3,
            "tecnologia_id": cat["tech"]["id"],
            "potencia_id": cat["pot"]["id"],
            "marca_id": cat["marca"]["id"],
            "es_rural": False,
            "orden_compra": f"OC-OK-{run_id}-{base}",
            "fecha_orden_compra": "2026-04-01",
            "entrada_almacen": f"EA-OK-{run_id}-{base}",
            "fecha_entrada_almacen": "2026-04-02",
        },
    )
    assert ok_lote.status_code == 201, ok_lote.text

    overlap = admin.post(
        "/api/v1/lotes",
        sede="montelibano",
        json_body={
            "consecutivo_inicial": base + 1,
            "consecutivo_final": base + 3,
            "cantidad": 3,
            "tecnologia_id": cat["tech"]["id"],
            "potencia_id": cat["pot"]["id"],
            "marca_id": cat["marca"]["id"],
            "es_rural": False,
            "orden_compra": f"OC-COL-{run_id}-{base}",
            "fecha_orden_compra": "2026-04-01",
            "entrada_almacen": f"EA-COL-{run_id}-{base}",
            "fecha_entrada_almacen": "2026-04-02",
        },
    )
    assert_problem_json(overlap, expected_status=409)


def test_mapa_pmtiles_invalid_range_416_missing_404_and_unassigned_sede_403(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """PMTiles invalid Range -> 416; missing sede PMTiles -> 404; unassigned sede -> 403."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    bad_range = admin.get(
        "/api/v1/mapa/base/montelibano.pmtiles",
        omit_sede=True,
        byte_range="bytes=999999999-",
    )
    assert bad_range.status_code == 416, bad_range.text

    sede_code = f"{run_id.lower()}_nopm_{uuid.uuid4().hex[:5]}"
    new_sede = admin.post(
        "/api/v1/sedes",
        omit_sede=True,
        json_body={
            "codigo": sede_code,
            "nombre": f"Sede Sin PMTiles {sede_code}",
            "municipio": "Test",
            "departamento": "Córdoba",
            "activa": True,
        },
    )
    assert new_sede.status_code == 201, new_sede.text
    missing_pm = admin.get(f"/api/v1/mapa/base/{sede_code}.pmtiles", omit_sede=True)
    assert_problem_json(missing_pm, expected_status=404)

    mtl_user = _create_user(
        admin,
        run_id=run_id,
        tag="pm403",
        role_codigo="CENSO",
        sedes=["montelibano"],
    )
    try:
        mtl_client = auth_session_factory(
            mtl_user["nombre_usuario"],
            mtl_user["_secret"],
            sede="montelibano",
        )
        unassigned = mtl_client.get("/api/v1/mapa/base/alcala.pmtiles", omit_sede=True)
        assert_problem_json(unassigned, expected_status=403)
    finally:
        admin.patch(
            f"/api/v1/usuarios/{mtl_user['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )


def test_mapa_mvt_invalid_tile_coords_422_and_unassigned_sede_403(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Invalid MVT z/x/y -> 422 RFC 9457; unassigned sede -> 403."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    for bad_path in (
        "/api/v1/mapa/luminarias/-1/0/0.mvt",
        "/api/v1/mapa/luminarias/31/0/0.mvt",
        "/api/v1/mapa/luminarias/10/9999/0.mvt",
    ):
        resp = admin.get(bad_path, sede="montelibano")
        assert_problem_json(resp, expected_status=422)

    tx, ty = _latlng_to_tile(4.675, -75.785, 14)
    mtl_user = _create_user(
        admin,
        run_id=run_id,
        tag="mvt403",
        role_codigo="CENSO",
        sedes=["montelibano"],
    )
    try:
        mtl_client = auth_session_factory(
            mtl_user["nombre_usuario"],
            mtl_user["_secret"],
            sede="montelibano",
        )
        resp = mtl_client.get(f"/api/v1/mapa/luminarias/14/{tx}/{ty}.mvt", sede="alcala")
        assert_problem_json(resp, expected_status=403)
    finally:
        admin.patch(
            f"/api/v1/usuarios/{mtl_user['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )


def test_pqrs_missing_canal_or_empty_luminarias_returns_422(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """POST /pqrs missing canal_id or empty luminarias[] returns 422 RFC 9457."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    cat = _resolve_sede_catalogs(admin, "montelibano")

    suffix = uuid.uuid4().hex[:6].upper()
    lum = _create_luminaire(admin, cat, f"{run_id}-PQV-{suffix}", sede="montelibano", seed=20)
    cit = admin.post(
        "/api/v1/ciudadanos",
        sede="montelibano",
        json_body={
            "identificacion": f"74{suffix}",
            "nombre_completo": f"Ciudadano Val {suffix}",
            "correo": f"val.{suffix.lower()}@example.test",
        },
    )
    assert cit.status_code == 201, cit.text
    cit_id = cit.json()["id"]

    no_canal = admin.post(
        "/api/v1/pqrs",
        sede="montelibano",
        json_body={
            "ciudadano_id": cit_id,
            "prioridad": 1,
            "observacion_solicitante": "Sin canal",
            "luminarias": [{"luminaria_id": lum["id"]}],
        },
    )
    assert_problem_json(no_canal, expected_status=422)

    empty_lums = admin.post(
        "/api/v1/pqrs",
        sede="montelibano",
        json_body={
            "canal_id": cat["canal"]["id"],
            "ciudadano_id": cit_id,
            "prioridad": 1,
            "observacion_solicitante": "Sin luminarias",
            "luminarias": [],
        },
    )
    assert_problem_json(empty_lums, expected_status=422)


def test_pqrs_and_ciudadanos_pii_masked_without_datos_personales_perm(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Caller lacking atencion.datos_personales.ver sees masked PII on /ciudadanos and /pqrs."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    cat = _resolve_sede_catalogs(admin, "montelibano")

    suffix = uuid.uuid4().hex[:6].upper()
    raw_ident = f"10679{int(suffix, 16) % 100000:05d}"
    raw_tel = "7729988"
    raw_cel = "3159876543"
    raw_email = f"privado.{suffix.lower()}@example.test"

    cit = admin.post(
        "/api/v1/ciudadanos",
        sede="montelibano",
        json_body={
            "identificacion": raw_ident,
            "nombre_completo": f"Persona Privada {suffix}",
            "barrio_id": cat["barrio"]["id"],
            "telefono": raw_tel,
            "celular": raw_cel,
            "correo": raw_email,
        },
    )
    assert cit.status_code == 201, cit.text
    lum = _create_luminaire(admin, cat, f"{run_id}-PII-{suffix}", sede="montelibano", seed=25)
    pqrs = admin.post(
        "/api/v1/pqrs",
        sede="montelibano",
        json_body={
            "canal_id": cat["canal"]["id"],
            "ciudadano_id": cit.json()["id"],
            "prioridad": 1,
            "observacion_solicitante": f"Falla PII {suffix}",
            "notificar_cliente": False,
            "luminarias": [{"luminaria_id": lum["id"]}],
        },
    )
    assert pqrs.status_code == 201, pqrs.text
    pqrs_id = pqrs.json()["id"]

    masked_user = _create_user(
        admin,
        run_id=run_id,
        tag="nopii",
        role_codigo="INTERVENTORIA",
        sedes=["montelibano"],
    )
    try:
        uclient = auth_session_factory(
            masked_user["nombre_usuario"],
            masked_user["_secret"],
            sede="montelibano",
        )
        cit_resp = uclient.get(
            "/api/v1/ciudadanos",
            sede="montelibano",
            params={"buscar": f"Persona Privada {suffix}", "page": 1, "size": 20},
        )
        assert cit_resp.status_code == 200, cit_resp.text
        assert len(_extract_items(cit_resp.json())) >= 1
        for secret_pii in (raw_ident, raw_tel, raw_cel, raw_email):
            assert secret_pii not in cit_resp.text

        pqrs_detail = uclient.get(f"/api/v1/pqrs/{pqrs_id}", sede="montelibano")
        assert pqrs_detail.status_code == 200, pqrs_detail.text
        for secret_pii in (raw_ident, raw_tel, raw_cel, raw_email):
            assert secret_pii not in pqrs_detail.text
    finally:
        admin.patch(
            f"/api/v1/usuarios/{masked_user['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )


def test_pqrs_cancel_atendida_303_409_and_remove_last_or_repaired_luminaire_409(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Deleting last/repaired luminaire or cancelling 303 Atendida PQRS returns 409."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    cat = _resolve_sede_catalogs(admin, "montelibano")

    suffix = uuid.uuid4().hex[:6].upper()
    lum1 = _create_luminaire(admin, cat, f"{run_id}-PQR1-{suffix}", sede="montelibano", seed=30)
    lum2 = _create_luminaire(admin, cat, f"{run_id}-PQR2-{suffix}", sede="montelibano", seed=31)
    cit = admin.post(
        "/api/v1/ciudadanos",
        sede="montelibano",
        json_body={
            "identificacion": f"75{suffix}",
            "nombre_completo": f"Ciudadano Close {suffix}",
            "correo": f"cls.{suffix.lower()}@example.test",
        },
    )
    assert cit.status_code == 201, cit.text

    pqrs_resp = admin.post(
        "/api/v1/pqrs",
        sede="montelibano",
        json_body={
            "canal_id": cat["canal"]["id"],
            "ciudadano_id": cit.json()["id"],
            "prioridad": 1,
            "observacion_solicitante": f"Dos luces {run_id}",
            "notificar_cliente": False,
            "luminarias": [{"luminaria_id": lum1["id"]}],
        },
    )
    assert pqrs_resp.status_code == 201, pqrs_resp.text
    pqrs_id = pqrs_resp.json()["id"]

    del_last = admin.delete(f"/api/v1/pqrs/{pqrs_id}/luminarias/{lum1['id']}", sede="montelibano")
    assert_problem_json(del_last, expected_status=409)

    add_second = admin.post(
        f"/api/v1/pqrs/{pqrs_id}/luminarias",
        sede="montelibano",
        json_body={"luminaria_id": lum2["id"]},
    )
    assert add_second.status_code == 201, add_second.text

    tec_user = _create_user(
        admin,
        run_id=run_id,
        tag="pqrtec",
        role_codigo="TECNICO",
        sedes=["montelibano"],
    )
    try:
        for idx, lum in enumerate((lum1, lum2)):
            ot_resp = admin.post(
                "/api/v1/ordenes",
                sede="montelibano",
                json_body={
                    "tipo": "mantenimiento",
                    "prioridad": 1,
                    "pqrs_id": pqrs_id,
                    "luminarias": [{"luminaria_id": lum["id"], "rol": "intervenida"}],
                },
            )
            assert ot_resp.status_code == 201, ot_resp.text
            ot_id = ot_resp.json()["id"]
            assert (
                admin.post(
                    f"/api/v1/ordenes/{ot_id}/asignar",
                    sede="montelibano",
                    json_body={"tecnico_id": tec_user["id"]},
                ).status_code
                in {200, 202}
            )
            close_resp = admin.post(
                f"/api/v1/ordenes/{ot_id}/cerrar",
                sede="montelibano",
                json_body={
                    "sitio_arreglo": "Calle 5",
                    "quien_recibe": "Vecino",
                    "requiere_desmonte": False,
                    "componentes": build_maintenance_components(all_ok=True),
                    "materiales": [],
                    "evidencias": [],
                },
            )
            assert close_resp.status_code == 200, close_resp.text
            if idx == 0:
                del_repaired = admin.delete(
                    f"/api/v1/pqrs/{pqrs_id}/luminarias/{lum1['id']}",
                    sede="montelibano",
                )
                assert_problem_json(del_repaired, expected_status=409)

        pqrs_after = admin.get(f"/api/v1/pqrs/{pqrs_id}", sede="montelibano").json()
        state_code = str(
            pqrs_after.get("estado_codigo") or (pqrs_after.get("estado") or {}).get("codigo", "")
        )
        assert state_code == "303"

        cancel_303 = admin.post(
            f"/api/v1/pqrs/{pqrs_id}/anular",
            sede="montelibano",
            json_body={"motivo": "Intento tardío"},
        )
        assert_problem_json(cancel_303, expected_status=409)

        patch_303 = admin.patch(
            f"/api/v1/pqrs/{pqrs_id}",
            sede="montelibano",
            json_body={"observacion_interna": "Intento editar cerrada"},
        )
        assert_problem_json(patch_303, expected_status=409)
    finally:
        admin.patch(
            f"/api/v1/usuarios/{tec_user['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )
