"""Almacén Parquet de los cortes comerciales (§6.6, §11.5).

    <comercial_dir>/<sede>/<comercializador>/<YYYYMM>/<familia>.parquet + manifest.json

Se escribe en un directorio provisional y se publica el periodo completo con `rename`. Al
reemplazar, la versión vigente se aparta, se publica la nueva y luego se borra la anterior; si algo
falla se restaura. Nunca queda publicado un periodo parcial. Los originales de cada cargue se
guardan aparte, en el almacén de archivos, con su SHA-256.
"""

import hashlib
import json
import os
import shutil
import threading
import uuid
from collections import OrderedDict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from app.core.config import obtener_configuracion

BLOQUE = 1 << 20  # copia por bloques de 1 MiB
_TIPOS = {
    "texto": pa.string(),
    "entero": pa.int64(),
    "decimal": pa.decimal128(20, 4),
    "fecha": pa.date32(),
    "booleano": pa.bool_(),
}


class ArchivoDemasiadoGrande(Exception):
    pass


def raiz() -> Path:
    return obtener_configuracion().comercial_dir


def raiz_originales() -> Path:
    return obtener_configuracion().archivos_dir / "comercial"


def ruta_corte(sede: str, comercializador: str, periodo: str) -> Path:
    return raiz() / sede / comercializador / periodo


def sha256_archivo(ruta: Path) -> str:
    digesto = hashlib.sha256()
    with ruta.open("rb") as f:
        while bloque := f.read(BLOQUE):
            digesto.update(bloque)
    return digesto.hexdigest()


# --- Originales -------------------------------------------------------------------------------


def guardar_original(
    carpeta: Path, indice: int, nombre: str, fuente: BinaryIO, limite: int, restante: int
) -> tuple[Path, str, int]:
    """Copia por bloques y se detiene al superar el límite del archivo o el total de la carga
    (borra lo parcial). Devuelve (ruta, sha256, tamaño)."""
    carpeta.mkdir(parents=True, exist_ok=True)
    seguro = "".join(c if c.isalnum() or c in "._-" else "_" for c in nombre)[-120:]
    destino = carpeta / f"{indice:03d}_{seguro}"
    digesto = hashlib.sha256()
    tamano = 0
    try:
        with destino.open("wb") as salida:
            while bloque := fuente.read(BLOQUE):
                tamano += len(bloque)
                if tamano > limite or tamano > restante:
                    raise ArchivoDemasiadoGrande(nombre)
                digesto.update(bloque)
                salida.write(bloque)
    except BaseException:
        destino.unlink(missing_ok=True)
        raise
    return destino, digesto.hexdigest(), tamano


def borrar_originales(cargue_id: int) -> None:
    shutil.rmtree(raiz_originales() / str(cargue_id), ignore_errors=True)


def leer_original(ruta: str) -> bytes:
    camino = Path(ruta).resolve()
    if raiz_originales().resolve() not in camino.parents:
        raise PermissionError("ruta fuera del almacén de originales")
    return camino.read_bytes()


# --- Escritura y publicación ------------------------------------------------------------------


def _esquema(columnas: dict[str, str]) -> pa.Schema:
    return pa.schema([pa.field(nombre, _TIPOS[tipo]) for nombre, tipo in columnas.items()])


