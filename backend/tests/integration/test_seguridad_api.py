"""Pruebas de integración reales contra PostgreSQL/PostGIS para seguridad (EP-01)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.modulos.seguridad import dominio as seg_dominio
from app.modulos.seguridad import servicio as seg_servicio
from app.modulos.seguridad.modelos import (
    Auditoria,
    AuditoriaConsulta,
    Sesion,
    TokenRecuperacion,
    Usuario,
)
from tests.conftest import crear_usuario_db, iniciar_sesion_cliente


def test_login_argon2id_cookies_y_usuario_importado_sin_clave(cliente: TestClient, db):
    crear_usuario_db(
        db,
        nombre_usuario="AdminUser",
        correo="admin@sapef.com",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano", "alcala"],
        clave="ClaveSegura123",
    )
    crear_usuario_db(
        db,
        nombre_usuario="importado_sin_clave",
        correo="imp@sapef.com",
        rol_codigo="TECNICO",
        sede_codigos=["montelibano"],
        clave=None,
        debe_cambiar_clave=True,
    )

    # Usuario importado con hash_clave=NULL debe responder 401 controlado (nunca 500)
    resp_null = cliente.post(
        "/api/v1/auth/ingresar",
        json={"usuario": "importado_sin_clave", "clave": "ClaveSegura123"},
    )
    assert resp_null.status_code == 401

    # Login case-insensitive
    resp = cliente.post(
        "/api/v1/auth/ingresar",
        json={"usuario": "  ADMINUSER ", "clave": "ClaveSegura123", "tipo_cliente": "pwa"},
    )
    assert resp.status_code == 200
    cuerpo = resp.json()
    assert cuerpo["nombre_usuario"] == "adminuser"
    assert "hash_clave" not in resp.text
    assert len(cuerpo["sedes"]) == 2
    assert "sapef_acceso" in resp.cookies
    assert "sapef_renovacion" in resp.cookies

    set_cookies = resp.headers.get_list("set-cookie")
    assert any("HttpOnly" in h and "SameSite=strict" in h for h in set_cookies)


def test_bloqueo_cinco_intentos_fallidos(cliente: TestClient, db):
    crear_usuario_db(
        db,
        nombre_usuario="bloqueable",
        correo="bloq@sapef.com",
        rol_codigo="TECNICO",
        sede_codigos=["montelibano"],
        clave="ClaveSegura123",
    )

    for intento in range(4):
        r = cliente.post(
            "/api/v1/auth/ingresar",
            json={"usuario": "bloqueable", "clave": f"MalaClave{intento}"},
        )
        assert r.status_code == 401

    r5 = cliente.post(
        "/api/v1/auth/ingresar",
        json={"usuario": "bloqueable", "clave": "MalaClave5"},
    )
    assert r5.status_code == 423

    # Incluso con la clave correcta sigue bloqueado con 423
    r_correcta = cliente.post(
        "/api/v1/auth/ingresar",
        json={"usuario": "bloqueable", "clave": "ClaveSegura123"},
    )
    assert r_correcta.status_code == 423

    eventos = db.query(Auditoria).filter(Auditoria.accion == "login_bloqueado").all()
    assert len(eventos) >= 1


def test_rotacion_refresh_deteccion_reuso_y_salir(cliente: TestClient, db):
    crear_usuario_db(
        db,
        nombre_usuario="rotador",
        correo="rot@sapef.com",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano"],
    )
    iniciar_sesion_cliente(cliente, "rotador")
    token_viejo = cliente.cookies.get("sapef_renovacion")
    assert token_viejo is not None

    # Rotación legítima
    r_ren = cliente.post("/api/v1/auth/renovar")
    assert r_ren.status_code == 200
    assert r_ren.json()["estado"] == "renovada"
    token_nuevo = cliente.cookies.get("sapef_renovacion")
    assert token_nuevo and token_nuevo != token_viejo

    # Reuso del token ya rotado: revoca toda la familia y audita
    cliente.cookies.set("sapef_renovacion", token_viejo)
    r_reuso = cliente.post("/api/v1/auth/renovar")
    assert r_reuso.status_code == 401
    assert r_reuso.headers["content-type"].startswith("application/problem+json")

    aud_reuso = db.query(Auditoria).filter(Auditoria.accion == "reuso_sesion").all()
    assert len(aud_reuso) == 1

    # Intentar usar el token nuevo después del reuso también falla (familia revocada)
    cliente.cookies.set("sapef_renovacion", token_nuevo)
    assert cliente.post("/api/v1/auth/renovar").status_code == 401

    # Nuevo login + /salir revoca sesión
    iniciar_sesion_cliente(cliente, "rotador")
    assert cliente.get("/api/v1/yo").status_code == 200
    r_salir = cliente.post("/api/v1/auth/salir")
    assert r_salir.status_code == 204
    assert cliente.get("/api/v1/yo").status_code == 401


def test_recuperacion_ids_only_procrastinate_y_restablecer(cliente: TestClient, db):
    usuario = crear_usuario_db(
        db,
        nombre_usuario="recup",
        correo="recup@sapef.com",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano"],
    )
    iniciar_sesion_cliente(cliente, "recup")

    # Correo inexistente: misma respuesta 202 neutra, sin trabajo en cola
    r_no = cliente.post("/api/v1/auth/recuperar", json={"correo": "noexiste@sapef.com"})
    assert r_no.status_code == 202
    assert db.execute(text("SELECT count(*) FROM procrastinate_jobs")).scalar_one() == 0

    # Correo existente: 202 + trabajo Procrastinate estrictamente con (usuario_id, token_id)
    r_ok = cliente.post("/api/v1/auth/recuperar", json={"correo": "recup@sapef.com"})
    assert r_ok.status_code == 202
    assert r_ok.json() == r_no.json()

    jobs = db.execute(text("SELECT task_name, args FROM procrastinate_jobs")).all()
    assert len(jobs) == 1
    task_name, args = jobs[0]
    assert task_name == "seguridad.enviar_correo_recuperacion"
    assert set(args.keys()) == {"usuario_id", "token_id"}
    assert args["usuario_id"] == usuario.id
    assert "recup@sapef.com" not in str(args)

    # Extraer el token en claro usando el mecanismo interno del worker y verificar limpieza
    token_row = db.query(TokenRecuperacion).filter(
        TokenRecuperacion.usuario_id == usuario.id
    ).one()
    raw_token = seg_dominio.descifrar_token_envio(
        token_row.token_cifrado_envio,
        seg_servicio.obtener_configuracion().secret_key.get_secret_value(),
    )
    assert raw_token is not None

    seg_servicio.procesar_envio_correo_recuperacion(usuario.id, str(token_row.id))
    db.expire_all()
    token_row = db.query(TokenRecuperacion).filter(TokenRecuperacion.id == token_row.id).one()
    assert token_row.token_cifrado_envio is None

    # Restablecer contraseña revoca sesiones activas y rechaza reuso del token
    r_reset = cliente.post(
        "/api/v1/auth/restablecer",
        json={"token": raw_token, "clave_nueva": "NuevaClaveSegura99"},
    )
    assert r_reset.status_code == 200
    assert cliente.get("/api/v1/yo").status_code == 401
    assert (
        cliente.post(
            "/api/v1/auth/restablecer",
            json={"token": raw_token, "clave_nueva": "OtraClave999"},
        ).status_code
        == 400
    )

    iniciar_sesion_cliente(cliente, "recup", "NuevaClaveSegura99")


def test_debe_cambiar_clave_aceptar_condiciones_y_cambio_clave(cliente: TestClient, db):
    u = crear_usuario_db(
        db,
        nombre_usuario="forzado",
        correo="forzado@sapef.com",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano"],
        debe_cambiar_clave=True,
        acepto_condiciones=False,
    )
    iniciar_sesion_cliente(cliente, "forzado")
    # Guardar otra sesión en BD para verificar que cambiar-clave revoca las otras sesiones
    otra_sesion = Sesion(
        usuario_id=u.id,
        hash_token_renovacion=seg_dominio.hash_sha256_hex("otra-sesion-externa"),
        familia=u.id and __import__("uuid").uuid4(),
        tipo_cliente="web",
        expira_en=datetime.now(UTC) + timedelta(hours=12),
    )
    db.add(otra_sesion)
    db.commit()

    # /yo y /aceptar-condiciones permitidos; rutas operativas bloqueadas con 403
    assert cliente.get("/api/v1/yo").status_code == 200
    assert cliente.get("/api/v1/usuarios").status_code == 403
    r_cond = cliente.post("/api/v1/auth/aceptar-condiciones", json={"acepto": True})
    assert r_cond.status_code == 200
    assert r_cond.json()["acepto_condiciones_en"] is not None

    # Clave actual errónea -> 400; igual -> 422
    assert (
        cliente.post(
            "/api/v1/auth/cambiar-clave",
            json={"clave_actual": "Equivocada1", "clave_nueva": "OtraClave123"},
        ).status_code
        == 400
    )
    assert (
        cliente.post(
            "/api/v1/auth/cambiar-clave",
            json={"clave_actual": "ClaveSegura123", "clave_nueva": "ClaveSegura123"},
        ).status_code
        == 422
    )

    r_chg = cliente.post(
        "/api/v1/auth/cambiar-clave",
        json={"clave_actual": "ClaveSegura123", "clave_nueva": "ClaveDefinitiva456"},
    )
    assert r_chg.status_code == 200
    assert cliente.get("/api/v1/usuarios").status_code == 200

    db.expire_all()
    otra_recargada = db.query(Sesion).filter(Sesion.id == otra_sesion.id).one()
    assert otra_recargada.revocada_en is not None


def test_crud_usuarios_roles_auditoria_e_importado(cliente: TestClient, db):
    crear_usuario_db(
        db,
        nombre_usuario="superadmin",
        correo="super@sapef.com",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano", "alcala"],
    )
    iniciar_sesion_cliente(cliente, "superadmin")

    roles = cliente.get("/api/v1/roles").json()["items"]
    rol_tecnico_id = next(r["id"] for r in roles if r["codigo"] == "TECNICO")

    # Crear usuario
    r_create = cliente.post(
        "/api/v1/usuarios",
        json={
            "nombre_usuario": "NuevoTecnico",
            "nombre_completo": "Pedro Pérez",
            "identificacion": "98765432",
            "correo": "pedro@sapef.com",
            "clave": "TecnicoClave99",
            "debe_cambiar_clave": False,
            "rol_id": rol_tecnico_id,
            "sede_ids": [1],
            "activo": True,
        },
    )
    assert r_create.status_code == 201
    creado = r_create.json()
    assert creado["nombre_usuario"] == "nuevotecnico"
    assert "hash_clave" not in r_create.text

    # Duplicado -> 409
    assert (
        cliente.post(
            "/api/v1/usuarios",
            json={
                "nombre_usuario": "nuevotecnico",
                "nombre_completo": "Otro",
                "identificacion": "111",
                "correo": "otro@sapef.com",
                "rol_id": rol_tecnico_id,
                "sede_ids": [1],
            },
        ).status_code
        == 409
    )

    # Detalle genera auditoría de consulta nominal
    r_det = cliente.get(f"/api/v1/usuarios/{creado['id']}")
    assert r_det.status_code == 200
    assert (
        db.query(AuditoriaConsulta)
        .filter(AuditoriaConsulta.recurso == "usuario.detalle")
        .count()
        == 1
    )

    # Editar usuario y verificar sanitización de auditoría
    r_patch = cliente.patch(
        f"/api/v1/usuarios/{creado['id']}",
        json={"nombre_completo": "Pedro Modificado", "clave": "NuevaClaveTec1"},
    )
    assert r_patch.status_code == 200
    assert r_patch.json()["nombre_completo"] == "Pedro Modificado"

    # Auditoría cambios nunca contiene hash_clave ni clave
    r_aud = cliente.get("/api/v1/auditoria?tipo=cambios")
    assert r_aud.status_code == 200
    assert "NuevaClaveTec1" not in r_aud.text
    assert "hash_clave" not in r_aud.text

    r_aud_q = cliente.get("/api/v1/auditoria?tipo=consultas")
    assert r_aud_q.status_code == 200
    assert r_aud_q.json()["total"] == 1

    # Crear rol + editar rol + listar permisos
    perms = cliente.get("/api/v1/permisos").json()
    assert len(perms) >= 10
    r_rol = cliente.post(
        "/api/v1/roles",
        json={
            "codigo": "SUPERVISOR",
            "nombre": "Supervisor",
            "permisos": ["activos.luminaria.ver", "campo.app.usar"],
        },
    )
    assert r_rol.status_code == 201
    rol_id = r_rol.json()["id"]
    assert (
        cliente.patch(
            f"/api/v1/roles/{rol_id}", json={"nombre": "Supervisor General"}
        ).status_code
        == 200
    )

    # Auto-desactivación -> 409
    yo_id = cliente.get("/api/v1/yo").json()["id"]
    assert cliente.patch(f"/api/v1/usuarios/{yo_id}", json={"activo": False}).status_code == 409

    # Upsert importado IMP-6 idempotente + listar_tecnicos_sede
    u_imp, fue_creado = seg_servicio.crear_o_actualizar_usuario_importado(
        db,
        nombre_usuario="tecnico_imp",
        nombre_completo="Técnico Importado",
        identificacion="5551234",
        correo="timp@sapef.com",
        rol_codigo="TECNICO",
        sede_ids=[1],
    )
    assert fue_creado is True
    assert u_imp.debe_cambiar_clave is True
    _, fue_creado_2 = seg_servicio.crear_o_actualizar_usuario_importado(
        db,
        nombre_usuario="tecnico_imp",
        nombre_completo="Técnico Importado Editado",
        identificacion="5551234",
        correo="timp@sapef.com",
        rol_codigo="TECNICO",
        sede_ids=[1],
    )
    assert fue_creado_2 is False

    tecnicos_mt = seg_servicio.listar_tecnicos_sede(db, 1)
    assert any(t.nombre_usuario == "tecnico_imp" for t in tecnicos_mt)
    assert seg_servicio.listar_tecnicos_sede(db, 2) == []


def test_c1_6_colision_cruzada_nombre_usuario_y_correo(cliente: TestClient, db):
    crear_usuario_db(
        db,
        nombre_usuario="admin_cruce",
        correo="admincruce@sapef.co",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano"],
    )
    iniciar_sesion_cliente(cliente, "admin_cruce")

    roles = cliente.get("/api/v1/roles").json()["items"]
    rol_tecnico_id = next(r["id"] for r in roles if r["codigo"] == "TECNICO")

    # Usuario 1 con '@' en nombre_usuario
    r_u1 = cliente.post(
        "/api/v1/usuarios",
        json={
            "nombre_usuario": "cruce@sapef.co",
            "nombre_completo": "Usuario Cruce Uno",
            "identificacion": "1001",
            "correo": "cruce_uno@sapef.co",
            "clave": "ClaveValida123",
            "debe_cambiar_clave": False,
            "rol_id": rol_tecnico_id,
            "sede_ids": [1],
        },
    )
    assert r_u1.status_code == 201

    # Intentar crear Usuario 2 con correo igual al nombre_usuario de Usuario 1 -> 409
    r_col_correo = cliente.post(
        "/api/v1/usuarios",
        json={
            "nombre_usuario": "cruce_dos",
            "nombre_completo": "Usuario Cruce Dos",
            "identificacion": "1002",
            "correo": "CRUCE@SAPEF.CO",
            "clave": "ClaveValida123",
            "debe_cambiar_clave": False,
            "rol_id": rol_tecnico_id,
            "sede_ids": [1],
        },
    )
    assert r_col_correo.status_code == 409

    # Crear Usuario 2 con correo propio válido -> 201
    r_u2 = cliente.post(
        "/api/v1/usuarios",
        json={
            "nombre_usuario": "cruce_dos",
            "nombre_completo": "Usuario Cruce Dos",
            "identificacion": "1002",
            "correo": "cruce_dos@sapef.co",
            "clave": "ClaveValida123",
            "debe_cambiar_clave": False,
            "rol_id": rol_tecnico_id,
            "sede_ids": [1],
        },
    )
    assert r_u2.status_code == 201
    u2_id = r_u2.json()["id"]

    # Intentar crear Usuario 3 con nombre_usuario igual al correo de Usuario 2 -> 409
    r_col_user = cliente.post(
        "/api/v1/usuarios",
        json={
            "nombre_usuario": "CRUCE_DOS@SAPEF.CO",
            "nombre_completo": "Usuario Cruce Tres",
            "identificacion": "1003",
            "correo": "cruce_tres@sapef.co",
            "clave": "ClaveValida123",
            "debe_cambiar_clave": False,
            "rol_id": rol_tecnico_id,
            "sede_ids": [1],
        },
    )
    assert r_col_user.status_code == 409

    # Intentar editar Usuario 2 para poner correo igual al nombre_usuario de Usuario 1 -> 409
    r_patch_col = cliente.patch(
        f"/api/v1/usuarios/{u2_id}",
        json={"correo": "CRUCE@SAPEF.CO"},
    )
    assert r_patch_col.status_code == 409

    # Importación IMP-6 rechaza colisiones cruzadas y correo duplicado sin IntegrityError
    with pytest.raises(HTTPException) as exc_imp_correo_col:
        seg_servicio.crear_o_actualizar_usuario_importado(
            db,
            nombre_usuario="imp_nuevo",
            nombre_completo="Imp Nuevo",
            identificacion="2001",
            correo="cruce@sapef.co",
            rol_codigo="TECNICO",
            sede_ids=[1],
        )
    assert exc_imp_correo_col.value.status_code == 409

    with pytest.raises(HTTPException) as exc_imp_user_col:
        seg_servicio.crear_o_actualizar_usuario_importado(
            db,
            nombre_usuario="cruce_dos@sapef.co",
            nombre_completo="Imp Col User",
            identificacion="2002",
            correo="imp_unico@sapef.co",
            rol_codigo="TECNICO",
            sede_ids=[1],
        )
    assert exc_imp_user_col.value.status_code == 409

    with pytest.raises(HTTPException) as exc_imp_upd_dup:
        seg_servicio.crear_o_actualizar_usuario_importado(
            db,
            nombre_usuario="cruce_dos",
            nombre_completo="Imp Duplicado",
            identificacion="1002",
            correo="cruce_uno@sapef.co",
            rol_codigo="TECNICO",
            sede_ids=[1],
        )
    assert exc_imp_upd_dup.value.status_code == 409

    # Si existiera colisión heredada en BD, el login nunca lanza 500 MultipleResultsFound
    crear_usuario_db(
        db,
        nombre_usuario="heredado_legado",
        correo="cruce@sapef.co",
        rol_codigo="TECNICO",
        sede_codigos=["montelibano"],
        clave="ClaveValida123",
    )
    r_login_exacto = cliente.post(
        "/api/v1/auth/ingresar",
        json={"usuario": "cruce@sapef.co", "clave": "ClaveValida123"},
    )
    assert r_login_exacto.status_code == 200
    assert r_login_exacto.json()["nombre_usuario"] == "cruce@sapef.co"


def test_asignar_rol_inactivo_retorna_422(cliente: TestClient, db):
    crear_usuario_db(
        db,
        nombre_usuario="admin_roles",
        correo="adminroles@sapef.co",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano"],
    )
    iniciar_sesion_cliente(cliente, "admin_roles")

    roles = cliente.get("/api/v1/roles").json()["items"]
    rol_tecnico_id = next(r["id"] for r in roles if r["codigo"] == "TECNICO")

    r_rol_inactivo = cliente.post(
        "/api/v1/roles",
        json={
            "codigo": "ROL_INACTIVO",
            "nombre": "Rol Inactivo",
            "activo": False,
            "permisos": ["activos.luminaria.ver"],
        },
    )
    assert r_rol_inactivo.status_code == 201
    rol_inactivo_id = r_rol_inactivo.json()["id"]

    # Crear usuario con rol inactivo -> 422
    r_crear = cliente.post(
        "/api/v1/usuarios",
        json={
            "nombre_usuario": "user_rol_inactivo",
            "nombre_completo": "Usuario Rol Inactivo",
            "identificacion": "3001",
            "correo": "rolinactivo@sapef.co",
            "clave": "ClaveValida123",
            "rol_id": rol_inactivo_id,
            "sede_ids": [1],
        },
    )
    assert r_crear.status_code == 422

    # Crear usuario con rol activo y luego intentar editarlo hacia rol inactivo -> 422
    r_crear_ok = cliente.post(
        "/api/v1/usuarios",
        json={
            "nombre_usuario": "user_rol_valido",
            "nombre_completo": "Usuario Rol Valido",
            "identificacion": "3002",
            "correo": "rolvalido@sapef.co",
            "clave": "ClaveValida123",
            "rol_id": rol_tecnico_id,
            "sede_ids": [1],
        },
    )
    assert r_crear_ok.status_code == 201
    user_id = r_crear_ok.json()["id"]

    r_editar = cliente.patch(
        f"/api/v1/usuarios/{user_id}",
        json={"rol_id": rol_inactivo_id},
    )
    assert r_editar.status_code == 422


def test_post_expiracion_bloqueo_reinicia_contador_al_primer_fallo(cliente: TestClient, db):
    usuario = crear_usuario_db(
        db,
        nombre_usuario="expira_bloqueo",
        correo="expirabloq@sapef.co",
        rol_codigo="TECNICO",
        sede_codigos=["montelibano"],
        clave="ClaveSegura123",
    )

    for i in range(4):
        r = cliente.post(
            "/api/v1/auth/ingresar",
            json={"usuario": "expira_bloqueo", "clave": f"MalaClave{i}"},
        )
        assert r.status_code == 401
    assert (
        cliente.post(
            "/api/v1/auth/ingresar",
            json={"usuario": "expira_bloqueo", "clave": "MalaClave4"},
        ).status_code
        == 423
    )

    # Simular expiración del bloqueo en BD
    u_db = db.query(Usuario).filter(Usuario.id == usuario.id).one()
    u_db.bloqueado_hasta = datetime.now(UTC) - timedelta(seconds=10)
    db.commit()

    # 1er intento fallido tras expirar debe reiniciar a 1/5 (401, no 423 inmediato)
    r_post_1 = cliente.post(
        "/api/v1/auth/ingresar",
        json={"usuario": "expira_bloqueo", "clave": "MalaClavePost1"},
    )
    assert r_post_1.status_code == 401
    db.expire_all()
    u_db = db.query(Usuario).filter(Usuario.id == usuario.id).one()
    assert u_db.intentos_fallidos == 1
    assert u_db.bloqueado_hasta is None

    # Intentos 2, 3, 4 -> 401; intento 5 -> 423
    for i in range(2, 5):
        r_mid = cliente.post(
            "/api/v1/auth/ingresar",
            json={"usuario": "expira_bloqueo", "clave": f"MalaClavePost{i}"},
        )
        assert r_mid.status_code == 401
    r_post_5 = cliente.post(
        "/api/v1/auth/ingresar",
        json={"usuario": "expira_bloqueo", "clave": "MalaClavePost5"},
    )
    assert r_post_5.status_code == 423
