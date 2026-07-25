#!/usr/bin/env bash
# Bootstrap: gera .htpasswd + certificado TLS na primeira vez
set -euo pipefail

# Carrega .env
if [ ! -f .env ]; then
  echo "[ERROR] .env não encontrado. Copie .env.example e preencha os valores."
  exit 1
fi
source .env

# 1) Gera .htpasswd se não existir
mkdir -p nginx
if [ ! -f nginx/.htpasswd ]; then
  echo "[+] Gerando nginx/.htpasswd..."
  docker run --rm httpd:alpine \
    htpasswd -Bbn "$BASIC_AUTH_USER" "$BASIC_AUTH_PASS" > nginx/.htpasswd
  echo "    Usuário: $BASIC_AUTH_USER"
fi

# 2) Cria diretórios do certbot
mkdir -p certbot/conf certbot/www

# 3) Sobe só nginx na porta 80 (sem SSL, sem depender da app) para o challenge ACME
# Usa config temporária sem bloco 443
echo "[+] Subindo nginx temporário para ACME challenge..."
cat > /tmp/nginx_acme_only.conf <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / { return 200 "aguardando cert"; }
}
EOF

docker run --rm -d \
  --name nginx_acme_tmp \
  -p 80:80 \
  -v /tmp/nginx_acme_only.conf:/etc/nginx/conf.d/default.conf:ro \
  -v "$(pwd)/certbot/www:/var/www/certbot:ro" \
  nginx:stable-alpine

# 4) Emite certificado
echo "[+] Emitindo certificado para $DOMAIN..."
docker run --rm \
  -v "$(pwd)/certbot/conf:/etc/letsencrypt" \
  -v "$(pwd)/certbot/www:/var/www/certbot" \
  certbot/certbot certonly \
  --webroot --webroot-path=/var/www/certbot \
  --email "$EMAIL" --agree-tos --no-eff-email \
  -d "$DOMAIN"

# 5) Para o nginx temporário
docker stop nginx_acme_tmp

# 6) Substitui nginx.conf com a versão final (DOMAIN interpolado)
sed "s/\${DOMAIN}/$DOMAIN/g" nginx/nginx.conf > /tmp/nginx_final.conf
cp /tmp/nginx_final.conf nginx/nginx.conf

# 7) Sobe a stack completa
echo "[+] Subindo stack completa..."
docker compose up -d

echo ""
echo "✅ Pronto! Acesse https://$DOMAIN"
echo "   Usuário: $BASIC_AUTH_USER / Senha: (definida no .env)"
