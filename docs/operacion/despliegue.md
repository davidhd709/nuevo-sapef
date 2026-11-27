# Despliegue en el VPS (staging y producción)

Para quien administra el servidor. El VPS se comparte con otros sistemas: SAPEF corre en proyectos
de Docker Compose aislados (su propia base, volúmenes y límites de memoria) y solo el Nginx del
host recibe tráfico de afuera.

| Ambiente | Proyecto | Puerto local de la API | Carpeta | Dominios |
| --- | --- | --- | --- | --- |
| Staging (pruebas) | `sapef-pruebas` | 8101 | `/srv/sapef-pruebas` | `pruebas.<dominio>`, `campo.pruebas.<dominio>` |
| Producción | `sapef` | 8100 | `/srv/sapef` | `sapef.<dominio>`, `campo.sapef.<dominio>` |

## De dónde salen las versiones

Cada `git push` a `main` que pasa las pruebas publica dos imágenes en GitHub Container Registry,
etiquetadas con los primeros 12 caracteres del commit (y con la etiqueta, si se sube una `v*`):

- `ghcr.io/<cuenta>/sapef-backend:<version>`: API, worker y migraciones.
- `ghcr.io/<cuenta>/sapef-estaticos:<version>`: la web de oficina y la app de campo ya compiladas.

La versión de cada ejecución aparece en el resumen de la CI («Versión publicada»). Se despliega
siempre una versión fija, nunca `latest`, para que staging y producción corran exactamente lo
que se probó.

Las imágenes nacen **privadas** en GHCR. Para que el servidor las descargue hay dos caminos:
1. `docker login ghcr.io` en el servidor con un token de GitHub de solo lectura de paquetes
   (`read:packages`); o
2. volver públicos los dos paquetes en GitHub (el código ya es público y las imágenes no traen
   datos ni secretos: los catálogos privados y las claves se cargan en el servidor).

## Preparación del servidor (una sola vez por ambiente)

Antes de empezar, acordar con el dueño del servidor la memoria disponible (y si se agrega swap):
producción usa hasta ~4 GB con los límites por defecto y staging ~2 GB.

1. Docker con el plugin de Compose, `git` y `curl` en el servidor.
2. Clonar el repositorio (solo se usan `infra/`): `git clone https://github.com/<cuenta>/nuevo-sapef.git /opt/sapef`.
3. Crear el archivo de entorno con permisos 600, a partir del ejemplo:
   - staging: `cp infra/env.pruebas.example .env.pruebas`
   - producción: `cp infra/env.prod.example .env.prod`

   Completar `SAPEF_REGISTRO`, las claves (`openssl rand -base64 32` y `-base64 48`), el correo y
   las rutas. Claves distintas en cada ambiente.
4. Crear las carpetas: `sudo mkdir -p /srv/sapef-pruebas/importacion && sudo chown $USER /srv/sapef-pruebas`.
5. DNS: registros A de los dos dominios del ambiente hacia la IP del VPS.
6. Nginx: copiar `infra/nginx/sapef.conf.example` (en staging con los cambios que indica su
   encabezado), `nginx -t`, recargar y emitir los certificados con
   `certbot --nginx -d <dominio> -d campo.<dominio>`.
7. Primer despliegue (ver abajo) y primer administrador:

   ```bash
   docker compose -f infra/docker-compose.prod.yml --env-file .env.pruebas -p sapef-pruebas \
     exec -e SAPEF_ADMIN_CLAVE='<clave temporal>' api python -m app.semillas admin \
     --usuario admin --correo <correo>
   ```

   La clave se cambia en el primer ingreso.
8. Claves de Web Push de la app de campo: `... run --rm migraciones python -m app.semillas vapid`,
   copiar la clave al `.env` y desplegar de nuevo.
9. Respaldo diario por cron y copia cifrada fuera del servidor: ver [respaldos.md](respaldos.md).
10. Monitoreo: un chequeo HTTP cada minuto (Uptime Kuma u otro) a
    `https://<dominio>/api/v1/salud`, que responde 200 cuando la API y la base están bien, con
    aviso por correo o Telegram al administrador.

## Desplegar una versión

Desde la carpeta del repositorio en el servidor:

```bash
infra/desplegar.sh -e .env.pruebas -v <version>     # staging
infra/desplegar.sh -e .env.prod -v <version>        # producción, con la versión ya probada en staging
```

El script:

1. descarga las dos imágenes;
2. toma un **respaldo completo** con `infra/respaldos/respaldar.sh`, salvo en la primera
   instalación;
3. corre las migraciones y arranca la API y el worker con la versión nueva;
4. espera hasta 2 minutos a que `/api/v1/salud` responda;
5. publica la web y la app de campo cambiando el enlace `estaticos/actual`, de modo que el Nginx
   nunca sirve una mezcla de dos versiones;
6. registra la versión (`version-actual`, `version-anterior`) y la deja fija en `SAPEF_IMAGEN`
   del `.env`.

Si la versión nueva no queda sana, los estáticos no se tocan y:
- si la base no cambió de esquema, el script vuelve solo a la versión anterior;
- si las migraciones ya cambiaron el esquema, **no revierte por su cuenta**: muestra cómo ver los
  registros (`... logs migraciones api`) y cómo restaurar el respaldo que acaba de tomar.

## Volver a la versión anterior

```bash
infra/desplegar.sh -e .env.prod -r
```

Vale cuando la versión anterior usa el mismo esquema de base. Si la nueva trajo migraciones,
primero se restaura el respaldo previo al despliegue ([respaldos.md](respaldos.md), «Restaurar el
sistema») y después se corre `-r`.

## Ensayo del script

El script se ensayó el 27-nov-2026 en un proyecto aislado con imágenes locales. Se probaron
cuatro casos: primera instalación, actualización con respaldo previo, reversión con `-r` y una
versión que no arranca. En el último, el script volvió solo a la anterior y la API siguió
respondiendo. Falta repetirlo en el VPS real con las imágenes de GHCR.
