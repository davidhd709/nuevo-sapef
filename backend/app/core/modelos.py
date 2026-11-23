"""Registro de modelos para Alembic.

core no puede importar los módulos de negocio directamente (regla de import-linter),
así que los modelos se descubren por nombre: cada `app/modulos/<modulo>/modelos.py`.
"""

import importlib
import pkgutil


def importar_modelos() -> None:
    paquete = importlib.import_module("app.modulos")  # por nombre: core no depende de módulos
    for info in pkgutil.iter_modules(paquete.__path__):
        if info.ispkg:
            try:
                importlib.import_module(f"{paquete.__name__}.{info.name}.modelos")
            except ModuleNotFoundError as error:
                if error.name != f"{paquete.__name__}.{info.name}.modelos":
                    raise
