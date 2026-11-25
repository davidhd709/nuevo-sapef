"""Capa de servicio público de seguridad: autenticación, sesiones, RBAC, sedes y auditoría."""

import contextlib
import logging
import secrets
import smtplib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Annotated, Any
from uuid import UUID, uuid4

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Header, HTTPException, Query, Request, Response
from procrastinate.exceptions import AppNotOpen
from sqlalchemy.orm import Session

from app.core.config import obtener_configuracion
from app.core.db import obtener_motor, obtener_sesion
from app.core.logs import id_peticion, sede_log, usuario_log
from app.core.tareas import app_tareas
from app.modulos.seguridad import datos_semilla, dominio, repositorio
from app.modulos.seguridad.esquemas import (
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
    RolResumen,
    RolSalida,
    SedeResumen,
    UsuarioAutenticado,
    UsuarioCrearEntrada,
    UsuarioEditarEntrada,
    UsuarioResumen,
    UsuarioSalida,
)
from app.modulos.seguridad.modelos import (
    Permiso,
    Rol,
    RolPermiso,
    Sesion,
    TokenRecuperacion,
    Usuario,
    UsuarioSede,
)

log = logging.getLogger("sapef.seguridad")

COOKIE_ACCESO = "sapef_acceso"
COOKIE_RENOVACION = "sapef_renovacion"

_ph = PasswordHasher(type=Type.ID, time_cost=3, memory_cost=65536, parallelism=4)
_HASH_DUMMY = _ph.hash("sapef-dummy-verificacion-constante")


class ErrorRenovarSesion(Exception):
    def __init__(self, detail: str, limpiar_cookies: bool = True) -> None:
        self.detail = detail
        self.limpiar_cookies = limpiar_cookies
        super().__init__(detail)


def _traducir_error_dominio(exc: dominio.ErrorDominioSeguridad) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _sedes_activas_usuario(db: Session, usuario: Usuario) -> list[SedeResumen]:
    sede_ids = [us.sede_id for us in usuario.sedes_asignadas]
    if not sede_ids:
        return []
    filas = repositorio.obtener_sedes_por_ids(db, sede_ids)
    return [sede for sede, activa in filas if activa]


def _a_perfil_actual(db: Session, usuario: Usuario) -> PerfilActual:
    permisos = sorted(p.codigo for p in usuario.rol.permisos) if usuario.rol else []
    return PerfilActual(
        id=usuario.id,
        nombre_usuario=usuario.nombre_usuario,
        nombre_completo=usuario.nombre_completo,
        identificacion=usuario.identificacion,
        correo=usuario.correo,
        activo=usuario.activo,
        debe_cambiar_clave=usuario.debe_cambiar_clave,
        acepto_condiciones_en=usuario.acepto_condiciones_en,
        rol=RolResumen(id=usuario.rol.id, codigo=usuario.rol.codigo, nombre=usuario.rol.nombre),
        permisos=permisos,
        sedes=_sedes_activas_usuario(db, usuario),
    )


def _a_usuario_salida(db: Session, usuario: Usuario) -> UsuarioSalida:
    return UsuarioSalida(
        id=usuario.id,
        nombre_usuario=usuario.nombre_usuario,
        nombre_completo=usuario.nombre_completo,
        identificacion=usuario.identificacion,
        correo=usuario.correo,
        activo=usuario.activo,
        debe_cambiar_clave=usuario.debe_cambiar_clave,
        acepto_condiciones_en=usuario.acepto_condiciones_en,
        rol=RolResumen(id=usuario.rol.id, codigo=usuario.rol.codigo, nombre=usuario.rol.nombre),
        sedes=_sedes_activas_usuario(db, usuario),
        creado_en=usuario.creado_en,
        modificado_en=usuario.modificado_en,
    )


def _a_rol_salida(rol: Rol) -> RolSalida:
    return RolSalida(
        id=rol.id,
        codigo=rol.codigo,
        nombre=rol.nombre,
        descripcion=rol.descripcion,
        activo=rol.activo,
        permisos=[
            PermisoSalida(
                id=p.id,
                codigo=p.codigo,
                modulo=p.modulo,
                descripcion=p.descripcion,
            )
            for p in rol.permisos
        ],
        creado_en=rol.creado_en,
        modificado_en=rol.modificado_en,
    )


def _snapshot_usuario(usuario: Usuario) -> dict[str, Any]:
    return {
        "id": usuario.id,
        "nombre_usuario": usuario.nombre_usuario,
        "nombre_completo": usuario.nombre_completo,
        "identificacion": usuario.identificacion,
        "correo": usuario.correo,
        "activo": usuario.activo,
        "debe_cambiar_clave": usuario.debe_cambiar_clave,
        "rol_id": usuario.rol_id,
        "sede_ids": sorted(us.sede_id for us in usuario.sedes_asignadas),
    }


def _snapshot_rol(rol: Rol) -> dict[str, Any]:
    return {
        "id": rol.id,
        "codigo": rol.codigo,
        "nombre": rol.nombre,
        "descripcion": rol.descripcion,
        "activo": rol.activo,
        "permisos": sorted(p.codigo for p in rol.permisos),
    }


def _crear_token_acceso(usuario_id: int, sesion_id: UUID, ahora: datetime) -> str:
    config = obtener_configuracion()
    iat = int(ahora.timestamp())
    exp = int((ahora + timedelta(minutes=config.sesion_acceso_minutos)).timestamp())
    payload = {
        "sub": str(usuario_id),
        "sid": str(sesion_id),
        "iat": iat,
        "exp": exp,
        "jti": uuid4().hex,
    }
    return dominio.firmar_token_acceso(payload, config.secret_key.get_secret_value())


def aplicar_cookies_sesion(
    respuesta: Response,
    token_acceso: str,
    token_renovacion: str,
    tipo_cliente: str,
) -> None:
    config = obtener_configuracion()
    segura = config.cookie_segura_efectiva
    ttl_acceso = config.sesion_acceso_minutos * 60
    ttl_renovacion = (
        config.sesion_renovacion_pwa_dias * 86400
        if tipo_cliente == "pwa"
        else config.sesion_renovacion_web_horas * 3600
    )
    respuesta.set_cookie(
        key=COOKIE_ACCESO,
        value=token_acceso,
        max_age=ttl_acceso,
        path="/api",
        httponly=True,
        secure=segura,
        samesite="strict",
    )
    respuesta.set_cookie(
        key=COOKIE_RENOVACION,
        value=token_renovacion,
        max_age=ttl_renovacion,
        path="/api/v1/auth",
        httponly=True,
        secure=segura,
        samesite="strict",
    )


