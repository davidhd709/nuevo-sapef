"""Repositorio SQLAlchemy del módulo de seguridad (consultas y persistencia)."""

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.modulos.seguridad.esquemas import SedeResumen
from app.modulos.seguridad.modelos import (
    Auditoria,
    AuditoriaConsulta,
    Permiso,
    Rol,
    Sesion,
    TokenRecuperacion,
    Usuario,
    UsuarioSede,
)

# Tabla sede referenciada por SQLAlchemy Core para no importar configuracion.modelos.
_TABLA_SEDE = sa.table(
    "sede",
    sa.column("id", sa.BigInteger),
    sa.column("codigo", sa.String),
    sa.column("nombre", sa.String),
    sa.column("activa", sa.Boolean),
)


def obtener_sede_por_codigo(db: Session, codigo: str) -> tuple[SedeResumen, bool] | None:
    stmt = select(
        _TABLA_SEDE.c.id,
        _TABLA_SEDE.c.codigo,
        _TABLA_SEDE.c.nombre,
        _TABLA_SEDE.c.activa,
    ).where(func.lower(_TABLA_SEDE.c.codigo) == codigo.strip().lower())
    fila = db.execute(stmt).one_or_none()
    if fila is None:
        return None
    return SedeResumen(id=fila.id, codigo=fila.codigo, nombre=fila.nombre), bool(fila.activa)


def listar_ids_sedes_activas(db: Session) -> list[int]:
    stmt = select(_TABLA_SEDE.c.id).where(_TABLA_SEDE.c.activa.is_(True)).order_by(
        _TABLA_SEDE.c.id
    )
    return [int(i) for i in db.execute(stmt).scalars().all()]


def obtener_sedes_por_ids(db: Session, sede_ids: list[int]) -> list[tuple[SedeResumen, bool]]:
    if not sede_ids:
        return []
    stmt = (
        select(
            _TABLA_SEDE.c.id,
            _TABLA_SEDE.c.codigo,
            _TABLA_SEDE.c.nombre,
            _TABLA_SEDE.c.activa,
        )
        .where(_TABLA_SEDE.c.id.in_(sede_ids))
        .order_by(_TABLA_SEDE.c.id)
    )
    return [
        (SedeResumen(id=f.id, codigo=f.codigo, nombre=f.nombre), bool(f.activa))
        for f in db.execute(stmt).all()
    ]


def obtener_usuario_por_identificador(db: Session, identificador: str) -> Usuario | None:
    ident = identificador.strip().lower()
    stmt = (
        select(Usuario)
        .options(
            selectinload(Usuario.rol).selectinload(Rol.permisos),
            selectinload(Usuario.sedes_asignadas),
        )
        .where(
            or_(
                func.lower(Usuario.nombre_usuario) == ident,
                func.lower(Usuario.correo) == ident,
            )
        )
        .order_by(Usuario.id.asc())
    )
    usuarios = list(db.execute(stmt).scalars().all())
    if not usuarios:
        return None
    for usuario in usuarios:
        if usuario.nombre_usuario.strip().lower() == ident:
            return usuario
    return usuarios[0]


def obtener_usuario_por_correo(db: Session, correo: str) -> Usuario | None:
    stmt = (
        select(Usuario)
        .options(
            selectinload(Usuario.rol).selectinload(Rol.permisos),
            selectinload(Usuario.sedes_asignadas),
        )
        .where(func.lower(Usuario.correo) == correo.strip().lower())
    )
    return db.execute(stmt).scalar_one_or_none()


def obtener_usuario_por_nombre_usuario(db: Session, nombre_usuario: str) -> Usuario | None:
    stmt = (
        select(Usuario)
        .options(
            selectinload(Usuario.rol).selectinload(Rol.permisos),
            selectinload(Usuario.sedes_asignadas),
        )
        .where(func.lower(Usuario.nombre_usuario) == nombre_usuario.strip().lower())
    )
    return db.execute(stmt).scalar_one_or_none()


def obtener_usuario_por_id(db: Session, usuario_id: int) -> Usuario | None:
    stmt = (
        select(Usuario)
        .options(
            selectinload(Usuario.rol).selectinload(Rol.permisos),
            selectinload(Usuario.sedes_asignadas),
        )
        .where(Usuario.id == usuario_id)
    )
    return db.execute(stmt).scalar_one_or_none()


