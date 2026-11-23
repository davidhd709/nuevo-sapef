"""Entorno de Alembic: usa la misma configuración y la misma Base que la aplicación."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

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

# SQLAlchemy 2 refleja como «esquema por defecto» toda tabla visible en el search_path. La imagen
# oficial de PostGIS (la de la CI) instala postgis_topology y postgis_tiger_geocoder y agrega sus
# esquemas al search_path: sin este filtro, `alembic check` propone borrar sus tablas.
_SQL_TABLAS_AJENAS = text(
    """
    SELECT c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND (
        n.nspname <> current_schema()
        OR EXISTS (
          SELECT 1 FROM pg_depend d
          WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e'
        )
      )
    """
)
_tablas_ajenas: set[str] = set()


def _incluir_objeto(objeto, nombre, tipo, reflejado, comparar_con) -> bool:
    tabla = nombre if tipo == "table" else getattr(getattr(objeto, "table", None), "name", None)
    if not tabla:
        return True
    if tabla.startswith(_EXCLUIDAS_PREFIJOS):
        return False
    # Solo se ignora lo reflejado de la base que no está en los modelos de la aplicación.
    return not (reflejado and tabla in _tablas_ajenas and tabla not in target_metadata.tables)


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
        _tablas_ajenas.update(conexion.execute(_SQL_TABLAS_AJENAS).scalars())
        conexion.commit()  # cierra la transacción implícita: Alembic abre la suya
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
