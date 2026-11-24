"""Integración de la Fase 5 (EP-09) contra PostgreSQL: tablas resumen por sede y consolidado,
permisos del consolidado, coherencia con el informe comercial y recálculo por la cola."""

import datetime as dt
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modulos.tablero import servicio as tablero
from tests.conftest import crear_usuario_db, iniciar_sesion_cliente
from tests.integration import test_fase2_api as f2
from tests.integration import test_fase4_comercial_api as f4

# Fixtures de las fases 2 y 4, reutilizadas tal cual.
admin = f2.admin
cat = f2.cat
almacen_comercial = f4.almacen_comercial
AL, MT = f2.AL, f2.MT
_luminaria, _pqrs = f2._luminaria, f2._pqrs
_cargar, _vatia = f4._cargar, f4._vatia


def _sede_id(db: Session, codigo: str) -> int:
    return db.execute(text("SELECT id FROM sede WHERE codigo = :c"), {"c": codigo}).scalar_one()


def _recalcular(db: Session, *codigos: str) -> None:
    for c in codigos:
        tablero.recalcular_sede(db, _sede_id(db, c))


def _usuario_con_permisos(
    db: Session, cliente: TestClient, nombre: str, permisos: list[str], sedes: list[str]
) -> TestClient:
    db.execute(
        text(
            "INSERT INTO rol (codigo, nombre, activo) VALUES (:c, :c, true) ON CONFLICT DO NOTHING"
        ),
        {"c": f"ROL_{nombre.upper()}"},
    )
    db.execute(
        text(
            "INSERT INTO rol_permiso (rol_id, permiso_id) SELECT r.id, p.id FROM rol r, permiso p"
            " WHERE r.codigo = :r AND p.codigo = ANY(:p) ON CONFLICT DO NOTHING"
        ),
        {"r": f"ROL_{nombre.upper()}", "p": permisos},
    )
    db.commit()
    crear_usuario_db(
        db,
        nombre_usuario=nombre,
        correo=f"{nombre}@sapef.test",
        rol_codigo=f"ROL_{nombre.upper()}",
        sede_codigos=sedes,
    )
    cliente.cookies.clear()
    iniciar_sesion_cliente(cliente, nombre)
    return cliente


def test_resumen_por_sede_y_consolidado(
    admin: TestClient, cat: dict[str, Any], db_configurado: Session
) -> None:
    anio = dt.date.today().year
    for codigo, mes in (("T-1", 2), ("T-2", 2), ("T-3", 5)):
        r = admin.patch(
            f"/api/v1/luminarias/{_luminaria(admin, cat, codigo)['id']}",
            headers=MT,
            json={"fecha_instalacion": f"{anio}-{mes:02d}-10"},
        )
        assert r.status_code == 200, r.text
    _luminaria(admin, cat, "T-BOD", estado="124")
    _luminaria(admin, cat, "T-AL", sede=AL, lat=3.9, lng=-76.0)
    _pqrs(admin, cat, [_luminaria(admin, cat, "T-PQR")["id"]])
    _recalcular(db_configurado, "montelibano", "alcala")

    mt = admin.get("/api/v1/tablero/resumen", headers=MT)
    assert mt.status_code == 200, mt.text
    cuerpo = mt.json()
    assert cuerpo["sede"] == "montelibano"
    act, op = cuerpo["activos"], cuerpo["operacion"]
    assert act["total_luminarias"] == 5 and act["en_bodega"] == 1 and act["en_servicio"] == 4
    meses = {m["mes"]: m for m in act["luminarias_instaladas_mes"]}
    assert len(meses) == 12 and meses[2]["cantidad"] == 2 and meses[5]["acumulado"] == 3
    assert act["instaladas_anio"] == 3
    assert {t["etiqueta"].upper(): t["cantidad"] for t in act["por_tecnologia"]}["LED"] == 4
    assert sum(b["cantidad"] for b in act["por_barrio"]) == 4  # la de bodega no tiene sector
    assert op["pqrs_abiertas"] == 1 and op["pqrs_semaforo"]["verde"] == 1
    assert op["pqrs_por_barrio"][0]["etiqueta"] == cat["barrio_nombre"]
    estados = {e["etiqueta"][:3]: e["cantidad"] for e in op["luminarias_por_estado"]}
    assert estados["122"] == 1 and estados["124"] == 1
    assert cuerpo["comercial"]["estado"] == "sin_cortes_cargados"

    todas = admin.get("/api/v1/tablero/resumen", params={"sede": "todas"}).json()
    assert todas["sede"] == "todas"
    assert {s["codigo"] for s in todas["sedes_incluidas"]} == {"montelibano", "alcala"}
    assert todas["activos"]["total_luminarias"] == 6
    assert {p["sede"]["codigo"]: p["total_luminarias"] for p in todas["por_sede"]} == {
        "montelibano": 5,
        "alcala": 1,
    }
    # En el consolidado los barrios llevan la sede: nunca se mezclan los de dos municipios.
    assert all(" · " in (b["grupo"] or "") for b in todas["activos"]["por_barrio"])


