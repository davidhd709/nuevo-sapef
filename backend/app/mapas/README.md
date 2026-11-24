# Mapas base de la app de campo

Estos dos PMTiles son recortes del **Protomaps Basemap 4.15.2** del 24 de noviembre de 2026, derivado de OpenStreetMap y Natural Earth. Se distribuyen como *Produced Work* bajo ODbL; la interfaz muestra la atribución a OpenStreetMap.

| Sede | Bbox (oeste, sur, este, norte) | Tamaño | SHA-256 |
| --- | --- | ---: | --- |
| Montelíbano | `-75.46,7.94,-75.38,8.02` | 709 690 bytes | `3ee78983c4e4b7dfaee1c637934b96f4e88ca4051e73f323133bc6fb28c76ced` |
| Alcalá | `-75.81,4.65,-75.76,4.70` | 1 066 073 bytes | `dbeab6ff26bea2cfcabbaa9a3d4d0fa934b5e0d6fcce3f1fcad4ef83dd3be44e` |

Origen: `https://build.protomaps.com/20261124.pmtiles`. Se generaron con `pmtiles` 1.31.2 y `--maxzoom=15`:

```bash
pmtiles extract https://build.protomaps.com/20261124.pmtiles montelibano.pmtiles --bbox=-75.46,7.94,-75.38,8.02 --maxzoom=15
pmtiles extract https://build.protomaps.com/20261124.pmtiles alcala.pmtiles --bbox=-75.81,4.65,-75.76,4.70 --maxzoom=15
pmtiles verify montelibano.pmtiles
pmtiles verify alcala.pmtiles
```

La API usa estos archivos incluidos en la imagen; `${SAPEF_ARCHIVOS_DIR}/mapa/` permite sustituirlos sin reconstruirla. Las URL del origen pueden caducar, por lo que los archivos necesarios para el MVP se conservan aquí.
