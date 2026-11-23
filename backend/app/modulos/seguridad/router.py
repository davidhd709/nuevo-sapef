"""Rutas HTTP del módulo de seguridad (EP-01)."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.db import obtener_sesion
from app.core.logs import id_peticion
from app.modulos.seguridad import servicio
from app.modulos.seguridad.esquemas import (
    AceptarCondicionesEntrada,
    AuditoriaConsultaSalida,
    AuditoriaSalida,
    CambiarClaveEntrada,
    EstadoRenovacionSalida,
    IngresarEntrada,
    MensajeSalida,
    Pagina,
    PerfilActual,
    PermisoSalida,
    RecuperarClaveEntrada,
    RestablecerClaveEntrada,
    RolCrearEntrada,
    RolEditarEntrada,
    RolSalida,
    UsuarioAutenticado,
    UsuarioCrearEntrada,
    UsuarioEditarEntrada,
    UsuarioSalida,
)

router = APIRouter(tags=["seguridad"])


def _ip_cliente(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post(
    "/auth/ingresar",
    response_model=PerfilActual,
    summary="Iniciar sesión con usuario y contraseña",
)
def ingresar(
    entrada: IngresarEntrada,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(obtener_sesion)],
) -> PerfilActual:
    perfil, token_acceso, token_renovacion = servicio.autenticar_usuario(
        db,
        entrada,
        agente=request.headers.get("User-Agent"),
        ip=_ip_cliente(request),
    )
    servicio.aplicar_cookies_sesion(
        response, token_acceso, token_renovacion, entrada.tipo_cliente
    )
    return perfil


@router.post(
    "/auth/renovar",
    response_model=EstadoRenovacionSalida,
    summary="Rotar cookies de acceso y renovación",
)
def renovar(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(obtener_sesion)],
) -> EstadoRenovacionSalida | JSONResponse:
    token_renovacion = request.cookies.get(servicio.COOKIE_RENOVACION)
    try:
        estado, nuevo_acceso, nuevo_refresh, tipo_cliente = servicio.renovar_sesion(
            db,
            token_renovacion,
            agente=request.headers.get("User-Agent"),
            ip=_ip_cliente(request),
        )
    except servicio.ErrorRenovarSesion as exc:
        cuerpo = {
            "type": "about:blank",
            "title": "Unauthorized",
            "status": 401,
            "detail": exc.detail,
        }
        if (rid := id_peticion.get()) is not None:
            cuerpo["requestId"] = rid
        error_resp = JSONResponse(
            cuerpo, status_code=401, media_type="application/problem+json"
        )
        if exc.limpiar_cookies:
            servicio.limpiar_cookies_sesion(error_resp)
        return error_resp

    servicio.aplicar_cookies_sesion(response, nuevo_acceso, nuevo_refresh, tipo_cliente)
    return estado


@router.post(
    "/auth/salir",
    status_code=204,
    summary="Cerrar sesión y revocar la familia de tokens",
)
def salir(
    request: Request,
    db: Annotated[Session, Depends(obtener_sesion)],
) -> Response:
    servicio.cerrar_sesion(
        db,
        request.cookies.get(servicio.COOKIE_RENOVACION),
        request.cookies.get(servicio.COOKIE_ACCESO),
    )
    respuesta = Response(status_code=204)
    servicio.limpiar_cookies_sesion(respuesta)
    return respuesta


@router.post(
    "/auth/recuperar",
    response_model=MensajeSalida,
    status_code=202,
    summary="Solicitar recuperación de contraseña (respuesta neutra)",
)
async def recuperar(
    entrada: RecuperarClaveEntrada,
    request: Request,
    db: Annotated[Session, Depends(obtener_sesion)],
) -> MensajeSalida:
    return await servicio.solicitar_recuperacion_clave(
        db, entrada, ip=_ip_cliente(request)
    )


@router.post(
    "/auth/restablecer",
    response_model=MensajeSalida,
    summary="Restablecer contraseña usando un token de un solo uso",
)
def restablecer(
    entrada: RestablecerClaveEntrada,
    db: Annotated[Session, Depends(obtener_sesion)],
) -> MensajeSalida:
    return servicio.restablecer_clave(db, entrada)


@router.post(
    "/auth/cambiar-clave",
    response_model=MensajeSalida,
    summary="Cambiar contraseña de la cuenta autenticada",
)
def cambiar_clave(
    entrada: CambiarClaveEntrada,
    usuario: Annotated[UsuarioAutenticado, Depends(servicio.requerir_usuario_sesion_abierta)],
    db: Annotated[Session, Depends(obtener_sesion)],
) -> MensajeSalida:
    return servicio.cambiar_clave(db, usuario, entrada)


@router.post(
    "/auth/aceptar-condiciones",
    response_model=PerfilActual,
    summary="Registrar aceptación de términos y condiciones",
)
def aceptar_condiciones(
    usuario: Annotated[UsuarioAutenticado, Depends(servicio.requerir_usuario_sesion_abierta)],
    db: Annotated[Session, Depends(obtener_sesion)],
    entrada: AceptarCondicionesEntrada | None = None,
) -> PerfilActual:
    acepto = entrada.acepto if entrada is not None else True
    return servicio.aceptar_condiciones(db, usuario, acepto)


@router.get(
    "/yo",
    response_model=PerfilActual,
    summary="Obtener perfil, rol, permisos y sedes del usuario autenticado",
)
def yo(
    usuario: Annotated[UsuarioAutenticado, Depends(servicio.requerir_usuario_sesion_abierta)],
    db: Annotated[Session, Depends(obtener_sesion)],
) -> PerfilActual:
    return servicio.obtener_perfil(db, usuario)


@router.get(
    "/usuarios",
    response_model=Pagina[UsuarioSalida],
    summary="Listar usuarios con filtros paginados",
)
def listar_usuarios(
    _: Annotated[UsuarioAutenticado, Depends(servicio.requerir_permiso("seguridad.usuario.ver"))],
    db: Annotated[Session, Depends(obtener_sesion)],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    buscar: str | None = None,
    activo: bool | None = None,
    rol_id: int | None = None,
    sede_id: int | None = None,
) -> Pagina[UsuarioSalida]:
    return servicio.listar_usuarios_paginado(
        db,
        page=page,
        size=size,
        buscar=buscar,
        activo=activo,
        rol_id=rol_id,
        sede_id=sede_id,
    )


@router.post(
    "/usuarios",
    response_model=UsuarioSalida,
    status_code=201,
    summary="Crear un usuario y asignarle rol y sedes",
)
def crear_usuario(
    entrada: UsuarioCrearEntrada,
    actor: Annotated[
        UsuarioAutenticado, Depends(servicio.requerir_permiso("seguridad.usuario.crear"))
    ],
    db: Annotated[Session, Depends(obtener_sesion)],
) -> UsuarioSalida:
    return servicio.crear_usuario(db, actor, entrada)


@router.get(
    "/usuarios/{usuario_id}",
    response_model=UsuarioSalida,
    summary="Consultar detalle de un usuario",
)
def obtener_usuario(
    usuario_id: int,
    actor: Annotated[
        UsuarioAutenticado, Depends(servicio.requerir_permiso("seguridad.usuario.ver"))
    ],
    db: Annotated[Session, Depends(obtener_sesion)],
) -> UsuarioSalida:
    return servicio.obtener_usuario_detalle(db, actor, usuario_id)


@router.patch(
    "/usuarios/{usuario_id}",
    response_model=UsuarioSalida,
    summary="Editar usuario, rol, sedes o estado activo",
)
def editar_usuario(
    usuario_id: int,
    entrada: UsuarioEditarEntrada,
    actor: Annotated[
        UsuarioAutenticado, Depends(servicio.requerir_permiso("seguridad.usuario.editar"))
    ],
    db: Annotated[Session, Depends(obtener_sesion)],
) -> UsuarioSalida:
    return servicio.editar_usuario(db, actor, usuario_id, entrada)


@router.get(
    "/roles",
    response_model=Pagina[RolSalida],
    summary="Listar roles y sus permisos asociados",
)
def listar_roles(
    _: Annotated[UsuarioAutenticado, Depends(servicio.requerir_permiso("seguridad.rol.ver"))],
    db: Annotated[Session, Depends(obtener_sesion)],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 50,
    activo: bool | None = None,
) -> Pagina[RolSalida]:
    return servicio.listar_roles_paginado(db, page=page, size=size, activo=activo)


@router.post(
    "/roles",
    response_model=RolSalida,
    status_code=201,
    summary="Crear un rol con permisos granulares",
)
def crear_rol(
    entrada: RolCrearEntrada,
    actor: Annotated[
        UsuarioAutenticado, Depends(servicio.requerir_permiso("seguridad.rol.editar"))
    ],
    db: Annotated[Session, Depends(obtener_sesion)],
) -> RolSalida:
    return servicio.crear_rol(db, actor, entrada)


@router.get(
    "/roles/{rol_id}",
    response_model=RolSalida,
    summary="Consultar un rol por identificador",
)
def obtener_rol(
    rol_id: int,
    _: Annotated[UsuarioAutenticado, Depends(servicio.requerir_permiso("seguridad.rol.ver"))],
    db: Annotated[Session, Depends(obtener_sesion)],
) -> RolSalida:
    return servicio.obtener_rol_detalle(db, rol_id)


@router.patch(
    "/roles/{rol_id}",
    response_model=RolSalida,
    summary="Editar un rol y su conjunto de permisos",
)
def editar_rol(
    rol_id: int,
    entrada: RolEditarEntrada,
    actor: Annotated[
        UsuarioAutenticado, Depends(servicio.requerir_permiso("seguridad.rol.editar"))
    ],
    db: Annotated[Session, Depends(obtener_sesion)],
) -> RolSalida:
    return servicio.editar_rol(db, actor, rol_id, entrada)


@router.get(
    "/permisos",
    response_model=list[PermisoSalida],
    summary="Listar permisos disponibles en el sistema",
)
def listar_permisos(
    _: Annotated[UsuarioAutenticado, Depends(servicio.requerir_permiso("seguridad.rol.ver"))],
    db: Annotated[Session, Depends(obtener_sesion)],
) -> list[PermisoSalida]:
    return servicio.listar_permisos_disponibles(db)


@router.get(
    "/auditoria",
    response_model=Pagina[AuditoriaSalida] | Pagina[AuditoriaConsultaSalida],
    summary="Consultar bitácora de cambios y consultas nominales",
)
def listar_auditoria(
    _: Annotated[
        UsuarioAutenticado, Depends(servicio.requerir_permiso("seguridad.auditoria.ver"))
    ],
    db: Annotated[Session, Depends(obtener_sesion)],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    tipo: Literal["cambios", "consultas"] = "cambios",
    entidad: str | None = None,
    usuario_id: int | None = None,
    sede_id: int | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
) -> Pagina[AuditoriaSalida] | Pagina[AuditoriaConsultaSalida]:
    return servicio.listar_auditoria_paginada(
        db,
        page=page,
        size=size,
        tipo=tipo,
        entidad=entidad,
        usuario_id=usuario_id,
        sede_id=sede_id,
        desde=desde,
        hasta=hasta,
    )
