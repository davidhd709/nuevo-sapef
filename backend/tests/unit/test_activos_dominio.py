"""Pruebas unitarias puras de dominio para activos, mapa y normalización de migración."""

from datetime import date

import pytest

from app.modulos.activos import dominio as activos_dom
from app.modulos.migracion import dominio as mig_dom


def test_validar_coordenadas_y_google_maps() -> None:
    assert activos_dom.validar_coordenadas(None, None) is None
    assert activos_dom.validar_coordenadas(7.98, -75.41) == (7.98, -75.41)
    assert (
        activos_dom.construir_url_google_maps(7.98, -75.41)
        == "https://www.google.com/maps?q=7.980000,-75.410000"
    )

    with pytest.raises(activos_dom.ErrorDominioActivo):
        activos_dom.validar_coordenadas(7.98, None)
    with pytest.raises(activos_dom.ErrorDominioActivo):
        activos_dom.validar_coordenadas(95.0, -75.41)
    with pytest.raises(activos_dom.ErrorDominioActivo):
        activos_dom.validar_coordenadas(7.98, -185.0)


def test_validar_lote_consecutivos() -> None:
    assert activos_dom.validar_lote_consecutivos(100, 102, 3) == ["100", "101", "102"]

    with pytest.raises(activos_dom.ErrorDominioActivo):
        activos_dom.validar_lote_consecutivos(105, 100, 1)
    with pytest.raises(activos_dom.ErrorDominioActivo):
        activos_dom.validar_lote_consecutivos(100, 104, 3)


def test_rango_pmtiles_y_teselas() -> None:
    activos_dom.validar_coordenadas_tesela(14, 4759, 7828)
    with pytest.raises(activos_dom.ErrorDominioActivo):
        activos_dom.validar_coordenadas_tesela(-1, 0, 0)
    with pytest.raises(activos_dom.ErrorDominioActivo):
        activos_dom.validar_coordenadas_tesela(10, 9999, 0)

    pm = activos_dom.construir_pmtiles_base_sede("montelibano")
    assert pm.startswith(b"PMTiles\x03")
    assert len(pm) == 4096
    assert activos_dom.parsear_rango_bytes("bytes=0-511", len(pm)) == (0, 511)
    with pytest.raises(activos_dom.ErrorDominioActivo):
        activos_dom.parsear_rango_bytes("bytes=999999-", len(pm))


def test_normalizacion_migracion() -> None:
    assert mig_dom.normalizar_codigo_marca("KÜNIX") == "KUNIX"
    assert mig_dom.normalizar_codigo_marca("SCHRÉDER") == "SCHREDER"
    assert mig_dom.normalizar_codigo_marca("SHRÉDER") == "SCHREDER"
    assert mig_dom.normalizar_codigo_tecnologia("MH") == "METAL_HALIDE"
    assert mig_dom.normalizar_codigo_tecnologia("Led") == "LED"
    assert mig_dom.normalizar_fecha_sapef("01/01/1900") is None
    assert mig_dom.normalizar_fecha_sapef(date(1900, 1, 1)) is None
    assert mig_dom.normalizar_fecha_sapef(date(2025, 3, 10)) == date(2025, 3, 10)
