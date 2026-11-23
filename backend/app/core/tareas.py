"""Cola de tareas en segundo plano (Procrastinate, sobre PostgreSQL: sin Redis).

- La API encola con `await tarea.defer_async(...)`.
- El worker (`python -m app.worker`) las ejecuta.
- Las tareas de cada módulo viven en `app/modulos/<modulo>/tareas.py` y se descubren solas
  (el worker solo ejecuta las tareas que conoce).

REGLA: los argumentos de una tarea deben ser identificadores (id de cargue, de orden…),
nunca datos personales ni secretos: Procrastinate los guarda en la tabla de la cola y los
escribe en los logs.
"""

import asyncio
import importlib
import pkgutil
import sys

from procrastinate import App, PsycopgConnector

from app.core.config import obtener_configuracion

# psycopg 3 en modo asíncrono requiere SelectorEventLoop en Windows
# (ProactorEventLoop no es compatible).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _conninfo() -> str:
    # Procrastinate usa psycopg directamente: la URL no lleva el sufijo "+psycopg" de SQLAlchemy.
    return str(obtener_configuracion().database_url).replace("postgresql+psycopg://", "postgresql://")


def _rutas_tareas() -> list[str]:
    rutas = ["app.core.tareas_sistema"]
    paquete = importlib.import_module("app.modulos")  # por nombre: core no depende de módulos
    for info in pkgutil.iter_modules(paquete.__path__):
        nombre = f"{paquete.__name__}.{info.name}.tareas"
        if info.ispkg and importlib.util.find_spec(nombre) is not None:
            rutas.append(nombre)
    return rutas


app_tareas = App(
    connector=PsycopgConnector(conninfo=_conninfo(), kwargs={"connect_timeout": 10}),
    import_paths=_rutas_tareas(),
)
