"""Conexión a PostgreSQL (SQLAlchemy 2 + psycopg 3)."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import obtener_configuracion


class Base(DeclarativeBase):
    """Base declarativa común de todos los modelos."""


@lru_cache
def obtener_motor() -> Engine:
    config = obtener_configuracion()
    return create_engine(
        str(config.database_url),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        # Si la base no responde, fallar en segundos en lugar de colgarse.
        connect_args={"connect_timeout": 10},
    )


@lru_cache
def _fabrica_sesiones() -> sessionmaker[Session]:
    return sessionmaker(bind=obtener_motor(), autoflush=False, expire_on_commit=False)


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por petición, cerrada al terminar."""
    sesion = _fabrica_sesiones()()
    try:
        yield sesion
    finally:
        sesion.close()


def comprobar_base_de_datos() -> dict[str, str]:
    """Devuelve las versiones de PostgreSQL y PostGIS; lanza excepción si no hay conexión."""
    with obtener_motor().connect() as conexion:
        postgres = conexion.execute(text("SHOW server_version")).scalar_one()
        postgis = conexion.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
        ).scalar_one_or_none()
    return {"postgres": str(postgres), "postgis": str(postgis) if postgis else "no instalado"}