def test_primera_consulta_sin_calculo_y_permisos_del_consolidado(
    admin: TestClient, cat: dict[str, Any], db_configurado: Session
) -> None:
    _luminaria(admin, cat, "P-1")
    # Sin recalcular: la primera consulta calcula lo operativo en el acto.
    r = admin.get("/api/v1/tablero/resumen", headers=MT)
    assert r.status_code == 200 and r.json()["activos"]["total_luminarias"] == 1
    assert r.json()["calculado_en"] is not None

    lector = _usuario_con_permisos(
        db_configurado, admin, "gte_mt", ["tablero.ver"], ["montelibano", "alcala"]
    )
    assert lector.get("/api/v1/tablero/resumen", headers=MT).status_code == 200
    assert lector.get("/api/v1/tablero/resumen", params={"sede": "todas"}).status_code == 403
    assert lector.post("/api/v1/tablero/recalcular", json={}).status_code == 403

    solo_mt = _usuario_con_permisos(
        db_configurado,
        admin,
        "cons_mt",
        ["tablero.ver", "tablero.consolidado.ver"],
        ["montelibano"],
    )
    assert solo_mt.get("/api/v1/tablero/resumen", headers=AL).status_code == 403
    assert solo_mt.get("/api/v1/tablero/resumen", params={"sede": "alcala"}).status_code == 403
    todas = solo_mt.get("/api/v1/tablero/resumen", params={"sede": "todas"}).json()
    assert [s["codigo"] for s in todas["sedes_incluidas"]] == ["montelibano"]
    otra = solo_mt.post(
        "/api/v1/tablero/recalcular", json={"sede_id": _sede_id(db_configurado, "alcala")}
    )
    assert otra.status_code == 403

    sin_permiso = _usuario_con_permisos(
        db_configurado, admin, "sin_tab", ["activos.luminaria.ver"], ["montelibano"]
    )
    assert sin_permiso.get("/api/v1/tablero/resumen", headers=MT).status_code == 403


def test_recalcular_encola_solo_ids(admin: TestClient, db_configurado: Session) -> None:
    r = admin.post("/api/v1/tablero/recalcular", headers=MT, json={})
    assert r.status_code == 202, r.text
    cuerpo = r.json()
    assert cuerpo["tarea_id"] == cuerpo["tareaId"] and cuerpo["sede_ids"] == [
        _sede_id(db_configurado, "montelibano")
    ]
    tarea, args = db_configurado.execute(
        text("SELECT task_name, args FROM procrastinate_jobs WHERE id = :i"),
        {"i": cuerpo["tarea_id"]},
    ).one()
    assert tarea == "tablero.recalcular"
    assert args == {"sede_ids": str(_sede_id(db_configurado, "montelibano"))}
    # La tarea hace lo mismo que el worker.
    assert tablero.procesar_recalculo(db_configurado, args["sede_ids"]) == "sedes:1"
    todas = admin.post("/api/v1/tablero/recalcular", json={}).json()
    assert len(todas["sede_ids"]) == 2


def test_comercial_coherente_con_el_informe(
    admin: TestClient, db_configurado: Session, almacen_comercial
) -> None:
    dia = dt.date(2026, 6, 18)
    filas = [
        ["202606", "V1", "Industria", "Industrial", dia, 180000, 180000, 0, 0, "Al día"],
        ["202606", "V2", "Cero", "Comercial", dia, 50000, 0, 0, 45000, "30 días"],
    ]
    _cargar(admin, db_configurado, AL, "vatia", "202606", [_vatia("202606", filas)])
    _recalcular(db_configurado, "alcala")

    cuerpo = admin.get("/api/v1/tablero/resumen", headers=AL).json()
    com = cuerpo["comercial"]
    assert com["estado"] == "con_datos"
    vatia = next(c for c in com["comercializadores"] if c["comercializador"] == "vatia")
    assert vatia["periodo"] == "202606" and vatia["anterior"] is None
    kpi = admin.get("/api/v1/comercial/vatia/analisis/indicadores/202606", headers=AL).json()
    assert vatia["actual"]["facturacion"] == float(kpi["facturacion"]) == 230000.0
    assert vatia["actual"]["recaudo"] == float(kpi["recaudo"])
    assert vatia["actual"]["n_facturados"] == kpi["n_facturados"]
    assert [h["periodo"] for h in vatia["historico"]] == ["202606"]
    assert {p["grupo"] for p in vatia["participacion"]}
    # Montelíbano no tiene cortes: su consolidado con Alcalá sí muestra el de Alcalá.
    todas = admin.get("/api/v1/tablero/resumen", params={"sede": "todas"}).json()
    assert todas["comercial"]["estado"] == "con_datos"
    assert {c["sede_codigo"] for c in todas["comercial"]["comercializadores"]} == {"alcala"}
