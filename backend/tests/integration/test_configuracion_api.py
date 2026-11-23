"""Integración de configuración (EP-02) contra PostgreSQL: permiso, sede, auditoría y semilla."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modulos.configuracion import servicio as configuracion_servicio
from app.modulos.seguridad import servicio as seguridad_servicio
from tests.conftest import crear_usuario_db, iniciar_sesion_cliente

MT = {"X-Sede": "montelibano"}
AL = {"X-Sede": "alcala"}


@pytest.fixture
def admin(cliente: TestClient, db_configurado: Session) -> TestClient:
    crear_usuario_db(
        db_configurado,
        nombre_usuario="admin_cfg",
        correo="admin_cfg@sapef.test",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano", "alcala"],
    )
    iniciar_sesion_cliente(cliente, "admin_cfg")
    return cliente


def _otro_cliente(cliente: TestClient, db: Session, usuario: str, rol: str, sedes: list[str]):
    crear_usuario_db(
        db, nombre_usuario=usuario, correo=f"{usuario}@sapef.test", rol_codigo=rol,
        sede_codigos=sedes,
    )
    nuevo = TestClient(cliente.app)
    iniciar_sesion_cliente(nuevo, usuario)
    return nuevo


def _auditorias(db: Session, entidad: str) -> int:
    return db.execute(
        text("SELECT count(*) FROM auditoria WHERE entidad = :e"), {"e": entidad}
    ).scalar_one()


# --- Catálogos sembrados -----------------------------------------------------------------------


def test_catalogos_sembrados_visibles(admin: TestClient) -> None:
    clases = {c["codigo"]: c for c in admin.get("/api/v1/maestros/clases").json()}
    assert len(clases) == 20
    assert clases["COMPONENTE_MANTENIMIENTO"]["total_valores"] == 12

    marcas = admin.get("/api/v1/maestros/LUMINARIA_MARCA").json()
    assert {"KUNIX", "SCHREDER", "PHILIPS"} <= {m["codigo"] for m in marcas}
    assert admin.get("/api/v1/maestros/NO_EXISTE").status_code == 404

    estados_pqrs = admin.get("/api/v1/estados", params={"proceso": "pqrs"}).json()
    assert [e["codigo"] for e in estados_pqrs] == ["301", "302", "305", "303", "304"]
    assert admin.get("/api/v1/estados", params={"proceso": "otro"}).status_code == 422

    assert len(admin.get("/api/v1/zonas", headers=MT).json()) == 11
    barrios = admin.get("/api/v1/barrios", headers=MT).json()
    assert len(barrios) == 101
    assert all(b["zona_nombre"] for b in barrios)
    # La búsqueda ignora tildes y la ñ: «pinalito» encuentra «Piñalito».
    encontrados = admin.get("/api/v1/barrios", headers=MT, params={"buscar": "pinalito"}).json()
    assert [b["nombre"] for b in encontrados] == ["Piñalito"]
    assert admin.get("/api/v1/zonas", headers=AL).json() == []

    conceptos = admin.get("/api/v1/comercial/catalogos/conceptos").json()
    assert len(conceptos) == 64
    assert {c["codigo"] for c in conceptos if c["entra_al_calculo"]} == {"CI400"}
    assert len(admin.get("/api/v1/comercial/catalogos/operaciones").json()) == 33
    assert admin.get("/api/v1/comercial/catalogos/otros").status_code == 422


def test_semilla_idempotente_y_admin_inicial(db_configurado: Session) -> None:
    repetida = configuracion_servicio.sembrar_catalogos(db_configurado, archivo_max_evidencia_mb=12)
    assert set(repetida.values()) == {0}
    roles = seguridad_servicio.sincronizar_permisos_y_roles(db_configurado)
    assert roles == {"permisos_creados": 0, "roles_creados": 0}
    limite = configuracion_servicio.obtener_valor_parametro(
        db_configurado, "archivo_tamano_max_evidencia_mb", sede_id=1
    )
    assert limite == {"valor": 12}  # el parámetro de sistema sigue a la configuración

    with pytest.raises(Exception):  # noqa: B017 - contraseña débil
        seguridad_servicio.crear_admin_inicial(
            db_configurado, nombre_usuario="raiz", correo="raiz@sapef.test",
            nombre_completo="Raíz", identificacion="1", clave="corta",
        )
    creado = seguridad_servicio.crear_admin_inicial(
        db_configurado, nombre_usuario="raiz", correo="raiz@sapef.test",
        nombre_completo="Raíz", identificacion="1", clave="Una-Clave-Larga-2026",
    )
    db_configurado.commit()
    assert creado is True
    sedes = db_configurado.execute(
        text(
            "SELECT count(*) FROM usuario_sede us JOIN usuario u ON u.id = us.usuario_id "
            "WHERE u.nombre_usuario = 'raiz'"
        )
    ).scalar_one()
    assert sedes == 2  # todas las sedes activas (la inactiva no)
    assert (
        seguridad_servicio.crear_admin_inicial(
            db_configurado, nombre_usuario="raiz", correo="otro@sapef.test",
            nombre_completo="Raíz", identificacion="1", clave="Una-Clave-Larga-2026",
        )
        is False
    )


# --- Sedes y comercializadores ----------------------------------------------------------------


def test_sedes_y_comercializadores(admin: TestClient, db_configurado: Session) -> None:
    assert {s["codigo"] for s in admin.get("/api/v1/sedes").json()} == {
        "montelibano", "alcala", "inactiva"
    }
    nueva = admin.post(
        "/api/v1/sedes",
        json={"codigo": "Sahagun", "nombre": "Sahagún", "municipio": "Sahagún",
              "departamento": "Córdoba"},
    )
    assert nueva.status_code == 201, nueva.text
    assert nueva.json()["codigo"] == "sahagun"
    sede_id = nueva.json()["id"]
    # La sede nueva nace con sus parámetros y plantillas por defecto.
    por_defecto = db_configurado.execute(
        text("SELECT (SELECT count(*) FROM parametro WHERE sede_id = :s) + "
             "(SELECT count(*) FROM plantilla_correo WHERE sede_id = :s)"), {"s": sede_id}
    ).scalar_one()
    assert por_defecto == 5
    assert admin.post(
        "/api/v1/sedes",
        json={"codigo": "sahagun", "nombre": "x", "municipio": "x", "departamento": "x"},
    ).status_code == 409

    ruta = f"/api/v1/sedes/{sede_id}/comercializadores"
    puesta = admin.put(ruta, json=[
        {"comercializador_codigo": "afinia", "desde": "2026-01-01"},
        {"comercializador_codigo": "vatia"},
    ])
    assert puesta.status_code == 200, puesta.text
    assert {c["comercializador_codigo"] for c in puesta.json()} == {"afinia", "vatia"}
    # Omitir uno lo deja inactivo, no lo borra.
    segunda = admin.put(ruta, json=[{"comercializador_codigo": "afinia"}]).json()
    assert {(c["comercializador_codigo"], c["activo"]) for c in segunda} == {
        ("afinia", True), ("vatia", False)
    }
    assert admin.put(ruta, json=[{"comercializador_codigo": "otro"}]).status_code == 422
    assert admin.put(ruta, json=[{"comercializador_codigo": "afinia"}] * 2).status_code == 422
    assert _auditorias(db_configurado, "sede_comercializador") == 2

    tecnico = _otro_cliente(admin, db_configurado, "tec_cfg", "TECNICO", ["montelibano"])
    assert [s["codigo"] for s in tecnico.get("/api/v1/sedes").json()] == ["montelibano"]
    assert tecnico.post(
        "/api/v1/sedes", json={"codigo": "zz", "nombre": "x", "municipio": "x",
                               "departamento": "x"}
    ).status_code == 403
    assert tecnico.get(ruta).status_code == 403
    assert tecnico.put(ruta, json=[]).status_code == 403


# --- Maestros ----------------------------------------------------------------------------------


def test_maestros_crud_y_permisos(admin: TestClient, db_configurado: Session) -> None:
    creado = admin.post(
        "/api/v1/maestros/luminaria_marca", json={"codigo": "nueva marca", "nombre": "Nueva"}
    )
    assert creado.status_code == 201, creado.text
    assert creado.json()["codigo"] == "NUEVA_MARCA"
    # «Künix» normaliza a KUNIX, que ya existe.
    assert admin.post(
        "/api/v1/maestros/LUMINARIA_MARCA", json={"codigo": "Künix", "nombre": "Otra"}
    ).status_code == 409

    ruta = f"/api/v1/maestros/LUMINARIA_MARCA/{creado.json()['id']}"
    editado = admin.patch(ruta, json={"nombre": "  Editada  ", "activo": False})
    assert editado.status_code == 200
    assert editado.json()["nombre"] == "Editada"
    activas = admin.get("/api/v1/maestros/LUMINARIA_MARCA", params={"activo": True}).json()
    assert "NUEVA_MARCA" not in {m["codigo"] for m in activas}
    # Un id de otra clase no se puede editar por esta ruta.
    otra = admin.get("/api/v1/maestros/CANAL_PQRS").json()[0]["id"]
    assert admin.patch(f"/api/v1/maestros/LUMINARIA_MARCA/{otra}", json={}).status_code == 404
    assert admin.patch(ruta, json={"codigo": "X"}).status_code == 422  # el código no cambia
    assert _auditorias(db_configurado, "maestro_valor") == 2

    lector = _otro_cliente(admin, db_configurado, "int_cfg", "INTERVENTORIA", ["montelibano"])
    assert lector.get("/api/v1/maestros/LUMINARIA_MARCA").status_code == 200
    assert lector.post(
        "/api/v1/maestros/LUMINARIA_MARCA", json={"codigo": "X", "nombre": "X"}
    ).status_code == 403


# --- Zonas y barrios ---------------------------------------------------------------------------


def test_zonas_y_barrios_aislados_por_sede(admin: TestClient, db_configurado: Session) -> None:
    assert admin.get("/api/v1/zonas").status_code == 400  # sin X-Sede
    zona_mt = admin.post("/api/v1/zonas", headers=MT, json={"nombre": " Nueva  zona "})
    assert zona_mt.status_code == 201
    assert zona_mt.json()["nombre"] == "Nueva zona"
    assert admin.post("/api/v1/zonas", headers=MT, json={"nombre": "nueva ZONA"}).status_code == 409
    zona_al = admin.post("/api/v1/zonas", headers=AL, json={"nombre": "Zona Alcalá"}).json()

    barrio = admin.post(
        "/api/v1/barrios", headers=MT, json={"zona_id": zona_mt.json()["id"], "nombre": "B1"}
    )
    assert barrio.status_code == 201
    assert admin.post(
        "/api/v1/barrios", headers=MT, json={"zona_id": zona_mt.json()["id"], "nombre": "b1"}
    ).status_code == 409
    # Zona de otra sede: 404, igual que una inexistente.
    assert admin.post(
        "/api/v1/barrios", headers=MT, json={"zona_id": zona_al["id"], "nombre": "B2"}
    ).status_code == 404
    barrio_al = admin.post(
        "/api/v1/barrios", headers=AL, json={"zona_id": zona_al["id"], "nombre": "B Alcalá"}
    ).json()
    ruta_al = f"/api/v1/barrios/{barrio_al['id']}"
    assert admin.patch(ruta_al, headers=MT, json={"nombre": "x"}).status_code == 404
    assert admin.patch(
        f"/api/v1/barrios/{barrio.json()['id']}", headers=MT, json={"zona_id": zona_al["id"]}
    ).status_code == 404
    movido = admin.patch(ruta_al, headers=AL, json={"activo": False}).json()
    assert movido["activo"] is False

    solo_mt = _otro_cliente(admin, db_configurado, "tec_mt", "TECNICO", ["montelibano"])
    assert solo_mt.get("/api/v1/zonas", headers=MT).status_code == 200
    assert solo_mt.get("/api/v1/zonas", headers=AL).status_code == 403
    assert solo_mt.get("/api/v1/barrios", headers=AL).status_code == 403
    assert solo_mt.post("/api/v1/zonas", headers=MT, json={"nombre": "x"}).status_code == 403


# --- Parámetros y plantillas ------------------------------------------------------------------


def test_parametros(admin: TestClient, db_configurado: Session) -> None:
    respuesta = admin.get("/api/v1/parametros", headers=MT)
    assert respuesta.status_code == 200
    for prohibido in ("passwd", "password", "clave", "secret", "smtp"):
        assert prohibido not in respuesta.text.lower()
    params = {p["codigo"]: p for p in respuesta.json()}
    limite = params["archivo_tamano_max_evidencia_mb"]
    assert (limite["alcance"], limite["editable"]) == ("global", False)
    assert limite["valor"] == {"valor": 10}
    assert admin.patch(
        f"/api/v1/parametros/{limite['id']}", headers=MT, json={"valor": {"valor": 99}}
    ).status_code == 403

    semaforo = params["semaforo_pqrs_umbrales"]
    ruta = f"/api/v1/parametros/{semaforo['id']}"
    malo = admin.patch(ruta, headers=MT, json={"valor": {"verde_max_dias": -5,
                                                        "amarillo_max_dias": 1}})
    assert malo.status_code == 422
    bueno = admin.patch(ruta, headers=MT, json={"valor": {"verde_max_dias": 4,
                                                         "amarillo_max_dias": 8}})
    assert bueno.status_code == 200
    assert bueno.json()["valor"] == {"verde_max_dias": 4, "amarillo_max_dias": 8}
    # El de Montelíbano no se edita con la sede de Alcalá.
    assert admin.patch(ruta, headers=AL, json={"valor": semaforo["valor"]}).status_code == 404
    assert _auditorias(db_configurado, "parametro") == 1

    lector = _otro_cliente(admin, db_configurado, "int_par", "INTERVENTORIA", ["montelibano"])
    assert lector.get("/api/v1/parametros", headers=MT).status_code == 200
    assert lector.patch(ruta, headers=MT, json={"valor": semaforo["valor"]}).status_code == 403


def test_plantillas(admin: TestClient, db_configurado: Session) -> None:
    plantillas = {p["codigo"]: p for p in admin.get("/api/v1/plantillas-correo", headers=MT).json()}
    assert set(plantillas) == {
        "MAIL_RECUPERAR_CUENTA", "MAIL_PQRS", "MAIL.MANTENIMIENTO_LUMINARIA",
        "MAIL.INSTALACION_LUMINARIA",
    }
    pqrs = plantillas["MAIL_PQRS"]
    ruta = f"/api/v1/plantillas-correo/{pqrs['id']}"
    ok = admin.patch(ruta, headers=MT, json={"asunto": "PQRS {{numero}} recibida"})
    assert ok.status_code == 200
    assert ok.json()["asunto"] == "PQRS {{numero}} recibida"
    assert admin.patch(ruta, headers=MT, json={"asunto": "{{clave}}"}).status_code == 422
    assert admin.patch(
        ruta, headers=MT, json={"cuerpo_html": "<script>x</script>"}
    ).status_code == 422
    assert admin.patch(ruta, headers=AL, json={"asunto": "x"}).status_code == 404

    sede_mt = db_configurado.execute(text("SELECT id FROM sede WHERE codigo='montelibano'"))
    asunto, cuerpo = configuracion_servicio.renderizar_plantilla(
        db_configurado, sede_mt.scalar_one(), "MAIL_PQRS",
        {"numero": "17", "nombre": "<Ana>", "fecha": "hoy", "estado": "En proceso"},
    )
    assert asunto == "PQRS 17 recibida"
    assert "&lt;Ana&gt;" in cuerpo


# --- Acuerdos tarifarios -----------------------------------------------------------------------


def test_acuerdos_ciclo_completo(admin: TestClient, db_configurado: Session) -> None:
    lista = admin.get(
        "/api/v1/acuerdos", headers=MT, params={"comercializador": "afinia", "anio": 2026}
    ).json()
    assert len(lista) == 1
    vigente = lista[0]
    assert (vigente["estado"], vigente["uvt"], vigente["tolerancia"]) == (
        "aprobado", "52374.00", "1.00"
    )
    detalle = admin.get(f"/api/v1/acuerdos/{vigente['id']}", headers=MT).json()
    minimos = {t["tarifa"]: t["valor_minimo"] for t in detalle["tarifas"]}
    assert len(minimos) == 12
    assert minimos["AP_Residenciales_Estrato_1"] == "2094.96"
    assert minimos["AP_Comerciales_Nivel_1"] == "15712.20"
    # Un acuerdo de Montelíbano no existe para Alcalá.
    assert admin.get(f"/api/v1/acuerdos/{vigente['id']}", headers=AL).status_code == 404

    assert admin.patch(
        f"/api/v1/acuerdos/{vigente['id']}", headers=MT, json={"tolerancia": 999}
    ).status_code == 409

    copia = admin.post(
        f"/api/v1/acuerdos/{vigente['id']}/copiar", headers=MT, json={"anio_destino": 2027}
    )
    assert copia.status_code == 201, copia.text
    borrador = copia.json()
    assert (borrador["estado"], borrador["anio"], borrador["origen_id"]) == (
        "borrador", 2027, vigente["id"]
    )
    assert len(borrador["tarifas"]) == 12
    assert admin.post(
        f"/api/v1/acuerdos/{vigente['id']}/copiar", headers=MT, json={"anio_destino": 2027}
    ).status_code == 409

    editado = admin.patch(
        f"/api/v1/acuerdos/{borrador['id']}", headers=MT,
        json={"uvt": "55000", "fuente": "Acuerdo 2027",
              "excepciones": [{"identificador": "123456", "factor_uvt": "5"}]},
    )
    assert editado.status_code == 200, editado.text
    assert editado.json()["tarifas"][6]["valor_minimo"] == "2200.00"  # 55.000 × 0,04
    aprobado = admin.post(f"/api/v1/acuerdos/{borrador['id']}/aprobar", headers=MT, json={})
    assert aprobado.status_code == 200, aprobado.text
    assert aprobado.json()["estado"] == "aprobado"
    assert aprobado.json()["aprobado_en"] is not None
    assert admin.post(
        f"/api/v1/acuerdos/{borrador['id']}/aprobar", headers=MT
    ).status_code == 409

    # Una nueva versión del mismo año reemplaza a la aprobada (y queda en la bitácora).
    v2 = admin.post(
        f"/api/v1/acuerdos/{vigente['id']}/copiar", headers=MT, json={"anio_destino": 2026}
    ).json()
    assert admin.post(f"/api/v1/acuerdos/{v2['id']}/aprobar", headers=MT).status_code == 200
    estados_2026 = {
        a["id"]: a["estado"]
        for a in admin.get("/api/v1/acuerdos", headers=MT, params={"anio": 2026}).json()
    }
    assert estados_2026 == {vigente["id"]: "reemplazado", v2["id"]: "aprobado"}
    vigencia = configuracion_servicio.obtener_vigencia_aprobada(
        db_configurado, vigente["sede_id"], "afinia", 2026
    )
    assert vigencia is not None and vigencia.id == v2["id"]
    acciones = db_configurado.execute(
        text("SELECT accion FROM auditoria WHERE entidad = 'acuerdo_vigencia' ORDER BY id")
    ).scalars().all()
    assert acciones == ["copiar", "editar", "aprobar", "copiar", "reemplazar", "aprobar"]


def test_acuerdos_validaciones_y_permisos(admin: TestClient, db_configurado: Session) -> None:
    incompleto = admin.post(
        "/api/v1/acuerdos", headers=MT,
        json={"comercializador_codigo": "afinia", "anio": 2030, "uvt": 52374, "umbral_kwh": 173,
              "tolerancia": 1.0, "base_costo_variable": "valor_consumo_antes", "tarifas": []},
    )
    assert incompleto.status_code == 201, incompleto.text
    rechazo = admin.post(f"/api/v1/acuerdos/{incompleto.json()['id']}/aprobar", headers=MT)
    assert rechazo.status_code == 422
    assert "tarifas" in rechazo.json()["detail"]
    assert admin.post(
        "/api/v1/acuerdos", headers=MT, json={"comercializador_codigo": "afinia", "anio": 2030}
    ).status_code == 409  # ya hay un borrador ese año
    # Vatia no tiene control tarifario; Afinia no opera en Alcalá.
    assert admin.post(
        "/api/v1/acuerdos", headers=AL, json={"comercializador_codigo": "vatia", "anio": 2026}
    ).status_code == 422
    assert admin.post(
        "/api/v1/acuerdos", headers=AL, json={"comercializador_codigo": "afinia", "anio": 2026}
    ).status_code == 422
    assert admin.post(
        "/api/v1/acuerdos", headers=MT,
        json={"comercializador_codigo": "afinia", "anio": 2031,
              "tarifas": [{"tarifa": "A", "porcentaje_costo_variable": 12}]},
    ).status_code == 422  # el porcentaje es una fracción (0,12)

    celsia = admin.get(
        "/api/v1/acuerdos", headers=AL, params={"comercializador": "celsia"}
    ).json()[0]
    assert (celsia["estado"], celsia["tolerancia"], celsia["uvt"]) == ("aprobado", "100.00", None)

    analista = _otro_cliente(admin, db_configurado, "ana_cfg", "ANALISTA_COMERCIAL",
                             ["montelibano"])
    vigente = analista.get("/api/v1/acuerdos", headers=MT, params={"anio": 2026}).json()[0]
    copia = analista.post(
        f"/api/v1/acuerdos/{vigente['id']}/copiar", headers=MT, json={"anio_destino": 2028}
    )
    assert copia.status_code == 201
    assert analista.post(
        f"/api/v1/acuerdos/{copia.json()['id']}/aprobar", headers=MT
    ).status_code == 403
    assert analista.get("/api/v1/acuerdos", headers=AL).status_code == 403

    tecnico = _otro_cliente(admin, db_configurado, "tec_acu", "TECNICO", ["montelibano"])
    assert tecnico.get("/api/v1/acuerdos", headers=MT).status_code == 403


def test_detalle_con_excepciones_se_audita(admin: TestClient, db_configurado: Session) -> None:
    borrador = admin.post(
        "/api/v1/acuerdos", headers=MT,
        json={"comercializador_codigo": "afinia", "anio": 2032,
              "excepciones": [{"identificador": "999", "nombre": "Empresa", "factor_uvt": 90}]},
    ).json()
    assert admin.get(f"/api/v1/acuerdos/{borrador['id']}", headers=MT).status_code == 200
    consultas = db_configurado.execute(
        text("SELECT count(*) FROM auditoria_consulta WHERE recurso = 'acuerdo.detalle'")
    ).scalar_one()
    assert consultas == 1
    # La bitácora de cambios no guarda la razón social del contribuyente.
    despues = db_configurado.execute(
        text("SELECT despues::text FROM auditoria WHERE entidad = 'acuerdo_vigencia'")
    ).scalar_one()
    assert "Empresa" not in despues
