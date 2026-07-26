#!/usr/bin/env bash
# Renovação de certificado TLS via Certbot + reload do Nginx
# Cron: 0 3 * * * /caminho/absoluto/scripts/renew.sh >> /var/log/certbot-renew.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[$(date -Iseconds)] Iniciando renovação..."

# Roda certbot (só age se faltar <30 dias para expirar)
docker compose run --rm certbot renew --quiet

# Reload do nginx para carregar o novo certificado.
# nginx -s reload é zero-downtime: workers antigos concluem requests em andamento.
# É seguro rodar mesmo que não tenha renovado (certbot --quiet não falha).
docker compose exec nginx nginx -s reload

echo "[$(date -Iseconds)] Concluído."
