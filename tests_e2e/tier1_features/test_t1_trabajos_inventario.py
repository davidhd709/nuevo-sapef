"""Tier 1 E2E tests for EP-05 Work Orders (F5-1..F5-6) and EP-06 Inventory (F6-1..F6-3)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fixtures import (
    MAINTENANCE_12_COMPONENTS,
    build_bulk_ot_xlsx,
    build_maintenance_components,
    generate_coordinates,
    make_pdf,
    make_png,
    read_xlsx_sheets,
)
from harness.client import SapefClient
from harness.config import E2EConfig
from harness.db import DbHelper

pytestmark = pytest.mark.tier1


def _admin_client(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    sede: str = "montelibano",
) -> SapefClient:
    assert e2e_config.admin_password, (
        "SAPEF_E2E_ADMIN_PASSWORD must be set for live Tier 1 E2E tests"
    )
    return auth_session_factory(
        e2e_config.admin_user,
        e2e_config.admin_password,
        sede=sede,
    )


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, dict):
        for key in ("items", "resultados", "datos", "ordenes", "materiales"):
            val = payload.get(key)
            if isinstance(val, list):
                return list(val)
    raise AssertionError(f"Unexpected list/paginated payload shape: {payload!r}")


def _extract_id(payload: dict[str, Any], *keys: str) -> Any:
    for key in (*keys, "id", "tareaId", "tarea_id", "cargueId", "cargue_id"):
        if key in payload and payload[key] is not None:
            return payload[key]
    raise AssertionError(f"Could not extract identifier from response: {payload!r}")


def _resolve_maestro_id(client: SapefClient, clase: str, preferred_code: str | None = None) -> int:
    resp = client.get(f"/api/v1/maestros/{clase}", omit_sede=True)
    assert resp.status_code == 200, f"GET maestros/{clase} failed: {resp.status_code} {resp.text}"
    items = _extract_items(resp.json())
    assert items, f"No values seeded for maestro {clase}"
    if preferred_code:
        for item in items:
            if str(item.get("codigo", "")).upper() == preferred_code.upper():
                return int(item["id"])
    return int(items[0]["id"])


def _resolve_estado_id(client: SapefClient, proceso: str, codigo: str) -> int:
    resp = client.get("/api/v1/estados", params={"proceso": proceso}, omit_sede=True)
    assert resp.status_code == 200, f"GET estados failed: {resp.status_code} {resp.text}"
    items = _extract_items(resp.json())
    for item in items:
        if str(item.get("codigo")) == codigo:
            return int(item["id"])
    raise AssertionError(f"Estado {proceso}/{codigo} not found in {items!r}")


def _resolve_barrio_id(client: SapefClient, sede: str = "montelibano") -> tuple[int, str]:
    resp = client.get("/api/v1/barrios", sede=sede)
    assert resp.status_code == 200, f"GET barrios failed: {resp.status_code} {resp.text}"
    items = _extract_items(resp.json())
    assert items, f"No barrios seeded for sede {sede}"
    return int(items[0]["id"]), str(items[0]["nombre"])


def _create_luminaire(
    client: SapefClient,
    code: str,
    *,
    sede: str = "montelibano",
    estado_codigo: str = "121",
    seed_idx: int = 1,
) -> dict[str, Any]:
    barrio_id, _ = _resolve_barrio_id(client, sede)
    estado_id = _resolve_estado_id(client, "luminaria", estado_codigo)
    tec_id = _resolve_maestro_id(client, "LUMINARIA_TECNOLOGIA", "LED")
    pot_id = _resolve_maestro_id(client, "LUMINARIA_POTENCIA")
    marca_id = _resolve_maestro_id(client, "LUMINARIA_MARCA", "PHILIPS")
    lat, lng = generate_coordinates(sede, seed_idx + 1, seed=404)[seed_idx]
    resp = client.post(
        "/api/v1/luminarias",
        sede=sede,
        json_body={
            "codigo": code,
            "barrio_id": barrio_id,
            "latitud": lat,
            "longitud": lng,
            "estado_id": estado_id,
            "tecnologia_id": tec_id,
            "potencia_id": pot_id,
            "marca_id": marca_id,
            "poste": f"P-{code[-4:]}",
        },
    )
    assert resp.status_code == 201, f"POST luminarias failed: {resp.status_code} {resp.text}"
    return dict(resp.json())


def _create_pqrs(
    client: SapefClient,
    run_id: str,
    luminaire_id: Any,
    *,
    sede: str = "montelibano",
) -> dict[str, Any]:
    canal_id = _resolve_maestro_id(client, "CANAL_PQRS", "WHATSAPP")
    uid = uuid.uuid4().hex[:6].upper()
    cit_resp = client.post(
        "/api/v1/ciudadanos",
        sede=sede,
        json_body={
            "identificacion": f"CC-{run_id}-{uid}",
            "nombre_completo": f"Solicitante {run_id} {uid}",
            "telefono": "3005550101",
            "correo": f"pqr.{uid.lower()}@example.test",
        },
    )
    assert cit_resp.status_code == 201, f"POST ciudadanos failed: {cit_resp.status_code}"
    ciudadano_id = cit_resp.json()["id"]

    pqrs_resp = client.post(
        "/api/v1/pqrs",
        sede=sede,
        json_body={
            "canal_id": canal_id,
            "ciudadano_id": ciudadano_id,
            "prioridad": 1,
            "observacion_solicitante": f"Falla luminaria {run_id}",
            "notificar_cliente": True,
            "luminarias": [{"luminaria_id": luminaire_id}],
        },
    )
    assert pqrs_resp.status_code == 201, f"POST pqrs failed: {pqrs_resp.status_code} {pqrs_resp.text}"
    return dict(pqrs_resp.json())


def _ensure_tecnico_id(client: SapefClient, run_id: str, sede: str = "montelibano") -> Any:
    resp = client.get("/api/v1/tecnicos", sede=sede)
    assert resp.status_code == 200, f"GET tecnicos failed: {resp.status_code} {resp.text}"
    items = _extract_items(resp.json())
    if items:
        return items[0]["id"]

    roles_resp = client.get("/api/v1/roles", omit_sede=True)
    assert roles_resp.status_code == 200
    roles = _extract_items(roles_resp.json())
    tec_role = next(r for r in roles if str(r.get("codigo")).upper() == "TECNICO")

    sedes_resp = client.get("/api/v1/sedes", omit_sede=True)
    assert sedes_resp.status_code == 200
    sedes = _extract_items(sedes_resp.json())
    sede_obj = next(s for s in sedes if s.get("codigo") == sede)

    suffix = uuid.uuid4().hex[:6]
    temp_pw = f"Tec!{uuid.uuid4().hex[:12]}9a"
    u_resp = client.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": f"tec_{run_id.lower()}_{suffix}",
            "nombre_completo": f"Técnico E2E {suffix}",
            "identificacion": f"90{int(suffix, 16) % 10000000:07d}",
            "correo": f"tec.{suffix}@example.test",
            "clave": temp_pw,
            "rol_id": tec_role["id"],
            "sedes": [sede_obj["id"]],
            "activo": True,
            "debe_cambiar_clave": False,
        },
    )
    assert u_resp.status_code == 201, f"Create tecnico user failed: {u_resp.status_code}"
    return u_resp.json()["id"]


def test_ot_creation_from_pqrs_and_direct_all_four_types(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """F5-1: Create unified OTs from PQRS and direct for all 4 types in initial state 201."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tag = uuid.uuid4().hex[:6].upper()
    lum_act = _create_luminaire(client, f"{run_id}-OT1-{tag}", estado_codigo="121", seed_idx=1)
    lum_bod = _create_luminaire(client, f"{run_id}-OT2-{tag}", estado_codigo="124", seed_idx=2)
    pqrs = _create_pqrs(client, run_id, lum_act["id"])

    # From PQRS
    resp_pqrs_ot = client.post(
        "/api/v1/ordenes",
        sede="montelibano",
        json_body={
            "tipo": "mantenimiento",
            "prioridad": 1,
            "pqrs_id": pqrs["id"],
            "observaciones": f"OT desde PQRS {run_id}",
            "luminarias": [{"luminaria_id": lum_act["id"], "rol": "intervenida"}],
        },
    )
    assert resp_pqrs_ot.status_code == 201, resp_pqrs_ot.text
    ot_pqrs = resp_pqrs_ot.json()
    assert str(ot_pqrs.get("estado_codigo") or ot_pqrs.get("estado", {}).get("codigo")) == "201"
    assert ot_pqrs.get("numero")

    # Direct creation for all 4 types
    payloads = [
        {
            "tipo": "mantenimiento",
            "prioridad": 2,
            "observaciones": f"Directa mant {run_id}",
            "luminarias": [{"luminaria_id": lum_act["id"], "rol": "intervenida"}],
        },
        {
            "tipo": "modernizacion",
            "prioridad": 1,
            "observaciones": f"Directa mod {run_id}",
            "luminarias": [
                {"luminaria_id": lum_bod["id"], "rol": "instalada"},
                {"luminaria_id": lum_act["id"], "rol": "desmontada"},
            ],
        },
        {
            "tipo": "expansion",
            "prioridad": 1,
            "observaciones": f"Directa exp {run_id}",
            "luminarias": [{"luminaria_id": lum_bod["id"], "rol": "instalada"}],
        },
        {
            "tipo": "reubicacion",
            "prioridad": 2,
            "observaciones": f"Directa reub {run_id}",
            "luminarias": [
                {"luminaria_id": lum_bod["id"], "rol": "instalada"},
                {"luminaria_id": lum_act["id"], "rol": "desmontada"},
            ],
        },
    ]
    created_ids = [ot_pqrs["id"]]
    for body in payloads:
        resp = client.post("/api/v1/ordenes", sede="montelibano", json_body=body)
        assert resp.status_code == 201, f"Direct OT {body['tipo']} failed: {resp.text}"
        data = resp.json()
        estado_cod = str(data.get("estado_codigo") or data.get("estado", {}).get("codigo"))
        assert estado_cod == "201"
        created_ids.append(data["id"])

    list_resp = client.get("/api/v1/ordenes", sede="montelibano", params={"page": 1, "size": 50})
    assert list_resp.status_code == 200
    listed_ids = {item["id"] for item in _extract_items(list_resp.json())}
    assert set(created_ids).issubset(listed_ids)


