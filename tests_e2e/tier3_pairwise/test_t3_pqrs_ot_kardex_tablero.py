"""Tier 3 pairwise E2E workflows: PQRS -> OT -> Atomic Kardex -> Email Job -> Timeline -> Tablero."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fixtures import (
    MAINTENANCE_12_COMPONENTS,
    build_maintenance_components,
    generate_coordinates,
    make_jpeg,
    make_png,
)
from harness.client import SapefClient, assert_problem_json
from harness.config import E2EConfig
from harness.db import DbHelper

pytestmark = pytest.mark.tier3


def _admin_client(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    sede: str = "montelibano",
) -> SapefClient:
    assert e2e_config.admin_password, (
        "SAPEF_E2E_ADMIN_PASSWORD must be configured to run authenticated E2E tests"
    )
    return auth_session_factory(
        e2e_config.admin_user,
        e2e_config.admin_password,
        sede=sede,
    )


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    if isinstance(payload, dict):
        for key in ("items", "resultados", "datos", "ordenes", "materiales", "pqrs"):
            val = payload.get(key)
            if isinstance(val, list):
                return [dict(item) for item in val]
    raise AssertionError(f"Unexpected list/paginated payload: {payload!r}")


def _estado_codigo(dto: dict[str, Any]) -> str:
    val = dto.get("estado_codigo")
    if val is not None:
        return str(val)
    est = dto.get("estado")
    if isinstance(est, dict) and est.get("codigo") is not None:
        return str(est["codigo"])
    return str(est or "")


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
    for item in _extract_items(resp.json()):
        if str(item.get("codigo")) == codigo:
            return int(item["id"])
    raise AssertionError(f"Estado {proceso}/{codigo} not found")


def _resolve_barrio_id(client: SapefClient, sede: str = "montelibano") -> int:
    resp = client.get("/api/v1/barrios", sede=sede)
    assert resp.status_code == 200, f"GET barrios failed: {resp.status_code} {resp.text}"
    items = _extract_items(resp.json())
    assert items, f"No barrios seeded for sede {sede}"
    return int(items[0]["id"])


def _create_technician(
    admin: SapefClient,
    run_id: str,
    tag: str,
    sede: str = "montelibano",
) -> dict[str, Any]:
    sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
    sede_id = next(s["id"] for s in sedes if s.get("codigo") == sede)
    roles = _extract_items(admin.get("/api/v1/roles", omit_sede=True).json())
    tec_role = next(r for r in roles if str(r.get("codigo")).upper() == "TECNICO")

    suffix = uuid.uuid4().hex[:6].lower()
    secret = f"SapefT3!{uuid.uuid4().hex[:10]}9A"
    username = f"{run_id.lower()}_{tag}_{suffix}"
    resp = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": username,
            "nombre_completo": f"Técnico Pairwise {suffix}",
            "identificacion": f"71{int(suffix, 16) % 10000000:07d}",
            "correo": f"{username}@example.test",
            "clave": secret,
            "rol_id": tec_role["id"],
            "sedes": [sede_id],
            "activo": True,
            "debe_cambiar_clave": False,
        },
    )
    assert resp.status_code == 201, f"Create technician failed: {resp.status_code} {resp.text}"
    return dict(resp.json())


def _create_luminaire(
    admin: SapefClient,
    codigo: str,
    *,
    sede: str = "montelibano",
    estado_codigo: str = "121",
    seed: int = 1,
) -> dict[str, Any]:
    barrio_id = _resolve_barrio_id(admin, sede)
    estado_id = _resolve_estado_id(admin, "luminaria", estado_codigo)
    tec_id = _resolve_maestro_id(admin, "LUMINARIA_TECNOLOGIA", "LED")
    pot_id = _resolve_maestro_id(admin, "LUMINARIA_POTENCIA", "70")
    marca_id = _resolve_maestro_id(admin, "LUMINARIA_MARCA", "PHILIPS")
    lat, lng = generate_coordinates(sede, 1, seed=seed)[0]
    resp = admin.post(
        "/api/v1/luminarias",
        sede=sede,
        json_body={
            "codigo": codigo,
            "barrio_id": barrio_id,
            "latitud": lat,
            "longitud": lng,
            "estado_id": estado_id,
            "tecnologia_id": tec_id,
            "potencia_id": pot_id,
            "marca_id": marca_id,
            "poste": f"P-{codigo[-4:]}",
        },
    )
    assert resp.status_code == 201, f"POST /luminarias failed: {resp.status_code} {resp.text}"
    return dict(resp.json())


def _create_citizen(
    admin: SapefClient,
    *,
    run_id: str,
    suffix: str,
    sede: str = "montelibano",
) -> dict[str, Any]:
    ident = f"1066{int(suffix, 16) % 1000000:06d}"
    email = f"ciudadano.{run_id.lower()}.{suffix.lower()}@example.test"
    nombre = f"Lucía Pairwise {suffix}"
    resp = admin.post(
        "/api/v1/ciudadanos",
        sede=sede,
        json_body={
            "identificacion": ident,
            "nombre_completo": nombre,
            "barrio_id": _resolve_barrio_id(admin, sede),
            "sector": "Centro",
            "telefono": "7721122",
            "celular": "3009998877",
            "correo": email,
        },
    )
    assert resp.status_code == 201, f"POST /ciudadanos failed: {resp.status_code} {resp.text}"
    dto = dict(resp.json())
    dto["_pii_markers"] = [ident, email, nombre, "3009998877", "7721122"]
    return dto


def _assert_primitive_ids_only_no_pii(args: dict[str, Any], pii_markers: list[str]) -> None:
    assert args, "Procrastinate job args must not be empty"
    for key, val in args.items():
        assert isinstance(val, (int, str, bool)) or val is None, (
            f"Procrastinate arg {key!r} must be primitive ID, got {type(val).__name__}"
        )
    serialized = str(args).lower()
    for forbidden in ("correo", "email", "telefono", "celular", "nombre", "hash_clave", "clave"):
        assert forbidden not in serialized, (
            f"Procrastinate job args leaked PII/secret key {forbidden!r}: {args}"
        )
    for marker in pii_markers:
        assert marker.lower() not in serialized, (
            f"Procrastinate job args leaked PII value {marker!r}: {args}"
        )


def test_t3_pqrs_to_ot_maintenance_kardex_autoclose_email_timeline_and_tablero(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """Full lifecycle: PQRS (121->122) -> OT (201->202) -> close (12 comp + rep + kardex + media)
    -> PQRS auto-close (303) + IDs-only email job -> evento_activo -> Tablero recalc & summary."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tec = _create_technician(admin, run_id, "t3pqrs", sede="montelibano")
    try:
        tag = uuid.uuid4().hex[:6].upper()
        lum_old = _create_luminaire(admin, f"{run_id}-T3OLD-{tag}", estado_codigo="121", seed=101)
        lum_rep = _create_luminaire(admin, f"{run_id}-T3REP-{tag}", estado_codigo="124", seed=102)
        citizen = _create_citizen(admin, run_id=run_id, suffix=tag, sede="montelibano")
        canal_id = _resolve_maestro_id(admin, "CANAL_PQRS", "WHATSAPP")

        mat_resp = admin.post(
            "/api/v1/materiales",
            sede="montelibano",
            json_body={
                "categoria": "ELECTRICO",
                "codigo": f"{run_id}-T3MAT-{tag}",
                "descripcion": f"Fotocelda T3 {tag}",
                "unidad": "UND",
                "existencias": 20,
                "existencias_minimas": 5,
            },
        )
        assert mat_resp.status_code == 201, mat_resp.text
        mat_id = mat_resp.json()["id"]

        # 1. Create PQRS -> luminaire 121 -> 122
        pqrs_resp = admin.post(
            "/api/v1/pqrs",
            sede="montelibano",
            json_body={
                "canal_id": canal_id,
                "ciudadano_id": citizen["id"],
                "prioridad": 1,
                "observacion_solicitante": f"Luminaria apagada {run_id}",
                "notificar_cliente": True,
                "luminarias": [{"luminaria_id": lum_old["id"], "observacion_solicitante": "Falla"}],
            },
        )
        assert pqrs_resp.status_code == 201, pqrs_resp.text
        pqrs_id = pqrs_resp.json()["id"]

        lum_after_pqrs = admin.get(
            f"/api/v1/luminarias/{lum_old['id']}", sede="montelibano"
        ).json()
        assert _estado_codigo(lum_after_pqrs) == "122"

        # 2. Create OT (201) & assign to technician (202)
        ot_resp = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 1,
                "pqrs_id": pqrs_id,
                "observaciones": f"OT pairwise {run_id}",
                "luminarias": [{"luminaria_id": lum_old["id"], "rol": "intervenida"}],
            },
        )
        assert ot_resp.status_code == 201, ot_resp.text
        ot_id = ot_resp.json()["id"]
        assert _estado_codigo(ot_resp.json()) == "201"

        asg_resp = admin.post(
            f"/api/v1/ordenes/{ot_id}/asignar",
            sede="montelibano",
            json_body={"tecnico_id": tec["id"]},
        )
        assert asg_resp.status_code in (200, 202), asg_resp.text
        assert _estado_codigo(asg_resp.json()) == "202"

        # 3. Upload evidences with Idempotency-Key
        ev_photo = admin.post(
            "/api/v1/archivos",
            sede="montelibano",
            idempotency_key=str(uuid.uuid4()),
            files={"archivo": ("antes_despues.png", make_png(8, 8), "image/png")},
        )
        assert ev_photo.status_code in (200, 201), ev_photo.text
        ev_sign = admin.post(
            "/api/v1/archivos",
            sede="montelibano",
            idempotency_key=str(uuid.uuid4()),
            files={"archivo": ("firma_recibe.jpg", make_jpeg(), "image/jpeg")},
        )
        assert ev_sign.status_code in (200, 201), ev_sign.text

        max_job_before_close = int(
            db_helper.scalar("SELECT COALESCE(MAX(id), 0) FROM procrastinate_jobs") or 0
        )

        # 4. Close maintenance OT (all 12 components + replacement + atomic kardex + evidences)
        componentes = build_maintenance_components(all_ok=True, overrides={"fotocelda": False})
        assert tuple(componentes.keys()) == MAINTENANCE_12_COMPONENTS

        close_resp = admin.post(
            f"/api/v1/ordenes/{ot_id}/cerrar",
            sede="montelibano",
            json_body={
                "sitio_arreglo": "Calle 14 # 8-22",
                "quien_recibe": "Representante Barrio",
                "requiere_desmonte": True,
                "causal_desmonte": "Luminaria dañada por sobrecarga",
                "luminaria_reemplazo_id": lum_rep["id"],
                "componentes": componentes,
                "materiales": [{"material_id": mat_id, "cantidad": 4}],
                "evidencias": [
                    {"archivo_id": ev_photo.json()["id"], "tipo": "foto"},
                    {"archivo_id": ev_sign.json()["id"], "tipo": "firma"},
                ],
            },
        )
        assert close_resp.status_code == 200, close_resp.text
        assert _estado_codigo(close_resp.json()) == "203"

        # 5. Atomic kardex deduction & movement recorded
        mat_after = admin.get(f"/api/v1/materiales/{mat_id}", sede="montelibano").json()
        assert float(mat_after["existencias"]) == 16.0
        kardex_items = _extract_items(
            admin.get(f"/api/v1/materiales/{mat_id}/movimientos", sede="montelibano").json()
        )
        assert any(
            str(m.get("tipo")) == "salida" and str(m.get("orden_id")) == str(ot_id)
            for m in kardex_items
        ), f"Expected kardex salida linked to orden_id={ot_id}, got {kardex_items}"

        # 6. Replacement luminaire activated (121) & timelines updated
        rep_after = admin.get(f"/api/v1/luminarias/{lum_rep['id']}", sede="montelibano").json()
        assert _estado_codigo(rep_after) == "121"

        hist_old = admin.get(
            f"/api/v1/luminarias/{lum_old['id']}/historial", sede="montelibano"
        ).json()
        assert len(hist_old.get("eventos", [])) >= 2
        assert any(str(p.get("id")) == str(pqrs_id) for p in hist_old.get("pqrs", []))
        assert any(str(o.get("id")) == str(ot_id) for o in hist_old.get("ordenes", []))

        hist_rep = admin.get(
            f"/api/v1/luminarias/{lum_rep['id']}/historial", sede="montelibano"
        ).json()
        assert len(hist_rep.get("eventos", [])) >= 1

        # 7. PQRS auto-closed (303) & Procrastinate email job queued with primitive IDs ONLY
        pqrs_after = admin.get(f"/api/v1/pqrs/{pqrs_id}", sede="montelibano").json()
        assert _estado_codigo(pqrs_after) == "303"

        email_job = db_helper.fetch_one(
            """
            SELECT id, task_name, args
            FROM procrastinate_jobs
            WHERE id > %s
              AND (task_name ILIKE '%%correo%%' OR task_name ILIKE '%%mail%%'
                   OR task_name ILIKE '%%pqrs%%' OR task_name ILIKE '%%notif%%')
              AND args::text LIKE %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (max_job_before_close, f"%{pqrs_id}%"),
        )
        assert email_job is not None, (
            f"Expected Procrastinate email notification job for auto-closed PQRS {pqrs_id}"
        )
        job_args = db_helper.get_procrastinate_job_args(int(email_job["id"]))
        _assert_primitive_ids_only_no_pii(job_args, citizen["_pii_markers"])

        # 8. Tablero recalculate + operational/PQRS summary check
        sedes = _extract_items(admin.get("/api/v1/sedes", omit_sede=True).json())
        mtl_id = next(s["id"] for s in sedes if s.get("codigo") == "montelibano")
        recalc = admin.post(
            "/api/v1/tablero/recalcular",
            sede="montelibano",
            json_body={"sede_id": mtl_id},
        )
        assert recalc.status_code == 202, recalc.text
        tarea_id = int(
            recalc.json().get("tareaId")
            or recalc.json().get("tarea_id")
            or recalc.json().get("id")
        )
        db_helper.wait_for_procrastinate_job(tarea_id, timeout=e2e_config.timeout_seconds)

        t0 = time.perf_counter()
        tablero_resp = admin.get("/api/v1/tablero/resumen", sede="montelibano")
        elapsed = time.perf_counter() - t0
        assert tablero_resp.status_code == 200, tablero_resp.text
        assert elapsed < 2.0
        tablero = tablero_resp.json()
        assert "operacion" in tablero or "pqrs" in tablero or "pqrs_semaforo" in tablero
    finally:
        admin.patch(f"/api/v1/usuarios/{tec['id']}", omit_sede=True, json_body={"activo": False})


def test_t3_multi_luminaire_pqrs_stays_open_until_all_repaired_then_autoclose(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """Multi-luminaire PQRS remains open until all linked pqrs_luminaria are repaired -> 303."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tec = _create_technician(admin, run_id, "t3multi", sede="montelibano")
    try:
        tag = uuid.uuid4().hex[:6].upper()
        lum1 = _create_luminaire(admin, f"{run_id}-M1-{tag}", estado_codigo="121", seed=111)
        lum2 = _create_luminaire(admin, f"{run_id}-M2-{tag}", estado_codigo="121", seed=112)
        citizen = _create_citizen(admin, run_id=run_id, suffix=tag, sede="montelibano")
        canal_id = _resolve_maestro_id(admin, "CANAL_PQRS", "PRESENCIAL")

        pqrs_resp = admin.post(
            "/api/v1/pqrs",
            sede="montelibano",
            json_body={
                "canal_id": canal_id,
                "ciudadano_id": citizen["id"],
                "prioridad": 1,
                "observacion_solicitante": f"Dos luminarias apagadas {run_id}",
                "notificar_cliente": True,
                "luminarias": [
                    {"luminaria_id": lum1["id"], "observacion_solicitante": "Poste 1"},
                    {"luminaria_id": lum2["id"], "observacion_solicitante": "Poste 2"},
                ],
            },
        )
        assert pqrs_resp.status_code == 201, pqrs_resp.text
        pqrs_id = pqrs_resp.json()["id"]

        for lum in (lum1, lum2):
            state = _estado_codigo(
                admin.get(f"/api/v1/luminarias/{lum['id']}", sede="montelibano").json()
            )
            assert state == "122"

        # Repair ONLY lum1 via OT #1
        ot1_id = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 1,
                "pqrs_id": pqrs_id,
                "luminarias": [{"luminaria_id": lum1["id"], "rol": "intervenida"}],
            },
        ).json()["id"]
        assert (
            admin.post(
                f"/api/v1/ordenes/{ot1_id}/asignar",
                sede="montelibano",
                json_body={"tecnico_id": tec["id"]},
            ).status_code
            in (200, 202)
        )
        close1 = admin.post(
            f"/api/v1/ordenes/{ot1_id}/cerrar",
            sede="montelibano",
            json_body={
                "sitio_arreglo": "Tramo A",
                "quien_recibe": "Vecino 1",
                "requiere_desmonte": False,
                "componentes": build_maintenance_components(all_ok=True),
                "materiales": [],
                "evidencias": [],
            },
        )
        assert close1.status_code == 200, close1.text

        # Lum1 -> 121, Lum2 -> still 122, PQRS -> STILL OPEN (!= 303)
        assert (
            _estado_codigo(
                admin.get(f"/api/v1/luminarias/{lum1['id']}", sede="montelibano").json()
            )
            == "121"
        )
        assert (
            _estado_codigo(
                admin.get(f"/api/v1/luminarias/{lum2['id']}", sede="montelibano").json()
            )
            == "122"
        )
        pqrs_mid = admin.get(f"/api/v1/pqrs/{pqrs_id}", sede="montelibano").json()
        assert _estado_codigo(pqrs_mid) != "303", (
            f"Multi-luminaire PQRS closed prematurely with lum2 unrepaired: {pqrs_mid}"
        )

        # Verify lum2 still on pendientes semaphore board
        pend_items = _extract_items(
            admin.get("/api/v1/pqrs/pendientes", sede="montelibano", params={"size": 100}).json()
        )
        assert any(
            (item.get("luminaria_id") == lum2["id"] or (item.get("luminaria") or {}).get("id") == lum2["id"])
            for item in pend_items
        )

        max_job_before_second = int(
            db_helper.scalar("SELECT COALESCE(MAX(id), 0) FROM procrastinate_jobs") or 0
        )

        # Now repair lum2 via OT #2 -> PQRS auto-closes (303)
        ot2_id = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 1,
                "pqrs_id": pqrs_id,
                "luminarias": [{"luminaria_id": lum2["id"], "rol": "intervenida"}],
            },
        ).json()["id"]
        assert (
            admin.post(
                f"/api/v1/ordenes/{ot2_id}/asignar",
                sede="montelibano",
                json_body={"tecnico_id": tec["id"]},
            ).status_code
            in (200, 202)
        )
        close2 = admin.post(
            f"/api/v1/ordenes/{ot2_id}/cerrar",
            sede="montelibano",
            json_body={
                "sitio_arreglo": "Tramo B",
                "quien_recibe": "Vecino 2",
                "requiere_desmonte": False,
                "componentes": build_maintenance_components(all_ok=True),
                "materiales": [],
                "evidencias": [],
            },
        )
        assert close2.status_code == 200, close2.text

        assert (
            _estado_codigo(
                admin.get(f"/api/v1/luminarias/{lum2['id']}", sede="montelibano").json()
            )
            == "121"
        )
        pqrs_final = admin.get(f"/api/v1/pqrs/{pqrs_id}", sede="montelibano").json()
        assert _estado_codigo(pqrs_final) == "303"
        assert all(bool(item.get("reparada")) for item in pqrs_final.get("luminarias", []))

        email_job = db_helper.fetch_one(
            """
            SELECT id, args
            FROM procrastinate_jobs
            WHERE id > %s
              AND (task_name ILIKE '%%correo%%' OR task_name ILIKE '%%mail%%'
                   OR task_name ILIKE '%%pqrs%%' OR task_name ILIKE '%%notif%%')
              AND args::text LIKE %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (max_job_before_second, f"%{pqrs_id}%"),
        )
        assert email_job is not None, "Expected auto-close email job once all luminaires repaired"
        _assert_primitive_ids_only_no_pii(
            db_helper.get_procrastinate_job_args(int(email_job["id"])),
            citizen["_pii_markers"],
        )
    finally:
        admin.patch(f"/api/v1/usuarios/{tec['id']}", omit_sede=True, json_body={"activo": False})


def test_t3_kardex_insufficient_stock_rollback_keeps_pqrs_open_and_prevents_email(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """Insufficient stock mid-close rolls back material #1, keeps PQRS open (122), prevents email."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tec = _create_technician(admin, run_id, "t3roll", sede="montelibano")
    try:
        tag = uuid.uuid4().hex[:6].upper()
        mat1 = admin.post(
            "/api/v1/materiales",
            sede="montelibano",
            json_body={
                "categoria": "ELECTRICO",
                "codigo": f"{run_id}-RBM1-{tag}",
                "descripcion": "Material suficiente rollback",
                "unidad": "UND",
                "existencias": 15,
                "existencias_minimas": 2,
            },
        ).json()
        mat2 = admin.post(
            "/api/v1/materiales",
            sede="montelibano",
            json_body={
                "categoria": "ELECTRICO",
                "codigo": f"{run_id}-RBM2-{tag}",
                "descripcion": "Material insuficiente rollback",
                "unidad": "UND",
                "existencias": 2,
                "existencias_minimas": 1,
            },
        ).json()

        lum = _create_luminaire(admin, f"{run_id}-RBL-{tag}", estado_codigo="121", seed=121)
        citizen = _create_citizen(admin, run_id=run_id, suffix=tag, sede="montelibano")
        canal_id = _resolve_maestro_id(admin, "CANAL_PQRS", "TELEFONO")

        pqrs_id = admin.post(
            "/api/v1/pqrs",
            sede="montelibano",
            json_body={
                "canal_id": canal_id,
                "ciudadano_id": citizen["id"],
                "prioridad": 1,
                "observacion_solicitante": f"Falla con rollback {run_id}",
                "notificar_cliente": True,
                "luminarias": [{"luminaria_id": lum["id"]}],
            },
        ).json()["id"]

        ot_id = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "mantenimiento",
                "prioridad": 1,
                "pqrs_id": pqrs_id,
                "luminarias": [{"luminaria_id": lum["id"], "rol": "intervenida"}],
            },
        ).json()["id"]
        assert (
            admin.post(
                f"/api/v1/ordenes/{ot_id}/asignar",
                sede="montelibano",
                json_body={"tecnico_id": tec["id"]},
            ).status_code
            in (200, 202)
        )

        max_job_before_close = int(
            db_helper.scalar("SELECT COALESCE(MAX(id), 0) FROM procrastinate_jobs") or 0
        )

        fail_close = admin.post(
            f"/api/v1/ordenes/{ot_id}/cerrar",
            sede="montelibano",
            json_body={
                "sitio_arreglo": "Calle Rollback T3",
                "quien_recibe": "Vecino",
                "requiere_desmonte": False,
                "componentes": build_maintenance_components(all_ok=True),
                "materiales": [
                    {"material_id": mat1["id"], "cantidad": 5},
                    {"material_id": mat2["id"], "cantidad": 10},
                ],
                "evidencias": [],
            },
        )
        assert_problem_json(fail_close, expected_status=409)

        # Material stocks untouched
        m1_after = admin.get(f"/api/v1/materiales/{mat1['id']}", sede="montelibano").json()
        m2_after = admin.get(f"/api/v1/materiales/{mat2['id']}", sede="montelibano").json()
        assert float(m1_after["existencias"]) == 15.0
        assert float(m2_after["existencias"]) == 2.0

        # OT remains 202, luminaire remains 122, PQRS remains open (!= 303)
        assert (
            _estado_codigo(admin.get(f"/api/v1/ordenes/{ot_id}", sede="montelibano").json())
            == "202"
        )
        assert (
            _estado_codigo(
                admin.get(f"/api/v1/luminarias/{lum['id']}", sede="montelibano").json()
            )
            == "122"
        )
        pqrs_after = admin.get(f"/api/v1/pqrs/{pqrs_id}", sede="montelibano").json()
        assert _estado_codigo(pqrs_after) != "303"
        assert all(not bool(item.get("reparada")) for item in pqrs_after.get("luminarias", []))

        # Zero new email/PQRS jobs enqueued by failed close
        leaked_email_jobs = int(
            db_helper.scalar(
                """
                SELECT COUNT(*)
                FROM procrastinate_jobs
                WHERE id > %s
                  AND args::text LIKE %s
                """,
                (max_job_before_close, f"%{pqrs_id}%"),
            )
            or 0
        )
        assert leaked_email_jobs == 0, (
            "Failed OT close due to insufficient stock must not enqueue PQRS email job"
        )
    finally:
        admin.patch(f"/api/v1/usuarios/{tec['id']}", omit_sede=True, json_body={"activo": False})
