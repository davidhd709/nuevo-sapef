"""Fixtures compartidas para pruebas unitarias, integración (PostgreSQL/PostGIS) y aislamiento."""

import io
import shutil
import uuid
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import obtener_configuracion
from app.core.db import _fabrica_sesiones, obtener_motor
from app.main import crear_app
from app.modulos.activos import servicio as activos_servicio
from app.modulos.configuracion import servicio as configuracion_servicio
from app.modulos.configuracion.modelos import Sede
from app.modulos.seguridad import servicio as seguridad_servicio
from app.modulos.seguridad.modelos import Permiso, Rol, RolPermiso, Usuario, UsuarioSede

PERMISOS_BASE = [
    ("seguridad.usuario.ver", "seguridad", "Ver usuarios"),
    ("seguridad.usuario.crear", "seguridad", "Crear usuarios"),
    ("seguridad.usuario.editar", "seguridad", "Editar usuarios"),
    ("seguridad.usuario.desactivar", "seguridad", "Desactivar usuarios"),
    ("seguridad.rol.ver", "seguridad", "Ver roles y permisos"),
    ("seguridad.rol.editar", "seguridad", "Crear y editar roles"),
    ("seguridad.auditoria.ver", "seguridad", "Consultar auditoría"),
    ("campo.app.usar", "campo", "Usar app de campo y cargar evidencias"),
    ("tablero.consolidado.ver", "tablero", "Consultar tablero consolidado"),
    ("activos.luminaria.ver", "activos", "Consultar luminarias"),
]


@pytest.fixture
def almacen_temporal(monkeypatch):
    base_tmp = Path(__file__).resolve().parent.parent / ".pytest_cache" / "archivos_tmp"
    ruta = base_tmp / uuid.uuid4().hex
    ruta.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SAPEF_ARCHIVOS_DIR", str(ruta))
    obtener_configuracion.cache_clear()
    try:
        yield ruta
    finally:
        obtener_configuracion.cache_clear()
        shutil.rmtree(ruta, ignore_errors=True)


@pytest.fixture
def db(almacen_temporal) -> Iterator[Session]:
    motor = obtener_motor()
    tablas = (
        "cargue_comercial, hallazgo_comercial, "
        "operacion_campo, suscripcion_push, orden_asignacion, "
        "orden_mantenimiento, orden_instalacion, orden_luminaria, orden_trabajo, cargue_masivo, "
        "cuadrilla_tecnico, cuadrilla, pqrs_luminaria, pqrs, ciudadano, "
        "movimiento_material, material, cargue_bodega, "
        "ejecucion_migracion, evento_activo, luminaria_ubicacion, luminaria, lote, "
        "operacion_contable, concepto_comercial, acuerdo_excepcion, acuerdo_tarifa, "
        "acuerdo_vigencia, plantilla_correo, parametro, estado, barrio, zona, maestro_valor, "
        "maestro_clase, sede_comercializador, comercializador, "
        "evidencia, archivo, auditoria_consulta, auditoria, token_recuperacion, "
        "sesion, usuario_sede, usuario, rol_permiso, rol, permiso, sede"
    )
    with motor.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {tablas} RESTART IDENTITY CASCADE"))
        conn.execute(text("DELETE FROM procrastinate_events"))
        conn.execute(text("DELETE FROM procrastinate_jobs"))

    sesion = _fabrica_sesiones()()
    try:
        sede_mt = Sede(
            codigo="montelibano",
            nombre="Montelíbano",
            municipio="Montelíbano",
            departamento="Córdoba",
            activa=True,
        )
        sede_al = Sede(
            codigo="alcala",
            nombre="Alcalá",
            municipio="Alcalá",
            departamento="Valle del Cauca",
            activa=True,
        )
        sede_inactiva = Sede(
            codigo="inactiva",
            nombre="Sede Inactiva",
            municipio="Prueba",
            departamento="Prueba",
            activa=False,
        )
        sesion.add_all([sede_mt, sede_al, sede_inactiva])

        permisos_objs: dict[str, Permiso] = {}
        for codigo, modulo, desc in PERMISOS_BASE:
            p = Permiso(codigo=codigo, modulo=modulo, descripcion=desc)
            sesion.add(p)
            permisos_objs[codigo] = p
        sesion.flush()

        rol_admin = Rol(codigo="ADMIN", nombre="Administrador", activo=True)
        rol_tecnico = Rol(codigo="TECNICO", nombre="Técnico de campo", activo=True)
        rol_lector = Rol(codigo="LECTOR", nombre="Solo lectura", activo=True)
        sesion.add_all([rol_admin, rol_tecnico, rol_lector])
        sesion.flush()

        for p in permisos_objs.values():
            sesion.add(RolPermiso(rol_id=rol_admin.id, permiso_id=p.id))
        sesion.add(
            RolPermiso(rol_id=rol_tecnico.id, permiso_id=permisos_objs["campo.app.usar"].id)
        )
        sesion.add(
            RolPermiso(
                rol_id=rol_lector.id, permiso_id=permisos_objs["activos.luminaria.ver"].id
            )
        )
        sesion.commit()
        yield sesion
    finally:
        sesion.close()


@pytest.fixture
def db_configurado(db: Session) -> Session:
    """`db` más la semilla real: catálogos de configuración, permisos §4.3, roles §4.2 y comodín."""
    configuracion_servicio.sembrar_catalogos(db, archivo_max_evidencia_mb=10)
    seguridad_servicio.sincronizar_permisos_y_roles(db)
    activos_servicio.sembrar_comodines_activos(db)
    db.commit()
    return db


@pytest.fixture
def cliente(db) -> Iterator[TestClient]:
    app = crear_app()
    with TestClient(app) as c:
        yield c


def crear_usuario_db(
    db: Session,
    *,
    nombre_usuario: str,
    correo: str,
    rol_codigo: str,
    sede_codigos: list[str],
    clave: str | None = "ClaveSegura123",
    debe_cambiar_clave: bool = False,
    activo: bool = True,
    acepto_condiciones: bool = True,
) -> Usuario:
    rol = db.execute(
        text("SELECT id FROM rol WHERE codigo = :c"), {"c": rol_codigo}
    ).scalar_one()
    sede_ids = [
        db.execute(text("SELECT id FROM sede WHERE codigo = :c"), {"c": sc}).scalar_one()
        for sc in sede_codigos
    ]
    hash_clave = seguridad_servicio._ph.hash(clave) if clave is not None else None
    usuario = Usuario(
        nombre_usuario=nombre_usuario.lower(),
        nombre_completo=f"Usuario {nombre_usuario}",
        identificacion="10000001",
        correo=correo.lower(),
        hash_clave=hash_clave,
        debe_cambiar_clave=debe_cambiar_clave,
        acepto_condiciones_en=datetime.now(UTC) if acepto_condiciones else None,
        activo=activo,
        rol_id=rol,
    )
    db.add(usuario)
    db.flush()
    for sid in sede_ids:
        db.add(UsuarioSede(usuario_id=usuario.id, sede_id=sid))
    db.commit()
    db.refresh(usuario)
    return usuario


def iniciar_sesion_cliente(
    cliente: TestClient,
    usuario: str,
    clave: str = "ClaveSegura123",
    tipo_cliente: str = "web",
) -> None:
    resp = cliente.post(
        "/api/v1/auth/ingresar",
        json={"usuario": usuario, "clave": clave, "tipo_cliente": tipo_cliente},
    )
    assert resp.status_code == 200, resp.text


def construir_xlsx_minimo_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types></Types>")
        zf.writestr("xl/workbook.xml", "<workbook></workbook>")
    return buf.getvalue()
