"""Pruebas de aislamiento estricto por sede, sesión y permisos RBAC (M1.1)."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.modulos.seguridad import servicio as seg_servicio
from tests.conftest import crear_usuario_db, iniciar_sesion_cliente

PNG_MINIMO = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"


def test_sin_sesion_y_cookie_manipulada_retornan_401(cliente: TestClient, db):
    assert cliente.get("/api/v1/yo").status_code == 401
    assert cliente.get("/api/v1/usuarios").status_code == 401

    cliente.cookies.set("sapef_acceso", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.invalida")
    assert cliente.get("/api/v1/yo").status_code == 401


def test_rbac_deniega_con_403_sin_permiso(cliente: TestClient, db):
    crear_usuario_db(
        db,
        nombre_usuario="lector1",
        correo="lector@sapef.com",
        rol_codigo="LECTOR",
        sede_codigos=["montelibano"],
    )
    iniciar_sesion_cliente(cliente, "lector1")

    assert cliente.get("/api/v1/usuarios").status_code == 403
    assert cliente.get("/api/v1/roles").status_code == 403
    assert cliente.get("/api/v1/permisos").status_code == 403
    assert cliente.get("/api/v1/auditoria").status_code == 403
    assert (
        cliente.post(
            "/api/v1/archivos",
            headers={"X-Sede": "montelibano"},
            files={"archivo": ("p.png", PNG_MINIMO, "image/png")},
        ).status_code
        == 403
    )


def test_x_sede_faltante_inexistente_inactiva_y_ajena(cliente: TestClient, db):
    crear_usuario_db(
        db,
        nombre_usuario="user_mt",
        correo="mt@sapef.com",
        rol_codigo="TECNICO",
        sede_codigos=["montelibano"],
    )
    iniciar_sesion_cliente(cliente, "user_mt")

    # Sin X-Sede -> 400
    r_sin = cliente.post(
        "/api/v1/archivos",
        files={"archivo": ("p.png", PNG_MINIMO, "image/png")},
    )
    assert r_sin.status_code == 400

    # Sede inexistente o no asignada o inactiva -> 403
    for sede in ("alcala", "noexiste", "inactiva"):
        r_forb = cliente.post(
            "/api/v1/archivos",
            headers={"X-Sede": sede},
            files={"archivo": ("p.png", PNG_MINIMO, "image/png")},
        )
        assert r_forb.status_code == 403


def test_aislamiento_cruzado_archivos_entre_montelibano_y_alcala(cliente: TestClient, db):
    crear_usuario_db(
        db,
        nombre_usuario="tec_mt",
        correo="tecmt@sapef.com",
        rol_codigo="TECNICO",
        sede_codigos=["montelibano"],
    )
    crear_usuario_db(
        db,
        nombre_usuario="tec_al",
        correo="tecal@sapef.com",
        rol_codigo="TECNICO",
        sede_codigos=["alcala"],
    )

    # Montelíbano sube archivo
    iniciar_sesion_cliente(cliente, "tec_mt")
    r_up = cliente.post(
        "/api/v1/archivos",
        headers={"X-Sede": "montelibano"},
        files={"archivo": ("evidencia_mt.png", PNG_MINIMO, "image/png")},
    )
    assert r_up.status_code == 201
    archivo_id = r_up.json()["id"]

    # Usuario de Alcalá intenta descargarlo o ver sus metadatos usando X-Sede: alcala -> 403
    iniciar_sesion_cliente(cliente, "tec_al")
    assert (
        cliente.get(
            f"/api/v1/archivos/{archivo_id}", headers={"X-Sede": "alcala"}
        ).status_code
        == 403
    )
    assert (
        cliente.get(
            f"/api/v1/archivos/{archivo_id}/metadatos", headers={"X-Sede": "alcala"}
        ).status_code
        == 403
    )
    # Tampoco puede usar X-Sede: montelibano -> 403
    assert (
        cliente.get(
            f"/api/v1/archivos/{archivo_id}", headers={"X-Sede": "montelibano"}
        ).status_code
        == 403
    )


def test_tablero_alcance_consolidado_y_permiso(cliente: TestClient, db):
    crear_usuario_db(
        db,
        nombre_usuario="admin_solo_mt",
        correo="admmt@sapef.com",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano"],
    )
    crear_usuario_db(
        db,
        nombre_usuario="tec_sin_consolidado",
        correo="tecsin@sapef.com",
        rol_codigo="TECNICO",
        sede_codigos=["montelibano", "alcala"],
    )

    iniciar_sesion_cliente(cliente, "admin_solo_mt")
    auth_admin = seg_servicio.obtener_sesion_actual(db, cliente.cookies.get("sapef_acceso"))
    sedes_admin = seg_servicio.requerir_tablero_alcance(
        usuario=auth_admin, db=db, sede="todas", x_sede=None
    )
    assert [s.codigo for s in sedes_admin] == ["montelibano"]

    iniciar_sesion_cliente(cliente, "tec_sin_consolidado")
    auth_tec = seg_servicio.obtener_sesion_actual(db, cliente.cookies.get("sapef_acceso"))
    with pytest.raises(HTTPException) as exc:
        seg_servicio.requerir_tablero_alcance(
            usuario=auth_tec, db=db, sede="todas", x_sede=None
        )
    assert exc.value.status_code == 403
