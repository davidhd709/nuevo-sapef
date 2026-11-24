"""Configuración leída de variables de entorno (prefijo SAPEF_). Nunca se escriben secretos aquí."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SECRETO_DEV_DEFECTO = "dev-solo-local-no-usar-en-produccion-32bytes"


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SAPEF_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    entorno: Literal["desarrollo", "pruebas", "produccion"] = "desarrollo"
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+psycopg://sapef:sapef@127.0.0.1:55432/sapef"),
        description="URL de PostgreSQL con el driver psycopg 3",
    )
    log_nivel: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Seguridad y sesiones
    secret_key: SecretStr = Field(
        default=SecretStr(_SECRETO_DEV_DEFECTO),
        description=(
            "Secreto HMAC/cifrado de sesiones y tokens (>=32 chars obligatorio en produccion)"
        ),
    )
    cookie_segura: bool | None = None
    sesion_acceso_minutos: int = Field(default=15, ge=1)
    sesion_renovacion_web_horas: int = Field(default=12, ge=1)
    sesion_renovacion_pwa_dias: int = Field(default=30, ge=1)
    login_max_intentos: int = Field(default=5, ge=1)
    login_bloqueo_minutos: int = Field(default=15, ge=1)
    recuperacion_token_minutos: int = Field(default=30, ge=1)

    # Archivos y evidencias
    archivos_dir: Path = Path("/data/archivos")
    archivos_backend: Literal["local", "s3"] = "local"
    archivo_max_evidencia_mb: int = Field(default=10, ge=1)
    archivo_max_general_mb: int = Field(default=256, ge=1)

    # SMTP opcional (solo por variables de entorno; nunca se persiste en BD ni API)
    smtp_host: str | None = None
    smtp_puerto: int = Field(default=587, ge=1, le=65535)
    smtp_usuario: str | None = None
    smtp_clave: SecretStr | None = None
    smtp_remitente: str = "noreply@sapef.local"
    smtp_tls: bool = True

    # Web Push (app de campo). Clave privada VAPID en base64url (python -m app.semillas vapid).
    vapid_clave_privada: SecretStr | None = None
    vapid_sujeto: str = "mailto:soporte@sapef.local"
    push_ttl_segundos: int = Field(default=86400, ge=60)

    @model_validator(mode="after")
    def _validar_seguridad_produccion(self) -> "Configuracion":
        if self.es_produccion:
            secreto = self.secret_key.get_secret_value()
            if (
                len(secreto) < 32
                or secreto == _SECRETO_DEV_DEFECTO
                or "dev-solo-local" in secreto.lower()
                or "cambiar" in secreto.lower()
                or len(set(secreto)) < 8
            ):
                raise ValueError(
                    "SAPEF_SECRET_KEY es obligatorio en produccion, debe tener al menos "
                    "32 caracteres con suficiente entropia y no usar valores de ejemplo."
                )
        return self

    @property
    def es_produccion(self) -> bool:
        return self.entorno == "produccion"

    @property
    def cookie_segura_efectiva(self) -> bool:
        if self.cookie_segura is not None:
            return self.cookie_segura
        return self.es_produccion


@lru_cache
def obtener_configuracion() -> Configuracion:
    return Configuracion()
