#!/usr/bin/env bash
# Staging local: el mismo despliegue del VPS (infra/docker-compose.prod.yml + infra/desplegar.sh)
# corriendo en este equipo, con HTTPS de una CA local para probar desde el PC y desde teléfonos.
#
# Uso (desde la raíz del repositorio; en Windows, con Git Bash y Docker Desktop):
#   infra/local/staging.sh todo [ip]     preparar + construir + desplegar + datos + proxy
#   infra/local/staging.sh preparar [ip] .env.local, certificados (para la IP de la red) e imagen auxiliar
#   infra/local/staging.sh construir     imágenes locales sapef-backend y sapef-estaticos del commit actual
#   infra/local/staging.sh desplegar [v] infra/desplegar.sh con la última versión construida (o la indicada)
#   infra/local/staging.sh revertir      infra/desplegar.sh -r
#   infra/local/staging.sh datos         copia la base y los archivos de desarrollo (sapef-dev) al staging
#   infra/local/staging.sh proxy         levanta el Nginx con HTTPS (8443 web, 8444 campo, 8080 CA)
#   infra/local/staging.sh estado | bajar | borrar
#
# Todo queda en .staging-local/ (ignorado por git): entorno, certificados, estáticos por versión y
# respaldos. El proyecto de Compose es «sapef-local» y no toca la base de desarrollo (salvo leerla
# en «datos», con un respaldo).
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$RAIZ"
LOCAL="$RAIZ/.staging-local"
ENV_LOCAL=".env.local"
PROYECTO="sapef-local"
REGISTRO="local"
PUERTO_API=8101
AUX="sapef-desplegador:local"

# En Windows (Git Bash) los scripts del VPS corren en un contenedor Linux que usa el Docker del
# equipo; las rutas se escriben como las ve Docker Desktop.
if [ "$(uname -s)" = "Linux" ]; then
  EN_WINDOWS=0
  RAIZ_D="$RAIZ"
else
  EN_WINDOWS=1
  ruta_w="$(cygpath -m "$RAIZ")"                       # C:/Users/...
  unidad="$(printf '%s' "${ruta_w:0:1}" | tr '[:upper:]' '[:lower:]')"
  RAIZ_D="/run/desktop/mnt/host/$unidad${ruta_w:2}"
fi
LOCAL_D="$RAIZ_D/.staging-local"

en_linux() {
  # Corre un comando de bash con las herramientas del VPS (bash, curl, coreutils, docker compose).
  if [ "$EN_WINDOWS" -eq 0 ]; then
    bash -c "$1"
  else
    MSYS_NO_PATHCONV=1 docker run --rm --network host \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v "$RAIZ_D:$RAIZ_D" -w "$RAIZ_D" \
      -e SAPEF_RESPALDOS_DIR="$LOCAL_D/respaldos" \
      "$AUX" bash -c "$1"
  fi
}

ip_red() {
  if [ "$EN_WINDOWS" -eq 1 ]; then
    ipconfig | tr -d '\r' | awk '/Wi-Fi|Ethernet/{a=1} a&&/IPv4/{sub(/.*: /,"");print;exit}'
  else
    hostname -I | awk '{print $1}'
  fi
}

aleatorio() { openssl rand -base64 "$1" | tr -d '/+=\n' | cut -c1-"$2"; }

preparar() {
  local ip="${1:-$(ip_red)}"
  if [ -z "$ip" ]; then echo "No se encontró la IP de la red; pásela: $0 preparar 192.168.x.x" >&2; exit 2; fi
  mkdir -p "$LOCAL/srv/estaticos" "$LOCAL/importacion" "$LOCAL/respaldos" "$LOCAL/certs" "$LOCAL/certs-publicos"

  if [ ! -f "$ENV_LOCAL" ]; then
    cat > "$ENV_LOCAL" <<EOF
# Staging local (infra/local/staging.sh). No se sube al repositorio.
SAPEF_PROYECTO=$PROYECTO
SAPEF_REGISTRO=$REGISTRO
SAPEF_IMAGEN=$REGISTRO/sapef-backend:sin-desplegar
SAPEF_ENTORNO=pruebas
SAPEF_PUERTO_API=$PUERTO_API
SAPEF_DESPLIEGUE_DIR=$LOCAL_D/srv
SAPEF_IMPORTACION_HOST_DIR=$LOCAL_D/importacion
POSTGRES_DB=sapef
POSTGRES_USER=sapef
POSTGRES_PASSWORD=$(aleatorio 32 40)
SAPEF_SECRET_KEY=$(aleatorio 48 64)
SAPEF_MEM_DB=1g
SAPEF_MEM_API=768m
SAPEF_MEM_WORKER=2g
SAPEF_API_WORKERS=2
EOF
    echo "--> creado $ENV_LOCAL"
  fi

  # CA local (una vez) y certificado del servidor para la IP de la red (se rehace si cambia la IP).
  local c="$LOCAL/certs"
  if [ ! -f "$c/ca.key" ]; then
    # Rutas relativas: en Git Bash, openssl es un programa de Windows y no entiende /c/...
    (cd "$c" && MSYS_NO_PATHCONV=1 openssl req -x509 -new -nodes -newkey rsa:2048 -sha256 -days 825 \
      -keyout ca.key -out ca.crt -subj "/CN=SAPEF staging local CA" \
      -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null)
    echo "--> CA local creada (.staging-local/certs/ca.crt)"
  fi
  if [ "$(cat "$c/ip" 2>/dev/null || true)" != "$ip" ] || [ ! -f "$c/servidor.crt" ]; then
    printf 'subjectAltName=IP:%s,IP:127.0.0.1,DNS:localhost\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n' "$ip" > "$c/ext.cnf"
    (cd "$c" && MSYS_NO_PATHCONV=1 openssl req -new -nodes -newkey rsa:2048 -sha256 \
      -keyout servidor.key -out servidor.csr -subj "/CN=sapef-local" 2>/dev/null)
    (cd "$c" && openssl x509 -req -sha256 -days 397 -in servidor.csr \
      -CA ca.crt -CAkey ca.key -CAcreateserial -out servidor.crt -extfile ext.cnf 2>/dev/null)
    echo "$ip" > "$c/ip"
    echo "--> certificado del servidor para $ip"
  fi
  cp "$c/ca.crt" "$LOCAL/certs-publicos/ca.crt"

  if [ "$EN_WINDOWS" -eq 1 ] && ! docker image inspect "$AUX" >/dev/null 2>&1; then
    printf 'FROM docker:27-cli\nRUN apk add --no-cache bash curl coreutils findutils sed\n' \
      | docker build -q -t "$AUX" - >/dev/null
    echo "--> imagen auxiliar $AUX"
  fi
}