def listar_usuarios(
    db: Session,
    *,
    page: int,
    size: int,
    buscar: str | None = None,
    activo: bool | None = None,
    rol_id: int | None = None,
    sede_id: int | None = None,
) -> tuple[list[Usuario], int]:
    filtros = []
    if buscar:
        patron = f"%{buscar.strip().lower()}%"
        filtros.append(
            or_(
                func.lower(Usuario.nombre_usuario).like(patron),
                func.lower(Usuario.nombre_completo).like(patron),
                func.lower(Usuario.correo).like(patron),
                func.lower(Usuario.identificacion).like(patron),
            )
        )
    if activo is not None:
        filtros.append(Usuario.activo == activo)
    if rol_id is not None:
        filtros.append(Usuario.rol_id == rol_id)
    if sede_id is not None:
        subq = select(UsuarioSede.usuario_id).where(UsuarioSede.sede_id == sede_id)
        filtros.append(Usuario.id.in_(subq))

    conteo_stmt = select(func.count(Usuario.id)).where(*filtros)
    total = int(db.execute(conteo_stmt).scalar_one())

    stmt = (
        select(Usuario)
        .options(
            selectinload(Usuario.rol).selectinload(Rol.permisos),
            selectinload(Usuario.sedes_asignadas),
        )
        .where(*filtros)
        .order_by(Usuario.id.asc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = list(db.execute(stmt).scalars().all())
    return items, total


def listar_tecnicos_sede(db: Session, sede_id: int) -> list[Usuario]:
    stmt = (
        select(Usuario)
        .join(UsuarioSede, UsuarioSede.usuario_id == Usuario.id)
        .join(Rol, Rol.id == Usuario.rol_id)
        .options(selectinload(Usuario.rol))
        .where(
            UsuarioSede.sede_id == sede_id,
            Usuario.activo.is_(True),
            Rol.activo.is_(True),
            func.upper(Rol.codigo) == "TECNICO",
        )
        .order_by(Usuario.nombre_completo.asc())
    )
    return list(db.execute(stmt).scalars().all())


def reemplazar_sedes_usuario(db: Session, usuario: Usuario, sede_ids: list[int]) -> None:
    unicas = list(dict.fromkeys(sede_ids))
    usuario.sedes_asignadas.clear()
    db.flush()
    for sid in unicas:
        usuario.sedes_asignadas.append(UsuarioSede(usuario_id=usuario.id, sede_id=sid))
    db.flush()


def obtener_sesion_por_id(db: Session, sesion_id: UUID) -> Sesion | None:
    return db.execute(select(Sesion).where(Sesion.id == sesion_id)).scalar_one_or_none()


def obtener_sesion_por_hash(db: Session, hash_token: str) -> Sesion | None:
    return db.execute(
        select(Sesion).where(Sesion.hash_token_renovacion == hash_token)
    ).scalar_one_or_none()


def revocar_familia_sesiones(db: Session, familia: UUID, ahora: datetime) -> None:
    db.execute(
        update(Sesion)
        .where(Sesion.familia == familia, Sesion.revocada_en.is_(None))
        .values(revocada_en=ahora)
    )


def revocar_sesiones_usuario(
    db: Session, usuario_id: int, ahora: datetime, excluir_sesion_id: UUID | None = None
) -> None:
    condiciones = [Sesion.usuario_id == usuario_id, Sesion.revocada_en.is_(None)]
    if excluir_sesion_id is not None:
        condiciones.append(Sesion.id != excluir_sesion_id)
    db.execute(update(Sesion).where(*condiciones).values(revocada_en=ahora))


def obtener_token_recuperacion_por_hash(db: Session, hash_token: str) -> TokenRecuperacion | None:
    return db.execute(
        select(TokenRecuperacion).where(TokenRecuperacion.hash_token == hash_token)
    ).scalar_one_or_none()


def obtener_token_recuperacion_por_id(db: Session, token_id: UUID) -> TokenRecuperacion | None:
    return db.execute(
        select(TokenRecuperacion).where(TokenRecuperacion.id == token_id)
    ).scalar_one_or_none()


def obtener_rol_por_id(db: Session, rol_id: int) -> Rol | None:
    stmt = select(Rol).options(selectinload(Rol.permisos)).where(Rol.id == rol_id)
    return db.execute(stmt).scalar_one_or_none()


def obtener_rol_por_codigo(db: Session, codigo: str) -> Rol | None:
    stmt = (
        select(Rol)
        .options(selectinload(Rol.permisos))
        .where(func.upper(Rol.codigo) == codigo.strip().upper())
    )
    return db.execute(stmt).scalar_one_or_none()


def listar_roles(
    db: Session, *, page: int, size: int, activo: bool | None = None
) -> tuple[list[Rol], int]:
    filtros = []
    if activo is not None:
        filtros.append(Rol.activo == activo)
    total = int(db.execute(select(func.count(Rol.id)).where(*filtros)).scalar_one())
    stmt = (
        select(Rol)
        .options(selectinload(Rol.permisos))
        .where(*filtros)
        .order_by(Rol.id.asc())
        .offset((page - 1) * size)
        .limit(size)
    )
    return list(db.execute(stmt).scalars().all()), total


def listar_permisos(db: Session) -> list[Permiso]:
    return list(db.execute(select(Permiso).order_by(Permiso.codigo.asc())).scalars().all())


def obtener_permisos_por_codigos(db: Session, codigos: list[str]) -> list[Permiso]:
    if not codigos:
        return []
    return list(db.execute(select(Permiso).where(Permiso.codigo.in_(codigos))).scalars().all())


def crear_auditoria(
    db: Session,
    *,
    usuario_id: int | None,
    sede_id: int | None,
    accion: str,
    entidad: str,
    entidad_id: str,
    antes: dict[str, Any] | None,
    despues: dict[str, Any] | None,
    request_id: str | None,
) -> Auditoria:
    registro = Auditoria(
        usuario_id=usuario_id,
        sede_id=sede_id,
        accion=accion,
        entidad=entidad,
        entidad_id=entidad_id,
        antes=antes,
        despues=despues,
        request_id=request_id,
    )
    db.add(registro)
    return registro


def crear_auditoria_consulta(
    db: Session,
    *,
    usuario_id: int,
    sede_id: int | None,
    recurso: str,
    parametros_permitidos: dict[str, Any],
    request_id: str | None,
) -> AuditoriaConsulta:
    registro = AuditoriaConsulta(
        usuario_id=usuario_id,
        sede_id=sede_id,
        recurso=recurso,
        parametros_permitidos=parametros_permitidos,
        request_id=request_id,
    )
    db.add(registro)
    return registro


def listar_auditoria_cambios(
    db: Session,
    *,
    page: int,
    size: int,
    entidad: str | None = None,
    usuario_id: int | None = None,
    sede_id: int | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
) -> tuple[list[Auditoria], int]:
    filtros = []
    if entidad:
        filtros.append(Auditoria.entidad == entidad)
    if usuario_id is not None:
        filtros.append(Auditoria.usuario_id == usuario_id)
    if sede_id is not None:
        filtros.append(Auditoria.sede_id == sede_id)
    if desde is not None:
        filtros.append(Auditoria.instante >= desde)
    if hasta is not None:
        filtros.append(Auditoria.instante <= hasta)

    total = int(db.execute(select(func.count(Auditoria.id)).where(*filtros)).scalar_one())
    stmt = (
        select(Auditoria)
        .where(*filtros)
        .order_by(Auditoria.instante.desc(), Auditoria.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    return list(db.execute(stmt).scalars().all()), total


def listar_auditoria_consultas(
    db: Session,
    *,
    page: int,
    size: int,
    usuario_id: int | None = None,
    sede_id: int | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
) -> tuple[list[AuditoriaConsulta], int]:
    filtros = []
    if usuario_id is not None:
        filtros.append(AuditoriaConsulta.usuario_id == usuario_id)
    if sede_id is not None:
        filtros.append(AuditoriaConsulta.sede_id == sede_id)
    if desde is not None:
        filtros.append(AuditoriaConsulta.instante >= desde)
    if hasta is not None:
        filtros.append(AuditoriaConsulta.instante <= hasta)

    total = int(db.execute(select(func.count(AuditoriaConsulta.id)).where(*filtros)).scalar_one())
    stmt = (
        select(AuditoriaConsulta)
        .where(*filtros)
        .order_by(AuditoriaConsulta.instante.desc(), AuditoriaConsulta.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    return list(db.execute(stmt).scalars().all()), total