def limpiar_cookies_sesion(respuesta: Response) -> None:
    config = obtener_configuracion()
    segura = config.cookie_segura_efectiva
    respuesta.delete_cookie(
        key=COOKIE_ACCESO,
        path="/api",
        httponly=True,
        secure=segura,
        samesite="strict",
    )
    respuesta.delete_cookie(
        key=COOKIE_RENOVACION,
        path="/api/v1/auth",
        httponly=True,
        secure=segura,
        samesite="strict",
    )


def _verificar_dummy(clave: str) -> None:
    with contextlib.suppress(VerificationError):
        _ph.verify(_HASH_DUMMY, clave)


def autenticar_usuario(
    db: Session,
    entrada: IngresarEntrada,
    *,
    agente: str | None,
    ip: str | None,
) -> tuple[PerfilActual, str, str]:
    config = obtener_configuracion()
    ahora = datetime.now(UTC)
    usuario = repositorio.obtener_usuario_por_identificador(db, entrada.usuario)

    invalido = (
        usuario is None
        or not usuario.activo
        or not usuario.rol.activo
        or usuario.hash_clave is None
    )
    if invalido:
        _verificar_dummy(entrada.clave)
        raise HTTPException(status_code=401, detail="Credenciales inválidas.")

    if dominio.evaluar_bloqueo(usuario.bloqueado_hasta, ahora):
        bloqueo_iso = usuario.bloqueado_hasta.isoformat() if usuario.bloqueado_hasta else None
        repositorio.crear_auditoria(
            db,
            usuario_id=usuario.id,
            sede_id=None,
            accion="login_bloqueado",
            entidad="usuario",
            entidad_id=str(usuario.id),
            antes=None,
            despues={"bloqueado_hasta": bloqueo_iso},
            request_id=id_peticion.get(),
        )
        db.commit()
        raise HTTPException(
            status_code=423,
            detail="Cuenta bloqueada temporalmente por intentos fallidos. Intente más tarde.",
        )

    if usuario.bloqueado_hasta is not None and usuario.bloqueado_hasta <= ahora:
        usuario.intentos_fallidos = 0
        usuario.bloqueado_hasta = None

    try:
        _ph.verify(usuario.hash_clave, entrada.clave)
    except (VerifyMismatchError, VerificationError, InvalidHashError) as exc:
        nuevos_intentos, bloqueado_hasta = dominio.calcular_estado_fallo_login(
            usuario.intentos_fallidos,
            config.login_max_intentos,
            config.login_bloqueo_minutos,
            ahora,
        )
        usuario.intentos_fallidos = nuevos_intentos
        if bloqueado_hasta is not None:
            usuario.bloqueado_hasta = bloqueado_hasta
        repositorio.crear_auditoria(
            db,
            usuario_id=usuario.id,
            sede_id=None,
            accion="login_bloqueado" if bloqueado_hasta else "login_fallido",
            entidad="usuario",
            entidad_id=str(usuario.id),
            antes=None,
            despues={"intentos_fallidos": nuevos_intentos},
            request_id=id_peticion.get(),
        )
        db.commit()
        if bloqueado_hasta is not None:
            raise HTTPException(
                status_code=423,
                detail="Cuenta bloqueada temporalmente por intentos fallidos. Intente más tarde.",
            ) from exc
        raise HTTPException(status_code=401, detail="Credenciales inválidas.") from exc

    if _ph.check_needs_rehash(usuario.hash_clave):
        usuario.hash_clave = _ph.hash(entrada.clave)

    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None

    raw_refresh = secrets.token_urlsafe(48)
    ttl_renovacion = (
        timedelta(days=config.sesion_renovacion_pwa_dias)
        if entrada.tipo_cliente == "pwa"
        else timedelta(hours=config.sesion_renovacion_web_horas)
    )
    sesion = Sesion(
        id=uuid4(),
        usuario_id=usuario.id,
        hash_token_renovacion=dominio.hash_sha256_hex(raw_refresh),
        familia=uuid4(),
        tipo_cliente=entrada.tipo_cliente,
        expira_en=ahora + ttl_renovacion,
        agente=agente[:512] if agente else None,
        ip=ip[:45] if ip else None,
    )
    db.add(sesion)
    db.commit()

    token_acceso = _crear_token_acceso(usuario.id, sesion.id, ahora)
    usuario_log.set(usuario.nombre_usuario)
    return _a_perfil_actual(db, usuario), token_acceso, raw_refresh


def renovar_sesion(
    db: Session,
    token_renovacion: str | None,
    *,
    agente: str | None,
    ip: str | None,
) -> tuple[EstadoRenovacionSalida, str, str, str]:
    if not token_renovacion:
        raise ErrorRenovarSesion("Sesión no encontrada o inválida.", limpiar_cookies=True)

    config = obtener_configuracion()
    ahora = datetime.now(UTC)
    hash_recibido = dominio.hash_sha256_hex(token_renovacion)
    sesion = repositorio.obtener_sesion_por_hash(db, hash_recibido)
    if sesion is None:
        raise ErrorRenovarSesion("Token de renovación inválido.", limpiar_cookies=True)

    if sesion.usada_en is not None or sesion.revocada_en is not None:
        repositorio.revocar_familia_sesiones(db, sesion.familia, ahora)
        repositorio.crear_auditoria(
            db,
            usuario_id=sesion.usuario_id,
            sede_id=None,
            accion="reuso_sesion",
            entidad="sesion",
            entidad_id=str(sesion.familia),
            antes=None,
            despues={"sesion_id": str(sesion.id)},
            request_id=id_peticion.get(),
        )
        db.commit()
        raise ErrorRenovarSesion(
            "Se detectó reutilización de sesión. "
            "Todas las sesiones de la familia fueron revocadas.",
            limpiar_cookies=True,
        )

    usuario = repositorio.obtener_usuario_por_id(db, sesion.usuario_id)
    if sesion.expira_en <= ahora or usuario is None or not usuario.activo or not usuario.rol.activo:
        raise ErrorRenovarSesion(
            "La sesión expiró o el usuario está inactivo.", limpiar_cookies=True
        )

    sesion.usada_en = ahora
    nuevo_raw_refresh = secrets.token_urlsafe(48)
    ttl_renovacion = (
        timedelta(days=config.sesion_renovacion_pwa_dias)
        if sesion.tipo_cliente == "pwa"
        else timedelta(hours=config.sesion_renovacion_web_horas)
    )
    nueva_sesion = Sesion(
        id=uuid4(),
        usuario_id=usuario.id,
        hash_token_renovacion=dominio.hash_sha256_hex(nuevo_raw_refresh),
        familia=sesion.familia,
        tipo_cliente=sesion.tipo_cliente,
        expira_en=ahora + ttl_renovacion,
        agente=agente[:512] if agente else sesion.agente,
        ip=ip[:45] if ip else sesion.ip,
    )
    db.add(nueva_sesion)
    db.commit()

    nuevo_acceso = _crear_token_acceso(usuario.id, nueva_sesion.id, ahora)
    return (
        EstadoRenovacionSalida(estado="renovada"),
        nuevo_acceso,
        nuevo_raw_refresh,
        sesion.tipo_cliente,
    )


