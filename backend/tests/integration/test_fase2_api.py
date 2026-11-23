"""Integración de la Fase 2 contra PostgreSQL: PQRS, órdenes de trabajo e inventario."""

import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modulos.inventario import servicio as inventario_servicio
from app.modulos.seguridad import datos_semilla as semilla_seguridad
from app.modulos.trabajos import servicio as trabajos_servicio
from tests.conftest import crear_usuario_db, iniciar_sesion_cliente

MT = {"X-Sede": "montelibano"}
AL = {"X-Sede": "alcala"}
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
COMPONENTES = (
    "conexion_red",
    "conexion_interna",
    "base_fotocelda",
    "fotocelda",
    "bombillo",
    "socket",
    "arrancador",
    "condensador",
    "balasta",
    "tubo",
    "collarin",
    "conectores_perforacion",
)


# --- Ayudas ------------------------------------------------------------------------------------


@pytest.fixture
def admin(cliente: TestClient, db_configurado: Session) -> TestClient:
    # El conftest base crea un TECNICO mínimo y la semilla no toca roles existentes: aquí el
    # técnico recibe los permisos de la semilla real (§4.2).
    db_configurado.execute(
        text(
            "INSERT INTO rol_permiso (rol_id, permiso_id) SELECT r.id, p.id FROM rol r, permiso p"
            " WHERE r.codigo = 'TECNICO' AND p.codigo = ANY(:c) ON CONFLICT DO NOTHING"
        ),
        {"c": list(semilla_seguridad.ROLES["TECNICO"][2])},
    )
    db_configurado.commit()
    crear_usuario_db(
        db_configurado,
        nombre_usuario="admin_f2",
        correo="admin_f2@sapef.test",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano", "alcala"],
    )
    iniciar_sesion_cliente(cliente, "admin_f2")
    return cliente


@pytest.fixture
def cat(admin: TestClient) -> dict[str, Any]:
    def maestro(clase: str, codigo: str | None = None) -> int:
        valores = admin.get(f"/api/v1/maestros/{clase}").json()
        return next(v["id"] for v in valores if codigo is None or v["codigo"] == codigo)

    estados = {
        e["codigo"]: e["id"]
        for e in admin.get("/api/v1/estados", params={"proceso": "luminaria"}).json()
    }
    barrios = admin.get("/api/v1/barrios", headers=MT).json()
    zona_al = admin.post("/api/v1/zonas", headers=AL, json={"nombre": "Zona A"}).json()
    barrio_al = admin.post(
        "/api/v1/barrios", headers=AL, json={"zona_id": zona_al["id"], "nombre": "Barrio A"}
    ).json()
    return {
        "estado": estados,
        "barrio": next(b["id"] for b in barrios if b["nombre"] == "El Centro"),
        "barrio_nombre": "El Centro",
        "barrio_al": barrio_al["id"],
        "led": maestro("LUMINARIA_TECNOLOGIA", "LED"),
        "w70": maestro("LUMINARIA_POTENCIA", "70"),
        "canal": maestro("CANAL_PQRS", "WHATSAPP"),
        "tipo_exp": maestro("TIPO_EXPANSION", "COMPLEMENTARIA"),
        "tipo_mod": maestro("TIPO_MODERNIZACION", "PRIORITARIA"),
    }