def escribir_provisional(
    familias: dict[str, list[dict[str, Any]]],
    esquemas: dict[str, dict[str, str]],
    manifiesto: dict[str, Any],
) -> Path:
    provisional = raiz() / ".provisional" / uuid.uuid4().hex
    provisional.mkdir(parents=True)
    detalle: dict[str, Any] = {}
    for familia, columnas in esquemas.items():
        esquema = _esquema(columnas)
        filas = [{c: fila.get(c) for c in columnas} for fila in familias.get(familia, [])]
        tabla = pa.Table.from_pylist(filas, schema=esquema)
        archivo = provisional / f"{familia}.parquet"
        pq.write_table(tabla, archivo, compression="zstd")
        detalle[familia] = {
            "archivo_parquet": archivo.name,
            "filas": tabla.num_rows,
            "sha256_parquet": sha256_archivo(archivo),
            "presente": familia in manifiesto.get("presentes", []),
        }
    manifiesto = {**manifiesto, "familias": detalle}
    (provisional / "manifest.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return provisional


def publicar(provisional: Path, destino: Path) -> None:
    """Reemplazo atómico del periodo. Si falla, el periodo anterior queda como estaba."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    aparte = destino.with_name(f".{destino.name}.anterior-{uuid.uuid4().hex[:8]}")
    tenia_anterior = destino.exists()
    if tenia_anterior:
        os.replace(destino, aparte)
    try:
        os.replace(provisional, destino)
    except BaseException:
        if tenia_anterior:
            os.replace(aparte, destino)
        shutil.rmtree(provisional, ignore_errors=True)
        raise
    if tenia_anterior:
        shutil.rmtree(aparte, ignore_errors=True)
    _invalidar(destino)


def descartar(provisional: Path | None) -> None:
    if provisional is not None:
        shutil.rmtree(provisional, ignore_errors=True)


def eliminar_corte(destino: Path) -> None:
    if not destino.exists():
        return
    aparte = destino.with_name(f".{destino.name}.eliminado-{uuid.uuid4().hex[:8]}")
    os.replace(destino, aparte)
    shutil.rmtree(aparte, ignore_errors=True)
    _invalidar(destino)


def leer_manifiesto(destino: Path) -> dict[str, Any] | None:
    archivo = destino / "manifest.json"
    if not archivo.is_file():
        return None
    return json.loads(archivo.read_text(encoding="utf-8"))


# --- Lectura con caché ------------------------------------------------------------------------

_CACHE: "OrderedDict[tuple[Any, ...], list[dict[str, Any]]]" = OrderedDict()
_CACHE_MAX = 48
_CANDADO = threading.Lock()


def _invalidar(destino: Path) -> None:
    prefijo = str(destino)
    with _CANDADO:
        for clave in [k for k in _CACHE if str(k[0]).startswith(prefijo)]:
            del _CACHE[clave]


def leer_familia(
    destino: Path, familia: str, columnas: Iterable[str] | None = None
) -> list[dict[str, Any]]:
    """Filas de la familia como diccionarios (decimales exactos, fechas). Lista vacía si el corte
    no tiene esa familia. El resultado se comparte desde caché: no modificarlo."""
    archivo = destino / f"{familia}.parquet"
    if not archivo.is_file():
        return []
    cols = tuple(columnas) if columnas else None
    clave = (str(archivo), archivo.stat().st_mtime_ns, cols)
    with _CANDADO:
        if clave in _CACHE:
            _CACHE.move_to_end(clave)
            return _CACHE[clave]
    tabla = pq.read_table(archivo)
    if cols:
        tabla = tabla.select([c for c in cols if c in tabla.column_names])
    filas = tabla.to_pylist()
    with _CANDADO:
        _CACHE[clave] = filas
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return filas


def leer_pagina(
    destino: Path,
    familia: str,
    *,
    page: int,
    size: int,
    buscar: str | None,
    campos_busqueda: tuple[str, ...],
) -> tuple[list[dict[str, Any]], int]:
    archivo = destino / f"{familia}.parquet"
    if not archivo.is_file():
        return [], 0
    tabla = pq.read_table(archivo)
    if buscar:
        patron = buscar.strip().lower()
        mascara = None
        for campo in campos_busqueda:
            if campo not in tabla.column_names:
                continue
            columna = pc.utf8_lower(pc.cast(tabla[campo], pa.string()))
            coincide = pc.fill_null(pc.match_substring(columna, patron), False)
            mascara = coincide if mascara is None else pc.or_(mascara, coincide)
        if mascara is not None:
            tabla = tabla.filter(mascara)
    total = tabla.num_rows
    return tabla.slice((page - 1) * size, size).to_pylist(), total


def escribir_texto_temporal(contenido: bytes, sufijo: str) -> Path:
    carpeta = raiz() / ".exportaciones"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{uuid.uuid4().hex}{sufijo}"
    ruta.write_bytes(contenido)
    return ruta


# --- Paquetes de OPainn (HU-080) --------------------------------------------------------------

_IDENTIFICADORES = ("nic", "cuenta", "cliente_id")


def _a_tipo(valor: Any, tipo: str) -> Any:
    if valor is None:
        return None
    if tipo == "decimal":
        return Decimal(str(valor)).quantize(Decimal("0.0001"))
    if tipo == "entero":
        return int(valor)
    if tipo == "texto":
        return str(valor)
    if tipo == "fecha" and isinstance(valor, str):
        return date.fromisoformat(valor[:10])
    return valor


SIN_MANIFIESTO = (
    "El paquete de OPainn no trae manifest.json: las familias se tomaron de sus Parquet y las "
    "huellas se calcularon al importar (no se pudo verificar la integridad contra el origen)."
)
MANIFIESTO_OPAINN = (
    "El manifiesto de OPainn guarda las huellas de los archivos del comercializador, no las de "
    "los Parquet: las familias se tomaron de sus Parquet y sus huellas se calcularon al importar."
)


def _manifiesto_verificable(manifiesto: dict[str, Any]) -> bool:
    """Formato con la huella de cada Parquet: {"familias": {familia: {archivo_parquet,
    sha256_parquet}}}. El almacén de OPainn usa otro (huellas de los archivos fuente)."""
    familias = manifiesto.get("familias")
    return isinstance(familias, dict) and all(
        isinstance(m, dict) and m.get("sha256_parquet") for m in familias.values()
    )


def aviso_manifiesto(carpeta: Path) -> str | None:
    """Por qué no se pudo verificar la integridad del paquete contra el origen (o None)."""
    manifiesto = leer_manifiesto(carpeta)
    if manifiesto is None:
        return SIN_MANIFIESTO
    return None if _manifiesto_verificable(manifiesto) else MANIFIESTO_OPAINN


def manifiesto_efectivo(
    carpeta: Path, esquemas: dict[str, dict[str, str]]
) -> dict[str, Any] | None:
    """El manifiesto con huellas de los Parquet. Si el paquete no lo trae (cortes viejos de
    OPainn) o trae el de OPainn (huellas de los archivos fuente), se arma uno con los
    `<familia>.parquet` conocidos y sus huellas, `inferido: True`, conservando el original en
    `origen` para la trazabilidad. None si no hay Parquet de familias conocidas."""
    manifiesto = leer_manifiesto(carpeta)
    if manifiesto is not None and _manifiesto_verificable(manifiesto):
        return manifiesto
    familias = {
        familia: {
            "archivo_parquet": f"{familia}.parquet",
            "sha256_parquet": sha256_archivo(carpeta / f"{familia}.parquet"),
        }
        for familia in esquemas
        if (carpeta / f"{familia}.parquet").is_file()
    }
    if not familias:
        return None
    periodo = (manifiesto or {}).get("periodo") or carpeta.name
    return {"periodo": str(periodo), "familias": familias, "inferido": True, "origen": manifiesto}


def leer_paquete(
    carpeta: Path, esquemas: dict[str, dict[str, str]]
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Lee un periodo del almacén de OPainn: verifica el SHA-256 de cada Parquet contra su
    manifiesto y que el esquema sea compatible. Devuelve (familias, errores)."""
    manifiesto = manifiesto_efectivo(carpeta, esquemas)
    if manifiesto is None:
        return {}, ["El paquete no trae manifest.json ni Parquet de familias conocidas."]
    familias: dict[str, list[dict[str, Any]]] = {}
    errores: list[str] = []
    for familia, meta in (manifiesto.get("familias") or {}).items():
        if familia not in esquemas:
            errores.append(f"Familia desconocida en el manifiesto: {familia}.")
            continue
        archivo = (carpeta / str(meta.get("archivo_parquet", ""))).resolve()
        if carpeta.resolve() not in archivo.parents or not archivo.is_file():
            errores.append(f"{familia}: el Parquet del manifiesto no existe.")
            continue
        if sha256_archivo(archivo) != meta.get("sha256_parquet"):
            errores.append(f"{familia}: el SHA-256 no coincide con el manifiesto.")
            continue
        try:
            tabla = pq.read_table(archivo)
        except Exception:  # pyarrow lanza varios tipos según el daño
            errores.append(f"{familia}: el archivo no es un Parquet válido.")
            continue
        esquema = esquemas[familia]
        clave = next((c for c in _IDENTIFICADORES if c in esquema), None)
        if clave is None or clave not in tabla.column_names:
            errores.append(f"{familia}: esquema incompatible (falta la columna {clave}).")
            continue
        comunes = [c for c in esquema if c in tabla.column_names]
        try:
            filas = [
                {c: _a_tipo(fila.get(c), esquema[c]) for c in comunes}
                for fila in tabla.select(comunes).to_pylist()
            ]
        except (ValueError, ArithmeticError, TypeError):
            errores.append(f"{familia}: hay valores que no corresponden al tipo esperado.")
            continue
        familias[familia] = filas
    return familias, errores


def verificar_paquete(carpeta: Path, esquemas: dict[str, dict[str, str]]) -> list[str]:
    """Comprobación rápida antes de encolar: manifiesto, SHA-256 y esquema (sin leer los datos)."""
    manifiesto = manifiesto_efectivo(carpeta, esquemas)
    if manifiesto is None:
        return ["El paquete no trae manifest.json ni Parquet de familias conocidas."]
    errores = []
    for familia, meta in (manifiesto.get("familias") or {}).items():
        archivo = (carpeta / str(meta.get("archivo_parquet", ""))).resolve()
        if familia not in esquemas:
            errores.append(f"Familia desconocida en el manifiesto: {familia}.")
        elif carpeta.resolve() not in archivo.parents or not archivo.is_file():
            errores.append(f"{familia}: el Parquet del manifiesto no existe.")
        elif sha256_archivo(archivo) != meta.get("sha256_parquet"):
            errores.append(f"{familia}: el SHA-256 no coincide con el manifiesto.")
        else:
            try:
                columnas = pq.read_schema(archivo).names
            except Exception:  # pyarrow lanza varios tipos según el daño
                errores.append(f"{familia}: el archivo no es un Parquet válido.")
                continue
            clave = next((c for c in _IDENTIFICADORES if c in esquemas[familia]), None)
            if clave not in columnas:
                errores.append(f"{familia}: esquema incompatible (falta la columna {clave}).")
    return errores
