#!/usr/bin/env bash
# Respaldo completo de SAPEF: base de datos (pg_dump formato custom), evidencias y cargues
# (volumen «archivos») y almacén Parquet del comercial (volumen «comercial»).
#
# Uso:
#   infra/respaldos/respaldar.sh [-f archivo-compose] [-e archivo-env] [-d carpeta-destino]
#
# Variables opcionales:
#   SAPEF_RESPALDOS_DIR      carpeta local de respaldos (por defecto ./respaldos)
#   SAPEF_RESPALDOS_LOCALES  cuántos respaldos locales conservar (por defecto 3)
#   RESTIC_REPOSITORY / RESTIC_PASSWORD_FILE  si están, el respaldo se sube cifrado fuera del
#     servidor con restic y se aplica la retención 7 diarios, 4 semanales, 12 mensuales (§6.12).
#
# Lo corre el cron diario y el despliegue antes de `alembic upgrade head`. Sale con error si
# cualquier paso falla: un respaldo a medias no se da por bueno.
set -euo pipefail

COMPOSE_FILE="infra/docker-compose.dev.yml"
ENV_FILE=".env"
DESTINO_BASE="${SAPEF_RESPALDOS_DIR:-./respaldos}"
LOCALES="${SAPEF_RESPALDOS_LOCALES:-3}"

while getopts "f:e:d:" opt; do
  case "$opt" in
    f) COMPOSE_FILE="$OPTARG" ;;
    e) ENV_FILE="$OPTARG" ;;
    d) DESTINO_BASE="$OPTARG" ;;
    *) echo "Uso: $0 [-f compose] [-e env] [-d destino]" >&2; exit 2 ;;
  esac
done

dc() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

PROYECTO="$(dc config | sed -n 's/^name: *//p' | head -n 1)"
MARCA="$(date -u +%Y%m%dT%H%M%SZ)"
DESTINO="$DESTINO_BASE/$PROYECTO-$MARCA"
mkdir -p "$DESTINO"
DESTINO="$(cd "$DESTINO" && pwd)"
echo "==> Respaldo de $PROYECTO en $DESTINO"

volumen() {
  docker volume ls -q \
    --filter "label=com.docker.compose.project=$PROYECTO" \
    --filter "label=com.docker.compose.volume=$1"
}

# 1) Base de datos: formato custom (comprimido, restaurable por partes con pg_restore).
echo "--> base de datos"
dc exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner' \
  > "$DESTINO/base.dump"
test -s "$DESTINO/base.dump"
dc exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT version_num FROM alembic_version"' \
  | tr -d '[:space:]' > "$DESTINO/alembic_version.txt"

# 2) Volúmenes de archivos: se leen en solo lectura desde un contenedor desechable.
for nombre in archivos comercial; do
  vol="$(volumen "$nombre")"
  if [ -z "$vol" ]; then
    echo "--> volumen $nombre: no existe, se omite"
    continue
  fi
  echo "--> volumen $nombre ($vol)"
  docker run --rm -v "$vol:/origen:ro" -v "$DESTINO:/destino" alpine:3.20 \
    tar -czf "/destino/$nombre.tar.gz" -C /origen .
done

# 3) Manifiesto con huellas: la restauración se niega si algo no coincide.
(
  cd "$DESTINO"
  {
    echo "proyecto=$PROYECTO"
    echo "fecha_utc=$MARCA"
    echo "alembic=$(cat alembic_version.txt)"
  } > LEEME.txt
  sha256sum base.dump ./*.tar.gz alembic_version.txt LEEME.txt 2>/dev/null > SHA256SUMS
)
echo "--> manifiesto: $(wc -l < "$DESTINO/SHA256SUMS") archivos"

# 4) Copia fuera del servidor (cifrada) si hay repositorio de restic.
if [ -n "${RESTIC_REPOSITORY:-}" ]; then
  echo "--> restic: subiendo a $RESTIC_REPOSITORY"
  restic backup --tag "$PROYECTO" "$DESTINO"
  restic forget --tag "$PROYECTO" --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune
else
  echo "AVISO: RESTIC_REPOSITORY no está definido; el respaldo queda solo en este servidor." >&2
fi

# 5) Retención local: los más recientes, el resto se borra (fuera del servidor quedan más).
ls -1d "$DESTINO_BASE/$PROYECTO-"* 2>/dev/null | sort | head -n "-$LOCALES" | while read -r viejo; do
  echo "--> borrando respaldo local antiguo $viejo"
  rm -rf -- "$viejo"
done

echo "==> Respaldo terminado: $DESTINO"
