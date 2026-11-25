#!/usr/bin/env bash
# Restaura un respaldo sobre el sistema (reemplaza la base y los volúmenes de archivos).
# Es destructivo: exige --confirmar <proyecto> con el nombre del proyecto de Compose.
#
# Uso:
#   infra/respaldos/restaurar.sh -f infra/docker-compose.prod.yml -e .env \
#       --confirmar sapef <carpeta-del-respaldo>
#
# Pasos: verifica huellas → detiene API y worker → restaura base y volúmenes → aplica las
# migraciones pendientes (por si el respaldo es de una versión anterior) → arranca de nuevo.
set -euo pipefail

COMPOSE_FILE="infra/docker-compose.dev.yml"
ENV_FILE=".env"
CONFIRMAR=""
RESPALDO=""
while [ $# -gt 0 ]; do
  case "$1" in
    -f) COMPOSE_FILE="$2"; shift 2 ;;
    -e) ENV_FILE="$2"; shift 2 ;;
    --confirmar) CONFIRMAR="$2"; shift 2 ;;
    *) RESPALDO="$1"; shift ;;
  esac
done
[ -n "$RESPALDO" ] || { echo "Indique la carpeta del respaldo." >&2; exit 2; }
RESPALDO="$(cd "$RESPALDO" && pwd)"

dc() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }
PROYECTO="$(dc config | sed -n 's/^name: *//p' | head -n 1)"
if [ "$CONFIRMAR" != "$PROYECTO" ]; then
  echo "Esto REEMPLAZA los datos de «$PROYECTO». Repita con --confirmar $PROYECTO" >&2
  exit 3
fi

echo "==> Verificando huellas de $RESPALDO"
(cd "$RESPALDO" && sha256sum -c --quiet SHA256SUMS)

echo "==> Deteniendo API y worker"
dc stop api worker

echo "==> Restaurando la base"
dc exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
dc exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error' \
  < "$RESPALDO/base.dump"

for nombre in archivos comercial; do
  [ -f "$RESPALDO/$nombre.tar.gz" ] || continue
  vol="$(docker volume ls -q --filter "label=com.docker.compose.project=$PROYECTO" \
    --filter "label=com.docker.compose.volume=$nombre")"
  [ -n "$vol" ] || { echo "No existe el volumen $nombre de $PROYECTO" >&2; exit 4; }
  echo "==> Restaurando volumen $nombre"
  docker run --rm -v "$vol:/destino" -v "$RESPALDO:/respaldo:ro" alpine:3.20 \
    sh -c 'find /destino -mindepth 1 -delete && tar -xzf "/respaldo/'"$nombre"'.tar.gz" -C /destino'
done

echo "==> Migraciones pendientes y arranque"
dc up -d migraciones api worker
echo "==> Restauración terminada. Compruebe /api/v1/salud y los conteos del tablero."
