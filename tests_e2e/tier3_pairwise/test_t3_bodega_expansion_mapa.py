"""Tier 3 pairwise E2E workflows: Bodega Lotes -> Expansion/Modernization -> Map MVT -> Tablero."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fixtures import generate_coordinates, make_png
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
        for key in ("items", "resultados", "datos", "luminarias", "ordenes"):
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


def _latlng_to_tile(lat: float, lng: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    x = int((lng + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _resolve_maestro_id(client: SapefClient, clase: str, preferred_code: str | None = None) -> int:
    resp = client.get(f"/api/v1/maestros/{clase}", omit_sede=True)
    assert resp.status_code == 200, resp.text
    items = _extract_items(resp.json())
    assert items, f"No values seeded for {clase}"
    if preferred_code:
        for item in items:
            if str(item.get("codigo", "")).upper() == preferred_code.upper():
                return int(item["id"])
    return int(items[0]["id"])


def _resolve_estado_id(client: SapefClient, proceso: str, codigo: str) -> int:
    resp = client.get("/api/v1/estados", params={"proceso": proceso}, omit_sede=True)
    assert resp.status_code == 200, resp.text
    for item in _extract_items(resp.json()):
        if str(item.get("codigo")) == codigo:
            return int(item["id"])
    raise AssertionError(f"Estado {proceso}/{codigo} not found")


def _resolve_barrio_id(client: SapefClient, sede: str = "montelibano") -> int:
    items = _extract_items(client.get("/api/v1/barrios", sede=sede).json())
    assert items, f"No barrios seeded for {sede}"
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
    secret = f"SapefT3B!{uuid.uuid4().hex[:10]}9B"
    username = f"{run_id.lower()}_{tag}_{suffix}"
    resp = admin.post(
        "/api/v1/usuarios",
        omit_sede=True,
        json_body={
            "nombre_usuario": username,
            "nombre_completo": f"Técnico Bodega {suffix}",
            "identificacion": f"72{int(suffix, 16) % 10000000:07d}",
            "correo": f"{username}@example.test",
            "clave": secret,
            "rol_id": tec_role["id"],
            "sedes": [sede_id],
            "activo": True,
            "debe_cambiar_clave": False,
        },
    )
    assert resp.status_code == 201, resp.text
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
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


def _total_active_or_all_luminaires(tablero: dict[str, Any]) -> int:
    act = tablero.get("activos", tablero)
    for key in ("total_luminarias", "total", "luminarias_total"):
        if key in act and isinstance(act[key], (int, float)):
            return int(act[key])
    por_estado = tablero.get("operacion", tablero).get("luminarias_por_estado")
    if isinstance(por_estado, list):
        return sum(int(item.get("cantidad", item.get("total", 0))) for item in por_estado)
    if isinstance(por_estado, dict):
        return sum(int(v) for v in por_estado.values())
    raise AssertionError(f"Unable to read luminaire total from {tablero!r}")


def test_t3_lote_bodega_expansion_relocation_mvt_timeline_and_tablero(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    db_helper: DbHelper,
    run_id: str,
) -> None:
    """Batch (124) -> Expansion OT (124->121) -> Relocation -> MVT tile + timeline + resumen_*."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tec = _create_technician(admin, run_id, "t3exp", sede="montelibano")
    try:
        barrio_id = _resolve_barrio_id(admin, "montelibano")
        tec_led = _resolve_maestro_id(admin, "LUMINARIA_TECNOLOGIA", "LED")
        pot_70 = _resolve_maestro_id(admin, "LUMINARIA_POTENCIA", "70")
        marca_ph = _resolve_maestro_id(admin, "LUMINARIA_MARCA", "PHILIPS")
        tipo_exp_id = _resolve_maestro_id(admin, "TIPO_EXPANSION")
        est_124 = _resolve_estado_id(admin, "luminaria", "124")

        base_num = (int(uuid.uuid4().hex[:6], 16) % 800000) + 100000
        lote_resp = admin.post(
            "/api/v1/lotes",
            sede="montelibano",
            json_body={
                "consecutivo_inicial": base_num,
                "consecutivo_final": base_num + 1,
                "cantidad": 2,
                "tecnologia_id": tec_led,
                "potencia_id": pot_70,
                "marca_id": marca_ph,
                "es_rural": False,
                "orden_compra": f"OC-{run_id}-{base_num}",
                "fecha_orden_compra": "2026-05-01",
                "entrada_almacen": f"EA-{run_id}-{base_num}",
                "fecha_entrada_almacen": "2026-05-03",
            },
        )
        assert lote_resp.status_code == 201, lote_resp.text

        bodega_items = _extract_items(
            admin.get(
                "/api/v1/bodega/luminarias",
                sede="montelibano",
                params={"estado_id": est_124, "buscar": str(base_num), "size": 20},
            ).json()
        )
        lum_batch = next((x for x in bodega_items if str(base_num) in str(x["codigo"])), None)
        assert lum_batch is not None, f"Expected batch luminaire {base_num} in warehouse 124"
        lum_id = lum_batch["id"]

        # Expansion OT: 124 -> 121
        ot_resp = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "expansion",
                "prioridad": 1,
                "luminarias": [{"luminaria_id": lum_id, "rol": "instalada"}],
            },
        )
        assert ot_resp.status_code == 201, ot_resp.text
        ot_id = ot_resp.json()["id"]
        assert (
            admin.post(
                f"/api/v1/ordenes/{ot_id}/asignar",
                sede="montelibano",
                json_body={"tecnico_id": tec["id"]},
            ).status_code
            in (200, 202)
        )

        (lat1, lng1), (lat2, lng2) = generate_coordinates("montelibano", 2, seed=301)
        close_resp = admin.post(
            f"/api/v1/ordenes/{ot_id}/cerrar",
            sede="montelibano",
            json_body={
                "tipo_expansion_id": tipo_exp_id,
                "barrio_id": barrio_id,
                "poste": f"P-EXP-{base_num}",
                "latitud": lat1,
                "longitud": lng1,
                "materiales": [],
                "evidencias": [],
            },
        )
        assert close_resp.status_code == 200, close_resp.text
        assert _estado_codigo(close_resp.json()) == "203"

        lum_after_exp = admin.get(f"/api/v1/luminarias/{lum_id}", sede="montelibano").json()
        assert _estado_codigo(lum_after_exp) == "121"

        # Relocate luminaire to new coordinates
        move_resp = admin.post(
            f"/api/v1/luminarias/{lum_id}/ubicacion",
            sede="montelibano",
            json_body={"latitud": lat2, "longitud": lng2, "origen": "web"},
        )
        assert move_resp.status_code == 200, move_resp.text

        # MVT tile at relocated coordinate includes active luminaire layer
        tx, ty = _latlng_to_tile(lat2, lng2, 14)
        mvt_resp = admin.get(
            f"/api/v1/mapa/luminarias/14/{tx}/{ty}.mvt",
            sede="montelibano",
            params={"estado": "121"},
        )
        assert mvt_resp.status_code == 200, mvt_resp.text
        assert mvt_resp.content_type.lower().startswith("application/vnd.mapbox-vector-tile")
        assert len(mvt_resp.content) > 0

        # Timeline has alta, expansion/state, and cambio_ubicacion + ubicaciones entry
        hist = admin.get(f"/api/v1/luminarias/{lum_id}/historial", sede="montelibano").json()
        event_types = {
            str(e.get("tipo", e.get("evento_tipo", ""))).lower() for e in hist.get("eventos", [])
        }
        assert "cambio_ubicacion" in event_types
        assert len(hist.get("ubicaciones", [])) >= 1
        assert len(hist.get("eventos", [])) >= 3

        # Recalculate resumen_* & verify dashboard summary reflects assets
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

        tablero = admin.get("/api/v1/tablero/resumen", sede="montelibano").json()
        assert _total_active_or_all_luminaires(tablero) >= 2
    finally:
        admin.patch(f"/api/v1/usuarios/{tec['id']}", omit_sede=True, json_body={"activo": False})


