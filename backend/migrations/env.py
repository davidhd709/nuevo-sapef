"""Entorno de Alembic: usa la misma configuración y la misma Base que la aplicación."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import obtener_configuracion
from app.core.db import Base
from app.core.modelos import importar_modelos

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", str(obtener_configuracion().database_url))

# Todos los modelos de los módulos deben estar importados para que autogenerate los vea.
importar_modelos()
target_metadata = Base.metadata

# Tablas que no son de la aplicación y que autogenerate debe ignorar.
_EXCLUIDAS_PREFIJOS = ("procrastinate_", "spatial_ref_sys")


def _incluir_objeto(objeto, nombre, tipo, reflejado, comparar_con) -> bool:
    es_ajena = tipo == "table" and bool(nombre) and nombre.startswith(_EXCLUIDAS_PREFIJOS)
    return not es_ajena


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=_incluir_objeto,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    motor = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 10},
    )
    with motor.connect() as conexion:
        context.configure(
            connection=conexion,
            target_metadata=target_metadata,
            include_object=_incluir_objeto,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
