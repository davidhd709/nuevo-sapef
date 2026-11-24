"""Esquemas Pydantic v2 (DTOs) del módulo de notificaciones."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClavesPush(_Entrada):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class SuscripcionEntrada(BaseModel):
    """Lo que entrega `PushSubscription.toJSON()` del navegador (con `keys` o `claves`)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    endpoint: str = Field(max_length=2048)
    claves: ClavesPush = Field(alias="keys")


class SuscripcionBorrarEntrada(_Entrada):
    endpoint: str = Field(max_length=2048)


class SuscripcionSalida(BaseModel):
    id: int
    creado_en: datetime


class ClavePublicaSalida(BaseModel):
    habilitado: bool
    clave_publica: str | None
