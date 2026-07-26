#!/usr/bin/env bash
# setup-ingress.sh
# Emite o certificado TLS para COCKPIT_DOMAIN e adiciona o bloco
# server{} no nginx do global-ingress (btv-nginx-prod).
#
# Uso: bash scripts/setup-ingress.sh docker.danzeroum.com
# Pre-requisito: DNS A do dominio ja apontando para este servidor.

set -euo pipefail

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
  echo "Uso: $0 <dominio>  ex: $0 docker.danzeroum.com"
  exit 1
fi

INGRESS_CONF="/opt/btv/ingress/nginx/nginx.conf"
HTTPASSWD="/opt/btv/ingress/.htpasswd"
CERTBOT_WWW="/var/www/certbot"
CERTBOT_CONF="/etc/letsencrypt"

echo "[1/4] Verificando DNS para $DOMAIN..."
if ! host "$DOMAIN" > /dev/null 2>&1; then
  echo "ERRO: DNS NXDOMAIN para $DOMAIN. Aponte um registro A para o IP deste servidor antes de continuar."
  exit 1
fi
echo "  OK: $(host "$DOMAIN" | head -1)"

echo "[2/4] Emitindo certificado via certbot (webroot)..."
docker run --rm \
  -v "${CERTBOT_CONF}:/etc/letsencrypt" \
  -v "${CERTBOT_WWW}:/var/www/certbot" \
  certbot/certbot certonly \
    --webroot \
    --webroot-path /var/www/certbot \
    --non-interactive \
    --agree-tos \
    --email admin@buildtovalue.cloud \
    -d "$DOMAIN"

echo "[3/4] Adicionando bloco server{} em $INGRESS_CONF..."

# Verifica se ja existe entrada para o dominio
if grep -q "server_name ${DOMAIN}" "$INGRESS_CONF"; then
  echo "  Bloco para $DOMAIN ja existe em nginx.conf — pulando."
else
  # Injeta antes do ultimo '}' do bloco http {}
  BLOCK="
    # ---- docker-cockpit (${DOMAIN}) ----
    server {
        listen 80;
        server_name ${DOMAIN};
        location /.well-known/acme-challenge/ { root /var/www/certbot; }
        location / { return 301 https://\$host\$request_uri; }
    }
    server {
        listen 443 ssl;
        server_name ${DOMAIN};
        ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
        add_header Strict-Transport-Security \"max-age=63072000\" always;

        # Autenticacao basica (mesmo .htpasswd do ingress)
        auth_basic \"Docker Cockpit\";
        auth_basic_user_file /etc/nginx/.htpasswd;

        location ~* (wp-login|\.git|\.env) { return 444; }
        location / {
            set \$upstream \"http://docker-cockpit:8000\";
            proxy_pass \$upstream;
            proxy_read_timeout 60s;
        }
    }"

  # Insere antes do ultimo } do arquivo
  python3 - <<PYEOF
import re, pathlib
p = pathlib.Path("$INGRESS_CONF")
content = p.read_text()
# Insere o bloco antes do ultimo }
insert = '''$BLOCK'''
new_content = content.rstrip().rstrip('}').rstrip() + '\n' + insert + '\n}\n'
p.write_text(new_content)
print('  Bloco inserido em nginx.conf')
PYEOF
fi

echo "[4/4] Recarregando btv-nginx-prod (zero-downtime)..."
docker exec btv-nginx-prod nginx -s reload

echo ""
echo "Pronto! Cockpit disponivel em https://${DOMAIN}"
echo "Use as credenciais do .htpasswd do ingress (admin / senha configurada)."
