"""Esquemas Pydantic v2 (DTOs) del módulo de seguridad."""

import re
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, BeforeValidator, Field

_RE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validar_correo(valor: Any) -> str:
    if not isinstance(valor, str):
        raise ValueError("Correo electrónico inválido.")
    limpio = valor.strip().lower()
    if len(limpio) > 254 or not _RE_CORREO.match(limpio):
        raise ValueError("Correo electrónico inválido.")
    return limpio


CorreoValido = Annotated[str, BeforeValidator(_validar_correo)]


class Pagina[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int


class SedeResumen(BaseModel):
    id: int
    codigo: str
    nombre: str


class RolResumen(BaseModel):
    id: int
    codigo: str
    nombre: str


class UsuarioAutenticado(BaseModel):
    id: int
    nombre_usuario: str
    nombre_completo: str
    identificacion: str
    correo: str
    activo: bool
    debe_cambiar_clave: bool
    acepto_condiciones_en: datetime | None
    rol: RolResumen
    permisos: list[str]
    sedes: list[SedeResumen]
    sesion_id: UUID


class UsuarioResumen(BaseModel):
    id: int
    nombre_usuario: str
    nombre_completo: str
    rol_codigo: str
    activo: bool


class IngresarEntrada(BaseModel):
    usuario: str = Field(min_length=1, max_length=180)
    clave: str = Field(min_length=1, max_length=128)
    tipo_cliente: Literal["web", "pwa"] = "web"


class RecuperarClaveEntrada(BaseModel):
    correo: CorreoValido


class RestablecerClaveEntrada(BaseModel):
    token: str = Field(min_length=10, max_length=256)
    clave_nueva: str = Field(min_length=1, max_length=128)


class CambiarClaveEntrada(BaseModel):
    clave_actual: str = Field(min_length=1, max_length=128)
    clave_nueva: str = Field(min_length=1, max_length=128)


class AceptarCondicionesEntrada(BaseModel):
    acepto: bool = True


class MensajeSalida(BaseModel):
    mensaje: str


class EstadoRenovacionSalida(BaseModel):
    estado: str


class PerfilActual(BaseModel):
    id: int
    nombre_usuario: str
    nombre_completo: str
    identificacion: str
    correo: str
    activo: bool
    debe_cambiar_clave: bool
    acepto_condiciones_en: datetime | None
    rol: RolResumen
    permisos: list[str]
    sedes: list[SedeResumen]


class PermisoSalida(BaseModel):
    id: int
    codigo: str
    modulo: str
    descripcion: str


class RolCrearEntrada(BaseModel):
    codigo: str = Field(min_length=2, max_length=60)
    nombre: str = Field(min_length=2, max_length=120)
    descripcion: str | None = Field(default=None, max_length=255)
    activo: bool = True
    permisos: list[str] = Field(default_factory=list)


class RolEditarEntrada(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    descripcion: str | None = Field(default=None, max_length=255)
    activo: bool | None = None
    permisos: list[str] | None = None


class RolSalida(BaseModel):
    id: int
    codigo: str
    nombre: str
    descripcion: str | None
    activo: bool
    permisos: list[PermisoSalida]
    creado_en: datetime
    modificado_en: datetime


class UsuarioCrearEntrada(BaseModel):
    nombre_usuario: str = Field(min_length=3, max_length=80)
    nombre_completo: str = Field(min_length=2, max_length=180)
    identificacion: str = Field(min_length=2, max_length=40)
    correo: CorreoValido
    clave: str | None = Field(default=None, max_length=128)
    debe_cambiar_clave: bool = True
    rol_id: int
    sede_ids: list[int] = Field(min_length=1, validation_alias=AliasChoices("sede_ids", "sedes"))
    activo: bool = True


class UsuarioEditarEntrada(BaseModel):
    nombre_completo: str | None = Field(default=None, min_length=2, max_length=180)
    identificacion: str | None = Field(default=None, min_length=2, max_length=40)
    correo: CorreoValido | None = None
    rol_id: int | None = None
    sede_ids: list[int] | None = Field(
        default=None, min_length=1, validation_alias=AliasChoices("sede_ids", "sedes")
    )
    activo: bool | None = None
    debe_cambiar_clave: bool | None = None
    clave: str | None = Field(default=None, max_length=128)


class UsuarioSalida(BaseModel):
    id: int
    nombre_usuario: str
    nombre_completo: str
    identificacion: str
    correo: str
    activo: bool
    debe_cambiar_clave: bool
    acepto_condiciones_en: datetime | None
    rol: RolResumen
    sedes: list[SedeResumen]
    creado_en: datetime
    modificado_en: datetime


class AuditoriaSalida(BaseModel):
    id: int
    instante: datetime
    usuario_id: int | None
    sede_id: int | None
    accion: str
    entidad: str
    entidad_id: str
    antes: dict[str, Any] | None
    despues: dict[str, Any] | None
    request_id: str | None


class AuditoriaConsultaSalida(BaseModel):
    id: int
    instante: datetime
    usuario_id: int
    sede_id: int | None
    recurso: str
    parametros_permitidos: dict[str, Any]
    request_id: str | None
