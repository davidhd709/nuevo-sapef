"""Carga de datos semilla y creación del primer administrador.

Uso (desde backend/, con la base migrada):

    python -m app.semillas                      # permisos, roles y catálogos (idempotente)
    python -m app.semillas admin --usuario admin --correo admin@ejemplo.co \\
        --nombre "Administrador" --identificacion 0

La contraseña del administrador se toma de SAPEF_ADMIN_CLAVE o se pide por consola; nunca se
pasa como argumento (quedaría en el historial y en la lista de procesos). Por defecto el
administrador debe cambiarla en el primer ingreso; `--sin-cambio-obligatorio` lo evita
(solo para desarrollo y pruebas E2E).

    python -m app.semillas vapid                # genera un par de claves VAPID (Web Push)

    python -m app.semillas excepciones --sede montelibano --comercializador afinia \
        --anio 2026 --archivo /ruta/excepciones_tarifarias_afinia_2026.json

`excepciones` carga los contribuyentes especiales desde los catálogos privados de OPainn en el
acuerdo aprobado de ese año (crea una vigencia aprobada nueva y la anterior queda reemplazada):
Afinia, `{"vigencias": {"2026": {"factores_uvt_por_nic": {"<NIC>": <factor>}}}}` (RN-004);
Celsia, `{"reglas_por_cuenta": {"<cuenta>": {"tipo": ...}}, "pendientes_revision": [...]}` (anexo
de la carta). El archivo nunca se copia al repositorio.

`vapid` imprime la clave privada para `SAPEF_VAPID_CLAVE_PRIVADA` (va en el .env del servidor,
nunca al repositorio) y la pública que la app de campo recibirá de la API.
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
from app.modulos.notificaciones import servicio as notificaciones
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


def _cargar_excepciones(args: argparse.Namespace) -> int:
    import json
    from decimal import Decimal
    from pathlib import Path

    try:
        documento = json.loads(Path(args.archivo).read_text(encoding="utf-8"))
        vigencia = documento.get("vigencias", {}).get(str(args.anio)) or {}
        factores = {
            str(nic): Decimal(str(f))
            for nic, f in (vigencia.get("factores_uvt_por_nic") or {}).items()
        }
        reglas = {str(c): dict(r) for c, r in (documento.get("reglas_por_cuenta") or {}).items()}
        for cuenta in documento.get("pendientes_revision") or []:
            reglas[str(cuenta)] = {"pendiente_revision": True}
        if not factores and not reglas:
            raise ValueError("no trae factores_uvt_por_nic ni reglas_por_cuenta")
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
        log.error("archivo de excepciones inválido: %s", exc)
        return 1
    with _fabrica_sesiones()() as db:
        sede = configuracion.obtener_sede_por_codigo_publico(db, args.sede)
        if sede is None:
            log.error("sede desconocida: %s", args.sede)
            return 1
        try:
            resultado = configuracion.reemplazar_excepciones_acuerdo(
                db,
                sede_id=sede["id"],
                comercializador_codigo=args.comercializador,
                anio=args.anio,
                factores=factores,
                reglas=reglas,
                fuente=f"Catálogo de excepciones {Path(args.archivo).name}",
                actor_id=None,
            )
        except Exception as exc:  # HTTPException del servicio: sin acuerdo aprobado, etc.
            log.error("%s", getattr(exc, "detail", exc))
            return 1
        db.commit()
    log.info("contribuyentes especiales: %s", resultado)
    return 0


def main(argv: list[str] | None = None) -> int:
    configurar_logs(obtener_configuracion().log_nivel)
    parser = argparse.ArgumentParser(
        prog="python -m app.semillas",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="comando")
    admin = sub.add_parser("admin", help="crear el primer administrador (todas las sedes)")
    admin.add_argument("--usuario", required=True)
    admin.add_argument("--correo", required=True)
    admin.add_argument("--nombre", default="Administrador")
    admin.add_argument("--identificacion", default="0")
    admin.add_argument("--sin-cambio-obligatorio", action="store_true")
    sub.add_parser("vapid", help="generar claves VAPID para Web Push (no toca la base)")
    exc = sub.add_parser("excepciones", help="cargar contribuyentes especiales desde un archivo")
    exc.add_argument("--sede", required=True)
    exc.add_argument("--comercializador", required=True)
    exc.add_argument("--anio", type=int, required=True)
    exc.add_argument("--archivo", required=True)
    args = parser.parse_args(argv)

    if args.comando == "vapid":
        privada, publica = notificaciones.generar_claves_vapid()
        print(f"SAPEF_VAPID_CLAVE_PRIVADA={privada}")  # noqa: T201
        print(f"# clave pública (applicationServerKey): {publica}")  # noqa: T201
        return 0

    conteos = sembrar()
    log.info("semilla aplicada; registros creados: %s", conteos)
    if args.comando == "admin":
        return _crear_admin(args)
    if args.comando == "excepciones":
        return _cargar_excepciones(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
