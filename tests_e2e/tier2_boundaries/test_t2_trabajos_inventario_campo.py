"""Tier 2 boundary and error E2E tests for EP-05 Trabajos, EP-06 Inventario & EP-07 Campo."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fixtures.operational_builder import (
    MAINTENANCE_12_COMPONENTS,
    build_bulk_ot_xlsx,
    build_maintenance_components,
    generate_coordinates,
)
from harness.browser import BrowserDriver
from harness.client import SapefClient, assert_problem_json
from harness.config import E2EConfig
from harness.db import DbHelper

pytestmark = [pytest.mark.tier2, pytest.mark.pwa]


def _admin_creds(e2e_config: E2EConfig) -> tuple[str, str]:
    assert e2e_config.admin_password, (
        "SAPEF_E2E_ADMIN_PASSWORD must be configured to run authenticated E2E tests"
    )
    return e2e_config.admin_user, e2e_config.admin_password


def _unique_secret() -> str:
    return f"SapefOps!{uuid.uuid4().hex[:10]}9Z"


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    if isinstance(payload, dict):
        for key in ("items", "resultados", "datos", "ordenes", "materiales"):
            val = payload.get(key)
            if isinstance(val, list):
                return [dict(item) for item in val]
    raise AssertionError(f"Unexpected list/paginated payload: {payload!r}")


def _resolve_estado_id(admin: SapefClient, proceso: str, codigo: str) -> int:
    items = _extract_items(
        admin.get("/api/v1/estados", omit_sede=True, params={"proceso": proceso}).json()
    )
    return int(next(item["id"] for item in items if str(item["codigo"]) == codigo))


def _resolve_maestro_id(admin: SapefClient, clase: str, preferred: str | None = None) -> int:
    items = _extract_items(admin.get(f"/api/v1/maestros/{clase}", omit_sede=True).json())
    if preferred:
        for item in items:
            if str(item["codigo"]).upper() == preferred.upper():
                return int(item["id"])
    return int(items[0]["id"])


def _resolve_barrio(admin: SapefClient, sede: str = "montelibano") -> dict[str, Any]:
    items = _extract_items(admin.get("/api/v1/barrios", sede=sede).json())
    return dict(items[0])


def _create_user(
    admin: SapefClient,
    *,
    run_id: str,
    tag: str,
    role_codigo: str,
    sedes: list[str],
) -> dict[str, Any]:
    sede_items = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    sede_ids = [next(s["id"] for s in sede_items if s["codigo"] == c) for c in sedes]
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
            "identificacion": f"82{int(suffix, 16) % 10000000:07d}",
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
    codigo: str,
    *,
    sede: str = "montelibano",
    estado_codigo: str = "121",
    seed: int = 1,
) -> dict[str, Any]:
    barrio = _resolve_barrio(admin, sede)
    estado_id = _resolve_estado_id(admin, "luminaria", estado_codigo)
    tech_id = _resolve_maestro_id(admin, "LUMINARIA_TECNOLOGIA", "LED")
    pot_id = _resolve_maestro_id(admin, "LUMINARIA_POTENCIA")
    marca_id = _resolve_maestro_id(admin, "LUMINARIA_MARCA", "PHILIPS")
    lat, lng = generate_coordinates(sede, 1, seed=seed)[0]
    resp = admin.post(
        "/api/v1/luminarias",
        sede=sede,
        json_body={
            "codigo": codigo,
            "barrio_id": barrio["id"],
            "latitud": lat,
            "longitud": lng,
            "estado_id": estado_id,
            "tecnologia_id": tech_id,
            "potencia_id": pot_id,
            "marca_id": marca_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


def test_ot_invalid_tipo_or_cross_sede_luminaire_returns_422(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """POST /ordenes with invalid tipo or luminaire from another sede returns 422."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    suffix = uuid.uuid4().hex[:6].upper()
    mtl_lum = _create_luminaire(
        admin, f"{run_id}-OTM-{suffix}", sede="montelibano", estado_codigo="121", seed=1
    )
    alc_lum = _create_luminaire(
        admin, f"{run_id}-OTA-{suffix}", sede="alcala", estado_codigo="121", seed=2
    )

    bad_tipo = admin.post(
        "/api/v1/ordenes",
        sede="montelibano",
        json_body={
            "tipo": "poda_inventada",
            "prioridad": 1,
            "luminarias": [{"luminaria_id": mtl_lum["id"], "rol": "intervenida"}],
        },
    )
    assert_problem_json(bad_tipo, expected_status=422)

    cross_lum = admin.post(
        "/api/v1/ordenes",
        sede="montelibano",
        json_body={
            "tipo": "mantenimiento",
            "prioridad": 1,
            "luminarias": [{"luminaria_id": alc_lum["id"], "rol": "intervenida"}],
        },
    )
    assert_problem_json(cross_lum, expected_status=422)


