#!/usr/bin/env bash
# Cron de renovação — rode como: 0 3 * * * /caminho/para/scripts/renew.sh
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose run --rm certbot renew --quiet
docker compose exec nginx nginx -s reload
