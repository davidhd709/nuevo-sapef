"""Reglas puras de dominio del módulo de activos y mapa (sin BD, HTTP ni cola)."""

import re
import struct
from dataclasses import dataclass
from typing import Any

_RE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


@dataclass(frozen=True)
class ErrorDominioActivo(Exception):
    status_code: int
    detail: str


def agrupar_eventos_por(
    eventos: list[dict[str, Any]], clave: str, campos_detalle: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Resume los eventos por PQRS u orden (hoja de vida, RF-023).

    `activos` no depende de atención ni de trabajos: lo que la ficha muestra de cada PQRS u
    orden viaja en el `detalle` del evento que ellos registran.
    """
    grupos: dict[Any, dict[str, Any]] = {}
    for ev in sorted(eventos, key=lambda e: e["fecha"]):
        ident = ev.get(clave)
        if ident is None:
            continue
        grupo = grupos.setdefault(
            ident, {"id": ident, "desde": ev["fecha"], "hasta": ev["fecha"], "eventos": []}
        )
        grupo["hasta"] = ev["fecha"]
        grupo["eventos"].append(ev["tipo"])
        detalle = ev.get("detalle") or {}
        for campo in campos_detalle:
            if detalle.get(campo) is not None:
                grupo[campo] = detalle[campo]
    return list(grupos.values())


def normalizar_codigo_luminaria(codigo: str) -> str:
    limpio = codigo.strip()
    if not limpio:
        raise ErrorDominioActivo(422, "El código de luminaria es obligatorio.")
    return limpio


def validar_coordenadas(
    latitud: float | None, longitud: float | None
) -> tuple[float, float] | None:
    if latitud is None and longitud is None:
        return None
    if latitud is None or longitud is None:
        raise ErrorDominioActivo(
            422, "Debe proporcionar tanto latitud como longitud, o ninguna de las dos."
        )
    if not (-90.0 <= latitud <= 90.0 and -180.0 <= longitud <= 180.0):
        raise ErrorDominioActivo(422, "Coordenadas geográficas fuera de rango válido.")
    return float(latitud), float(longitud)


def construir_url_google_maps(latitud: float | None, longitud: float | None) -> str | None:
    if latitud is None or longitud is None:
        return None
    return f"https://www.google.com/maps?q={latitud:.6f},{longitud:.6f}"


def validar_lote_consecutivos(inicial: int, final: int, cantidad: int) -> list[str]:
    if inicial < 1 or final < 1:
        raise ErrorDominioActivo(422, "Los consecutivos deben ser mayores o iguales a 1.")
    if inicial > final:
        raise ErrorDominioActivo(
            422, "El consecutivo inicial no puede ser mayor que el consecutivo final."
        )
    esperada = final - inicial + 1
    if cantidad != esperada:
        raise ErrorDominioActivo(
            422,
            f"La cantidad ({cantidad}) no coincide con el rango ({esperada}).",
        )
    if esperada > 5000:
        raise ErrorDominioActivo(422, "Un lote no puede superar 5000 luminarias.")
    return [str(n) for n in range(inicial, final + 1)]


def validar_coordenadas_tesela(z: int, x: int, y: int) -> None:
    if z < 0 or z > 22:
        raise ErrorDominioActivo(422, "Nivel de zoom de tesela fuera de rango (0..22).")
    max_coord = 1 << z
    if x < 0 or x >= max_coord or y < 0 or y >= max_coord:
        raise ErrorDominioActivo(422, "Coordenadas de tesela fuera de rango para el zoom dado.")


def parsear_rango_bytes(cabecera: str, total: int) -> tuple[int, int]:
    """Parsea `Range: bytes=start-end`. Lanza ErrorDominioActivo(416, ...) si es inválido."""
    if total <= 0:
        raise ErrorDominioActivo(416, "Archivo vacío.")
    coincidencia = _RE_RANGE.match(cabecera.strip())
    if not coincidencia:
        raise ErrorDominioActivo(416, "Cabecera Range inválida.")
    inicio_txt, fin_txt = coincidencia.groups()
    if not inicio_txt and not fin_txt:
        raise ErrorDominioActivo(416, "Cabecera Range vacía.")
    if not inicio_txt:
        sufijo = int(fin_txt)
        if sufijo <= 0:
            raise ErrorDominioActivo(416, "Rango de bytes inválido.")
        inicio = max(0, total - sufijo)
        fin = total - 1
        return inicio, fin
    inicio = int(inicio_txt)
    if inicio >= total:
        raise ErrorDominioActivo(416, "Rango de bytes fuera del tamaño del archivo.")
    fin = int(fin_txt) if fin_txt else total - 1
    if fin < inicio:
        raise ErrorDominioActivo(416, "Rango de bytes invertido.")
    fin = min(fin, total - 1)
    return inicio, fin


def construir_pmtiles_base_sede(sede_codigo: str) -> bytes:
    """Genera un archivo PMTiles v3 válido y determinista para el mapa base offline de la sede."""
    bboxes: dict[str, tuple[float, float, float, float]] = {
        "montelibano": (-75.46, 7.94, -75.38, 8.02),
        "alcala": (-75.81, 4.65, -75.76, 4.70),
    }
    min_lon, min_lat, max_lon, max_lat = bboxes[sede_codigo]
    cabecera = bytearray(127)
    cabecera[0:8] = b"PMTiles\x03"
    # Root dir offset=127, length=1; metadata offset=128, length=2; leaf=0, data=130
    struct.pack_into("<QQQQQQQQ", cabecera, 8, 127, 1, 128, 2, 0, 0, 130, 0)
    # 1 byte tile type (1=MVT), 1 byte min_zoom=6, 1 byte max_zoom=16
    cabecera[97] = 1  # internal compression: none
    cabecera[98] = 1  # tile compression: none
    cabecera[99] = 1  # tile type: MVT
    cabecera[100] = 6
    cabecera[101] = 16
    struct.pack_into(
        "<iiii",
        cabecera,
        102,
        int(min_lon * 1e7),
        int(min_lat * 1e7),
        int(max_lon * 1e7),
        int(max_lat * 1e7),
    )
    cabecera[118] = 12
    struct.pack_into(
        "<ii",
        cabecera,
        119,
        int((min_lon + max_lon) / 2 * 1e7),
        int((min_lat + max_lat) / 2 * 1e7),
    )
    # Root dir (0 entries = 1 byte 0x00) + empty JSON "{}" (2 bytes) + padding hasta 4096 bytes
    cuerpo = bytes(cabecera) + b"\x00{}"
    return cuerpo.ljust(4096, b"\x00")