def cerrar_sesion(db: Session, token_renovacion: str | None, token_acceso: str | None) -> None:
    ahora = datetime.now(UTC)
    revoco = False
    if token_renovacion:
        sesion = repositorio.obtener_sesion_por_hash(db, dominio.hash_sha256_hex(token_renovacion))
        if sesion is not None:
            repositorio.revocar_familia_sesiones(db, sesion.familia, ahora)
            revoco = True
    if not revoco and token_acceso:
        config = obtener_configuracion()
        payload = dominio.verificar_token_acceso(
            token_acceso, config.secret_key.get_secret_value(), int(ahora.timestamp())
        )
        if payload and payload.get("sid"):
            try:
                sid = UUID(str(payload["sid"]))
                sesion = repositorio.obtener_sesion_por_id(db, sid)
                if sesion is not None:
                    repositorio.revocar_familia_sesiones(db, sesion.familia, ahora)
                    revoco = True
            except ValueError:
                pass
    if revoco:
        db.commit()


def obtener_sesion_actual(db: Session, token_acceso: str | None) -> UsuarioAutenticado:
    if not token_acceso:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    config = obtener_configuracion()
    ahora = datetime.now(UTC)
    payload = dominio.verificar_token_acceso(
        token_acceso, config.secret_key.get_secret_value(), int(ahora.timestamp())
    )
    if payload is None:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada.")

    try:
        usuario_id = int(payload["sub"])
        sesion_id = UUID(str(payload["sid"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Sesión inválida.") from exc

    sesion = repositorio.obtener_sesion_por_id(db, sesion_id)
    if (
        sesion is None
        or sesion.usuario_id != usuario_id
        or sesion.revocada_en is not None
        or sesion.expira_en <= ahora
    ):
        raise HTTPException(status_code=401, detail="La sesión ha sido revocada o expiró.")

    usuario = repositorio.obtener_usuario_por_id(db, usuario_id)
    if usuario is None or not usuario.activo or not usuario.rol.activo:
        raise HTTPException(status_code=401, detail="Usuario inactivo o inexistente.")

    permisos = sorted(p.codigo for p in usuario.rol.permisos)
    sedes = _sedes_activas_usuario(db, usuario)
    usuario_log.set(usuario.nombre_usuario)
    return UsuarioAutenticado(
        id=usuario.id,
        nombre_usuario=usuario.nombre_usuario,
        nombre_completo=usuario.nombre_completo,
        identificacion=usuario.identificacion,
        correo=usuario.correo,
        activo=usuario.activo,
        debe_cambiar_clave=usuario.debe_cambiar_clave,
        acepto_condiciones_en=usuario.acepto_condiciones_en,
        rol=RolResumen(id=usuario.rol.id, codigo=usuario.rol.codigo, nombre=usuario.rol.nombre),
        permisos=permisos,
        sedes=sedes,
        sesion_id=sesion.id,
    )


def requerir_usuario_sesion_abierta(
    request: Request,
    db: Annotated[Session, Depends(obtener_sesion)],
) -> UsuarioAutenticado:
    token_acceso = request.cookies.get(COOKIE_ACCESO)
    return obtener_sesion_actual(db, token_acceso)


def requerir_usuario(
    usuario: Annotated[UsuarioAutenticado, Depends(requerir_usuario_sesion_abierta)],
) -> UsuarioAutenticado:
    if usuario.debe_cambiar_clave:
        raise HTTPException(
            status_code=403,
            detail="Debe cambiar su contraseña antes de acceder al sistema.",
        )
    return usuario


def validar_acceso_sede(
    db: Session,
    usuario: UsuarioAutenticado,
    sede_codigo: str | None,
) -> SedeResumen:
    sede_eval: dominio.SedeEvaluacion | None = None
    if sede_codigo and sede_codigo.strip():
        encontrada = repositorio.obtener_sede_por_codigo(db, sede_codigo)
        if encontrada is not None:
            sede_res, activa = encontrada
            sede_eval = dominio.SedeEvaluacion(
                id=sede_res.id, codigo=sede_res.codigo, nombre=sede_res.nombre, activa=activa
            )
    try:
        aprobada = dominio.evaluar_acceso_sede(
            sede_codigo, sede_eval, {s.id for s in usuario.sedes}
        )
    except dominio.ErrorDominioSeguridad as exc:
        raise _traducir_error_dominio(exc) from exc
    sede_log.set(aprobada.codigo)
    return SedeResumen(id=aprobada.id, codigo=aprobada.codigo, nombre=aprobada.nombre)


def requerir_sede(
    usuario: Annotated[UsuarioAutenticado, Depends(requerir_usuario)],
    db: Annotated[Session, Depends(obtener_sesion)],
    x_sede: Annotated[str | None, Header(alias="X-Sede")] = None,
) -> SedeResumen:
    return validar_acceso_sede(db, usuario, x_sede)


def verificar_permiso(usuario: UsuarioAutenticado, permiso_codigo: str) -> None:
    if not dominio.usuario_tiene_permiso(set(usuario.permisos), permiso_codigo):
        raise HTTPException(
            status_code=403,
            detail=f"No tiene permiso suficiente ({permiso_codigo}).",
        )


def requerir_permiso(codigo: str) -> Callable[..., UsuarioAutenticado]:
    def _dependencia(
        usuario: Annotated[UsuarioAutenticado, Depends(requerir_usuario)],
    ) -> UsuarioAutenticado:
        verificar_permiso(usuario, codigo)
        return usuario

    return _dependencia


def requerir_algun_permiso(*codigos: str) -> Callable[..., UsuarioAutenticado]:
    def _dependencia(
        usuario: Annotated[UsuarioAutenticado, Depends(requerir_usuario)],
    ) -> UsuarioAutenticado:
        if not dominio.usuario_tiene_algun_permiso(set(usuario.permisos), codigos):
            raise HTTPException(
                status_code=403,
                detail="No tiene permisos suficientes para esta operación.",
            )
        return usuario

    return _dependencia


def requerir_permiso_carga_archivo(
    usuario: Annotated[UsuarioAutenticado, Depends(requerir_usuario)],
) -> UsuarioAutenticado:
    """Permite carga de archivos a campo o usuarios con permisos de escritura."""
    sufijos = (".crear", ".editar", ".cerrar", ".ejecutar", ".subir")
    permitido = any(p == "campo.app.usar" or p.endswith(sufijos) for p in usuario.permisos)
    if not permitido:
        raise HTTPException(
            status_code=403,
            detail="No tiene permiso para cargar archivos.",
        )
    return usuario


def requerir_tablero_alcance(
    usuario: Annotated[UsuarioAutenticado, Depends(requerir_usuario)],
    db: Annotated[Session, Depends(obtener_sesion)],
    sede: Annotated[str | None, Query()] = None,
    x_sede: Annotated[str | None, Header(alias="X-Sede")] = None,
) -> list[SedeResumen]:
    if sede == "todas":
        try:
            ids_permitidos = dominio.filtrar_sedes_consolidado(
                [s.id for s in usuario.sedes], set(usuario.permisos)
            )
        except dominio.ErrorDominioSeguridad as exc:
            raise _traducir_error_dominio(exc) from exc
        sede_log.set("todas")
        return [s for s in usuario.sedes if s.id in set(ids_permitidos)]
    return [validar_acceso_sede(db, usuario, sede or x_sede)]


async def _encolar_correo_recuperacion(usuario_id: int, token_id: str) -> None:
    deferrer = app_tareas.configure_task(name="seguridad.enviar_correo_recuperacion")
    try:
        await deferrer.defer_async(usuario_id=usuario_id, token_id=token_id)
    except AppNotOpen:
        async with app_tareas.open_async():
            await deferrer.defer_async(usuario_id=usuario_id, token_id=token_id)


async def solicitar_recuperacion_clave(
    db: Session,
    entrada: RecuperarClaveEntrada,
    *,
    ip: str | None,
) -> MensajeSalida:
    config = obtener_configuracion()
    ahora = datetime.now(UTC)
    usuario = repositorio.obtener_usuario_por_correo(db, str(entrada.correo))
    if usuario is not None and usuario.activo:
        raw_token = secrets.token_urlsafe(32)
        token = TokenRecuperacion(
            id=uuid4(),
            usuario_id=usuario.id,
            hash_token=dominio.hash_sha256_hex(raw_token),
            token_cifrado_envio=dominio.cifrar_token_envio(
                raw_token, config.secret_key.get_secret_value()
            ),
            expira_en=ahora + timedelta(minutes=config.recuperacion_token_minutos),
            ip_solicitud=ip[:45] if ip else None,
        )
        db.add(token)
        db.commit()
        await _encolar_correo_recuperacion(usuario.id, str(token.id))
    return MensajeSalida(
        mensaje=(
            "Si el correo está registrado, recibirá instrucciones para restablecer su contraseña."
        )
    )


def procesar_envio_correo_recuperacion(usuario_id: int, token_id: str) -> None:
    """Ejecutado por el worker Procrastinate usando exclusivamente IDs primitivos."""
    config = obtener_configuracion()
    with Session(obtener_motor()) as db:
        try:
            uid_token = UUID(token_id)
        except ValueError:
            return
        usuario = repositorio.obtener_usuario_por_id(db, usuario_id)
        token = repositorio.obtener_token_recuperacion_por_id(db, uid_token)
        if usuario is None or token is None or token.usuario_id != usuario.id:
            return
        if token.usado_en is not None or token.token_cifrado_envio is None:
            return

        raw_token = dominio.descifrar_token_envio(
            token.token_cifrado_envio, config.secret_key.get_secret_value()
        )
        token.token_cifrado_envio = None
        db.commit()

        if raw_token is None:
            return

        if config.smtp_host:
            mensaje = EmailMessage()
            mensaje["Subject"] = "SAPEF - Recuperación de contraseña"
            mensaje["From"] = config.smtp_remitente
            mensaje["To"] = usuario.correo
            mensaje.set_content(
                "Use el siguiente código de un solo uso para restablecer su contraseña "
                f"(válido por {config.recuperacion_token_minutos} minutos):\n\n{raw_token}\n"
            )
            with smtplib.SMTP(config.smtp_host, config.smtp_puerto, timeout=10) as smtp:
                if config.smtp_tls:
                    smtp.starttls()
                if config.smtp_usuario and config.smtp_clave:
                    smtp.login(config.smtp_usuario, config.smtp_clave.get_secret_value())
                smtp.send_message(mensaje)
        else:
            log.info(
                "Recuperación procesada sin SMTP configurado (entorno local)",
                extra={"usuario": usuario.nombre_usuario},
            )


def restablecer_clave(db: Session, entrada: RestablecerClaveEntrada) -> MensajeSalida:
    ahora = datetime.now(UTC)
    hash_recibido = dominio.hash_sha256_hex(entrada.token)
    token = repositorio.obtener_token_recuperacion_por_hash(db, hash_recibido)
    if token is None or token.usado_en is not None or token.expira_en <= ahora:
        raise HTTPException(status_code=400, detail="Token de recuperación inválido o expirado.")

    usuario = repositorio.obtener_usuario_por_id(db, token.usuario_id)
    if usuario is None or not usuario.activo:
        raise HTTPException(status_code=400, detail="Token de recuperación inválido o expirado.")

    try:
        dominio.validar_fortaleza_clave(entrada.clave_nueva, usuario.nombre_usuario)
    except dominio.ErrorDominioSeguridad as exc:
        raise _traducir_error_dominio(exc) from exc

    usuario.hash_clave = _ph.hash(entrada.clave_nueva)
    usuario.debe_cambiar_clave = False
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    token.usado_en = ahora
    token.token_cifrado_envio = None

    repositorio.revocar_sesiones_usuario(db, usuario.id, ahora)
    repositorio.crear_auditoria(
        db,
        usuario_id=usuario.id,
        sede_id=None,
        accion="restablecer_clave",
        entidad="usuario",
        entidad_id=str(usuario.id),
        antes=None,
        despues={"debe_cambiar_clave": False},
        request_id=id_peticion.get(),
    )
    db.commit()
    return MensajeSalida(mensaje="Contraseña restablecida correctamente.")


def cambiar_clave(
    db: Session,
    usuario_actual: UsuarioAutenticado,
    entrada: CambiarClaveEntrada,
) -> MensajeSalida:
    ahora = datetime.now(UTC)
    usuario = repositorio.obtener_usuario_por_id(db, usuario_actual.id)
    if usuario is None or not usuario.activo:
        raise HTTPException(status_code=401, detail="Usuario inválido.")

    if usuario.hash_clave is None:
        raise HTTPException(status_code=400, detail="La contraseña actual no es correcta.")
    try:
        _ph.verify(usuario.hash_clave, entrada.clave_actual)
    except (VerifyMismatchError, VerificationError, InvalidHashError) as exc:
        raise HTTPException(status_code=400, detail="La contraseña actual no es correcta.") from exc

    if entrada.clave_nueva == entrada.clave_actual:
        raise HTTPException(
            status_code=422,
            detail="La nueva contraseña no puede ser igual a la contraseña actual.",
        )

    try:
        dominio.validar_fortaleza_clave(entrada.clave_nueva, usuario.nombre_usuario)
    except dominio.ErrorDominioSeguridad as exc:
        raise _traducir_error_dominio(exc) from exc

    usuario.hash_clave = _ph.hash(entrada.clave_nueva)
    usuario.debe_cambiar_clave = False
    repositorio.revocar_sesiones_usuario(
        db, usuario.id, ahora, excluir_sesion_id=usuario_actual.sesion_id
    )
    repositorio.crear_auditoria(
        db,
        usuario_id=usuario.id,
        sede_id=None,
        accion="cambiar_clave",
        entidad="usuario",
        entidad_id=str(usuario.id),
        antes=None,
        despues={"debe_cambiar_clave": False},
        request_id=id_peticion.get(),
    )
    db.commit()
    return MensajeSalida(mensaje="Contraseña actualizada correctamente.")


def aceptar_condiciones(
    db: Session,
    usuario_actual: UsuarioAutenticado,
    acepto: bool,
) -> PerfilActual:
    if not acepto:
        raise HTTPException(status_code=422, detail="Debe aceptar las condiciones para continuar.")
    usuario = repositorio.obtener_usuario_por_id(db, usuario_actual.id)
    if usuario is None or not usuario.activo:
        raise HTTPException(status_code=401, detail="Usuario inválido.")

    ahora = datetime.now(UTC)
    antes = {
        "acepto_condiciones_en": (
            usuario.acepto_condiciones_en.isoformat() if usuario.acepto_condiciones_en else None
        )
    }
    if usuario.acepto_condiciones_en is None:
        usuario.acepto_condiciones_en = ahora
    repositorio.crear_auditoria(
        db,
        usuario_id=usuario.id,
        sede_id=None,
        accion="aceptar_condiciones",
        entidad="usuario",
        entidad_id=str(usuario.id),
        antes=antes,
        despues={"acepto_condiciones_en": usuario.acepto_condiciones_en.isoformat()},
        request_id=id_peticion.get(),
    )
    db.commit()
    db.refresh(usuario)
    return _a_perfil_actual(db, usuario)


def obtener_perfil(db: Session, usuario_actual: UsuarioAutenticado) -> PerfilActual:
    usuario = repositorio.obtener_usuario_por_id(db, usuario_actual.id)
    if usuario is None or not usuario.activo:
        raise HTTPException(status_code=401, detail="Usuario inválido.")
    return _a_perfil_actual(db, usuario)


def _validar_sedes_existen(db: Session, sede_ids: list[int]) -> list[int]:
    unicas = list(dict.fromkeys(sede_ids))
    if not unicas:
        raise HTTPException(status_code=422, detail="Debe asignar al menos una sede.")
    encontradas = repositorio.obtener_sedes_por_ids(db, unicas)
    if len(encontradas) != len(unicas):
        raise HTTPException(status_code=422, detail="Una o más sedes indicadas no existen.")
    return unicas


def listar_usuarios_paginado(
    db: Session,
    *,
    page: int,
    size: int,
    buscar: str | None = None,
    activo: bool | None = None,
    rol_id: int | None = None,
    sede_id: int | None = None,
) -> Pagina[UsuarioSalida]:
    usuarios, total = repositorio.listar_usuarios(
        db, page=page, size=size, buscar=buscar, activo=activo, rol_id=rol_id, sede_id=sede_id
    )
    return Pagina[UsuarioSalida](
        items=[_a_usuario_salida(db, u) for u in usuarios],
        total=total,
        page=page,
        size=size,
    )


def crear_usuario(
    db: Session,
    actor: UsuarioAutenticado,
    entrada: UsuarioCrearEntrada,
) -> UsuarioSalida:
    nombre_usuario_norm = dominio.normalizar_identificador(entrada.nombre_usuario)
    correo_norm = dominio.normalizar_identificador(str(entrada.correo))

    if repositorio.obtener_usuario_por_nombre_usuario(db, nombre_usuario_norm) is not None:
        raise HTTPException(status_code=409, detail="El nombre de usuario ya está registrado.")
    if repositorio.obtener_usuario_por_correo(db, nombre_usuario_norm) is not None:
        raise HTTPException(
            status_code=409,
            detail="El nombre de usuario coincide con el correo electrónico de otro usuario.",
        )
    if repositorio.obtener_usuario_por_correo(db, correo_norm) is not None:
        raise HTTPException(status_code=409, detail="El correo electrónico ya está registrado.")
    if repositorio.obtener_usuario_por_nombre_usuario(db, correo_norm) is not None:
        raise HTTPException(
            status_code=409,
            detail="El correo electrónico coincide con el nombre de usuario de otro usuario.",
        )

    rol = repositorio.obtener_rol_por_id(db, entrada.rol_id)
    if rol is None:
        raise HTTPException(status_code=422, detail="El rol indicado no existe.")
    if not rol.activo:
        raise HTTPException(status_code=422, detail="No se puede asignar un rol inactivo.")

    sedes_unicas = _validar_sedes_existen(db, entrada.sede_ids)

    hash_clave: str | None = None
    if entrada.clave is not None:
        try:
            dominio.validar_fortaleza_clave(entrada.clave, nombre_usuario_norm)
        except dominio.ErrorDominioSeguridad as exc:
            raise _traducir_error_dominio(exc) from exc
        hash_clave = _ph.hash(entrada.clave)

    nuevo = Usuario(
        nombre_usuario=nombre_usuario_norm,
        nombre_completo=entrada.nombre_completo.strip(),
        identificacion=entrada.identificacion.strip(),
        correo=correo_norm,
        hash_clave=hash_clave,
        debe_cambiar_clave=entrada.debe_cambiar_clave,
        activo=entrada.activo,
        rol_id=rol.id,
        creado_por=actor.id,
        modificado_por=actor.id,
    )
    db.add(nuevo)
    db.flush()
    repositorio.reemplazar_sedes_usuario(db, nuevo, sedes_unicas)
    db.refresh(nuevo)

    _, despues = dominio.construir_diff_auditoria(None, _snapshot_usuario(nuevo))
    repositorio.crear_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=None,
        accion="crear",
        entidad="usuario",
        entidad_id=str(nuevo.id),
        antes=None,
        despues=despues,
        request_id=id_peticion.get(),
    )
    db.commit()
    recargado = repositorio.obtener_usuario_por_id(db, nuevo.id)
    return _a_usuario_salida(db, recargado or nuevo)


def obtener_usuario_detalle(
    db: Session,
    actor: UsuarioAutenticado,
    usuario_id: int,
) -> UsuarioSalida:
    usuario = repositorio.obtener_usuario_por_id(db, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    repositorio.crear_auditoria_consulta(
        db,
        usuario_id=actor.id,
        sede_id=None,
        recurso="usuario.detalle",
        parametros_permitidos={"usuario_id": usuario_id},
        request_id=id_peticion.get(),
    )
    db.commit()
    return _a_usuario_salida(db, usuario)


def editar_usuario(
    db: Session,
    actor: UsuarioAutenticado,
    usuario_id: int,
    entrada: UsuarioEditarEntrada,
) -> UsuarioSalida:
    usuario = repositorio.obtener_usuario_por_id(db, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    if entrada.activo is False:
        verificar_permiso(actor, "seguridad.usuario.desactivar")
        if usuario.id == actor.id:
            raise HTTPException(
                status_code=409,
                detail="No puede desactivar su propio usuario.",
            )

    antes = _snapshot_usuario(usuario)
    revocar_sesiones = False

    if entrada.nombre_completo is not None:
        usuario.nombre_completo = entrada.nombre_completo.strip()
    if entrada.identificacion is not None:
        usuario.identificacion = entrada.identificacion.strip()
    if entrada.correo is not None:
        correo_norm = dominio.normalizar_identificador(str(entrada.correo))
        existente = repositorio.obtener_usuario_por_correo(db, correo_norm)
        if existente is not None and existente.id != usuario.id:
            raise HTTPException(status_code=409, detail="El correo electrónico ya está registrado.")
        existente_nombre = repositorio.obtener_usuario_por_nombre_usuario(db, correo_norm)
        if existente_nombre is not None and existente_nombre.id != usuario.id:
            raise HTTPException(
                status_code=409,
                detail="El correo electrónico coincide con el nombre de usuario de otro usuario.",
            )
        usuario.correo = correo_norm
    if entrada.rol_id is not None and entrada.rol_id != usuario.rol_id:
        rol = repositorio.obtener_rol_por_id(db, entrada.rol_id)
        if rol is None:
            raise HTTPException(status_code=422, detail="El rol indicado no existe.")
        if not rol.activo:
            raise HTTPException(status_code=422, detail="No se puede asignar un rol inactivo.")
        usuario.rol_id = rol.id
        revocar_sesiones = True
    if entrada.sede_ids is not None:
        sedes_unicas = _validar_sedes_existen(db, entrada.sede_ids)
        if set(sedes_unicas) != {us.sede_id for us in usuario.sedes_asignadas}:
            repositorio.reemplazar_sedes_usuario(db, usuario, sedes_unicas)
            revocar_sesiones = True
    if entrada.activo is not None and entrada.activo != usuario.activo:
        usuario.activo = entrada.activo
        if not entrada.activo:
            revocar_sesiones = True
    if entrada.debe_cambiar_clave is not None:
        usuario.debe_cambiar_clave = entrada.debe_cambiar_clave
    if entrada.clave is not None:
        try:
            dominio.validar_fortaleza_clave(entrada.clave, usuario.nombre_usuario)
        except dominio.ErrorDominioSeguridad as exc:
            raise _traducir_error_dominio(exc) from exc
        usuario.hash_clave = _ph.hash(entrada.clave)
        revocar_sesiones = True

    usuario.modificado_por = actor.id
    db.flush()
    db.refresh(usuario)

    if revocar_sesiones:
        repositorio.revocar_sesiones_usuario(db, usuario.id, datetime.now(UTC))

    accion = "desactivar" if entrada.activo is False else "editar"
    antes_limpio, despues_limpio = dominio.construir_diff_auditoria(
        antes, _snapshot_usuario(usuario)
    )
    repositorio.crear_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=None,
        accion=accion,
        entidad="usuario",
        entidad_id=str(usuario.id),
        antes=antes_limpio,
        despues=despues_limpio,
        request_id=id_peticion.get(),
    )
    db.commit()
    recargado = repositorio.obtener_usuario_por_id(db, usuario.id)
    return _a_usuario_salida(db, recargado or usuario)


def crear_o_actualizar_usuario_importado(
    db: Session,
    *,
    nombre_usuario: str,
    nombre_completo: str,
    identificacion: str,
    correo: str,
    rol_codigo: str,
    sede_ids: list[int],
    activo: bool = True,
    actor_id: int | None = None,
) -> tuple[UsuarioSalida, bool]:
    """Upsert idempotente para IMP-6 (nunca fija contraseñas ni hashes)."""
    nombre_norm = dominio.normalizar_identificador(nombre_usuario)
    correo_norm = dominio.normalizar_identificador(correo)
    rol = repositorio.obtener_rol_por_codigo(db, rol_codigo)
    if rol is None:
        raise HTTPException(status_code=422, detail=f"El rol '{rol_codigo}' no existe.")
    sedes_unicas = _validar_sedes_existen(db, sede_ids)

    existente = repositorio.obtener_usuario_por_nombre_usuario(db, nombre_norm)
    if existente is None:
        if repositorio.obtener_usuario_por_correo(db, nombre_norm) is not None:
            raise HTTPException(
                status_code=409,
                detail="El nombre de usuario coincide con el correo electrónico de otro usuario.",
            )
        if repositorio.obtener_usuario_por_correo(db, correo_norm) is not None:
            raise HTTPException(status_code=409, detail="El correo electrónico ya está registrado.")
        if repositorio.obtener_usuario_por_nombre_usuario(db, correo_norm) is not None:
            raise HTTPException(
                status_code=409,
                detail="El correo electrónico coincide con el nombre de usuario de otro usuario.",
            )
        nuevo = Usuario(
            nombre_usuario=nombre_norm,
            nombre_completo=nombre_completo.strip(),
            identificacion=identificacion.strip(),
            correo=correo_norm,
            hash_clave=None,
            debe_cambiar_clave=True,
            activo=activo,
            rol_id=rol.id,
            creado_por=actor_id,
            modificado_por=actor_id,
        )
        db.add(nuevo)
        db.flush()
        repositorio.reemplazar_sedes_usuario(db, nuevo, sedes_unicas)
        db.flush()
        recargado = repositorio.obtener_usuario_por_id(db, nuevo.id) or nuevo
        return _a_usuario_salida(db, recargado), True

    existente_correo = repositorio.obtener_usuario_por_correo(db, correo_norm)
    if existente_correo is not None and existente_correo.id != existente.id:
        raise HTTPException(status_code=409, detail="El correo electrónico ya está registrado.")
    existente_nombre = repositorio.obtener_usuario_por_nombre_usuario(db, correo_norm)
    if existente_nombre is not None and existente_nombre.id != existente.id:
        raise HTTPException(
            status_code=409,
            detail="El correo electrónico coincide con el nombre de usuario de otro usuario.",
        )

    existente.nombre_completo = nombre_completo.strip()
    existente.identificacion = identificacion.strip()
    existente.correo = correo_norm
    existente.rol_id = rol.id
    existente.activo = activo
    existente.modificado_por = actor_id
    repositorio.reemplazar_sedes_usuario(db, existente, sedes_unicas)
    db.flush()
    recargado = repositorio.obtener_usuario_por_id(db, existente.id) or existente
    return _a_usuario_salida(db, recargado), False


def listar_roles_paginado(
    db: Session, *, page: int, size: int, activo: bool | None = None
) -> Pagina[RolSalida]:
    roles, total = repositorio.listar_roles(db, page=page, size=size, activo=activo)
    return Pagina[RolSalida](
        items=[_a_rol_salida(r) for r in roles],
        total=total,
        page=page,
        size=size,
    )


def obtener_rol_detalle(db: Session, rol_id: int) -> RolSalida:
    rol = repositorio.obtener_rol_por_id(db, rol_id)
    if rol is None:
        raise HTTPException(status_code=404, detail="Rol no encontrado.")
    return _a_rol_salida(rol)


def _resolver_permisos_por_codigo(db: Session, codigos: list[str]) -> list[Any]:
    unicos = list(dict.fromkeys(codigos))
    if not unicos:
        return []
    permisos = repositorio.obtener_permisos_por_codigos(db, unicos)
    encontrados = {p.codigo for p in permisos}
    faltantes = [c for c in unicos if c not in encontrados]
    if faltantes:
        raise HTTPException(
            status_code=422,
            detail=f"Permisos desconocidos: {', '.join(faltantes)}",
        )
    return permisos


def crear_rol(db: Session, actor: UsuarioAutenticado, entrada: RolCrearEntrada) -> RolSalida:
    codigo_norm = entrada.codigo.strip().upper()
    if repositorio.obtener_rol_por_codigo(db, codigo_norm) is not None:
        raise HTTPException(status_code=409, detail="Ya existe un rol con ese código.")
    permisos = _resolver_permisos_por_codigo(db, entrada.permisos)

    rol = Rol(
        codigo=codigo_norm,
        nombre=entrada.nombre.strip(),
        descripcion=entrada.descripcion.strip() if entrada.descripcion else None,
        activo=entrada.activo,
        creado_por=actor.id,
        modificado_por=actor.id,
    )
    db.add(rol)
    db.flush()
    for p in permisos:
        db.add(RolPermiso(rol_id=rol.id, permiso_id=p.id))
    db.flush()
    recargado = repositorio.obtener_rol_por_id(db, rol.id) or rol

    _, despues = dominio.construir_diff_auditoria(None, _snapshot_rol(recargado))
    repositorio.crear_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=None,
        accion="crear",
        entidad="rol",
        entidad_id=str(rol.id),
        antes=None,
        despues=despues,
        request_id=id_peticion.get(),
    )
    db.commit()
    return _a_rol_salida(recargado)


def editar_rol(
    db: Session, actor: UsuarioAutenticado, rol_id: int, entrada: RolEditarEntrada
) -> RolSalida:
    rol = repositorio.obtener_rol_por_id(db, rol_id)
    if rol is None:
        raise HTTPException(status_code=404, detail="Rol no encontrado.")
    antes = _snapshot_rol(rol)

    if entrada.nombre is not None:
        rol.nombre = entrada.nombre.strip()
    if entrada.descripcion is not None:
        rol.descripcion = entrada.descripcion.strip()
    if entrada.activo is not None:
        rol.activo = entrada.activo
    if entrada.permisos is not None:
        permisos = _resolver_permisos_por_codigo(db, entrada.permisos)
        rol.permisos = permisos

    rol.modificado_por = actor.id
    db.flush()
    db.refresh(rol)

    antes_limpio, despues_limpio = dominio.construir_diff_auditoria(antes, _snapshot_rol(rol))
    repositorio.crear_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=None,
        accion="editar",
        entidad="rol",
        entidad_id=str(rol.id),
        antes=antes_limpio,
        despues=despues_limpio,
        request_id=id_peticion.get(),
    )
    db.commit()
    recargado = repositorio.obtener_rol_por_id(db, rol.id) or rol
    return _a_rol_salida(recargado)


def listar_permisos_disponibles(db: Session) -> list[PermisoSalida]:
    return [
        PermisoSalida(id=p.id, codigo=p.codigo, modulo=p.modulo, descripcion=p.descripcion)
        for p in repositorio.listar_permisos(db)
    ]


def listar_auditoria_paginada(
    db: Session,
    *,
    page: int,
    size: int,
    tipo: str,
    entidad: str | None = None,
    usuario_id: int | None = None,
    sede_id: int | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
) -> Pagina[AuditoriaSalida] | Pagina[AuditoriaConsultaSalida]:
    if tipo == "consultas":
        filas, total = repositorio.listar_auditoria_consultas(
            db,
            page=page,
            size=size,
            usuario_id=usuario_id,
            sede_id=sede_id,
            desde=desde,
            hasta=hasta,
        )
        return Pagina[AuditoriaConsultaSalida](
            items=[
                AuditoriaConsultaSalida(
                    id=f.id,
                    instante=f.instante,
                    usuario_id=f.usuario_id,
                    sede_id=f.sede_id,
                    recurso=f.recurso,
                    parametros_permitidos=f.parametros_permitidos,
                    request_id=f.request_id,
                )
                for f in filas
            ],
            total=total,
            page=page,
            size=size,
        )

    filas, total = repositorio.listar_auditoria_cambios(
        db,
        page=page,
        size=size,
        entidad=entidad,
        usuario_id=usuario_id,
        sede_id=sede_id,
        desde=desde,
        hasta=hasta,
    )
    return Pagina[AuditoriaSalida](
        items=[
            AuditoriaSalida(
                id=f.id,
                instante=f.instante,
                usuario_id=f.usuario_id,
                sede_id=f.sede_id,
                accion=f.accion,
                entidad=f.entidad,
                entidad_id=f.entidad_id,
                antes=f.antes,
                despues=f.despues,
                request_id=f.request_id,
            )
            for f in filas
        ],
        total=total,
        page=page,
        size=size,
    )


def registrar_auditoria(
    db: Session,
    *,
    usuario_id: int | None,
    sede_id: int | None,
    accion: str,
    entidad: str,
    entidad_id: str,
    antes: dict[str, Any] | None = None,
    despues: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> None:
    antes_limpio, despues_limpio = dominio.construir_diff_auditoria(antes, despues)
    repositorio.crear_auditoria(
        db,
        usuario_id=usuario_id,
        sede_id=sede_id,
        accion=accion,
        entidad=entidad,
        entidad_id=entidad_id,
        antes=antes_limpio,
        despues=despues_limpio,
        request_id=request_id or id_peticion.get(),
    )


def registrar_auditoria_consulta(
    db: Session,
    *,
    usuario_id: int,
    sede_id: int | None,
    recurso: str,
    parametros_permitidos: dict[str, Any],
    request_id: str | None = None,
) -> None:
    repositorio.crear_auditoria_consulta(
        db,
        usuario_id=usuario_id,
        sede_id=sede_id,
        recurso=recurso,
        parametros_permitidos=dominio.sanitizar_datos_auditoria(parametros_permitidos),
        request_id=request_id or id_peticion.get(),
    )


def listar_tecnicos_sede(db: Session, sede_id: int) -> list[UsuarioResumen]:
    usuarios = repositorio.listar_tecnicos_sede(db, sede_id)
    return [
        UsuarioResumen(
            id=u.id,
            nombre_usuario=u.nombre_usuario,
            nombre_completo=u.nombre_completo,
            rol_codigo=u.rol.codigo,
            activo=u.activo,
        )
        for u in usuarios
    ]


# --- Semillas (python -m app.semillas) -------------------------------------------------


def sincronizar_permisos_y_roles(db: Session) -> dict[str, int]:
    """Idempotente: crea los permisos y roles que falten; ADMIN siempre queda con todos.

    No borra permisos que ya no estén en el catálogo ni modifica los roles existentes
    (salvo ADMIN), para no deshacer ajustes hechos por el administrador.
    """
    existentes = {p.codigo: p for p in repositorio.listar_permisos(db)}
    creados_permisos = 0
    for codigo, modulo, descripcion in datos_semilla.PERMISOS:
        permiso = existentes.get(codigo)
        if permiso is None:
            permiso = Permiso(codigo=codigo, modulo=modulo, descripcion=descripcion)
            db.add(permiso)
            existentes[codigo] = permiso
            creados_permisos += 1
        else:
            permiso.modulo = modulo
            permiso.descripcion = descripcion
    db.flush()

    creados_roles = 0
    for codigo, (nombre, descripcion, permisos) in datos_semilla.ROLES.items():
        rol = repositorio.obtener_rol_por_codigo(db, codigo)
        if codigo == datos_semilla.ROL_ADMIN:
            permisos = tuple(existentes)
        if rol is None:
            rol = Rol(codigo=codigo, nombre=nombre, descripcion=descripcion, activo=True)
            db.add(rol)
            db.flush()
            creados_roles += 1
            rol.permisos = [existentes[c] for c in permisos]
        elif codigo == datos_semilla.ROL_ADMIN:
            rol.permisos = [existentes[c] for c in permisos]
    db.flush()
    return {"permisos_creados": creados_permisos, "roles_creados": creados_roles}


def crear_admin_inicial(
    db: Session,
    *,
    nombre_usuario: str,
    correo: str,
    nombre_completo: str,
    identificacion: str,
    clave: str,
    forzar_cambio_clave: bool = True,
) -> bool:
    """Crea el primer administrador con todas las sedes activas. Devuelve False si ya existía.

    La contraseña llega por la línea de comandos o una variable de entorno: nunca se guarda
    en el repositorio ni se escribe en los logs.
    """
    nombre_norm = dominio.normalizar_identificador(nombre_usuario)
    correo_norm = dominio.normalizar_identificador(correo)
    if (
        repositorio.obtener_usuario_por_nombre_usuario(db, nombre_norm) is not None
        or repositorio.obtener_usuario_por_correo(db, correo_norm) is not None
    ):
        return False
    rol = repositorio.obtener_rol_por_codigo(db, datos_semilla.ROL_ADMIN)
    if rol is None:
        raise ValueError("Falta el rol ADMIN: ejecute primero la semilla de permisos y roles.")
    sede_ids = repositorio.listar_ids_sedes_activas(db)
    if not sede_ids:
        raise ValueError("No hay sedes activas: ejecute primero la semilla de configuración.")
    dominio.validar_fortaleza_clave(clave, nombre_norm)

    admin = Usuario(
        nombre_usuario=nombre_norm,
        nombre_completo=nombre_completo.strip(),
        identificacion=identificacion.strip(),
        correo=correo_norm,
        hash_clave=_ph.hash(clave),
        debe_cambiar_clave=forzar_cambio_clave,
        acepto_condiciones_en=None if forzar_cambio_clave else datetime.now(UTC),
        activo=True,
        rol_id=rol.id,
    )
    db.add(admin)
    db.flush()
    repositorio.reemplazar_sedes_usuario(db, admin, sede_ids)
    registrar_auditoria(
        db,
        usuario_id=None,
        sede_id=None,
        accion="crear",
        entidad="usuario",
        entidad_id=str(admin.id),
        despues=_snapshot_usuario(admin),
    )
    db.flush()
    return True


def asignar_sede_a_usuario(db: Session, usuario_id: int, sede_id: int) -> None:
    """Da acceso a una sede (p. ej., a quien la acaba de crear). Idempotente; sin commit."""
    if db.get(UsuarioSede, (usuario_id, sede_id)) is None:
        db.add(UsuarioSede(usuario_id=usuario_id, sede_id=sede_id))
        db.flush()
