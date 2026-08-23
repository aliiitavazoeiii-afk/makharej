#!/usr/bin/env bash
set -Eeuo pipefail

REPO="aliiitavazoeiii-afk/makharej"
BRANCH="main"
APP_DIR="/opt/kharj"
DOMAIN="${DOMAIN:-kharj.boro2film.top}"
TMP_DIR="/tmp/kharj-install.$$"
ARCHIVE="$TMP_DIR/repo.tar.gz"

cleanup(){ rm -rf "$TMP_DIR" 2>/dev/null || true; }
trap cleanup EXIT

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "ERROR: installer must run as root/sudo." >&2; exit 1
fi
if [[ ! -r /etc/os-release ]]; then echo "ERROR: Ubuntu/Debian required." >&2; exit 1; fi
. /etc/os-release
case "${ID:-}" in ubuntu|debian) ;; *) [[ " ${ID_LIKE:-} " == *" debian "* ]] || { echo "ERROR: Ubuntu/Debian required." >&2; exit 1; } ;; esac

export DEBIAN_FRONTEND=noninteractive
mkdir -p "$TMP_DIR"
echo "============================================================"
echo " Kharj - personal expense dashboard"
echo " Safe side-by-side install with VPN Control Center"
echo " Domain: $DOMAIN"
echo "============================================================"

apt-get update -y
apt-get install -y ca-certificates curl openssl tar gzip coreutils iproute2 nginx

if ! command -v docker >/dev/null 2>&1; then
  echo "[1/7] Installing Docker..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/${ID}/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  ARCH="$(dpkg --print-architecture)"; CODENAME="${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}"
  echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${ID} ${CODENAME} stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else echo "[1/7] Docker already installed."; fi
docker compose version >/dev/null

ENV_KEEP=""
if [[ -d "$APP_DIR" ]]; then
  echo "[2/7] Updating previous Kharj installation..."
  [[ -f "$APP_DIR/.env" ]] && { ENV_KEEP="$TMP_DIR/.env.keep"; cp "$APP_DIR/.env" "$ENV_KEEP"; }
  [[ -f "$APP_DIR/docker-compose.yml" ]] && (cd "$APP_DIR" && docker compose down --remove-orphans) || true
else echo "[2/7] Fresh install."; fi

# VPN Control Center normally uses 8080. Kharj starts from 8091 and binds only to localhost.
PORT="8091"
if [[ -n "$ENV_KEEP" ]]; then PORT="$(grep '^APP_PORT=' "$ENV_KEEP" | cut -d= -f2- || true)"; PORT="${PORT:-8091}"; fi
if ss -lnt 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)${PORT}$"; then
  FOUND=""; for P in $(seq 8091 8120); do
    if ! ss -lnt 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)${P}$"; then FOUND="$P"; break; fi
  done
  [[ -n "$FOUND" ]] || { echo "ERROR: no free port in 8091-8120." >&2; exit 2; }
  PORT="$FOUND"
fi

echo "[3/7] Downloading source from GitHub..."
curl -fL --retry 4 --retry-delay 2 --connect-timeout 20 "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz" -o "$ARCHIVE"
tar -xzf "$ARCHIVE" -C "$TMP_DIR"
SRC_DIR="$(find "$TMP_DIR" -maxdepth 1 -mindepth 1 -type d -name 'makharej-*' | head -n1)"
[[ -n "$SRC_DIR" && -f "$SRC_DIR/docker-compose.yml" && -f "$SRC_DIR/app/main.py" ]] || { echo "ERROR: incomplete source archive." >&2; exit 3; }
rm -rf "$APP_DIR"; mkdir -p "$APP_DIR"; cp -a "$SRC_DIR"/. "$APP_DIR"/; cd "$APP_DIR"

if [[ -n "$ENV_KEEP" && -f "$ENV_KEEP" ]]; then
  cp "$ENV_KEEP" .env
  if grep -q '^APP_PORT=' .env; then sed -i "s/^APP_PORT=.*/APP_PORT=$PORT/" .env; else echo "APP_PORT=$PORT" >> .env; fi
else
  cp .env.example .env
  NEW_PASS="$(openssl rand -hex 10)"; SECRET="$(openssl rand -hex 32)"
  sed -i "s|CHANGE_THIS_LONG_PASSWORD|$NEW_PASS|" .env
  sed -i "s|CHANGE_THIS_TO_A_LONG_RANDOM_SECRET|$SECRET|" .env
  sed -i "s/^APP_PORT=.*/APP_PORT=$PORT/" .env
fi
chmod 600 .env

echo "[4/7] Building and starting Kharj on 127.0.0.1:$PORT..."
docker compose build --no-cache app
docker compose up -d

OK=0
for _ in $(seq 1 60); do
  H="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/health" 2>/dev/null || true)"
  [[ "$H" == "200" ]] && { OK=1; break; }; sleep 2
done
if [[ "$OK" != "1" ]]; then docker compose logs --tail=250 app >&2 || true; echo "ERROR: Kharj failed health check." >&2; exit 4; fi

echo "[5/7] Configuring Nginx for $DOMAIN..."
NGINX_CONF="/etc/nginx/sites-available/${DOMAIN}.conf"
cat > "$NGINX_CONF" <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    client_max_body_size 10m;

    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
}
NGINX
ln -sfn "$NGINX_CONF" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo "[6/7] Checking domain and HTTPS..."
PUBLIC_IP="$(curl -4fsS --max-time 6 https://api.ipify.org 2>/dev/null || true)"
DOMAIN_IP="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}' || true)"
HTTPS_OK=0
if [[ -n "$PUBLIC_IP" && "$DOMAIN_IP" == "$PUBLIC_IP" ]]; then
  apt-get install -y certbot python3-certbot-nginx >/dev/null 2>&1 || true
  if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect; then HTTPS_OK=1; fi
else
  echo "DNS is not pointing to this server yet; HTTPS skipped for now."
fi

echo "[7/7] Final checks..."
curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null
ADMIN_USER="$(grep '^ADMIN_USERNAME=' .env | cut -d= -f2- || true)"; ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="$(grep '^ADMIN_PASSWORD=' .env | cut -d= -f2- || true)"
SCHEME="http"; [[ "$HTTPS_OK" == "1" ]] && SCHEME="https"
cat <<OUT
============================================================
Kharj READY
URL:      ${SCHEME}://${DOMAIN}
Internal: http://127.0.0.1:${PORT}
Username: ${ADMIN_USER}
Password: ${ADMIN_PASS}
============================================================
VPN Control Center remains untouched; this app is isolated in /opt/kharj
and binds only to localhost on its own port.
OUT
