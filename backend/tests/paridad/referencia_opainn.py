"""Calcula la referencia de paridad con el motor de OPainn, sobre su propio almacén.

Se ejecuta con el Python de OPainn (no con el del sistema nuevo), así que no importa nada de
`app`. Escribe en stdout (UTF-8) un JSON {nombre: resultado}:

- Las mismas instantáneas de `datos/golden/regresion/` (TD de Afinia, Celsia y Vatia), pero
  calculadas hoy: las de Celsia guardadas quedaron viejas (se tomaron antes de cargar 202610, y
  el sector de una cuenta se lee de todos los cortes, también los posteriores).
- El control tarifario de 2026 por NIC (Afinia) y por cuenta (Celsia): resumen y el estado de
  cada usuario que no quedó correcto.

    <opainn>/.venv/Scripts/python.exe referencia_opainn.py <opainn>
"""

import json
import sys
from pathlib import Path

RAIZ = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(RAIZ / "scripts" / "comun"))
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "src"))

import duckdb  # noqa: E402
import instantanea  # noqa: E402  (script de OPainn que toma sus instantáneas)
from opainn.afinia.control_tarifario import (  # noqa: E402
    cargar_parametros_tarifarios,
    control_facturacion_ap,
)
from opainn.afinia.td import periodos_disponibles  # noqa: E402
from opainn.api import base  # noqa: E402
from opainn.celsia.base import periodos_disponibles as periodos_celsia  # noqa: E402
from opainn.celsia.control_tarifario import control_tarifario_celsia  # noqa: E402

ANIO = 2026
salida = instantanea.tomar()
con = duckdb.connect()
parametros = cargar_parametros_tarifarios(base.CATALOGO_PARAMETROS_TARIFARIOS, ANIO)
for periodo in periodos_disponibles(base.ALMACEN):
    if not periodo.startswith(str(ANIO)):
        continue
    resumen = control_facturacion_ap(con, base.ALMACEN, periodo, parametros, por_pagina=1)[
        "resumen"
    ]
    hallazgos = {}
    for estado in ("por_encima", "por_debajo", "requiere_revision", "no_validable"):
        pagina = 1
        while True:
            datos = control_facturacion_ap(
                con,
                base.ALMACEN,
                periodo,
                parametros,
                estado=estado,
                pagina=pagina,
                por_pagina=1000,
            )
            for fila in datos["filas"]:
                hallazgos[str(fila["nic"])] = [fila["estado"], fila.get("diferencia_pesos")]
            if len(datos["filas"]) < 1000:
                break
            pagina += 1
    salida[f"afinia_control_{periodo}"] = {"resumen": resumen, "hallazgos": hallazgos}

for periodo in periodos_celsia(base.ALMACEN_CELSIA):
    if not periodo.startswith(str(ANIO)):
        continue
    datos = control_tarifario_celsia(
        con, base.ALMACEN_CELSIA, periodo, base.CATALOGO_PARAMETROS_CELSIA
    )
    salida[f"celsia_control_{periodo}"] = {
        "resumen": datos.get("resumen"),
        "hallazgos": {
            str(f["cuenta"]): [f["resultado"].upper(), f.get("diferencia")]
            for f in datos.get("resultados", [])
            if f["resultado"] != "correcto"
        },
    }

sys.stdout.buffer.write(json.dumps(salida, ensure_ascii=False, default=str).encode("utf-8"))
