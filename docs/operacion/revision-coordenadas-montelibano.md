# Revisión de coordenadas de Montelíbano · 25 de noviembre de 2026

El archivo [revision-coordenadas-montelibano.csv](revision-coordenadas-montelibano.csv) contiene los códigos que requieren verificación antes de corregir su ubicación en SAPEF Nuevo.

| Situación en la base de prueba | Cantidad |
| --- | ---: |
| Luminarias sin coordenadas | 720 (719 del exporte SAPEF y 1 registro de prueba anterior) |
| Coordenadas fuera del recorte ampliado del mapa (`-75.9,7.75,-75.1,8.2`) | 12 |
| Sin coordenadas con una coincidencia por código en el CENSO de 2024 | 14 |
| Sin coordenadas con una coincidencia en LUMINARIAS_VALIDACION | 0 |

El CENSO y LUMINARIAS_VALIDACION son de 2024; el exporte principal de luminarias es de noviembre de 2026. Sus coordenadas son **candidatas históricas**, no una confirmación de ubicación actual. No se ha modificado ninguna coordenada de la base con esos archivos. En especial, algunas de las 12 ubicaciones externas pueden corresponder a zonas rurales reales y otras parecen errores de digitación: se deben comprobar por código y, cuando sea posible, con GPS en campo antes de usar `POST /luminarias/{id}/ubicacion`, que registra historial y auditoría.

El CSV no contiene datos personales. Para revisar los casos, filtre por `problema` y contraste la ubicación actual con las columnas del censo y de validación. Los campos vacíos indican que no existe una coincidencia única con coordenadas válidas en ese archivo.