def test_ot_assign_cross_sede_technician_or_crew_returns_422(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Assigning a technician or crew from another sede returns 422 RFC 9457."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    alc_tec = _create_user(
        admin,
        run_id=run_id,
        tag="alctec",
        role_codigo="TECNICO",
        sedes=["alcala"],
    )
    try:
        suffix = uuid.uuid4().hex[:6].upper()
        alc_crew = admin.post(
            "/api/v1/cuadrillas",
            sede="alcala",
            json_body={
                "nombre": f"{run_id}-ALC-CRW-{suffix}",
                "tecnicos_ids": [alc_tec["id"]],
                "activa": True,
            },
        )
        assert alc_crew.status_code == 201, alc_crew.text

        bad_crew = admin.post(
            "/api/v1/cuadrillas",
            sede="montelibano",
            json_body={
                "nombre": f"{run_id}-BAD-CRW-{suffix}",
                "tecnicos_ids": [alc_tec["id"]],
                "activa": True,
            },
        )
        assert_problem_json(bad_crew, expected_status=422)

        lum = _create_luminaire(
            admin, f"{run_id}-XASG-{suffix}", sede="montelibano", estado_codigo="121", seed=3
        )
        ot = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 1,
                "luminarias": [{"luminaria_id": lum["id"], "rol": "intervenida"}],
            },
        )
        assert ot.status_code == 201, ot.text
        ot_id = ot.json()["id"]

        bad_tec_asg = admin.post(
            f"/api/v1/ordenes/{ot_id}/asignar",
            sede="montelibano",
            json_body={"tecnico_id": alc_tec["id"]},
        )
        assert_problem_json(bad_tec_asg, expected_status=422)

        bad_crew_asg = admin.post(
            f"/api/v1/ordenes/{ot_id}/asignar",
            sede="montelibano",
            json_body={"cuadrilla_id": alc_crew.json()["id"]},
        )
        assert_problem_json(bad_crew_asg, expected_status=422)
    finally:
        admin.patch(
            f"/api/v1/usuarios/{alc_tec['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )


def test_ot_assign_patch_or_cancel_closed_203_and_cancelled_204_returns_409(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Mutating, assigning, or cancelling closed (203) or cancelled (204) OT returns 409."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    tec = _create_user(
        admin,
        run_id=run_id,
        tag="ot409",
        role_codigo="TECNICO",
        sedes=["montelibano"],
    )
    try:
        suffix = uuid.uuid4().hex[:6].upper()
        lum_a = _create_luminaire(admin, f"{run_id}-OTA-{suffix}", sede="montelibano", seed=4)
        lum_b = _create_luminaire(admin, f"{run_id}-OTB-{suffix}", sede="montelibano", seed=5)

        ot_a = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 1,
                "luminarias": [{"luminaria_id": lum_a["id"], "rol": "intervenida"}],
            },
        ).json()["id"]
        assert (
            admin.post(
                f"/api/v1/ordenes/{ot_a}/asignar",
                sede="montelibano",
                json_body={"tecnico_id": tec["id"]},
            ).status_code
            in {200, 202}
        )
        close_a = admin.post(
            f"/api/v1/ordenes/{ot_a}/cerrar",
            sede="montelibano",
            json_body={
                "sitio_arreglo": "Calle 1",
                "quien_recibe": "Testigo",
                "requiere_desmonte": False,
                "componentes": build_maintenance_components(all_ok=True),
                "materiales": [],
                "evidencias": [],
            },
        )
        assert close_a.status_code == 200, close_a.text

        for method, path, body in (
            ("PATCH", f"/api/v1/ordenes/{ot_a}", {"observaciones": "Edit cerrada"}),
            ("POST", f"/api/v1/ordenes/{ot_a}/asignar", {"tecnico_id": tec["id"]}),
            ("POST", f"/api/v1/ordenes/{ot_a}/anular", {"motivo": "Anular cerrada"}),
        ):
            resp = admin.request(method, path, sede="montelibano", json_body=body)
            assert_problem_json(resp, expected_status=409)

        ot_b = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 2,
                "luminarias": [{"luminaria_id": lum_b["id"], "rol": "intervenida"}],
            },
        ).json()["id"]
        cancel_b = admin.post(
            f"/api/v1/ordenes/{ot_b}/anular",
            sede="montelibano",
            json_body={"motivo": "Cancelada antes de ejecutar"},
        )
        assert cancel_b.status_code == 200, cancel_b.text

        for method, path, body in (
            ("PATCH", f"/api/v1/ordenes/{ot_b}", {"observaciones": "Edit anulada"}),
            ("POST", f"/api/v1/ordenes/{ot_b}/asignar", {"tecnico_id": tec["id"]}),
            (
                "POST",
                f"/api/v1/ordenes/{ot_b}/cerrar",
                {
                    "sitio_arreglo": "Calle 2",
                    "quien_recibe": "Testigo",
                    "requiere_desmonte": False,
                    "componentes": build_maintenance_components(all_ok=True),
                    "materiales": [],
                    "evidencias": [],
                },
            ),
        ):
            resp = admin.request(method, path, sede="montelibano", json_body=body)
            assert_problem_json(resp, expected_status=409)
    finally:
        admin.patch(
            f"/api/v1/usuarios/{tec['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )


def test_maintenance_close_missing_required_component_returns_422(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Closing a maintenance OT missing any of the 12 required components returns 422."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    tec = _create_user(
        admin,
        run_id=run_id,
        tag="comp",
        role_codigo="TECNICO",
        sedes=["montelibano"],
    )
    try:
        lum = _create_luminaire(
            admin, f"{run_id}-CMP-{uuid.uuid4().hex[:6].upper()}", sede="montelibano", seed=6
        )
        ot_id = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 1,
                "luminarias": [{"luminaria_id": lum["id"], "rol": "intervenida"}],
            },
        ).json()["id"]
        admin.post(
            f"/api/v1/ordenes/{ot_id}/asignar",
            sede="montelibano",
            json_body={"tecnico_id": tec["id"]},
        )

        for omitted_key in (MAINTENANCE_12_COMPONENTS[3], MAINTENANCE_12_COMPONENTS[-1]):
            partial = build_maintenance_components(all_ok=True)
            partial.pop(omitted_key)
            resp = admin.post(
                f"/api/v1/ordenes/{ot_id}/cerrar",
                sede="montelibano",
                json_body={
                    "sitio_arreglo": "Calle 3",
                    "quien_recibe": "Testigo",
                    "requiere_desmonte": False,
                    "componentes": partial,
                    "materiales": [],
                    "evidencias": [],
                },
            )
            assert_problem_json(resp, expected_status=422)
    finally:
        admin.patch(
            f"/api/v1/usuarios/{tec['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )


def test_modernization_and_relocation_missing_pair_rn013_returns_422(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Modernization & Relocation missing instalada or desmontada pair return 422 (RN-013)."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    suffix = uuid.uuid4().hex[:6].upper()
    lum_in = _create_luminaire(
        admin, f"{run_id}-RN13I-{suffix}", sede="montelibano", estado_codigo="124", seed=7
    )
    lum_out = _create_luminaire(
        admin, f"{run_id}-RN13O-{suffix}", sede="montelibano", estado_codigo="121", seed=8
    )

    for mode in ("modernizacion", "reubicacion"):
        only_installed = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": mode,
                "prioridad": 1,
                "luminarias": [{"luminaria_id": lum_in["id"], "rol": "instalada"}],
            },
        )
        assert_problem_json(only_installed, expected_status=422)

        only_removed = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": mode,
                "prioridad": 1,
                "luminarias": [{"luminaria_id": lum_out["id"], "rol": "desmontada"}],
            },
        )
        assert_problem_json(only_removed, expected_status=422)


