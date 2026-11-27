#!/usr/bin/env bash
# Despliegue de SAPEF en el VPS (TASK-006): producción o staging, según el archivo .env.
#
# Uso:
#   infra/desplegar.sh -e .env.prod -v <version>     despliega esa versión (commit de 12 caracteres o etiqueta v*)
#   infra/desplegar.sh -e .env.prod -r               vuelve a la versión anterior
#   opciones: -f <compose> (por defecto infra/docker-compose.prod.yml)
#
# Pasos: descarga las dos imágenes de GHCR (backend y estáticos) → respaldo completo
# (infra/respaldos/respaldar.sh) → migraciones y arranque de la API y el worker con la versión
# nueva → espera a que /api/v1/salud responda → publica los estáticos de la web y de la app de
# campo (cambio atómico de un enlace) → registra la versión.
#
# Si la API nueva no queda sana:
#   - si la base no cambió de versión de Alembic, vuelve solo a la versión anterior;
#   - si cambió, NO revierte por su cuenta (el código anterior no conoce el esquema nuevo): deja
#     el sistema como está y muestra cómo restaurar el respaldo que acaba de tomar.
#
# Variables del .env que usa además de las del compose:
#   SAPEF_REGISTRO        p. ej., ghcr.io/<cuenta> (las imágenes son sapef-backend y sapef-estaticos)
#   SAPEF_DESPLIEGUE_DIR  carpeta de la instalación (por defecto /srv/<proyecto>): ahí quedan
#                         estaticos/<version>/{web,campo}, estaticos/actual y el registro de versiones
set -euo pipefail

COMPOSE_FILE="infra/docker-compose.prod.yml"
ENV_FILE=""
VERSION=""
REVERTIR=0

while getopts "f:e:v:r" opt; do
  case "$opt" in
    f) COMPOSE_FILE="$OPTARG" ;;
    e) ENV_FILE="$OPTARG" ;;
    v) VERSION="$OPTARG" ;;
    r) REVERTIR=1 ;;
    *) echo "Uso: $0 -e <archivo-env> (-v <version> | -r) [-f compose]" >&2; exit 2 ;;
  esac
done

if [ -z "$ENV_FILE" ] || [ ! -f "$ENV_FILE" ]; then
  echo "Falta el archivo de entorno (-e .env.prod)." >&2
  exit 2
fi
if [ -z "$VERSION" ] && [ "$REVERTIR" -eq 0 ]; then
  echo "Indique la versión (-v) o pida revertir (-r)." >&2
  exit 2
fi

leer_env() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r'; }

PROYECTO="$(leer_env SAPEF_PROYECTO)"; PROYECTO="${PROYECTO:-sapef}"
REGISTRO="$(leer_env SAPEF_REGISTRO)"
PUERTO="$(leer_env SAPEF_PUERTO_API)"; PUERTO="${PUERTO:-8100}"
BASE="$(leer_env SAPEF_DESPLIEGUE_DIR)"; BASE="${BASE:-/srv/$PROYECTO}"
if [ -z "$REGISTRO" ]; then
  echo "Defina SAPEF_REGISTRO en $ENV_FILE (p. ej., ghcr.io/<cuenta>)." >&2
  exit 2
fi

mkdir -p "$BASE/estaticos"
ACTUAL="$(cat "$BASE/version-actual" 2>/dev/null || true)"
ANTERIOR="$(cat "$BASE/version-anterior" 2>/dev/null || true)"

if [ "$REVERTIR" -eq 1 ]; then
  if [ -z "$ANTERIOR" ]; then
    echo "No hay versión anterior registrada en $BASE/version-anterior." >&2
    exit 1
  fi
  VERSION="$ANTERIOR"
fi
if [ "$VERSION" = "$ACTUAL" ]; then
  echo "La versión $VERSION ya está desplegada en $PROYECTO."
  exit 0
fi

IMG_BACKEND="$REGISTRO/sapef-backend:$VERSION"
IMG_ESTATICOS="$REGISTRO/sapef-estaticos:$VERSION"

dc() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" -p "$PROYECTO" "$@"; }

traer() {
  # Una etiqueta de versión no cambia: si la imagen ya está en el servidor, no se vuelve a bajar.
  if ! docker image inspect "$1" >/dev/null 2>&1; then
    docker pull "$1"
  fi
}