version_actual() {
  local v
  v="$(git rev-parse --short=12 HEAD)"
  if [ -n "$(git status --porcelain)" ]; then v="$v-local$(date +%H%M%S)"; fi
  echo "$v"
}

construir() {
  local v
  v="$(version_actual)"
  echo "==> construyendo la versión $v"
  docker build -q -t "$REGISTRO/sapef-backend:$v" backend >/dev/null
  docker build -q -f frontend/Dockerfile.estaticos -t "$REGISTRO/sapef-estaticos:$v" frontend >/dev/null
  echo "$v" > "$LOCAL/ultima-construida"
  echo "--> $REGISTRO/sapef-backend:$v y $REGISTRO/sapef-estaticos:$v"
}

desplegar() {
  local v="${1:-$(cat "$LOCAL/ultima-construida" 2>/dev/null || true)}"
  if [ -z "$v" ]; then echo "No hay versión construida: corra «$0 construir»." >&2; exit 1; fi
  en_linux "infra/desplegar.sh -e $ENV_LOCAL -v $v"
}

revertir() { en_linux "infra/desplegar.sh -e $ENV_LOCAL -r"; }

datos() {
  # Respaldo de desarrollo (sapef-dev) y restauración sobre el staging: así también se ensayan los
  # dos scripts de respaldos con datos reales.
  echo "==> copiando los datos de desarrollo al staging"
  en_linux "infra/respaldos/respaldar.sh -f infra/docker-compose.dev.yml -e .env -d $LOCAL_D/respaldos"
  local ultimo
  ultimo="$(ls -td "$LOCAL"/respaldos/sapef-dev-* | head -n 1)"
  local nombre
  nombre="$(basename "$ultimo")"
  en_linux "infra/respaldos/restaurar.sh -f infra/docker-compose.prod.yml -e $ENV_LOCAL --confirmar $PROYECTO $LOCAL_D/respaldos/$nombre"
}

proxy() {
  docker compose -f infra/local/docker-compose.proxy.yml up -d --force-recreate
  local ip
  ip="$(cat "$LOCAL/certs/ip")"
  echo
  echo "==> Staging local listo"
  echo "    Web de oficina:  https://$ip:8443   (en este PC también https://localhost:8443)"
  echo "    App de campo:    https://$ip:8444"
  echo "    Certificado CA:  http://$ip:8080    (instalarlo en el teléfono y en este PC para evitar avisos)"
}

estado() {
  docker compose -f infra/docker-compose.prod.yml --env-file "$ENV_LOCAL" -p "$PROYECTO" ps
  docker compose -f infra/local/docker-compose.proxy.yml ps
  echo "versión: $(cat "$LOCAL/srv/version-actual" 2>/dev/null || echo '-') (anterior: $(cat "$LOCAL/srv/version-anterior" 2>/dev/null || echo '-'))"
}

bajar() {
  docker compose -f infra/local/docker-compose.proxy.yml down
  SAPEF_IMAGEN=x docker compose -f infra/docker-compose.prod.yml --env-file "$ENV_LOCAL" -p "$PROYECTO" stop
}

borrar() {
  docker compose -f infra/local/docker-compose.proxy.yml down
  SAPEF_IMAGEN=x docker compose -f infra/docker-compose.prod.yml --env-file "$ENV_LOCAL" -p "$PROYECTO" down -v
  rm -rf "$LOCAL/srv"
  echo "Staging local borrado (se conservan .env.local, los certificados y los respaldos)."
}

case "${1:-}" in
  todo) preparar "${2:-}"; construir; desplegar; datos; proxy ;;
  preparar) preparar "${2:-}" ;;
  construir) construir ;;
  desplegar) desplegar "${2:-}" ;;
  revertir) revertir ;;
  datos) datos ;;
  proxy) proxy ;;
  estado) estado ;;
  bajar) bajar ;;
  borrar) borrar ;;
  *) sed -n '2,17p' "$0"; exit 2 ;;
esac
