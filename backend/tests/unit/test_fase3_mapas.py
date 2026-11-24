"""Los mapas que viajan en la imagen contienen teselas y las capas usadas por la PWA."""

import gzip
import json
import struct
from pathlib import Path

import pytest

MAPAS = Path(__file__).resolve().parents[2] / "app" / "mapas"


@pytest.mark.parametrize(
    ("sede", "centro"),
    [("montelibano", (-75.42, 7.98)), ("alcala", (-75.785, 4.675))],
)
def test_mapa_base_real_por_sede(sede: str, centro: tuple[float, float]) -> None:
    datos = (MAPAS / f"{sede}.pmtiles").read_bytes()
    assert len(datos) > 100_000
    assert datos[:8] == b"PMTiles\x03"
    assert struct.unpack_from("<Q", datos, 72)[0] > 0  # teselas con contenido
    oeste, sur, este, norte = (v / 1e7 for v in struct.unpack_from("<iiii", datos, 102))
    assert oeste < centro[0] < este
    assert sur < centro[1] < norte

    inicio, longitud = struct.unpack_from("<QQ", datos, 24)
    metadatos = datos[inicio : inicio + longitud]
    if datos[97] == 2:  # gzip
        metadatos = gzip.decompress(metadatos)
    capas = {c["id"] for c in json.loads(metadatos)["vector_layers"]}
    assert {"earth", "water", "buildings", "roads"} <= capas