version_alembic() {
  dc exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT version_num FROM alembic_version"' 2>/dev/null \
    | tr -d '[:space:]' || true
}

esperar_salud() {
  local i
  for i in $(seq 1 40); do
    if curl -fsS "http://127.0.0.1:$PUERTO/api/v1/salud" >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

arrancar() {
  # El compose toma SAPEF_IMAGEN del entorno antes que del archivo .env.
  SAPEF_IMAGEN="$1" dc up -d --remove-orphans
}

echo "==> $PROYECTO: ${ACTUAL:-(sin versión registrada)} -> $VERSION"

echo "--> imágenes"
traer "$IMG_BACKEND"
traer "$IMG_ESTATICOS"

DB_EN_MARCHA="$(dc ps -q db 2>/dev/null || true)"
ALEMBIC_ANTES=""
if [ -n "$DB_EN_MARCHA" ]; then
  echo "--> respaldo previo"
  SAPEF_IMAGEN="$IMG_BACKEND" infra/respaldos/respaldar.sh -f "$COMPOSE_FILE" -e "$ENV_FILE"
  ALEMBIC_ANTES="$(version_alembic)"
else
  echo "--> primera instalación: no hay base que respaldar"
fi

echo "--> migraciones y arranque de $IMG_BACKEND"
SANA=1
arrancar "$IMG_BACKEND" || SANA=0
if [ "$SANA" -eq 1 ]; then
  esperar_salud || SANA=0
fi

if [ "$SANA" -eq 0 ]; then
  echo "!! La versión $VERSION no quedó sana." >&2
  ALEMBIC_DESPUES="$(version_alembic)"
  if [ -n "$ACTUAL" ] && [ "$ALEMBIC_ANTES" = "$ALEMBIC_DESPUES" ]; then
    echo "!! El esquema no cambió ($ALEMBIC_DESPUES): se vuelve a $ACTUAL." >&2
    arrancar "$REGISTRO/sapef-backend:$ACTUAL"
    esperar_salud && echo "!! $PROYECTO sigue en $ACTUAL." >&2
  else
    echo "!! El esquema cambió (${ALEMBIC_ANTES:-vacío} -> ${ALEMBIC_DESPUES:-?}) o no hay versión anterior." >&2
    echo "!! No se revierte solo. Revise: docker compose ... -p $PROYECTO logs migraciones api" >&2
    echo "!! Para volver atrás: infra/respaldos/restaurar.sh con el respaldo recién tomado y luego $0 -e $ENV_FILE -r" >&2
  fi
  exit 1
fi

echo "--> estáticos de la web y de la app de campo"
DESTINO="$BASE/estaticos/$VERSION"
if [ ! -d "$DESTINO" ]; then
  TEMPORAL="$DESTINO.descarga"
  rm -rf "$TEMPORAL"
  CONTENEDOR="$(docker create "$IMG_ESTATICOS" true)"
  docker cp "$CONTENEDOR:/estaticos" "$TEMPORAL"
  docker rm "$CONTENEDOR" >/dev/null
  test -f "$TEMPORAL/web/index.html" && test -f "$TEMPORAL/campo/index.html"
  mv "$TEMPORAL" "$DESTINO"
fi
ln -sfn "$VERSION" "$BASE/estaticos/actual.nuevo"
mv -Tf "$BASE/estaticos/actual.nuevo" "$BASE/estaticos/actual"

# Registro: la que estaba pasa a ser la anterior (para -r) y la imagen queda fija en el .env, así
# un `docker compose up` manual usa la misma versión.
if [ -n "$ACTUAL" ]; then echo "$ACTUAL" > "$BASE/version-anterior"; fi
echo "$VERSION" > "$BASE/version-actual"
sed -i "s#^SAPEF_IMAGEN=.*#SAPEF_IMAGEN=$IMG_BACKEND#" "$ENV_FILE"

# Se conservan los estáticos de las 5 versiones más recientes.
find "$BASE/estaticos" -mindepth 1 -maxdepth 1 -type d ! -name "*.descarga" -printf '%T@ %f\n' \
  | sort -rn | tail -n +6 | while read -r _ viejo; do
      if [ "$viejo" != "$VERSION" ] && [ "$viejo" != "$ACTUAL" ]; then rm -rf "${BASE:?}/estaticos/$viejo"; fi
    done

echo "==> $PROYECTO quedó en $VERSION"