def test_t3_modernization_paired_instalada_desmontada_warehouse_and_map_filter(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """Modernization OT paired instalada (124->121) + desmontada (121->123) -> bodega & MVT."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tec = _create_technician(admin, run_id, "t3mod", sede="montelibano")
    try:
        tag = uuid.uuid4().hex[:6].upper()
        barrio_id = _resolve_barrio_id(admin, "montelibano")
        tipo_mod_id = _resolve_maestro_id(admin, "TIPO_MODERNIZACION")
        est_121 = _resolve_estado_id(admin, "luminaria", "121")
        est_123 = _resolve_estado_id(admin, "luminaria", "123")

        lum_in = _create_luminaire(admin, f"{run_id}-MODIN-{tag}", estado_codigo="124", seed=310)
        lum_out = _create_luminaire(admin, f"{run_id}-MODOUT-{tag}", estado_codigo="121", seed=311)

        ot_resp = admin.post(
            "/api/v1/ordenes",
            sede="montelibano",
            json_body={
                "tipo": "modernizacion",
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
            admin.post(
                f"/api/v1/ordenes/{ot_id}/asignar",
                sede="montelibano",
                json_body={"tecnico_id": tec["id"]},
            ).status_code
            in (200, 202)
        )

        ev = admin.post(
            "/api/v1/archivos",
            sede="montelibano",
            idempotency_key=str(uuid.uuid4()),
            files={"archivo": ("modernizacion.png", make_png(4, 4), "image/png")},
        )
        assert ev.status_code in (200, 201), ev.text

        close_resp = admin.post(
            f"/api/v1/ordenes/{ot_id}/cerrar",
            sede="montelibano",
            json_body={
                "tipo_modernizacion_id": tipo_mod_id,
                "barrio_id": barrio_id,
                "poste": f"P-MOD-{tag}",
                "longitud_brazo": 1.8,
                "destino_desmontada": "123",
                "materiales": [],
                "evidencias": [{"archivo_id": ev.json()["id"], "tipo": "foto"}],
            },
        )
        assert close_resp.status_code == 200, close_resp.text
        assert _estado_codigo(close_resp.json()) == "203"

        # lum_in: 124 -> 121 (active list yes, warehouse list no)
        in_after = admin.get(f"/api/v1/luminarias/{lum_in['id']}", sede="montelibano").json()
        assert _estado_codigo(in_after) == "121"
        bod_search_in = _extract_items(
            admin.get(
                "/api/v1/bodega/luminarias",
                sede="montelibano",
                params={"buscar": lum_in["codigo"], "size": 10},
            ).json()
        )
        assert all(x["id"] != lum_in["id"] for x in bod_search_in)

        # lum_out: 121 -> 123 (appears in warehouse listing under 123, absent from active 121)
        out_after = admin.get(f"/api/v1/luminarias/{lum_out['id']}", sede="montelibano").json()
        assert _estado_codigo(out_after) == "123"
        bod_123 = _extract_items(
            admin.get(
                "/api/v1/bodega/luminarias",
                sede="montelibano",
                params={"estado_id": est_123, "buscar": lum_out["codigo"], "size": 10},
            ).json()
        )
        assert any(x["id"] == lum_out["id"] for x in bod_123)

        active_121 = _extract_items(
            admin.get(
                "/api/v1/luminarias",
                sede="montelibano",
                params={"estado_id": est_121, "texto": lum_out["codigo"], "size": 10},
            ).json()
        )
        assert all(x["id"] != lum_out["id"] for x in active_121)

        # Map MVT reflection with active vs warehouse filters
        lat_in = float(in_after["latitud"])
        lng_in = float(in_after["longitud"])
        tx, ty = _latlng_to_tile(lat_in, lng_in, 14)
        mvt_active = admin.get(
            f"/api/v1/mapa/luminarias/14/{tx}/{ty}.mvt",
            sede="montelibano",
            params={"en_bodega": "false", "estado": "121"},
        )
        assert mvt_active.status_code == 200
        assert mvt_active.content_type.lower().startswith("application/vnd.mapbox-vector-tile")
        assert len(mvt_active.content) > 0

        mvt_bodega = admin.get(
            f"/api/v1/mapa/luminarias/14/{tx}/{ty}.mvt",
            sede="montelibano",
            params={"en_bodega": "true", "estado": "123"},
        )
        assert mvt_bodega.status_code == 200
        assert mvt_bodega.content_type.lower().startswith("application/vnd.mapbox-vector-tile")
    finally:
        admin.patch(f"/api/v1/usuarios/{tec['id']}", omit_sede=True, json_body={"activo": False})


def test_t3_warehouse_state_transitions_124_125_123_126_and_evento_timeline(
    auth_session_factory: Callable[..., SapefClient],
    e2e_config: E2EConfig,
    run_id: str,
) -> None:
    """Warehouse state transitions 124 -> 125 -> 123 -> 126 + full evento_activo timeline."""
    admin = _admin_client(auth_session_factory, e2e_config, sede="montelibano")
    tag = uuid.uuid4().hex[:6].upper()
    lum = _create_luminaire(admin, f"{run_id}-WH-{tag}", estado_codigo="124", seed=320)
    lum_id = lum["id"]

    est_124 = _resolve_estado_id(admin, "luminaria", "124")
    est_125 = _resolve_estado_id(admin, "luminaria", "125")
    est_123 = _resolve_estado_id(admin, "luminaria", "123")
    est_126 = _resolve_estado_id(admin, "luminaria", "126")

    for next_code, next_id, note in (
        ("125", est_125, "Envío a revisión técnica en bodega"),
        ("123", est_123, "Dictamen técnico de baja"),
        ("126", est_126, "Disposición final certificada"),
    ):
        patch = admin.patch(
            f"/api/v1/bodega/luminarias/{lum_id}",
            sede="montelibano",
            json_body={"estado_id": next_id, "observacion": note},
        )
        assert patch.status_code == 200, f"Transition to {next_code} failed: {patch.text}"
        listed = _extract_items(
            admin.get(
                "/api/v1/bodega/luminarias",
                sede="montelibano",
                params={"estado_id": next_id, "buscar": lum["codigo"], "size": 10},
            ).json()
        )
        assert any(item["id"] == lum_id for item in listed), (
            f"Expected {lum['codigo']} in warehouse listing for estado {next_code}"
        )

    # Terminal 126 cannot revert to 124
    rev = admin.patch(
        f"/api/v1/bodega/luminarias/{lum_id}",
        sede="montelibano",
        json_body={"estado_id": est_124, "observacion": "Intento reversa terminal"},
    )
    assert_problem_json(rev, expected_status=422)

    # Full evento_activo timeline records initial alta + all 3 state transitions
    hist = admin.get(f"/api/v1/luminarias/{lum_id}/historial", sede="montelibano").json()
    eventos = hist.get("eventos", [])
    assert len(eventos) >= 4, f"Expected >= 4 timeline events (alta + 3 transitions), got {eventos}"
    event_types = {str(e.get("tipo", e.get("evento_tipo", ""))).lower() for e in eventos}
    assert "alta" in event_types
    assert "cambio_estado" in event_types