def _luminaria(
    c: TestClient,
    cat: dict[str, Any],
    codigo: str,
    estado: str = "121",
    *,
    sede: dict = MT,
    lat: float = 7.98,
    lng: float = -75.42,
) -> dict[str, Any]:
    r = c.post(
        "/api/v1/luminarias",
        headers=sede,
        json={
            "codigo": codigo,
            "barrio_id": cat["barrio"] if sede is MT else cat["barrio_al"],
            "latitud": lat,
            "longitud": lng,
            "estado_id": cat["estado"][estado],
            "tecnologia_id": cat["led"],
            "potencia_id": cat["w70"],
            "poste": f"P-{codigo}",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _ciudadano(c: TestClient, ident: str, nombre: str = "Sofía Álvarez Ruiz") -> dict[str, Any]:
    r = c.post(
        "/api/v1/ciudadanos",
        headers=MT,
        json={
            "identificacion": ident,
            "nombre_completo": nombre,
            "telefono": "7729988",
            "celular": "3159876543",
            "correo": f"c{ident}@example.test",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _pqrs(
    c: TestClient,
    cat: dict[str, Any],
    lum_ids: list[int],
    ciudadano_id: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    r = c.post(
        "/api/v1/pqrs",
        headers=MT,
        json={
            "canal_id": cat["canal"],
            "ciudadano_id": ciudadano_id,
            "prioridad": 1,
            "observacion_solicitante": "Apagada",
            "luminarias": [{"luminaria_id": i} for i in lum_ids],
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _orden(c: TestClient, tipo: str, luminarias: list[tuple[int, str]], **extra: Any) -> dict:
    r = c.post(
        "/api/v1/ordenes",
        headers=MT,
        json={
            "tipo": tipo,
            "luminarias": [{"luminaria_id": i, "rol": rol} for i, rol in luminarias],
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _tecnico(db: Session, nombre: str, sede: str = "montelibano") -> int:
    return crear_usuario_db(
        db,
        nombre_usuario=nombre,
        correo=f"{nombre}@sapef.test",
        rol_codigo="TECNICO",
        sede_codigos=[sede],
    ).id


def _material(c: TestClient, codigo: str, existencias: int, minimas: int = 1) -> dict:
    r = c.post(
        "/api/v1/materiales",
        headers=MT,
        json={
            "categoria": "electrico",
            "codigo": codigo,
            "descripcion": f"Material {codigo}",
            "unidad": "und",
            "existencias": existencias,
            "existencias_minimas": minimas,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _estado(c: TestClient, ruta: str, sede: dict = MT) -> str:
    return c.get(ruta, headers=sede).json()["estado_codigo"]


def _cierre_mantenimiento(**extra: Any) -> dict[str, Any]:
    return {
        "sitio_arreglo": "Calle 10",
        "quien_recibe": "Presidente JAC",
        "componentes": dict.fromkeys(COMPONENTES, True),
        "materiales": [],
        "evidencias": [],
        **extra,
    }


def _jobs(db: Session, tarea: str) -> list[dict[str, Any]]:
    filas = db.execute(
        text("SELECT args FROM procrastinate_jobs WHERE task_name = :t ORDER BY id"), {"t": tarea}
    ).scalars()
    return [a if isinstance(a, dict) else json.loads(a) for a in filas]


def _xlsx(filas: list[list[Any]]) -> bytes:
    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    for fila in filas:
        hoja.append(fila)
    buf = io.BytesIO()
    libro.save(buf)
    return buf.getvalue()


# --- Hito de la Fase 2 ------------------------------------------------------------------


def test_hito_pqrs_orden_asignacion_y_cierre_con_materiales(
    admin: TestClient, cat: dict, db_configurado: Session
) -> None:
    lum = _luminaria(admin, cat, "H-1")
    ciudadano = _ciudadano(admin, "1067000001")
    pqrs = _pqrs(admin, cat, [lum["id"]], ciudadano["id"], notificar_cliente=True)
    assert (pqrs["estado_codigo"], pqrs["numero"], pqrs["canal_nombre"]) == ("301", 1, "WhatsApp")
    assert _estado(admin, f"/api/v1/luminarias/{lum['id']}") == "122"  # RN-011
    assert _jobs(db_configurado, "atencion.notificar_pqrs") == [
        {"pqrs_id": pqrs["id"], "evento": "registro"}
    ]

    orden = _orden(admin, "mantenimiento", [(lum["id"], "intervenida")], pqrs_id=pqrs["id"])
    assert (orden["estado_codigo"], orden["numero"]) == ("201", 1)
    assert _estado(admin, f"/api/v1/pqrs/{pqrs['id']}") == "302"

    tecnico_id = _tecnico(db_configurado, "tec_hito")
    asignada = admin.post(
        f"/api/v1/ordenes/{orden['id']}/asignar", headers=MT, json={"tecnico_id": tecnico_id}
    )
    assert asignada.status_code == 200, asignada.text
    assert (asignada.json()["estado_codigo"], asignada.json()["tecnico_id"]) == ("202", tecnico_id)
    assert _estado(admin, f"/api/v1/pqrs/{pqrs['id']}") == "305"
    # El aviso push solo lleva el id de la orden.
    assert _jobs(db_configurado, "trabajos.push_orden_asignada") == [{"orden_id": orden["id"]}]

    material = _material(admin, "FOTOCELDA", 20, 5)
    foto = admin.post(
        "/api/v1/archivos", headers=MT, files={"archivo": ("f.png", PNG, "image/png")}
    )
    assert foto.status_code == 201, foto.text
    cierre = admin.post(
        f"/api/v1/ordenes/{orden['id']}/cerrar",
        headers=MT,
        json=_cierre_mantenimiento(
            componentes={**dict.fromkeys(COMPONENTES, True), "fotocelda": False},
            materiales=[{"material_id": material["id"], "cantidad": 3}],
            evidencias=[{"archivo_id": foto.json()["id"], "tipo": "foto"}],
            latitud=7.981,
            longitud=-75.421,
            observacion_tecnica="Se cambió la fotocelda",
        ),
    )
    assert cierre.status_code == 200, cierre.text
    cerrada = cierre.json()
    assert cerrada["estado_codigo"] == "203"
    assert cerrada["mantenimiento"]["componentes"]["fotocelda"] is False
    assert [(m["material_codigo"], m["cantidad"]) for m in cerrada["materiales"]] == [
        ("FOTOCELDA", "3.000")
    ]
    assert [e["tipo"] for e in cerrada["evidencias"]] == ["foto"]
    assert (cerrada["latitud"], cerrada["longitud"]) == (7.981, -75.421)

    assert (
        admin.get(f"/api/v1/materiales/{material['id']}", headers=MT).json()["existencias"]
        == "17.000"
    )
    assert _estado(admin, f"/api/v1/luminarias/{lum['id']}") == "121"
    pqrs_final = admin.get(f"/api/v1/pqrs/{pqrs['id']}", headers=MT).json()
    assert (pqrs_final["estado_codigo"], pqrs_final["reparadas"]) == ("303", 1)
    assert pqrs_final["luminarias"][0]["observacion_tecnico"] == "Se cambió la fotocelda"
    assert _jobs(db_configurado, "atencion.notificar_pqrs")[-1] == {
        "pqrs_id": pqrs["id"],
        "evento": "atencion",
    }

    historial = admin.get(f"/api/v1/luminarias/{lum['id']}/historial", headers=MT).json()
    assert [p["id"] for p in historial["pqrs"]] == [pqrs["id"]]
    assert historial["pqrs"][0]["pqrs_numero"] == 1
    assert [(o["id"], o["orden_tipo"]) for o in historial["ordenes"]] == [
        (orden["id"], "mantenimiento")
    ]
    kardex = admin.get(f"/api/v1/materiales/{material['id']}/movimientos", headers=MT).json()
    assert [(m["tipo"], m["origen"], m["orden_id"]) for m in kardex["items"]] == [
        ("salida", "orden", orden["id"]),
        ("entrada", "inicial", None),
    ]


def test_cierre_atomico_si_falta_material(
    admin: TestClient, cat: dict, db_configurado: Session
) -> None:
    lum = _luminaria(admin, cat, "RB-1")
    pqrs = _pqrs(admin, cat, [lum["id"]])
    orden = _orden(admin, "mantenimiento", [(lum["id"], "intervenida")], pqrs_id=pqrs["id"])
    admin.post(
        f"/api/v1/ordenes/{orden['id']}/asignar",
        headers=MT,
        json={"tecnico_id": _tecnico(db_configurado, "tec_rb")},
    )
    m1, m2 = _material(admin, "M1", 10), _material(admin, "M2", 2)
    foto = admin.post(
        "/api/v1/archivos", headers=MT, files={"archivo": ("f.png", PNG, "image/png")}
    )
    r = admin.post(
        f"/api/v1/ordenes/{orden['id']}/cerrar",
        headers=MT,
        json=_cierre_mantenimiento(
            materiales=[
                {"material_id": m1["id"], "cantidad": 4},
                {"material_id": m2["id"], "cantidad": 5},
            ],
            evidencias=[{"archivo_id": foto.json()["id"], "tipo": "foto"}],
        ),
    )
    assert r.status_code == 409, r.text
    assert "M2" in r.json()["detail"]
    # Nada quedó a medias: materiales, orden, luminaria, PQRS ni evidencias.
    assert admin.get(f"/api/v1/materiales/{m1['id']}", headers=MT).json()["existencias"] == "10.000"
    detalle = admin.get(f"/api/v1/ordenes/{orden['id']}", headers=MT).json()
    assert (detalle["estado_codigo"], detalle["evidencias"], detalle["mantenimiento"]) == (
        "202",
        [],
        None,
    )
    assert _estado(admin, f"/api/v1/luminarias/{lum['id']}") == "122"
    assert _estado(admin, f"/api/v1/pqrs/{pqrs['id']}") == "305"


def test_mantenimiento_con_reemplazo_rn012(admin: TestClient, cat: dict) -> None:
    vieja = _luminaria(admin, cat, "V-1", lat=7.99, lng=-75.43)
    nueva = _luminaria(admin, cat, "N-1", "124", lat=7.5, lng=-75.0)
    orden = _orden(admin, "mantenimiento", [(vieja["id"], "intervenida")])
    r = admin.post(
        f"/api/v1/ordenes/{orden['id']}/cerrar",
        headers=MT,
        json=_cierre_mantenimiento(
            requiere_desmonte=True,
            causal_desmonte="Quemada",
            luminaria_reemplazo_id=nueva["id"],
            destino_desmontada="123",
        ),
    )
    assert r.status_code == 200, r.text
    assert {(x["luminaria_id"], x["rol"]) for x in r.json()["luminarias"]} == {
        (vieja["id"], "intervenida"),
        (nueva["id"], "instalada"),
    }
    nueva_final = admin.get(f"/api/v1/luminarias/{nueva['id']}", headers=MT).json()
    assert nueva_final["estado_codigo"] == "121"
    assert (nueva_final["latitud"], nueva_final["longitud"]) == (7.99, -75.43)
    assert nueva_final["luminaria_reemplazada_id"] == vieja["id"]
    assert nueva_final["poste"] == "P-V-1"
    assert _estado(admin, f"/api/v1/luminarias/{vieja['id']}") == "123"
    # Un reemplazo sin desmonte no tiene sentido.
    otra = _orden(admin, "mantenimiento", [(nueva["id"], "intervenida")])
    r = admin.post(
        f"/api/v1/ordenes/{otra['id']}/cerrar",
        headers=MT,
        json=_cierre_mantenimiento(luminaria_reemplazo_id=vieja["id"]),
    )
    assert r.status_code == 422


def test_expansion_modernizacion_y_reubicacion(admin: TestClient, cat: dict) -> None:
    bodega = _luminaria(admin, cat, "E-1", "124")
    exp = _orden(admin, "expansion", [(bodega["id"], "instalada")])
    sin_barrio = admin.post(
        f"/api/v1/ordenes/{exp['id']}/cerrar",
        headers=MT,
        json={"tipo_expansion_id": cat["tipo_exp"], "latitud": 8, "longitud": -75},
    )
    assert sin_barrio.status_code == 422
    r = admin.post(
        f"/api/v1/ordenes/{exp['id']}/cerrar",
        headers=MT,
        json={
            "tipo_expansion_id": cat["tipo_exp"],
            "barrio_id": cat["barrio"],
            "poste": "P-EXP",
            "latitud": 8.0,
            "longitud": -75.0,
        },
    )
    assert r.status_code == 200, r.text
    instalada = admin.get(f"/api/v1/luminarias/{bodega['id']}", headers=MT).json()
    assert (instalada["estado_codigo"], instalada["latitud"], instalada["poste"]) == (
        "121",
        8.0,
        "P-EXP",
    )
    assert instalada["fecha_instalacion"] is not None

    for tipo, destino in (("modernizacion", "124"), ("reubicacion", "112")):
        nueva = _luminaria(admin, cat, f"{tipo}-IN", "124", lat=7.0, lng=-74.0)
        vieja = _luminaria(admin, cat, f"{tipo}-OUT", lat=7.7, lng=-75.7)
        orden = _orden(admin, tipo, [(nueva["id"], "instalada"), (vieja["id"], "desmontada")])
        r = admin.post(
            f"/api/v1/ordenes/{orden['id']}/cerrar",
            headers=MT,
            json={
                "tipo_modernizacion_id": cat["tipo_mod"],
                "destino_desmontada": destino,
                "longitud_brazo": 1.5,
                "materiales": [],
                "evidencias": [],
            },
        )
        assert r.status_code == 200, r.text
        nueva_final = admin.get(f"/api/v1/luminarias/{nueva['id']}", headers=MT).json()
        # La instalada queda donde estaba la desmontada.
        assert (nueva_final["estado_codigo"], nueva_final["latitud"]) == ("121", 7.7)
        assert _estado(admin, f"/api/v1/luminarias/{vieja['id']}") == destino
        tipos = [
            e["tipo"]
            for e in admin.get(f"/api/v1/luminarias/{vieja['id']}/historial", headers=MT).json()[
                "eventos"
            ]
        ]
        assert f"{tipo}_desmontada" in tipos

    # Expansión con una luminaria que ya salió de bodega buena: 409 al cerrar.
    otra = _luminaria(admin, cat, "E-2", "124")
    orden = _orden(admin, "expansion", [(otra["id"], "instalada")])
    baja = admin.patch(
        f"/api/v1/bodega/luminarias/{otra['id']}",
        headers=MT,
        json={"estado_id": cat["estado"]["123"], "observacion": "Daño"},
    )
    assert baja.status_code == 200, baja.text
    r = admin.post(
        f"/api/v1/ordenes/{orden['id']}/cerrar",
        headers=MT,
        json={
            "tipo_expansion_id": cat["tipo_exp"],
            "barrio_id": cat["barrio"],
            "latitud": 8,
            "longitud": -75,
        },
    )
    assert r.status_code == 409


def test_validaciones_de_la_orden(admin: TestClient, cat: dict, db_configurado: Session) -> None:
    lum = _luminaria(admin, cat, "VAL-1")
    bodega = _luminaria(admin, cat, "VAL-2", "124")
    ajena = _luminaria(admin, cat, "VAL-AL", sede=AL)
    casos = [
        {"tipo": "poda", "luminarias": [{"luminaria_id": lum["id"], "rol": "intervenida"}]},
        {
            "tipo": "mantenimiento",
            "luminarias": [{"luminaria_id": ajena["id"], "rol": "intervenida"}],
        },
        {
            "tipo": "modernizacion",
            "luminarias": [{"luminaria_id": bodega["id"], "rol": "instalada"}],
        },
        {"tipo": "expansion", "luminarias": [{"luminaria_id": lum["id"], "rol": "instalada"}]},
        {"tipo": "mantenimiento", "luminarias": []},
    ]
    for caso in casos:
        assert admin.post("/api/v1/ordenes", headers=MT, json=caso).status_code == 422, caso

    orden = _orden(admin, "mantenimiento", [(lum["id"], "intervenida")])
    tecnico_al = _tecnico(db_configurado, "tec_al", "alcala")
    assert (
        admin.post(
            f"/api/v1/ordenes/{orden['id']}/asignar", headers=MT, json={"tecnico_id": tecnico_al}
        ).status_code
        == 422
    )
    assert (
        admin.post(f"/api/v1/ordenes/{orden['id']}/asignar", headers=MT, json={}).status_code == 422
    )
    assert (
        admin.post(
            "/api/v1/cuadrillas", headers=MT, json={"nombre": "Ajena", "tecnicos_ids": [tecnico_al]}
        ).status_code
        == 422
    )
    for quitado in ("fotocelda", "conectores_perforacion"):
        componentes = {k: True for k in COMPONENTES if k != quitado}
        r = admin.post(
            f"/api/v1/ordenes/{orden['id']}/cerrar",
            headers=MT,
            json=_cierre_mantenimiento(componentes=componentes),
        )
        assert r.status_code == 422 and quitado in r.json()["detail"]

    assert (
        admin.post(
            f"/api/v1/ordenes/{orden['id']}/cerrar", headers=MT, json=_cierre_mantenimiento()
        ).status_code
        == 200
    )
    anulada = _orden(admin, "mantenimiento", [(lum["id"], "intervenida")])
    assert (
        admin.post(
            f"/api/v1/ordenes/{anulada['id']}/anular", headers=MT, json={"motivo": "Duplicada"}
        ).status_code
        == 200
    )
    for o in (orden, anulada):
        for metodo, ruta, cuerpo in (
            ("PATCH", f"/api/v1/ordenes/{o['id']}", {"observaciones": "x"}),
            (
                "POST",
                f"/api/v1/ordenes/{o['id']}/asignar",
                {"tecnico_id": _tecnico(db_configurado, f"tec_{o['id']}")},
            ),
            ("POST", f"/api/v1/ordenes/{o['id']}/anular", {"motivo": "otra vez"}),
            ("POST", f"/api/v1/ordenes/{o['id']}/cerrar", _cierre_mantenimiento()),
        ):
            assert admin.request(metodo, ruta, headers=MT, json=cuerpo).status_code == 409
    assert admin.get(f"/api/v1/ordenes/{orden['id']}", headers=AL).status_code == 404


def test_tecnico_solo_ve_y_cierra_lo_suyo(
    admin: TestClient, cat: dict, db_configurado: Session
) -> None:
    lum1, lum2 = _luminaria(admin, cat, "TV-1"), _luminaria(admin, cat, "TV-2")
    tec_a, tec_b = _tecnico(db_configurado, "tec_a"), _tecnico(db_configurado, "tec_b")
    cuadrilla = admin.post(
        "/api/v1/cuadrillas",
        headers=MT,
        json={"nombre": "Cuadrilla Norte", "tecnicos_ids": [tec_a]},
    )
    assert cuadrilla.status_code == 201, cuadrilla.text
    assert (
        admin.post("/api/v1/cuadrillas", headers=MT, json={"nombre": "cuadrilla norte"}).status_code
        == 409
    )
    mia = _orden(admin, "mantenimiento", [(lum1["id"], "intervenida")])
    ajena = _orden(admin, "mantenimiento", [(lum2["id"], "intervenida")])
    admin.post(
        f"/api/v1/ordenes/{mia['id']}/asignar",
        headers=MT,
        json={"cuadrilla_id": cuadrilla.json()["id"]},
    )
    admin.post(f"/api/v1/ordenes/{ajena['id']}/asignar", headers=MT, json={"tecnico_id": tec_b})

    tecnico = TestClient(admin.app)
    iniciar_sesion_cliente(tecnico, "tec_a")
    visibles = tecnico.get("/api/v1/ordenes", headers=MT).json()
    assert [o["id"] for o in visibles["items"]] == [mia["id"]]
    assert tecnico.get(f"/api/v1/ordenes/{ajena['id']}", headers=MT).status_code == 403
    assert (
        tecnico.post(
            f"/api/v1/ordenes/{ajena['id']}/cerrar", headers=MT, json=_cierre_mantenimiento()
        ).status_code
        == 403
    )
    assert (
        tecnico.post(
            "/api/v1/ordenes",
            headers=MT,
            json={
                "tipo": "mantenimiento",
                "luminarias": [{"luminaria_id": lum1["id"], "rol": "intervenida"}],
            },
        ).status_code
        == 403
    )
    r = tecnico.post(
        f"/api/v1/ordenes/{mia['id']}/cerrar", headers=MT, json=_cierre_mantenimiento()
    )
    assert r.status_code == 200, r.text


# --- PQRS ---------------------------------------------------------------------------------------


def test_reglas_de_la_pqrs(admin: TestClient, cat: dict, db_configurado: Session) -> None:
    l1, l2 = _luminaria(admin, cat, "PQ-1"), _luminaria(admin, cat, "PQ-2")
    bodega = _luminaria(admin, cat, "PQ-B", "124")
    ajena = _luminaria(admin, cat, "PQ-AL", sede=AL)
    base = {"canal_id": cat["canal"], "luminarias": [{"luminaria_id": l1["id"]}]}
    for cuerpo in (
        {k: v for k, v in base.items() if k != "canal_id"},
        {**base, "luminarias": []},
        {**base, "canal_id": cat["led"]},
        {**base, "luminarias": [{"luminaria_id": ajena["id"]}]},
        {**base, "luminarias": [{"luminaria_id": bodega["id"]}]},
        {**base, "prioridad": 4},
    ):
        assert admin.post("/api/v1/pqrs", headers=MT, json=cuerpo).status_code == 422, cuerpo

    comodin = admin.get(
        "/api/v1/luminarias/buscar", headers=MT, params={"q": "SIN-IDENTIFICAR"}
    ).json()[0]
    pqrs_c = _pqrs(admin, cat, [comodin["id"]])
    assert _estado(admin, f"/api/v1/luminarias/{comodin['id']}") == "110"
    assert pqrs_c["luminarias"][0]["es_comodin"] is True

    pqrs = _pqrs(admin, cat, [l1["id"]])
    ruta = f"/api/v1/pqrs/{pqrs['id']}"
    assert admin.delete(f"{ruta}/luminarias/{l1['id']}", headers=MT).status_code == 409  # la última
    assert (
        admin.post(f"{ruta}/luminarias", headers=MT, json={"luminaria_id": l2["id"]}).status_code
        == 201
    )
    assert (
        admin.post(f"{ruta}/luminarias", headers=MT, json={"luminaria_id": l2["id"]}).status_code
        == 409
    )
    assert admin.delete(f"{ruta}/luminarias/{l2['id']}", headers=MT).status_code == 204
    assert _estado(admin, f"/api/v1/luminarias/{l2['id']}") == "121"  # vuelve a operación

    # Una luminaria reportada en dos PQRS no vuelve a 121 hasta que ninguna la tenga.
    otra = _pqrs(admin, cat, [l1["id"]])
    anulada = admin.post(f"{ruta}/anular", headers=MT, json={"motivo": "Duplicada"})
    assert anulada.status_code == 200 and anulada.json()["estado_codigo"] == "304"
    assert _estado(admin, f"/api/v1/luminarias/{l1['id']}") == "122"
    admin.post(f"/api/v1/pqrs/{otra['id']}/anular", headers=MT, json={"motivo": "Duplicada"})
    assert _estado(admin, f"/api/v1/luminarias/{l1['id']}") == "121"
    for metodo, sufijo, cuerpo in (
        ("POST", "/anular", {"motivo": "otra vez"}),
        ("PATCH", "", {"observacion_interna": "x"}),
        ("POST", "/luminarias", {"luminaria_id": l2["id"]}),
    ):
        assert admin.request(metodo, ruta + sufijo, headers=MT, json=cuerpo).status_code == 409
    assert admin.get(ruta, headers=AL).status_code == 404

    exportar = admin.post("/api/v1/pqrs/exportar", headers=MT, json={"prioridad": 1})
    assert exportar.status_code == 202
    assert _jobs(db_configurado, "atencion.exportar_pqrs")[-1]["prioridad"] == 1


def test_pqrs_con_varias_luminarias_se_cierra_al_reparar_todas(
    admin: TestClient, cat: dict
) -> None:
    l1, l2 = _luminaria(admin, cat, "MX-1"), _luminaria(admin, cat, "MX-2")
    pqrs = _pqrs(admin, cat, [l1["id"], l2["id"]])
    for lum, esperado in ((l1, "305"), (l2, "303")):
        orden = _orden(admin, "mantenimiento", [(lum["id"], "intervenida")], pqrs_id=pqrs["id"])
        admin.post(
            f"/api/v1/ordenes/{orden['id']}/asignar",
            headers=MT,
            json={
                "cuadrilla_id": admin.post(
                    "/api/v1/cuadrillas", headers=MT, json={"nombre": f"C-{lum['id']}"}
                ).json()["id"]
            },
        )
        assert (
            admin.post(
                f"/api/v1/ordenes/{orden['id']}/cerrar", headers=MT, json=_cierre_mantenimiento()
            ).status_code
            == 200
        )
        assert _estado(admin, f"/api/v1/pqrs/{pqrs['id']}") == esperado
        if esperado == "305":
            r = admin.delete(f"/api/v1/pqrs/{pqrs['id']}/luminarias/{l1['id']}", headers=MT)
            assert r.status_code == 409  # ya reparada
    # Con la PQRS atendida no se pueden crear más órdenes sobre ella.
    r = admin.post(
        "/api/v1/ordenes",
        headers=MT,
        json={
            "tipo": "mantenimiento",
            "pqrs_id": pqrs["id"],
            "luminarias": [{"luminaria_id": l1["id"], "rol": "intervenida"}],
        },
    )
    assert r.status_code == 409


def test_datos_personales_enmascarados_y_busqueda_sin_tildes(
    admin: TestClient, cat: dict, db_configurado: Session
) -> None:
    ciudadano = _ciudadano(admin, "1067123456", "Sofía Álvarez Peña")
    assert (
        admin.post(
            "/api/v1/ciudadanos",
            headers=MT,
            json={"identificacion": "1067123456", "nombre_completo": "Otra"},
        ).status_code
        == 409
    )
    lum = _luminaria(admin, cat, "PII-1")
    pqrs = _pqrs(admin, cat, [lum["id"]], ciudadano["id"])

    antes = db_configurado.execute(text("SELECT count(*) FROM auditoria_consulta")).scalar_one()
    encontrados = admin.get(
        "/api/v1/ciudadanos", headers=MT, params={"buscar": "sofia alvarez pena"}
    ).json()
    assert [c["id"] for c in encontrados["items"]] == [ciudadano["id"]]
    assert encontrados["items"][0]["celular"] == "3159876543"
    despues = db_configurado.execute(text("SELECT count(*) FROM auditoria_consulta")).scalar_one()
    assert despues == antes + 1

    crear_usuario_db(
        db_configurado,
        nombre_usuario="inter_f2",
        correo="inter_f2@sapef.test",
        rol_codigo="INTERVENTORIA",
        sede_codigos=["montelibano"],
    )
    lector = TestClient(admin.app)
    iniciar_sesion_cliente(lector, "inter_f2")
    for ruta, params in (
        ("/api/v1/ciudadanos", {"buscar": "Sofia"}),
        (f"/api/v1/pqrs/{pqrs['id']}", None),
        ("/api/v1/pqrs", None),
        ("/api/v1/pqrs/pendientes", None),
    ):
        r = lector.get(ruta, headers=MT, params=params)
        assert r.status_code == 200, (ruta, r.text)
        for dato in (
            "1067123456",
            "7729988",
            "3159876543",
            "c1067123456@example.test",
            "Sofía Álvarez Peña",
        ):
            assert dato not in r.text, (ruta, dato)
    assert (
        lector.post(
            "/api/v1/pqrs",
            headers=MT,
            json={"canal_id": cat["canal"], "luminarias": [{"luminaria_id": lum["id"]}]},
        ).status_code
        == 403
    )


def test_pendientes_con_semaforo_de_la_sede(
    admin: TestClient, cat: dict, db_configurado: Session
) -> None:
    ahora = datetime.now(UTC)
    for codigo, dias in (("S-0", 0), ("S-5", 5), ("S-10", 10)):
        lum = _luminaria(admin, cat, codigo)
        _pqrs(admin, cat, [lum["id"]], fecha_solicitud=(ahora - timedelta(days=dias)).isoformat())
    filas = admin.get("/api/v1/pqrs/pendientes", headers=MT).json()["items"]
    assert {(f["luminaria_codigo"], f["semaforo"]) for f in filas} == {
        ("S-0", "verde"),
        ("S-5", "amarillo"),
        ("S-10", "rojo"),
    }
    assert filas[0]["luminaria_codigo"] == "S-10"  # primero lo más antiguo
    rojos = admin.get("/api/v1/pqrs/pendientes", headers=MT, params={"semaforo": "rojo"}).json()
    assert [f["luminaria_codigo"] for f in rojos["items"]] == ["S-10"]

    # Los umbrales son los de la sede: con verde ≤ 10 días, todo queda en verde.
    semaforo = next(
        p
        for p in admin.get("/api/v1/parametros", headers=MT).json()
        if p["codigo"] == "semaforo_pqrs_umbrales"
    )
    admin.patch(
        f"/api/v1/parametros/{semaforo['id']}",
        headers=MT,
        json={"valor": {"verde_max_dias": 10, "amarillo_max_dias": 20}},
    )
    filas = admin.get("/api/v1/pqrs/pendientes", headers=MT).json()["items"]
    assert {f["semaforo"] for f in filas} == {"verde"}
    # La lista por defecto (último mes) y por número.
    assert admin.get("/api/v1/pqrs", headers=MT).json()["total"] == 3
    assert (
        admin.get("/api/v1/pqrs", headers=MT, params={"numero": 2}).json()["items"][0]["numero"]
        == 2
    )


# --- Inventario ---------------------------------------------------------------------------------


def test_materiales_y_kardex(admin: TestClient, cat: dict, db_configurado: Session) -> None:
    bajo = _material(admin, "cable-1", 4, 10)
    assert (bajo["codigo"], bajo["bajo_minimo"]) == ("CABLE-1", True)
    ok = _material(admin, "CABLE-2", 30, 10)
    assert ok["bajo_minimo"] is False
    assert (
        admin.post(
            "/api/v1/materiales",
            headers=MT,
            json={"categoria": "c", "codigo": "Cable-1", "descripcion": "d", "unidad": "m"},
        ).status_code
        == 409
    )
    assert (
        admin.post(
            "/api/v1/materiales",
            headers=MT,
            json={
                "categoria": "c",
                "codigo": "X",
                "descripcion": "d",
                "unidad": "m",
                "existencias": -1,
            },
        ).status_code
        == 422
    )
    lista = admin.get("/api/v1/materiales", headers=MT, params={"bajo_minimo": True}).json()
    assert [m["codigo"] for m in lista["items"]] == ["CABLE-1"]
    editado = admin.patch(
        f"/api/v1/materiales/{ok['id']}", headers=MT, json={"existencias_minimas": 50}
    )
    assert editado.json()["bajo_minimo"] is True
    assert (
        admin.patch(
            f"/api/v1/materiales/{ok['id']}", headers=MT, json={"existencias": 1}
        ).status_code
        == 422
    )  # solo con movimientos

    ruta = f"/api/v1/materiales/{ok['id']}/movimientos"
    uuid_origen = "5f0c7c3e-8a2d-4e55-9f1d-1d2b3c4d5e6f"
    primera = admin.post(
        ruta, headers=MT, json={"tipo": "entrada", "cantidad": 15, "uuid_origen": uuid_origen}
    )
    repetida = admin.post(
        ruta, headers=MT, json={"tipo": "entrada", "cantidad": 15, "uuid_origen": uuid_origen}
    )
    assert (primera.status_code, repetida.status_code) == (201, 200)
    assert primera.json()["id"] == repetida.json()["id"]
    assert (
        admin.post(
            f"/api/v1/materiales/{bajo['id']}/movimientos",
            headers=MT,
            json={"tipo": "entrada", "cantidad": 1, "uuid_origen": uuid_origen},
        ).status_code
        == 409
    )
    assert admin.post(ruta, headers=MT, json={"tipo": "salida", "cantidad": 46}).status_code == 409
    assert admin.post(ruta, headers=MT, json={"tipo": "ajuste", "cantidad": -46}).status_code == 409
    assert admin.post(ruta, headers=MT, json={"tipo": "ajuste", "cantidad": -2}).status_code == 201
    final = admin.get(f"/api/v1/materiales/{ok['id']}", headers=MT).json()
    assert final["existencias"] == "43.000"

    _tecnico(db_configurado, "tec_inv")
    tecnico = TestClient(admin.app)
    iniciar_sesion_cliente(tecnico, "tec_inv")
    assert tecnico.post(ruta, headers=MT, json={"tipo": "ajuste", "cantidad": 1}).status_code == 403
    assert tecnico.post(ruta, headers=MT, json={"tipo": "salida", "cantidad": 1}).status_code == 201
    # La base también impide existencias negativas (RN-017).
    with pytest.raises(Exception):  # noqa: B017
        db_configurado.execute(
            text("UPDATE material SET existencias = -1 WHERE id = :i"), {"i": ok["id"]}
        )
    db_configurado.rollback()


def test_bodega_y_cargue_de_bodega(admin: TestClient, cat: dict, db_configurado: Session) -> None:
    l1 = _luminaria(admin, cat, "BOD-1", "124")
    l2 = _luminaria(admin, cat, "BOD-2", "124")
    _luminaria(admin, cat, "BOD-OP")
    ajena = _luminaria(admin, cat, "BOD-AL", "124", sede=AL)
    lista = admin.get("/api/v1/bodega/luminarias", headers=MT).json()
    assert {x["codigo"] for x in lista["items"]} == {"BOD-1", "BOD-2"}
    filtrada = admin.get(
        "/api/v1/bodega/luminarias",
        headers=MT,
        params={"estado_id": cat["estado"]["124"], "texto": "BOD-1"},
    ).json()
    assert [x["codigo"] for x in filtrada["items"]] == ["BOD-1"]

    ruta = f"/api/v1/bodega/luminarias/{l1['id']}"
    assert (
        admin.patch(ruta, headers=MT, json={"estado_id": cat["estado"]["126"]}).status_code == 200
    )
    assert (
        admin.patch(ruta, headers=MT, json={"estado_id": cat["estado"]["124"]}).status_code == 422
    )
    assert (
        admin.patch(
            f"/api/v1/bodega/luminarias/{l2['id']}",
            headers=MT,
            json={"estado_id": cat["estado"]["121"]},
        ).status_code
        == 422
    )
    assert (
        admin.patch(
            f"/api/v1/bodega/luminarias/{ajena['id']}",
            headers=MT,
            json={"estado_id": cat["estado"]["123"]},
        ).status_code
        == 404
    )

    def cargar(filas: list[list[Any]]) -> dict[str, Any]:
        r = admin.post(
            "/api/v1/bodega/cargue",
            headers=MT,
            files={"archivo": ("b.xlsx", _xlsx(filas), "application/vnd.ms-excel")},
        )
        assert r.status_code == 202, r.text
        inventario_servicio.procesar_cargue_bodega(db_configurado, r.json()["cargueId"])
        return admin.get(f"/api/v1/bodega/cargue/{r.json()['cargueId']}", headers=MT).json()

    encabezado = ["luminaria_codigo", "estado_codigo", "observacion"]
    malo = cargar([encabezado, ["BOD-2", "125", "garantía"], ["NO-EXISTE", "123", None]])
    assert malo["estado"] == "con_errores" and malo["errores"][0]["fila"] == 3
    assert _estado(admin, f"/api/v1/luminarias/{l2['id']}") == "124"  # todo o nada
    bueno = cargar([encabezado, ["BOD-2", "125", "garantía"]])
    assert bueno["estado"] == "completado"
    assert _estado(admin, f"/api/v1/luminarias/{l2['id']}") == "125"


# --- Cargue masivo de órdenes --------------------------------------------------------------------


def test_cargue_masivo_todo_o_nada(admin: TestClient, cat: dict, db_configurado: Session) -> None:
    for tipo in ("expansion", "modernizacion", "reubicacion"):
        r = admin.get(f"/api/v1/ordenes/plantillas/{tipo}", headers=MT)
        assert r.status_code == 200 and r.content[:2] == b"PK"
    assert admin.get("/api/v1/ordenes/plantillas/mantenimiento", headers=MT).status_code == 422

    for i in range(3):
        _luminaria(admin, cat, f"BLK-{i}", "124")
    encabezado = ["luminaria_codigo", "tipo_expansion", "barrio", "poste", "latitud", "longitud"]
    validas = [
        [f"BLK-{i}", "COMPLEMENTARIA", cat["barrio_nombre"], f"P{i}", 7.9, -75.4] for i in range(2)
    ]

    def cargar(filas: list[list[Any]]) -> dict[str, Any]:
        r = admin.post(
            "/api/v1/ordenes/cargue-masivo/expansion",
            headers=MT,
            files={"archivo": ("c.xlsx", _xlsx(filas), "application/vnd.ms-excel")},
        )
        assert r.status_code == 202, r.text
        assert _jobs(db_configurado, "trabajos.procesar_cargue_masivo")[-1] == {
            "cargue_id": r.json()["cargueId"]
        }
        trabajos_servicio.procesar_cargue(db_configurado, r.json()["cargueId"])
        return admin.get(f"/api/v1/ordenes/cargue-masivo/{r.json()['cargueId']}", headers=MT).json()

    con_error = cargar(
        [encabezado, *validas, ["BLK-2", "COMPLEMENTARIA", "NO EXISTE", "P", 7.9, -75.4]]
    )
    assert con_error["estado"] == "con_errores"
    assert [e["fila"] for e in con_error["errores"]] == [4]
    assert "NO EXISTE" in json.dumps(con_error["errores"], ensure_ascii=False)
    assert admin.get("/api/v1/ordenes", headers=MT).json()["total"] == 0

    repetida = cargar([encabezado, validas[0], validas[0]])
    assert repetida["estado"] == "con_errores"

    ok = cargar([encabezado, *validas])
    assert (ok["estado"], ok["ordenes_creadas"]) == ("completado", 2)
    ordenes = admin.get("/api/v1/ordenes", headers=MT).json()["items"]
    assert {(o["estado_codigo"], o["origen"]) for o in ordenes} == {("203", "cargue")}
    lum = admin.get("/api/v1/luminarias", headers=MT, params={"texto": "BLK-0"}).json()["items"][0]
    assert (lum["estado_codigo"], lum["latitud"]) == ("121", 7.9)