def test_expansion_luminaire_not_in_124_bodega_buena_returns_409(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Closing an expansion OT with a luminaire not in state 124 Bodega buena returns 409."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    tec = _create_user(
        admin,
        run_id=run_id,
        tag="exp409",
        role_codigo="TECNICO",
        sedes=["montelibano"],
    )
    try:
        barrio = _resolve_barrio(admin, "montelibano")
        tipo_exp_id = _resolve_maestro_id(admin, "TIPO_EXPANSION")
        est_123 = _resolve_estado_id(admin, "luminaria", "123")

        lum = _create_luminaire(
            admin,
            f"{run_id}-EXP409-{uuid.uuid4().hex[:6].upper()}",
            sede="montelibano",
            estado_codigo="124",
            seed=9,
        )
        ot_resp = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "expansion",
                "prioridad": 1,
                "luminarias": [{"luminaria_id": lum["id"], "rol": "instalada"}],
            },
        )
        assert ot_resp.status_code == 201, ot_resp.text
        ot_id = ot_resp.json()["id"]
        admin.post(
            f"/api/v1/ordenes/{ot_id}/asignar",
            sede="montelibano",
            json_body={"tecnico_id": tec["id"]},
        )

        # Move luminaire out of 124 Bodega buena into 123 Bodega de baja before closing
        move_baja = admin.patch(
            f"/api/v1/bodega/luminarias/{lum['id']}",
            sede="montelibano",
            json_body={"estado_id": est_123, "observacion": "Baja previa al cierre"},
        )
        assert move_baja.status_code == 200, move_baja.text

        lat, lng = generate_coordinates("montelibano", 1, seed=10)[0]
        close_resp = admin.post(
            f"/api/v1/ordenes/{ot_id}/cerrar",
            sede="montelibano",
            json_body={
                "tipo_expansion_id": tipo_exp_id,
                "barrio_id": barrio["id"],
                "poste": "P-EXP-ERR",
                "latitud": lat,
                "longitud": lng,
                "materiales": [],
                "evidencias": [],
            },
        )
        assert_problem_json(close_resp, expected_status=409)
    finally:
        admin.patch(
            f"/api/v1/usuarios/{tec['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )


def test_ot_close_atomic_kardex_rollback_rn017(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """RN-017: insufficient stock on material #2 rolls back material #1, OT state, and luminaire."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    tec = _create_user(
        admin,
        run_id=run_id,
        tag="rn017",
        role_codigo="TECNICO",
        sedes=["montelibano"],
    )
    try:
        suffix = uuid.uuid4().hex[:6].upper()
        mat1 = admin.post(
            "/api/v1/materiales",
            sede="montelibano",
            json_body={
                "categoria": "ELECTRICO",
                "codigo": f"{run_id}-RB1-{suffix}",
                "descripcion": "Material 1 suficiente",
                "unidad": "UND",
                "existencias": 10,
                "existencias_minimas": 1,
            },
        ).json()
        mat2 = admin.post(
            "/api/v1/materiales",
            sede="montelibano",
            json_body={
                "categoria": "ELECTRICO",
                "codigo": f"{run_id}-RB2-{suffix}",
                "descripcion": "Material 2 insuficiente",
                "unidad": "UND",
                "existencias": 2,
                "existencias_minimas": 1,
            },
        ).json()

        lum = _create_luminaire(
            admin, f"{run_id}-RB-LUM-{suffix}", sede="montelibano", estado_codigo="121", seed=11
        )
        canal_id = _resolve_maestro_id(admin, "CANAL_PQRS", "WHATSAPP")
        cit = admin.post(
            "/api/v1/ciudadanos",
            sede="montelibano",
            json_body={
                "identificacion": f"83{suffix}",
                "nombre_completo": f"Ciudadano Rollback {suffix}",
                "correo": f"rb.{suffix.lower()}@example.test",
            },
        ).json()
        pqrs = admin.post(
            "/api/v1/pqrs",
            sede="montelibano",
            json_body={
                "canal_id": canal_id,
                "ciudadano_id": cit["id"],
                "prioridad": 1,
                "observacion_solicitante": "Falla rollback",
                "notificar_cliente": False,
                "luminarias": [{"luminaria_id": lum["id"]}],
            },
        ).json()

        ot = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 1,
                "pqrs_id": pqrs["id"],
                "luminarias": [{"luminaria_id": lum["id"], "rol": "intervenida"}],
            },
        ).json()
        ot_id = ot["id"]
        admin.post(
            f"/api/v1/ordenes/{ot_id}/asignar",
            sede="montelibano",
            json_body={"tecnico_id": tec["id"]},
        )

        close_fail = admin.post(
            f"/api/v1/ordenes/{ot_id}/cerrar",
            sede="montelibano",
            json_body={
                "sitio_arreglo": "Calle Rollback",
                "quien_recibe": "Testigo",
                "requiere_desmonte": False,
                "componentes": build_maintenance_components(all_ok=True),
                "materiales": [
                    {"material_id": mat1["id"], "cantidad": 4},
                    {"material_id": mat2["id"], "cantidad": 5},
                ],
                "evidencias": [],
            },
        )
        assert_problem_json(close_fail, expected_status=409)

        mat1_after = admin.get(f"/api/v1/materiales/{mat1['id']}", sede="montelibano").json()
        mat2_after = admin.get(f"/api/v1/materiales/{mat2['id']}", sede="montelibano").json()
        assert float(mat1_after["existencias"]) == 10.0
        assert float(mat2_after["existencias"]) == 2.0

        ot_after = admin.get(f"/api/v1/ordenes/{ot_id}", sede="montelibano").json()
        ot_state = str(
            ot_after.get("estado_codigo") or (ot_after.get("estado") or {}).get("codigo", "")
        )
        assert ot_state == "202"

        lum_after = admin.get(f"/api/v1/luminarias/{lum['id']}", sede="montelibano").json()
        lum_state = str(
            lum_after.get("estado_codigo") or (lum_after.get("estado") or {}).get("codigo", "")
        )
        assert lum_state == "122"

        pqrs_after = admin.get(f"/api/v1/pqrs/{pqrs['id']}", sede="montelibano").json()
        pqrs_state = str(
            pqrs_after.get("estado_codigo") or (pqrs_after.get("estado") or {}).get("codigo", "")
        )
        assert pqrs_state != "303"
    finally:
        admin.patch(
            f"/api/v1/usuarios/{tec['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )


def test_bulk_ot_expansion_all_or_nothing_9_valid_row_10_invalid(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """Bulk OT Excel with 9 valid rows + invalid row 10 inserts 0 rows and reports row 10."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    barrio = _resolve_barrio(admin, "montelibano")
    suffix = uuid.uuid4().hex[:6].upper()
    created_lums: list[dict[str, Any]] = []
    valid_rows: list[dict[str, Any]] = []
    for idx in range(9):
        code = f"{run_id}-B{idx + 1}-{suffix}"
        lum = _create_luminaire(admin, code, sede="montelibano", estado_codigo="124", seed=40 + idx)
        created_lums.append(lum)
        valid_rows.append(
            {
                "luminaria_codigo": code,
                "barrio": barrio["nombre"],
                "poste": f"P-BLK-{idx + 1}-{suffix}",
            }
        )

    xlsx_bytes = build_bulk_ot_xlsx("expansion", valid_rows, include_invalid_row=True)
    upload = admin.post(
        "/api/v1/ordenes/cargue-masivo/expansion",
        sede="montelibano",
        files={
            "archivo": (
                f"bulk_fail_{suffix}.xlsx",
                xlsx_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert upload.status_code == 202, upload.text
    payload = upload.json()
    cargue_id = payload.get("cargueId") or payload.get("cargue_id") or payload.get("id")
    job_id = payload.get("tareaId") or payload.get("tarea_id")

    if isinstance(job_id, int):
        db_helper.wait_for_procrastinate_job(
            job_id,
            timeout=e2e_config.timeout_seconds,
            allow_failed=True,
        )

    if cargue_id is not None:
        status_resp = admin.get(
            f"/api/v1/ordenes/cargue-masivo/{cargue_id}",
            sede="montelibano",
        )
        if status_resp.status_code == 200:
            status_text = status_resp.text.lower()
            assert "10" in status_text or "barrio_inexistente_xyz" in status_text, (
                f"Expected bulk error referencing row 10, got: {status_resp.text}"
            )

    for lum in created_lums:
        lum_after = admin.get(f"/api/v1/luminarias/{lum['id']}", sede="montelibano").json()
        state_code = str(
            lum_after.get("estado_codigo") or (lum_after.get("estado") or {}).get("codigo", "")
        )
        assert state_code == "124", f"All-or-nothing violated for {lum['codigo']}: {lum_after}"
        hist = admin.get(f"/api/v1/luminarias/{lum['id']}/historial", sede="montelibano").json()
        assert len(hist.get("ordenes", [])) == 0


def test_inventory_negative_initial_422_duplicate_409_and_negative_kardex_409(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """Negative initial stock -> 422; duplicate codigo -> 409; salida/ajuste < 0 -> 409."""
    assert db_helper.has_non_negative_stock_constraint()
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    suffix = uuid.uuid4().hex[:6].upper()
    code = f"{run_id}-INV-{suffix}"

    neg_init = admin.post(
        "/api/v1/materiales",
        sede="montelibano",
        json_body={
            "categoria": "CABLE",
            "codigo": f"{code}-NEG",
            "descripcion": "Stock negativo inicial",
            "unidad": "MTS",
            "existencias": -1,
            "existencias_minimas": 0,
        },
    )
    assert_problem_json(neg_init, expected_status=422)

    ok_mat = admin.post(
        "/api/v1/materiales",
        sede="montelibano",
        json_body={
            "categoria": "CABLE",
            "codigo": code,
            "descripcion": "Stock valido 5",
            "unidad": "MTS",
            "existencias": 5,
            "existencias_minimas": 2,
        },
    )
    assert ok_mat.status_code == 201, ok_mat.text
    mat_id = ok_mat.json()["id"]

    dup_mat = admin.post(
        "/api/v1/materiales",
        sede="montelibano",
        json_body={
            "categoria": "CABLE",
            "codigo": code,
            "descripcion": "Duplicado",
            "unidad": "MTS",
            "existencias": 10,
            "existencias_minimas": 2,
        },
    )
    assert_problem_json(dup_mat, expected_status=409)

    over_salida = admin.post(
        f"/api/v1/materiales/{mat_id}/movimientos",
        sede="montelibano",
        json_body={
            "tipo": "salida",
            "cantidad": 6,
            "descripcion": "Salida excesiva",
            "uuid_origen": str(uuid.uuid4()),
        },
    )
    assert_problem_json(over_salida, expected_status=409)

    over_ajuste = admin.post(
        f"/api/v1/materiales/{mat_id}/movimientos",
        sede="montelibano",
        json_body={
            "tipo": "ajuste",
            "cantidad": -6,
            "descripcion": "Ajuste negativo excesivo",
            "uuid_origen": str(uuid.uuid4()),
        },
    )
    assert_problem_json(over_ajuste, expected_status=(409, 422))

    mat_after = admin.get(f"/api/v1/materiales/{mat_id}", sede="montelibano").json()
    assert float(mat_after["existencias"]) == 5.0


def test_inventory_ajuste_without_permission_403_and_uuid_origen_idempotency(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Ajuste without inventario.movimiento.ajustar -> 403; duplicate uuid_origen deducts once."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    suffix = uuid.uuid4().hex[:6].upper()
    mat = admin.post(
        "/api/v1/materiales",
        sede="montelibano",
        json_body={
            "categoria": "ACCESORIOS",
            "codigo": f"{run_id}-ADJ-{suffix}",
            "descripcion": "Material ajuste",
            "unidad": "UND",
            "existencias": 10,
            "existencias_minimas": 2,
        },
    ).json()
    mat_id = mat["id"]

    tec = _create_user(
        admin,
        run_id=run_id,
        tag="noadj",
        role_codigo="TECNICO",
        sedes=["montelibano"],
    )
    try:
        tec_client = auth_session_factory(
            tec["nombre_usuario"],
            tec["_secret"],
            sede="montelibano",
        )
        denied_adj = tec_client.post(
            f"/api/v1/materiales/{mat_id}/movimientos",
            sede="montelibano",
            json_body={
                "tipo": "ajuste",
                "cantidad": 2,
                "descripcion": "Ajuste sin permiso",
                "uuid_origen": str(uuid.uuid4()),
            },
        )
        assert_problem_json(denied_adj, expected_status=403)
    finally:
        admin.patch(
            f"/api/v1/usuarios/{tec['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )

    idem_uuid = str(uuid.uuid4())
    for _ in range(2):
        r = admin.post(
            f"/api/v1/materiales/{mat_id}/movimientos",
            sede="montelibano",
            json_body={
                "tipo": "salida",
                "cantidad": 3,
                "descripcion": "Salida idempotente",
                "uuid_origen": idem_uuid,
            },
        )
        assert r.status_code in {200, 201}, r.text

    mat_after = admin.get(f"/api/v1/materiales/{mat_id}", sede="montelibano").json()
    assert float(mat_after["existencias"]) == 7.0


def test_warehouse_luminaire_terminal_126_invalid_transition_422_and_cross_sede_404(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Transitions from terminal 126 or to non-warehouse -> 422; cross-sede -> 404."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    est_121 = _resolve_estado_id(admin, "luminaria", "121")
    est_124 = _resolve_estado_id(admin, "luminaria", "124")
    est_126 = _resolve_estado_id(admin, "luminaria", "126")

    suffix = uuid.uuid4().hex[:6].upper()
    lum_mtl = _create_luminaire(
        admin, f"{run_id}-W126-{suffix}", sede="montelibano", estado_codigo="124", seed=16
    )
    lum_non = _create_luminaire(
        admin, f"{run_id}-WNON-{suffix}", sede="montelibano", estado_codigo="124", seed=17
    )
    lum_alc = _create_luminaire(
        admin, f"{run_id}-WALC-{suffix}", sede="alcala", estado_codigo="124", seed=18
    )

    to_126 = admin.patch(
        f"/api/v1/bodega/luminarias/{lum_mtl['id']}",
        sede="montelibano",
        json_body={"estado_id": est_126, "observacion": "Disposición final"},
    )
    assert to_126.status_code == 200, to_126.text

    from_126 = admin.patch(
        f"/api/v1/bodega/luminarias/{lum_mtl['id']}",
        sede="montelibano",
        json_body={"estado_id": est_124, "observacion": "Reverso ilegal"},
    )
    assert_problem_json(from_126, expected_status=422)

    to_non_warehouse = admin.patch(
        f"/api/v1/bodega/luminarias/{lum_non['id']}",
        sede="montelibano",
        json_body={"estado_id": est_121, "observacion": "A operacion directo"},
    )
    assert_problem_json(to_non_warehouse, expected_status=422)

    cross_sede = admin.patch(
        f"/api/v1/bodega/luminarias/{lum_alc['id']}",
        sede="montelibano",
        json_body={"estado_id": est_126, "observacion": "Otra sede"},
    )
    assert_problem_json(cross_sede, expected_status=404)


def test_campo_endpoints_without_perm_403_and_ver_propias_peer_ot_403(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Missing campo.app.usar -> 403; ver_propias blocks viewing peer technician's OT -> 403."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    no_campo = _create_user(
        admin,
        run_id=run_id,
        tag="nocampo",
        role_codigo="INTERVENTORIA",
        sedes=["montelibano"],
    )
    tec_a = _create_user(
        admin,
        run_id=run_id,
        tag="teca",
        role_codigo="TECNICO",
        sedes=["montelibano"],
    )
    tec_b = _create_user(
        admin,
        run_id=run_id,
        tag="tecb",
        role_codigo="TECNICO",
        sedes=["montelibano"],
    )
    try:
        no_campo_client = auth_session_factory(
            no_campo["nombre_usuario"],
            no_campo["_secret"],
            sede="montelibano",
        )
        assert_problem_json(
            no_campo_client.get("/api/v1/campo/paquete", sede="montelibano"),
            expected_status=403,
        )
        assert_problem_json(
            no_campo_client.post(
                "/api/v1/campo/sincronizar",
                sede="montelibano",
                json_body={"operaciones": []},
            ),
            expected_status=403,
        )

        suffix = uuid.uuid4().hex[:6].upper()
        lum_b = _create_luminaire(admin, f"{run_id}-PEER-{suffix}", sede="montelibano", seed=19)
        ot_b = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 1,
                "luminarias": [{"luminaria_id": lum_b["id"], "rol": "intervenida"}],
            },
        ).json()["id"]
        admin.post(
            f"/api/v1/ordenes/{ot_b}/asignar",
            sede="montelibano",
            json_body={"tecnico_id": tec_b["id"]},
        )

        tec_a_client = auth_session_factory(
            tec_a["nombre_usuario"],
            tec_a["_secret"],
            sede="montelibano",
            tipo_cliente="pwa",
        )
        peer_detail = tec_a_client.get(f"/api/v1/ordenes/{ot_b}", sede="montelibano")
        assert_problem_json(peer_detail, expected_status=403)

        list_own = tec_a_client.get("/api/v1/ordenes", sede="montelibano", params={"size": 100})
        assert list_own.status_code == 200
        assert all(item["id"] != ot_b for item in _extract_items(list_own.json()))
    finally:
        for uid in (no_campo["id"], tec_a["id"], tec_b["id"]):
            admin.patch(f"/api/v1/usuarios/{uid}", omit_sede=True, json_body={"activo": False})


def test_campo_sync_replay_ya_aplicada_and_conflict_preserves_valid_sibling_ops(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Replay uuid -> ya_aplicada; cancelled/reassigned OT -> conflicto while valid -> aplicada."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")

    tec_a = _create_user(
        admin, run_id=run_id, tag="syna", role_codigo="TECNICO", sedes=["montelibano"]
    )
    tec_b = _create_user(
        admin, run_id=run_id, tag="synb", role_codigo="TECNICO", sedes=["montelibano"]
    )
    try:
        suffix = uuid.uuid4().hex[:6].upper()
        mat = admin.post(
            "/api/v1/materiales",
            sede="montelibano",
            json_body={
                "categoria": "ELECTRICO",
                "codigo": f"{run_id}-SYNM-{suffix}",
                "descripcion": "Material sync idempotente",
                "unidad": "UND",
                "existencias": 10,
                "existencias_minimas": 1,
            },
        ).json()

        lums = [
            _create_luminaire(admin, f"{run_id}-SL{i}-{suffix}", sede="montelibano", seed=20 + i)
            for i in range(3)
        ]
        ots = []
        for lum in lums:
            ot_id = admin.post(
                "/api/v1/ordenes",
                sede="montelibano",
                json_body={
                    "tipo": "mantenimiento",
                    "prioridad": 1,
                    "luminarias": [{"luminaria_id": lum["id"], "rol": "intervenida"}],
                },
            ).json()["id"]
            admin.post(
                f"/api/v1/ordenes/{ot_id}/asignar",
                sede="montelibano",
                json_body={"tecnico_id": tec_a["id"]},
            )
            ots.append(ot_id)

        ot_valid, ot_cancelled, ot_reassigned = ots
        assert (
            admin.post(
                f"/api/v1/ordenes/{ot_cancelled}/anular",
                sede="montelibano",
                json_body={"motivo": "Anulada mientras tecnico estaba offline"},
            ).status_code
            == 200
        )
        assert (
            admin.post(
                f"/api/v1/ordenes/{ot_reassigned}/asignar",
                sede="montelibano",
                json_body={"tecnico_id": tec_b["id"]},
            ).status_code
            in {200, 202}
        )

        tec_a_client = auth_session_factory(
            tec_a["nombre_usuario"],
            tec_a["_secret"],
            sede="montelibano",
            tipo_cliente="pwa",
        )
        u_valid = str(uuid.uuid4())
        u_cancel = str(uuid.uuid4())
        u_reasg = str(uuid.uuid4())
        lat, lng = generate_coordinates("montelibano", 1, seed=25)[0]

        def _payload(with_mat: bool) -> dict[str, Any]:
            return {
                "sitio_arreglo": "Calle Sync",
                "quien_recibe": "Vecino Sync",
                "requiere_desmonte": False,
                "componentes": build_maintenance_components(all_ok=True),
                "materiales": [{"material_id": mat["id"], "cantidad": 2}] if with_mat else [],
                "evidencias": [],
                "latitud": lat,
                "longitud": lng,
            }

        batch_resp = tec_a_client.post(
            "/api/v1/campo/sincronizar",
            sede="montelibano",
            json_body={
                "operaciones": [
                    {
                        "uuid": u_valid,
                        "tipo": "mantenimiento",
                        "ordenId": ot_valid,
                        "creadaEn": "2026-07-20T10:00:00Z",
                        "payload": _payload(True),
                    },
                    {
                        "uuid": u_cancel,
                        "tipo": "mantenimiento",
                        "ordenId": ot_cancelled,
                        "creadaEn": "2026-07-20T10:05:00Z",
                        "payload": _payload(False),
                    },
                    {
                        "uuid": u_reasg,
                        "tipo": "mantenimiento",
                        "ordenId": ot_reassigned,
                        "creadaEn": "2026-07-20T10:10:00Z",
                        "payload": _payload(False),
                    },
                ]
            },
        )
        assert batch_resp.status_code == 200, batch_resp.text
        by_uuid = {r["uuid"]: r for r in batch_resp.json()["resultados"]}
        assert by_uuid[u_valid]["estado"] == "aplicada"
        assert by_uuid[u_cancel]["estado"] == "conflicto"
        assert by_uuid[u_reasg]["estado"] == "conflicto"

        replay_resp = tec_a_client.post(
            "/api/v1/campo/sincronizar",
            sede="montelibano",
            json_body={
                "operaciones": [
                    {
                        "uuid": u_valid,
                        "tipo": "mantenimiento",
                        "ordenId": ot_valid,
                        "creadaEn": "2026-07-20T10:00:00Z",
                        "payload": _payload(True),
                    }
                ]
            },
        )
        assert replay_resp.status_code == 200, replay_resp.text
        assert replay_resp.json()["resultados"][0]["estado"] == "ya_aplicada"

        mat_after = admin.get(f"/api/v1/materiales/{mat['id']}", sede="montelibano").json()
        assert float(mat_after["existencias"]) == 8.0
    finally:
        for uid in (tec_a["id"], tec_b["id"]):
            admin.patch(f"/api/v1/usuarios/{uid}", omit_sede=True, json_body={"activo": False})


def test_campo_push_subscription_invalid_422_and_delete_404(
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """Invalid Web Push subscription keys/endpoint -> 422; deleting missing sub -> 404."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    tec = _create_user(
        admin, run_id=run_id, tag="push422", role_codigo="TECNICO", sedes=["montelibano"]
    )
    try:
        tec_client = auth_session_factory(
            tec["nombre_usuario"],
            tec["_secret"],
            sede="montelibano",
            tipo_cliente="pwa",
        )
        bad_sub = tec_client.post(
            "/api/v1/notificaciones/push/suscripciones",
            sede="montelibano",
            json_body={"endpoint": "not-a-valid-url", "claves": {"p256dh": "", "auth": ""}},
        )
        assert_problem_json(bad_sub, expected_status=422)

        missing_del = tec_client.delete(
            "/api/v1/notificaciones/push/suscripciones",
            sede="montelibano",
            json_body={
                "endpoint": f"https://fcm.googleapis.com/fcm/send/missing-{uuid.uuid4().hex}"
            },
        )
        assert_problem_json(missing_del, expected_status=404)
    finally:
        admin.patch(
            f"/api/v1/usuarios/{tec['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )


@pytest.mark.browser
def test_browser_campo_sw_update_blocked_while_dexie_outbox_has_pending_ops(
    browser_driver: BrowserDriver,
    e2e_config: E2EConfig,
    auth_session_factory: Callable[..., SapefClient],
    run_id: str,
) -> None:
    """apps/campo Service Worker must not activate an update while Dexie outbox is non-empty."""
    admin_user, admin_pw = _admin_creds(e2e_config)
    admin = auth_session_factory(admin_user, admin_pw, sede="montelibano")
    tec = _create_user(
        admin, run_id=run_id, tag="swlock", role_codigo="TECNICO", sedes=["montelibano"]
    )
    try:
        lum = _create_luminaire(
            admin, f"{run_id}-SWL-{uuid.uuid4().hex[:6].upper()}", sede="montelibano", seed=33
        )
        ot_id = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 1,
                "luminarias": [{"luminaria_id": lum["id"], "rol": "intervenida"}],
            },
        ).json()["id"]
        admin.post(
            f"/api/v1/ordenes/{ot_id}/asignar",
            sede="montelibano",
            json_body={"tecnico_id": tec["id"]},
        )

        browser_driver.navigate(e2e_config.campo_url)
        browser_driver.wait_for_selector("input", timeout=e2e_config.timeout_seconds)
        browser_driver.fill('input[name="usuario"], input[type="text"]', tec["nombre_usuario"])
        browser_driver.fill('input[name="clave"], input[type="password"]', tec["_secret"])
        browser_driver.click('button[type="submit"]')

        browser_driver.wait_for_selector("[data-testid='orden-item'], [data-orden-id], a, button")
        time.sleep(1.0)

        sw_before = browser_driver.get_service_worker_state()
        assert sw_before.get("supported") is True
        initial_controller = sw_before.get("controller")

        browser_driver.set_offline(True)
        browser_driver.eval_js("window.dispatchEvent(new Event('offline'))")
        browser_driver.click("[data-testid='orden-item'], [data-orden-id], [data-testid='ejecutar-ot']")
        browser_driver.wait_for_selector("form")
        browser_driver.fill("input[name='sitio_arreglo']", f"Sitio SW Lock {run_id}")
        browser_driver.fill("input[name='quien_recibe']", "Testigo SW Lock")
        browser_driver.click("button[type='submit']")

        deadline = time.monotonic() + e2e_config.timeout_seconds
        outbox_count = 0
        while time.monotonic() < deadline:
            outbox_count = int(
                browser_driver.eval_js(
                    """
                    new Promise((resolve) => {
                      if (!indexedDB.databases) { resolve(0); return; }
                      indexedDB.databases().then(async (dbs) => {
                        let count = 0;
                        for (const info of dbs) {
                          if (!info.name) continue;
                          const n = await new Promise((res) => {
                            const req = indexedDB.open(info.name);
                            req.onsuccess = () => {
                              const db = req.result;
                              if (!db.objectStoreNames.contains('outbox')) {
                                db.close(); res(0); return;
                              }
                              const tx = db.transaction('outbox', 'readonly');
                              const c = tx.objectStore('outbox').count();
                              c.onsuccess = () => { db.close(); res(c.result || 0); };
                              c.onerror = () => { db.close(); res(0); };
                            };
                            req.onerror = () => res(0);
                          });
                          count += n;
                        }
                        resolve(count);
                      }).catch(() => resolve(0));
                    })
                    """,
                    await_promise=True,
                )
                or 0
            )
            if outbox_count >= 1:
                break
            time.sleep(0.25)

        assert outbox_count >= 1, "Expected pending operation in Dexie outbox"

        sw_guard_result = browser_driver.eval_js(
            """
            new Promise(async (resolve) => {
              let controllerChanged = false;
              const onChange = () => { controllerChanged = true; };
              navigator.serviceWorker.addEventListener('controllerchange', onChange);
              const regs = await navigator.serviceWorker.getRegistrations();
              for (const reg of regs) {
                if (reg.waiting) {
                  reg.waiting.postMessage({type: 'SKIP_WAITING'});
                }
              }
              await new Promise((r) => setTimeout(r, 400));
              navigator.serviceWorker.removeEventListener('controllerchange', onChange);
              resolve({
                controllerChanged,
                controllerAfter: navigator.serviceWorker.controller
                  ? navigator.serviceWorker.controller.scriptURL : null,
              });
            })
            """,
            await_promise=True,
        )
        assert sw_guard_result["controllerChanged"] is False
        assert sw_guard_result["controllerAfter"] == initial_controller
    finally:
        admin.patch(
            f"/api/v1/usuarios/{tec['id']}",
            omit_sede=True,
            json_body={"activo": False},
        )
