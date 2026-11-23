"""Carga de datos semilla y creación del primer administrador.

Uso (desde backend/, con la base migrada):

    python -m app.semillas                      # permisos, roles y catálogos (idempotente)
    python -m app.semillas admin --usuario admin --correo admin@ejemplo.co \\
        --nombre "Administrador" --identificacion 0

La contraseña del administrador se toma de SAPEF_ADMIN_CLAVE o se pide por consola; nunca se
pasa como argumento (quedaría en el historial y en la lista de procesos). Por defecto el
administrador debe cambiarla en el primer ingreso; `--sin-cambio-obligatorio` lo evita
(solo para desarrollo y pruebas E2E).
"""

import argparse
import getpass
import logging
import os
import sys

from app.core.config import obtener_configuracion
from app.core.db import _fabrica_sesiones
from app.core.logs import configurar_logs
from app.modulos.activos import servicio as activos
from app.modulos.configuracion import servicio as configuracion
from app.modulos.seguridad import servicio as seguridad

log = logging.getLogger("sapef.semillas")


def sembrar() -> dict[str, int]:
    config = obtener_configuracion()
    with _fabrica_sesiones()() as db:
        conteos = configuracion.sembrar_catalogos(
            db, archivo_max_evidencia_mb=config.archivo_max_evidencia_mb
        )
        conteos |= seguridad.sincronizar_permisos_y_roles(db)
        conteos |= activos.sembrar_comodines_activos(db)
        db.commit()
    return conteos


def _crear_admin(args: argparse.Namespace) -> int:
    clave = os.environ.get("SAPEF_ADMIN_CLAVE") or getpass.getpass("Contraseña del admin: ")
    with _fabrica_sesiones()() as db:
        try:
            creado = seguridad.crear_admin_inicial(
                db,
                nombre_usuario=args.usuario,
                correo=args.correo,
                nombre_completo=args.nombre,
                identificacion=args.identificacion,
                clave=clave,
                forzar_cambio_clave=not args.sin_cambio_obligatorio,
            )
        except ValueError as exc:
            log.error("%s", exc)
            return 1
        except Exception as exc:  # p. ej., la contraseña no cumple la política
            detalle = getattr(exc, "detail", None) or "no se pudo crear el administrador"
            log.error("%s", detalle)
            return 1
        db.commit()
    log.info("administrador %s", "creado" if creado else "ya existía; no se modificó")
    return 0


def main(argv: list[str] | None = None) -> int:
    configurar_logs(obtener_configuracion().log_nivel)
    parser = argparse.ArgumentParser(prog="python -m app.semillas", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="comando")
    admin = sub.add_parser("admin", help="crear el primer administrador (todas las sedes)")
    admin.add_argument("--usuario", required=True)
    admin.add_argument("--correo", required=True)
    admin.add_argument("--nombre", default="Administrador")
    admin.add_argument("--identificacion", default="0")
    admin.add_argument("--sin-cambio-obligatorio", action="store_true")
    args = parser.parse_args(argv)

    conteos = sembrar()
    log.info("semilla aplicada; registros creados: %s", conteos)
    if args.comando == "admin":
        return _crear_admin(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
