# Respaldos y restauración

Para quien opera el servidor. Los scripts están en `infra/respaldos/` y funcionan con cualquier
proyecto de Docker Compose de SAPEF (desarrollo, pruebas o producción): se elige con `-f` y `-e`.

## Qué se respalda

| Pieza | Cómo | Archivo en el respaldo |
| --- | --- | --- |
| Base de datos (PostgreSQL + PostGIS) | `pg_dump -Fc` desde el contenedor `db` | `base.dump` |
| Evidencias y cargues (fotos, firmas, audios, Excel/CSV subidos) | volumen `archivos` en `tar.gz` | `archivos.tar.gz` |
| Almacén Parquet del comercial | volumen `comercial` en `tar.gz` | `comercial.tar.gz` |
| Versión del esquema | `alembic_version` | `alembic_version.txt` |
| Huellas SHA-256 de todo lo anterior | `sha256sum` | `SHA256SUMS` |

Cada respaldo queda en `respaldos/<proyecto>-<fecha UTC>/`. Esa carpeta tiene **datos personales**:
nunca se sube al repositorio (está en `.gitignore`) ni se comparte por correo o chat.

## Respaldo diario

```bash
# desde la raíz del repositorio en el servidor
RESTIC_REPOSITORY=sftp:respaldos@otro-servidor:/sapef \
RESTIC_PASSWORD_FILE=/root/.restic-sapef \
infra/respaldos/respaldar.sh -f infra/docker-compose.prod.yml -e .env -d /var/backups/sapef
```

- Con `RESTIC_REPOSITORY` el respaldo se sube **cifrado fuera del servidor** y se aplica la
  retención 7 diarios, 4 semanales y 12 mensuales. Sin esa variable el script avisa: un respaldo
  que solo vive en el mismo servidor no protege contra la pérdida del servidor.
- En el servidor quedan los 3 respaldos más recientes (`SAPEF_RESPALDOS_LOCALES`).
- Programarlo con cron a una hora de poco uso, por ejemplo `30 2 * * *`, y enviar la salida al
  log del sistema. Si el script falla, sale con error: configurar el aviso del monitoreo.
- El despliegue corre el mismo script **antes** de `alembic upgrade head`.

Objetivo propuesto: pérdida máxima de 24 h (RPO) y recuperación en 4 h o menos (RTO), pendientes
de confirmar con el dueño.

## Prueba de restauración (mensual)

No toca el sistema en uso: restaura en un contenedor PostGIS desechable y muestra conteos.

```bash
infra/respaldos/probar_restauracion.sh /var/backups/sapef/sapef-20261125T023000Z
```

Comparar los conteos (luminarias por sede, PQRS, órdenes, materiales, archivos) con el tablero del
sistema en uso y anotar en la bitácora la fecha, la duración y el resultado. Medido en desarrollo
con 11.143 luminarias: el `pg_restore` tarda unos 2 s.

## Restaurar el sistema

**Destructivo:** reemplaza la base y los volúmenes. Pide el nombre del proyecto como confirmación.

```bash
infra/respaldos/restaurar.sh -f infra/docker-compose.prod.yml -e .env \
    --confirmar sapef /var/backups/sapef/sapef-20261125T023000Z
```

El script verifica las huellas, detiene la API y el worker, restaura la base y los volúmenes,
aplica las migraciones pendientes (si el respaldo es de una versión anterior) y arranca de nuevo.
Después, comprobar `GET /api/v1/salud`, ingresar con un usuario de cada sede y revisar el tablero.

Para traer un respaldo que solo está en restic: `restic restore latest --tag <proyecto> --target /tmp/r`
y usar la carpeta restaurada.