def test_crew_technician_management_and_ot_assignment_web_push_job(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """F5-2: Manage technicians/crews and assign OT -> state 202 + IDs-only Web Push job."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tag = uuid.uuid4().hex[:6].upper()
    tec_id = _ensure_tecnico_id(client, run_id, sede="montelibano")

    crew_resp = client.post(
        "/api/v1/cuadrillas",
        sede="montelibano",
        json_body={
            "nombre": f"{run_id}-CUADRILLA-{tag}",
            "tecnicos_ids": [tec_id],
            "activa": True,
        },
    )
    assert crew_resp.status_code == 201, f"POST cuadrillas failed: {crew_resp.text}"
    crew = crew_resp.json()

    lum = _create_luminaire(client, f"{run_id}-ASG-{tag}", estado_codigo="121", seed_idx=3)
    ot_resp = client.post(
        "/api/v1/ordenes",
        sede="montelibano",
        json_body={
            "tipo": "mantenimiento",
            "prioridad": 1,
            "luminarias": [{"luminaria_id": lum["id"], "rol": "intervenida"}],
        },
    )
    assert ot_resp.status_code == 201
    ot_id = ot_resp.json()["id"]

    asg_resp = client.post(
        f"/api/v1/ordenes/{ot_id}/asignar",
        sede="montelibano",
        json_body={"tecnico_id": tec_id, "cuadrilla_id": crew["id"]},
    )
    assert asg_resp.status_code in (200, 202), f"Assign failed: {asg_resp.status_code} {asg_resp.text}"
    asg_body = asg_resp.json()
    estado_cod = str(asg_body.get("estado_codigo") or asg_body.get("estado", {}).get("codigo"))
    assert estado_cod == "202"

    # Verify Procrastinate Web Push job was queued with primitive IDs only (no PII/secrets)
    job_row = db_helper.fetch_one(
        """
        SELECT id, task_name, args
        FROM procrastinate_jobs
        WHERE task_name ILIKE '%push%'
          AND (args::text LIKE %s)
        ORDER BY id DESC
        LIMIT 1
        """,
        (f"%{ot_id}%",),
    )
    assert job_row is not None, "Expected Procrastinate Web Push job for assigned OT"
    args = db_helper.get_procrastinate_job_args(int(job_row["id"]))
    assert args, "Procrastinate push job args must not be empty"
    for key, val in args.items():
        assert isinstance(val, (int, str, bool)) or val is None, (
            f"Procrastinate arg {key!r} must be primitive ID, got {type(val)}"
        )
    serialized = str(args).lower()
    assert "hash_clave" not in serialized and "vapid" not in serialized


def test_maintenance_ot_close_12_components_replacement_kardex_and_pqrs_autoclose(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """F5-3: Close maintenance OT with 12 components, replacement, atomic kardex, PQRS 303."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tag = uuid.uuid4().hex[:6].upper()
    tec_id = _ensure_tecnico_id(client, run_id, sede="montelibano")

    mat_resp = client.post(
        "/api/v1/materiales",
        sede="montelibano",
        json_body={
            "categoria": "ELECTRICO",
            "codigo": f"{run_id}-MAT-{tag}",
            "descripcion": f"Fotocelda E2E {tag}",
            "unidad": "UND",
            "existencias": 20,
            "existencias_minimas": 5,
        },
    )
    assert mat_resp.status_code == 201, mat_resp.text
    mat_id = mat_resp.json()["id"]

    lum_old = _create_luminaire(client, f"{run_id}-MNT-OLD-{tag}", estado_codigo="121", seed_idx=4)
    lum_rep = _create_luminaire(client, f"{run_id}-MNT-REP-{tag}", estado_codigo="124", seed_idx=5)
    pqrs = _create_pqrs(client, run_id, lum_old["id"])

    ot_resp = client.post(
        "/api/v1/ordenes",
        sede="montelibano",
        json_body={
            "tipo": "mantenimiento",
            "prioridad": 1,
            "pqrs_id": pqrs["id"],
            "luminarias": [{"luminaria_id": lum_old["id"], "rol": "intervenida"}],
        },
    )
    assert ot_resp.status_code == 201
    ot_id = ot_resp.json()["id"]

    asg = client.post(
        f"/api/v1/ordenes/{ot_id}/asignar",
        sede="montelibano",
        json_body={"tecnico_id": tec_id},
    )
    assert asg.status_code in (200, 202)

    ev_resp = client.post(
        "/api/v1/archivos",
        sede="montelibano",
        idempotency_key=str(uuid.uuid4()),
        files={"archivo": ("evidencia.png", make_png(4, 4), "image/png")},
    )
    assert ev_resp.status_code in (200, 201), ev_resp.text
    ev_id = ev_resp.json()["id"]

    componentes = build_maintenance_components(all_ok=True, overrides={"fotocelda": False})
    assert tuple(componentes.keys()) == MAINTENANCE_12_COMPONENTS

    close_resp = client.post(
        f"/api/v1/ordenes/{ot_id}/cerrar",
        sede="montelibano",
        json_body={
            "sitio_arreglo": "Calle Principal # 10-20",
            "quien_recibe": "Presidente JAC",
            "requiere_desmonte": True,
            "causal_desmonte": "Luminaria quemada",
            "luminaria_reemplazo_id": lum_rep["id"],
            "componentes": componentes,
            "materiales": [{"material_id": mat_id, "cantidad": 3}],
            "evidencias": [{"archivo_id": ev_id, "tipo": "foto"}],
        },
    )
    assert close_resp.status_code == 200, f"Close OT failed: {close_resp.status_code} {close_resp.text}"
    closed = close_resp.json()
    assert str(closed.get("estado_codigo") or closed.get("estado", {}).get("codigo")) == "203"

    # Atomic kardex deduction: 20 -> 17
    mat_after = client.get(f"/api/v1/materiales/{mat_id}", sede="montelibano")
    assert mat_after.status_code == 200
    assert float(mat_after.json()["existencias"]) == 17.0

    # Replacement luminaire activated (121) & history event recorded
    rep_after = client.get(f"/api/v1/luminarias/{lum_rep['id']}", sede="montelibano")
    assert rep_after.status_code == 200
    assert str(
        rep_after.json().get("estado_codigo") or rep_after.json().get("estado", {}).get("codigo")
    ) == "121"

    hist_resp = client.get(f"/api/v1/luminarias/{lum_old['id']}/historial", sede="montelibano")
    assert hist_resp.status_code == 200
    assert len(hist_resp.json().get("eventos", [])) >= 1

    # PQRS auto-closed to 303
    pqrs_after = client.get(f"/api/v1/pqrs/{pqrs['id']}", sede="montelibano")
    assert pqrs_after.status_code == 200
    assert str(
        pqrs_after.json().get("estado_codigo") or pqrs_after.json().get("estado", {}).get("codigo")
    ) == "303"


def test_modernization_and_relocation_paired_luminaires_and_eventos(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """F5-4: Modernization & Relocation update paired instalada+desmontada and log eventos."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tag = uuid.uuid4().hex[:6].upper()
    tec_id = _ensure_tecnico_id(client, run_id, sede="montelibano")
    barrio_id, _ = _resolve_barrio_id(client, "montelibano")
    tipo_mod_id = _resolve_maestro_id(client, "TIPO_MODERNIZACION")

    for mode, idx_a, idx_b in (("modernizacion", 6, 7), ("reubicacion", 8, 9)):
        lum_in = _create_luminaire(
            client, f"{run_id}-{mode[:3].upper()}-IN-{tag}", estado_codigo="124", seed_idx=idx_a
        )
        lum_out = _create_luminaire(
            client, f"{run_id}-{mode[:3].upper()}-OUT-{tag}", estado_codigo="121", seed_idx=idx_b
        )
        ot_resp = client.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": mode,
                "prioridad": 1,
                "luminarias": [
                    {"luminaria_id": lum_in["id"], "rol": "instalada"},
                    {"luminaria_id": lum_out["id"], "rol": "desmontada"},
                ],
            },
        )
        assert ot_resp.status_code == 201, ot_resp.text
        ot_id = ot_resp.json()["id"]
        assert (
            client.post(
                f"/api/v1/ordenes/{ot_id}/asignar",
                sede="montelibano",
                json_body={"tecnico_id": tec_id},
            ).status_code
            in (200, 202)
        )

        ev_resp = client.post(
            "/api/v1/archivos",
            sede="montelibano",
            idempotency_key=str(uuid.uuid4()),
            files={"archivo": ("doc.pdf", make_pdf(f"OT {mode}"), "application/pdf")},
        )
        assert ev_resp.status_code in (200, 201)

        close_resp = client.post(
            f"/api/v1/ordenes/{ot_id}/cerrar",
            sede="montelibano",
            json_body={
                "tipo_modernizacion_id": tipo_mod_id,
                "barrio_id": barrio_id,
                "poste": f"P-{mode[:3].upper()}-{tag}",
                "longitud_brazo": 1.5,
                "destino_desmontada": "124",
                "materiales": [],
                "evidencias": [{"archivo_id": ev_resp.json()["id"], "tipo": "soporte"}],
            },
        )
        assert close_resp.status_code == 200, f"Close {mode} failed: {close_resp.text}"
        assert (
            str(
                close_resp.json().get("estado_codigo")
                or close_resp.json().get("estado", {}).get("codigo")
            )
            == "203"
        )

        in_after = client.get(f"/api/v1/luminarias/{lum_in['id']}", sede="montelibano").json()
        out_after = client.get(f"/api/v1/luminarias/{lum_out['id']}", sede="montelibano").json()
        assert str(in_after.get("estado_codigo") or in_after.get("estado", {}).get("codigo")) == "121"
        assert (
            str(out_after.get("estado_codigo") or out_after.get("estado", {}).get("codigo")) == "124"
        )

        for lid in (lum_in["id"], lum_out["id"]):
            hist = client.get(f"/api/v1/luminarias/{lid}/historial", sede="montelibano").json()
            assert len(hist.get("eventos", [])) >= 1


def test_expansion_ot_installs_warehouse_124_to_121_and_evento(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """F5-5: Expansion OT installs luminaire from warehouse 124 -> 121 and logs evento_activo."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tag = uuid.uuid4().hex[:6].upper()
    tec_id = _ensure_tecnico_id(client, run_id, sede="montelibano")
    barrio_id, _ = _resolve_barrio_id(client, "montelibano")
    tipo_exp_id = _resolve_maestro_id(client, "TIPO_EXPANSION")

    lum = _create_luminaire(client, f"{run_id}-EXP-{tag}", estado_codigo="124", seed_idx=10)
    ot_resp = client.post(
        "/api/v1/ordenes",
        sede="montelibano",
        json_body={
            "tipo": "expansion",
            "prioridad": 1,
            "luminarias": [{"luminaria_id": lum["id"], "rol": "instalada"}],
        },
    )
    assert ot_resp.status_code == 201
    ot_id = ot_resp.json()["id"]
    assert (
        client.post(
            f"/api/v1/ordenes/{ot_id}/asignar",
            sede="montelibano",
            json_body={"tecnico_id": tec_id},
        ).status_code
        in (200, 202)
    )

    lat, lng = generate_coordinates("montelibano", 12, seed=909)[11]
    close_resp = client.post(
        f"/api/v1/ordenes/{ot_id}/cerrar",
        sede="montelibano",
        json_body={
            "tipo_expansion_id": tipo_exp_id,
            "barrio_id": barrio_id,
            "poste": f"P-EXP-{tag}",
            "latitud": lat,
            "longitud": lng,
            "materiales": [],
            "evidencias": [],
        },
    )
    assert close_resp.status_code == 200, close_resp.text
    lum_after = client.get(f"/api/v1/luminarias/{lum['id']}", sede="montelibano").json()
    assert str(lum_after.get("estado_codigo") or lum_after.get("estado", {}).get("codigo")) == "121"
    hist = client.get(f"/api/v1/luminarias/{lum['id']}/historial", sede="montelibano").json()
    assert len(hist.get("eventos", [])) >= 1


def test_bulk_ot_templates_and_valid_upload_async(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """F5-6: Download bulk OT Excel templates and execute valid async expansion upload."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    for tipo in ("expansion", "modernizacion", "reubicacion"):
        tpl = client.get(f"/api/v1/ordenes/plantillas/{tipo}", sede="montelibano")
        assert tpl.status_code == 200, f"Template {tipo} failed: {tpl.status_code}"
        assert tpl.content[:2] == b"PK"
        sheets = read_xlsx_sheets(tpl.content)
        assert len(sheets) >= 1

    tag = uuid.uuid4().hex[:6].upper()
    _, barrio_nombre = _resolve_barrio_id(client, "montelibano")
    c1 = f"{run_id}-BLK1-{tag}"
    c2 = f"{run_id}-BLK2-{tag}"
    _create_luminaire(client, c1, estado_codigo="124", seed_idx=13)
    _create_luminaire(client, c2, estado_codigo="124", seed_idx=14)

    xlsx_bytes = build_bulk_ot_xlsx(
        "expansion",
        [
            {"luminaria_codigo": c1, "barrio": barrio_nombre, "poste": f"PB1-{tag}"},
            {"luminaria_codigo": c2, "barrio": barrio_nombre, "poste": f"PB2-{tag}"},
        ],
    )
    upload = client.post(
        "/api/v1/ordenes/cargue-masivo/expansion",
        sede="montelibano",
        files={
            "archivo": (
                f"cargue_{tag}.xlsx",
                xlsx_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert upload.status_code == 202, upload.text
    job_id = upload.json().get("tareaId") or upload.json().get("tarea_id")
    if job_id is not None:
        db_helper.wait_for_procrastinate_job(int(job_id), timeout=e2e_config.timeout_seconds)


def test_materials_crud_bajo_minimo_flag_and_non_negative_db_constraint(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """F6-1: Materials CRUD, bajo_minimo alert flag, and DB CHECK (existencias >= 0)."""
    assert db_helper.has_non_negative_stock_constraint(), (
        "PostgreSQL must enforce CHECK (existencias >= 0) on inventario.material"
    )
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tag = uuid.uuid4().hex[:6].upper()

    low_resp = client.post(
        "/api/v1/materiales",
        sede="montelibano",
        json_body={
            "categoria": "CABLE",
            "codigo": f"{run_id}-LOW-{tag}",
            "descripcion": "Cable bajo mínimo",
            "unidad": "MTS",
            "existencias": 4,
            "existencias_minimas": 10,
        },
    )
    assert low_resp.status_code == 201, low_resp.text
    low_mat = low_resp.json()
    assert low_mat["bajo_minimo"] is True

    ok_resp = client.post(
        "/api/v1/materiales",
        sede="montelibano",
        json_body={
            "categoria": "CABLE",
            "codigo": f"{run_id}-OK-{tag}",
            "descripcion": "Cable normal",
            "unidad": "MTS",
            "existencias": 30,
            "existencias_minimas": 10,
        },
    )
    assert ok_resp.status_code == 201, ok_resp.text
    ok_mat = ok_resp.json()
    assert ok_mat["bajo_minimo"] is False

    list_low = client.get(
        "/api/v1/materiales",
        sede="montelibano",
        params={"bajo_minimo": "true", "size": 100},
    )
    assert list_low.status_code == 200
    low_ids = {m["id"] for m in _extract_items(list_low.json())}
    assert low_mat["id"] in low_ids
    assert ok_mat["id"] not in low_ids

    patch_resp = client.patch(
        f"/api/v1/materiales/{ok_mat['id']}",
        sede="montelibano",
        json_body={"existencias_minimas": 50, "descripcion": "Cable umbral elevado"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["bajo_minimo"] is True


def test_kardex_movements_entrada_salida_ajuste_and_uuid_origen_idempotency(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """F6-2: Kardex entrada/salida/ajuste movements and uuid_origen idempotency."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tag = uuid.uuid4().hex[:6].upper()
    mat_resp = client.post(
        "/api/v1/materiales",
        sede="montelibano",
        json_body={
            "categoria": "ACCESORIOS",
            "codigo": f"{run_id}-KDX-{tag}",
            "descripcion": "Conector perforación",
            "unidad": "UND",
            "existencias": 10,
            "existencias_minimas": 2,
        },
    )
    assert mat_resp.status_code == 201
    mat_id = mat_resp.json()["id"]

    u_in = str(uuid.uuid4())
    for _ in range(2):
        r_in = client.post(
            f"/api/v1/materiales/{mat_id}/movimientos",
            sede="montelibano",
            json_body={
                "tipo": "entrada",
                "cantidad": 15,
                "descripcion": "Compra bodega",
                "uuid_origen": u_in,
            },
        )
        assert r_in.status_code in (200, 201), r_in.text

    mat_mid = client.get(f"/api/v1/materiales/{mat_id}", sede="montelibano").json()
    assert float(mat_mid["existencias"]) == 25.0, "uuid_origen replay must not double-count"

    r_out = client.post(
        f"/api/v1/materiales/{mat_id}/movimientos",
        sede="montelibano",
        json_body={
            "tipo": "salida",
            "cantidad": 5,
            "descripcion": "Salida cuadrilla",
            "uuid_origen": str(uuid.uuid4()),
        },
    )
    assert r_out.status_code in (200, 201), r_out.text
    assert float(client.get(f"/api/v1/materiales/{mat_id}", sede="montelibano").json()["existencias"]) == 20.0

    r_adj = client.post(
        f"/api/v1/materiales/{mat_id}/movimientos",
        sede="montelibano",
        json_body={
            "tipo": "ajuste",
            "cantidad": 2,
            "descripcion": "Ajuste conteo físico",
            "uuid_origen": str(uuid.uuid4()),
        },
    )
    assert r_adj.status_code in (200, 201), r_adj.text

    kardex = client.get(f"/api/v1/materiales/{mat_id}/movimientos", sede="montelibano")
    assert kardex.status_code == 200
    tipos = {m["tipo"] for m in _extract_items(kardex.json())}
    assert {"entrada", "salida", "ajuste"}.issubset(tipos)


def test_warehouse_luminaires_list_transition_and_bulk_upload(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """F6-3: Warehouse luminaires listing, state transitions, and Excel bulk load."""
    client = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tag = uuid.uuid4().hex[:6].upper()
    lum = _create_luminaire(client, f"{run_id}-BOD-{tag}", estado_codigo="124", seed_idx=15)

    est_124 = _resolve_estado_id(client, "luminaria", "124")
    est_123 = _resolve_estado_id(client, "luminaria", "123")

    list_resp = client.get(
        "/api/v1/bodega/luminarias",
        sede="montelibano",
        params={"estado_id": est_124, "size": 100},
    )
    assert list_resp.status_code == 200, list_resp.text
    assert any(item["id"] == lum["id"] for item in _extract_items(list_resp.json()))

    patch_resp = client.patch(
        f"/api/v1/bodega/luminarias/{lum['id']}",
        sede="montelibano",
        json_body={"estado_id": est_123, "observacion": "Baja técnica E2E"},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    hist = client.get(f"/api/v1/luminarias/{lum['id']}/historial", sede="montelibano").json()
    assert len(hist.get("eventos", [])) >= 1

    from fixtures import XlsxSheet, build_xlsx_bytes

    bodega_xlsx = build_xlsx_bytes(
        [
            XlsxSheet(
                "Bodega",
                [
                    ["luminaria_codigo", "estado_codigo", "observacion"],
                    [f"{run_id}-BOD-{tag}", "125", "Ingreso a mantenimiento bodega"],
                ],
            )
        ]
    )
    cargue_resp = client.post(
        "/api/v1/bodega/cargue",
        sede="montelibano",
        files={
            "archivo": (
                f"bodega_{tag}.xlsx",
                bodega_xlsx,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert cargue_resp.status_code == 202, cargue_resp.text
    job_id = _extract_id(cargue_resp.json(), "cargueId", "cargue_id", "tareaId", "tarea_id")
    if isinstance(job_id, int):
        db_helper.wait_for_procrastinate_job(job_id, timeout=e2e_config.timeout_seconds)
