"""Tier 1 E2E tests for EP-02 Configuracion, SEED-1..6 & CFG-OPEN-1..5."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from harness.client import SapefClient
from harness.config import E2EConfig


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


@pytest.mark.tier1
def test_seeded_sedes_and_comercializadores_crud(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    sedes_resp = admin.get("/api/v1/sedes", omit_sede=True)
    assert sedes_resp.status_code == 200
    sedes = _extract_items(sedes_resp.json())
    by_code = {s["codigo"]: s for s in sedes}
    assert {"montelibano", "alcala"}.issubset(by_code.keys())

    mtl_coms_resp = admin.get(
        f"/api/v1/sedes/{by_code['montelibano']['id']}/comercializadores",
        omit_sede=True,
    )
    assert mtl_coms_resp.status_code == 200
    mtl_coms = {
        c["comercializador_codigo"]
        for c in _extract_items(mtl_coms_resp.json())
        if c.get("activo", True)
    }
    assert "afinia" in mtl_coms

    alc_coms_resp = admin.get(
        f"/api/v1/sedes/{by_code['alcala']['id']}/comercializadores",
        omit_sede=True,
    )
    assert alc_coms_resp.status_code == 200
    alc_coms = {
        c["comercializador_codigo"]
        for c in _extract_items(alc_coms_resp.json())
        if c.get("activo", True)
    }
    assert {"celsia", "vatia"}.issubset(alc_coms)

    suffix = uuid.uuid4().hex[:6].lower()
    sede_code = f"{run_id.lower()}_{suffix}"
    create_sede = admin.post(
        "/api/v1/sedes",
        omit_sede=True,
        json_body={
            "codigo": sede_code,
            "nombre": f"Sede Prueba {suffix}",
            "municipio": f"Municipio {suffix}",
            "departamento": "Córdoba",
            "activa": True,
        },
    )
    assert create_sede.status_code == 201, create_sede.text
    sede_id = create_sede.json()["id"]

    put_coms = admin.put(
        f"/api/v1/sedes/{sede_id}/comercializadores",
        omit_sede=True,
        json_body=[
            {"comercializador_codigo": "afinia", "activo": True, "desde": "2026-01-01"},
            {"comercializador_codigo": "vatia", "activo": True, "desde": "2026-06-01"},
        ],
    )
    assert put_coms.status_code == 200, put_coms.text
    assigned = {
        c["comercializador_codigo"]
        for c in _extract_items(put_coms.json())
        if c.get("activo", True)
    }
    assert {"afinia", "vatia"}.issubset(assigned)


@pytest.mark.tier1
def test_deduplicated_maestros_seeded_and_crud(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    clases_resp = admin.get("/api/v1/maestros/clases", omit_sede=True)
    assert clases_resp.status_code == 200
    clases = _extract_items(clases_resp.json())
    clase_codes = {c.get("codigo", c.get("nombre")) for c in clases}
    assert len(clase_codes) >= 12
    expected_core = {
        "LUMINARIA_TECNOLOGIA",
        "LUMINARIA_MARCA",
        "LUMINARIA_POTENCIA",
        "TIPO_INTERVENCION",
        "COMPONENTE_MANTENIMIENTO",
        "PRIORIDAD_PQRS",
        "CANAL_PQRS",
        "TIPO_MOVIMIENTO_MATERIAL",
    }
    assert expected_core.issubset(clase_codes)

    tech_vals = _extract_items(
        admin.get("/api/v1/maestros/LUMINARIA_TECNOLOGIA", omit_sede=True).json()
    )
    tech_codes = [v["codigo"] for v in tech_vals]
    assert len(tech_codes) == len(set(tech_codes))
    assert {"LED", "LED_SOLAR", "SODIO", "METAL_HALIDE", "INDUCCION", "MIXTA", "AHORRADORA"}.issubset(
        set(tech_codes)
    )

    marca_vals = _extract_items(
        admin.get("/api/v1/maestros/LUMINARIA_MARCA", omit_sede=True).json()
    )
    marca_codes = [v["codigo"] for v in marca_vals]
    assert len(marca_codes) == len(set(marca_codes))
    assert {"KUNIX", "SCHREDER", "LEDVANCE", "PHILIPS"}.issubset(set(marca_codes))
    assert "KÜNIX" not in marca_codes and "SCHRÉDER" not in marca_codes

    pot_vals = _extract_items(
        admin.get("/api/v1/maestros/LUMINARIA_POTENCIA", omit_sede=True).json()
    )
    pot_codes = [v["codigo"] for v in pot_vals]
    assert len(pot_codes) == len(set(pot_codes))
    assert len(pot_codes) >= 35

    comp_vals = _extract_items(
        admin.get("/api/v1/maestros/COMPONENTE_MANTENIMIENTO", omit_sede=True).json()
    )
    assert len(comp_vals) == 12

    canal_vals = _extract_items(
        admin.get("/api/v1/maestros/CANAL_PQRS", omit_sede=True).json()
    )
    assert {"WHATSAPP", "PRESENCIAL", "TELEFONO", "CORREO"}.issubset(
        {v["codigo"] for v in canal_vals}
    )

    suffix = uuid.uuid4().hex[:6].upper()
    new_code = f"{run_id}_MARCA_{suffix}"
    create_val = admin.post(
        "/api/v1/maestros/LUMINARIA_MARCA",
        omit_sede=True,
        json_body={
            "codigo": new_code,
            "nombre": f"Marca E2E {suffix}",
            "orden": 999,
            "activo": True,
        },
    )
    assert create_val.status_code == 201, create_val.text
    val_id = create_val.json()["id"]

    patch_val = admin.patch(
        f"/api/v1/maestros/LUMINARIA_MARCA/{val_id}",
        omit_sede=True,
        json_body={"nombre": f"Marca Editada {suffix}", "activo": False},
    )
    assert patch_val.status_code == 200, patch_val.text
    assert patch_val.json()["nombre"] == f"Marca Editada {suffix}"
    assert patch_val.json()["activo"] is False


@pytest.mark.tier1
def test_zonas_and_barrios_seeded_and_crud_by_sede(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    zonas_resp = admin.get("/api/v1/zonas", sede="montelibano")
    assert zonas_resp.status_code == 200
    zonas_mtl = _extract_items(zonas_resp.json())
    assert len(zonas_mtl) >= 11
    assert {"Centro", "Norte", "Sur", "Rurales"}.issubset({z["nombre"] for z in zonas_mtl})

    barrios_resp = admin.get("/api/v1/barrios", sede="montelibano")
    assert barrios_resp.status_code == 200
    barrios_mtl = _extract_items(barrios_resp.json())
    assert len(barrios_mtl) >= 90
    assert any(b["nombre"] == "El Centro" and b.get("zona_id") for b in barrios_mtl)

    suffix = uuid.uuid4().hex[:6].upper()
    zona_name = f"{run_id}_ZONA_{suffix}"
    create_zona = admin.post(
        "/api/v1/zonas",
        sede="montelibano",
        json_body={"nombre": zona_name},
    )
    assert create_zona.status_code == 201, create_zona.text
    zona_id = create_zona.json()["id"]

    barrio_name = f"{run_id}_BARRIO_{suffix}"
    create_barrio = admin.post(
        "/api/v1/barrios",
        sede="montelibano",
        json_body={"zona_id": zona_id, "nombre": barrio_name, "activo": True},
    )
    assert create_barrio.status_code == 201, create_barrio.text
    barrio_id = create_barrio.json()["id"]
    assert create_barrio.json()["zona_id"] == zona_id

    patch_barrio = admin.patch(
        f"/api/v1/barrios/{barrio_id}",
        sede="montelibano",
        json_body={"nombre": f"{barrio_name}_UPD", "activo": False},
    )
    assert patch_barrio.status_code == 200
    assert patch_barrio.json()["nombre"] == f"{barrio_name}_UPD"
    assert patch_barrio.json()["activo"] is False

    alc_zonas = {
        z["nombre"] for z in _extract_items(admin.get("/api/v1/zonas", sede="alcala").json())
    }
    assert zona_name not in alc_zonas


@pytest.mark.tier1
def test_process_states_1xx_to_4xx_and_patch(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    all_states_resp = admin.get("/api/v1/estados", omit_sede=True)
    assert all_states_resp.status_code == 200
    all_states = _extract_items(all_states_resp.json())

    by_proc: dict[str, set[str]] = {}
    for st in all_states:
        by_proc.setdefault(str(st["proceso"]), set()).add(str(st["codigo"]))

    assert {"121", "122", "124", "123", "125", "112", "126", "127", "110"}.issubset(
        by_proc.get("luminaria", set())
    )
    assert {"301", "302", "305", "303", "304"}.issubset(by_proc.get("pqrs", set()))
    assert {"201", "202", "205", "203", "204"}.issubset(by_proc.get("orden", set()))
    assert {"401", "402", "403", "404"}.issubset(by_proc.get("solicitud", set()))

    lum_filtered = _extract_items(
        admin.get("/api/v1/estados", omit_sede=True, params={"proceso": "luminaria"}).json()
    )
    assert all(s["proceso"] == "luminaria" for s in lum_filtered)

    target = next(s for s in lum_filtered if str(s["codigo"]) == "127")
    original_name = target["nombre"]
    try:
        patch_resp = admin.patch(
            f"/api/v1/estados/{target['id']}",
            omit_sede=True,
            json_body={"nombre": "Otros E2E"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["nombre"] == "Otros E2E"
    finally:
        admin.patch(
            f"/api/v1/estados/{target['id']}",
            omit_sede=True,
            json_body={"nombre": original_name},
        )


@pytest.mark.tier1
def test_annual_tariff_agreements_2026_seeded_copy_and_approve(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    mtl_acuerdos = _extract_items(
        admin.get(
            "/api/v1/acuerdos",
            sede="montelibano",
            params={"comercializador": "afinia", "anio": 2026},
        ).json()
    )
    assert len(mtl_acuerdos) >= 1
    afinia_2026 = next(a for a in mtl_acuerdos if int(a["anio"]) == 2026)
    assert afinia_2026["estado"] == "aprobado"
    assert float(afinia_2026["uvt"]) == pytest.approx(52374.0)
    assert float(afinia_2026["umbral_kwh"]) == pytest.approx(173.0)
    assert float(afinia_2026["tolerancia"]) == pytest.approx(1.0)

    alc_acuerdos = _extract_items(
        admin.get(
            "/api/v1/acuerdos",
            sede="alcala",
            params={"comercializador": "celsia", "anio": 2026},
        ).json()
    )
    assert len(alc_acuerdos) >= 1
    celsia_2026 = next(a for a in alc_acuerdos if int(a["anio"]) == 2026)
    assert celsia_2026["estado"] == "aprobado"
    assert float(celsia_2026["tolerancia"]) == pytest.approx(100.0)

    detail_2026 = admin.get(
        f"/api/v1/acuerdos/{afinia_2026['id']}",
        sede="montelibano",
    ).json()
    assert len(detail_2026.get("tarifas", [])) >= 12

    existing_years = {
        int(a["anio"])
        for a in _extract_items(admin.get("/api/v1/acuerdos", sede="montelibano").json())
    }
    target_year = max(existing_years | {2090}) + 1

    copy_resp = admin.post(
        f"/api/v1/acuerdos/{afinia_2026['id']}/copiar",
        sede="montelibano",
        json_body={"anio_destino": target_year},
    )
    assert copy_resp.status_code == 201, copy_resp.text
    draft = copy_resp.json()
    assert draft["estado"] == "borrador"
    assert int(draft["anio"]) == target_year

    patch_resp = admin.patch(
        f"/api/v1/acuerdos/{draft['id']}",
        sede="montelibano",
        json_body={"fuente": f"Acuerdo Sintético {run_id}"},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["fuente"] == f"Acuerdo Sintético {run_id}"

    approve_resp = admin.post(
        f"/api/v1/acuerdos/{draft['id']}/aprobar",
        sede="montelibano",
        json_body={},
    )
    assert approve_resp.status_code == 200, approve_resp.text
    approved = approve_resp.json()
    assert approved["estado"] == "aprobado"
    assert approved.get("aprobado_en") is not None

    recheck_2026 = admin.get(
        f"/api/v1/acuerdos/{afinia_2026['id']}",
        sede="montelibano",
    )
    assert recheck_2026.status_code == 200
    assert recheck_2026.json()["estado"] == "aprobado"


@pytest.mark.tier1
def test_editable_parametros_no_secrets_and_plantillas_correo(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    params_resp = admin.get("/api/v1/parametros", sede="montelibano")
    assert params_resp.status_code == 200
    lowered_text = params_resp.text.lower()
    for secret_key in ("mailpasswd", "vapid_private_key", "smtp_password", "secret_key"):
        assert secret_key not in lowered_text, f"Secret key {secret_key!r} exposed in /parametros"

    params = _extract_items(params_resp.json())
    by_code = {p["codigo"]: p for p in params}
    assert "semaforo_pqrs_umbrales" in by_code
    assert "archivo_tamano_max_evidencia_mb" in by_code

    semaforo = by_code["semaforo_pqrs_umbrales"]
    original_val = semaforo["valor"]
    try:
        upd = admin.patch(
            f"/api/v1/parametros/{semaforo['id']}",
            sede="montelibano",
            json_body={"valor": {"verde_max_dias": 4, "amarillo_max_dias": 8}},
        )
        assert upd.status_code == 200, upd.text
        assert upd.json()["valor"] == {"verde_max_dias": 4, "amarillo_max_dias": 8}
    finally:
        admin.patch(
            f"/api/v1/parametros/{semaforo['id']}",
            sede="montelibano",
            json_body={"valor": original_val},
        )

    tpl_resp = admin.get("/api/v1/plantillas-correo", sede="montelibano")
    assert tpl_resp.status_code == 200
    templates = _extract_items(tpl_resp.json())
    tpl_by_code = {t["codigo"]: t for t in templates}
    assert {
        "MAIL_RECUPERAR_CUENTA",
        "MAIL_PQRS",
        "MAIL.MANTENIMIENTO_LUMINARIA",
        "MAIL.INSTALACION_LUMINARIA",
    }.issubset(tpl_by_code.keys())

    pqrs_tpl = tpl_by_code["MAIL_PQRS"]
    original_subject = pqrs_tpl["asunto"]
    try:
        patch_tpl = admin.patch(
            f"/api/v1/plantillas-correo/{pqrs_tpl['id']}",
            sede="montelibano",
            json_body={"asunto": f"{original_subject} [{run_id}]"},
        )
        assert patch_tpl.status_code == 200, patch_tpl.text
        assert run_id in patch_tpl.json()["asunto"]
    finally:
        admin.patch(
            f"/api/v1/plantillas-correo/{pqrs_tpl['id']}",
            sede="montelibano",
            json_body={"asunto": original_subject},
        )


@pytest.mark.tier1
def test_commercial_catalogs_ci_and_oc_crud(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    ci_resp = admin.get("/api/v1/comercial/catalogos/conceptos", omit_sede=True)
    assert ci_resp.status_code == 200
    ci_items = _extract_items(ci_resp.json())
    ci_codes = {c["codigo"] for c in ci_items}
    assert len(ci_items) >= 62
    assert {"CI400", "CI401", "CI851", "CI306", "CI102", "CI300"}.issubset(ci_codes)

    oc_resp = admin.get("/api/v1/comercial/catalogos/operaciones", omit_sede=True)
    assert oc_resp.status_code == 200
    oc_items = _extract_items(oc_resp.json())
    oc_codes = {o["codigo"] for o in oc_items}
    assert len(oc_items) >= 33
    assert {"OC135", "OC136", "OC100"}.issubset(oc_codes)

    suffix = uuid.uuid4().hex[:4].upper()
    ci_code = f"CIE{suffix}"
    create_ci = admin.post(
        "/api/v1/comercial/catalogos/conceptos",
        omit_sede=True,
        json_body={
            "comercializador_codigo": "afinia",
            "codigo": ci_code,
            "descripcion": f"Concepto E2E {run_id}",
            "entra_al_calculo": False,
            "activo": True,
        },
    )
    assert create_ci.status_code == 201, create_ci.text
    ci_id = create_ci.json()["id"]

    patch_ci = admin.patch(
        f"/api/v1/comercial/catalogos/conceptos/{ci_id}",
        omit_sede=True,
        json_body={"entra_al_calculo": True, "activo": False},
    )
    assert patch_ci.status_code == 200, patch_ci.text
    assert patch_ci.json()["entra_al_calculo"] is True
    assert patch_ci.json()["activo"] is False

    oc_code = f"OCE{suffix}"
    create_oc = admin.post(
        "/api/v1/comercial/catalogos/operaciones",
        omit_sede=True,
        json_body={
            "comercializador_codigo": "afinia",
            "codigo": oc_code,
            "descripcion": f"Operación E2E {run_id}",
            "entra_al_calculo": False,
            "activo": True,
        },
    )
    assert create_oc.status_code == 201, create_oc.text
    oc_id = create_oc.json()["id"]

    patch_oc = admin.patch(
        f"/api/v1/comercial/catalogos/operaciones/{oc_id}",
        omit_sede=True,
        json_body={"entra_al_calculo": True, "activo": False},
    )
    assert patch_oc.status_code == 200, patch_oc.text
    assert patch_oc.json()["entra_al_calculo"] is True
    assert patch_oc.json()["activo"] is False
