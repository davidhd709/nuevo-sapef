# Mapas base de la app de campo

Estos dos PMTiles son recortes del **Protomaps Basemap 4.15.2** del 24 de noviembre de 2026, derivado de OpenStreetMap y Natural Earth. Se distribuyen como *Produced Work* bajo ODbL; la interfaz muestra la atribución a OpenStreetMap.

| Sede | Bbox (oeste, sur, este, norte) | Tamaño | SHA-256 |
| --- | --- | ---: | --- |
| Montelíbano | `-75.9,7.75,-75.1,8.2` | 5 172 268 bytes | `f6a0707fa5d66de5b4bbd9545b2c426bfa931f6f78736b1344a140e163aa01f6` |
| Alcalá | `-75.9,4.55,-75.65,4.8` | 4 740 177 bytes | `0d6693bfdda5063aacabe961789c63157381b3fd1547e2b382a4057372a1924e` |

Origen: `https://build.protomaps.com/20261124.pmtiles`. Se generaron con `pmtiles` 1.31.2 y `--maxzoom=15`:

```bash
pmtiles extract https://build.protomaps.com/20261124.pmtiles montelibano.pmtiles --bbox=-75.9,7.75,-75.1,8.2 --maxzoom=15
pmtiles extract https://build.protomaps.com/20261124.pmtiles alcala.pmtiles --bbox=-75.9,4.55,-75.65,4.8 --maxzoom=15
pmtiles verify montelibano.pmtiles
pmtiles verify alcala.pmtiles
```

La API usa estos archivos incluidos en la imagen; `${SAPEF_ARCHIVOS_DIR}/mapa/` permite sustituirlos sin reconstruirla. Las URL del origen pueden caducar, por lo que los archivos necesarios para el MVP se conservan aquí.

Los nombres de calles, poblaciones y puntos de interés vienen en las capas `roads`, `places` y `pois`. La web y la app de campo usan el glifo local `Noto Sans Regular/0-255.pbf` de [Protomaps basemaps-assets](https://github.com/protomaps/basemaps-assets), con licencia OFL incluida en `frontend/mapa-fonts-OFL.txt`. La app de campo lo precarga para mostrar las etiquetas sin conexión. La URL del paquete de campo incluye una versión para renovar el archivo guardado cuando cambia el recorte.
