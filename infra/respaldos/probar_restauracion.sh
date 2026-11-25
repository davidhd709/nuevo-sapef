#!/usr/bin/env bash
# Prueba de restauración (mensual, §6.12): restaura un respaldo en una base PostGIS desechable,
# sin tocar el sistema en uso, y muestra conteos para compararlos con producción.
#
# Uso:  infra/respaldos/probar_restauracion.sh <carpeta-del-respaldo>
set -euo pipefail

RESPALDO="${1:?Indique la carpeta del respaldo}"
RESPALDO="$(cd "$RESPALDO" && pwd)"
NOMBRE="sapef-prueba-restauracion-$$"
CLAVE="prueba-$(date +%s)"

echo "==> Verificando huellas"
(cd "$RESPALDO" && sha256sum -c --quiet SHA256SUMS)

limpiar() { docker rm -f "$NOMBRE" >/dev/null 2>&1 || true; }
trap limpiar EXIT

echo "==> Base desechable ($NOMBRE)"
docker run -d --name "$NOMBRE" -e POSTGRES_PASSWORD="$CLAVE" -e POSTGRES_DB=sapef \
  -v "$RESPALDO:/respaldo:ro" postgis/postgis:17-3.5 >/dev/null
for _ in $(seq 1 60); do
  if docker exec "$NOMBRE" pg_isready -U postgres -d sapef >/dev/null 2>&1; then break; fi
  sleep 2
done
# La imagen reinicia PostgreSQL al terminar su inicialización: esperar a que quede estable.
sleep 5
until docker exec "$NOMBRE" pg_isready -U postgres -d sapef >/dev/null 2>&1; do sleep 2; done

echo "==> pg_restore"
INICIO=$(date +%s)
docker exec "$NOMBRE" pg_restore -U postgres -d sapef --no-owner --exit-on-error /respaldo/base.dump
echo "    restaurado en $(( $(date +%s) - INICIO )) s"

echo "==> Conteos"
docker exec "$NOMBRE" psql -U postgres -d sapef -P pager=off -c "
  SELECT (SELECT version_num FROM alembic_version) AS alembic,
         (SELECT count(*) FROM usuario) AS usuarios,
         (SELECT count(*) FROM luminaria) AS luminarias,
         (SELECT count(*) FROM pqrs) AS pqrs,
         (SELECT count(*) FROM orden_trabajo) AS ordenes,
         (SELECT count(*) FROM material) AS materiales,
         (SELECT count(*) FROM archivo) AS archivos,
         (SELECT count(*) FROM cargue_comercial) AS cargues_comerciales;"
docker exec "$NOMBRE" psql -U postgres -d sapef -P pager=off -c "
  SELECT s.codigo AS sede, count(l.id) AS luminarias
  FROM sede s LEFT JOIN luminaria l ON l.sede_id = s.id GROUP BY s.codigo ORDER BY s.codigo;"

for nombre in archivos comercial; do
  if [ -f "$RESPALDO/$nombre.tar.gz" ]; then
    echo "==> $nombre.tar.gz: $(tar -tzf "$RESPALDO/$nombre.tar.gz" | grep -vc '/$') archivos legibles"
  fi
done
echo "==> Prueba de restauración correcta. Anote fecha, duración y conteos en la bitácora."
