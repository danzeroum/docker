#!/usr/bin/env bash
#
# Janela de deploy: producao pre-F5 -> F0..F6 acumuladas + migration v8.
# Roda NA VPS srv1351082, no diretorio do compose do cockpit.
#
#   bash scripts/deploy-v8.sh              janela completa (deploy + validacao)
#   bash scripts/deploy-v8.sh --validate   so revalida, nao mexe em nada
#   bash scripts/deploy-v8.sh --dry-run    mostra o que faria, sem executar
#
# Ordem fixa: CIDR no .env -> bloco nginx -> compose config -q -> up -d --build app
#             -> validacao dos 4 aceites.
#
# REGRA DURA: se a validacao de rede falhar, o conserto e o CIDR ou o bloco nginx.
# NUNCA restaure o backup do banco para "resolver" — o esquema antigo devolve o furo
# do token estatico junto. O backup existe para cockpit inoperante, nada mais.
#
# Servico compose = app. Container = docker-cockpit. O socket-proxy NAO e tocado:
# recria-lo derruba o cockpit junto (depends_on: service_healthy).

set -euo pipefail

SERVICO="app"
CONTAINER="docker-cockpit"
GATEWAY="btv-nginx-prod"
REDE="btv-prod-net"
DOMINIO="${DOMAIN:-docker.danzeroum.com}"
INGRESS_CONF="${INGRESS_CONF:-/opt/btv/ingress/nginx/nginx.conf}"
ENV_FILE="${ENV_FILE:-.env}"

MODO="completo"
if [ "${1:-}" = "--validate" ]; then MODO="validacao"; fi
if [ "${1:-}" = "--dry-run" ]; then MODO="dry-run"; fi

FALHAS=0
TOKEN_ANTIGO=""

c_ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
c_bad()  { printf '  \033[31mFALHA\033[0m %s\n' "$1"; FALHAS=$((FALHAS + 1)); }
c_warn() { printf '  \033[33maviso\033[0m %s\n' "$1"; }
titulo() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

executa() {
  if [ "$MODO" = "dry-run" ]; then
    printf '  [dry-run] %s\n' "$*"
    return 0
  fi
  "$@"
}

# ---------------------------------------------------------------------------
# 0 · Pre-voo
# ---------------------------------------------------------------------------
preflight() {
  titulo "0 · Pre-voo"

  if [ ! -f "$ENV_FILE" ]; then
    c_bad "$ENV_FILE nao encontrado — rode do diretorio do compose do cockpit"
    exit 1
  fi
  c_ok "$ENV_FILE encontrado"

  if docker network inspect "$REDE" >/dev/null 2>&1; then
    c_ok "rede $REDE existe"
  else
    c_bad "rede $REDE nao encontrada"
    exit 1
  fi

  # Captura o token estatico ANTES de remove-lo: e o payload do aceite 1.
  if grep -q '^UNLOCK_TOKEN=' "$ENV_FILE"; then
    TOKEN_ANTIGO="$(grep '^UNLOCK_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"'')"
    c_warn "UNLOCK_TOKEN presente no $ENV_FILE — furo confirmado, sera removido"
    printf '%s' "$TOKEN_ANTIGO" > .unlock-token-antigo.tmp
    chmod 600 .unlock-token-antigo.tmp
  else
    c_ok "UNLOCK_TOKEN ausente do $ENV_FILE"
    if [ -f .unlock-token-antigo.tmp ]; then
      TOKEN_ANTIGO="$(cat .unlock-token-antigo.tmp)"
    fi
  fi

  # Backup: rede de seguranca para cockpit inoperante. NAO e ferramenta de rollback
  # de validacao — ver o cabecalho.
  if [ "$MODO" = "completo" ]; then
    if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
      executa docker cp "$CONTAINER:/data/cockpit.db" ./cockpit-pre-v8.db
      c_ok "backup em ./cockpit-pre-v8.db (so para cockpit inoperante)"
    else
      c_warn "$CONTAINER nao esta rodando — sem backup, seguindo"
    fi
  fi
}

# ---------------------------------------------------------------------------
# 1 · Fechar o furo + CIDR real
# ---------------------------------------------------------------------------
passo_env() {
  titulo "1 · .env — remover UNLOCK_TOKEN e gravar o CIDR real"

  if grep -q '^UNLOCK_TOKEN=' "$ENV_FILE"; then
    executa sed -i '/^UNLOCK_TOKEN=/d' "$ENV_FILE"
    c_ok "UNLOCK_TOKEN removido"
  fi

  SUBNET="$(docker network inspect "$REDE" --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')"
  if [ -z "$SUBNET" ]; then
    c_bad "nao consegui ler a subnet de $REDE"
    exit 1
  fi
  printf '  subnet real de %s: %s\n' "$REDE" "$SUBNET"

  if grep -q '^TRUSTED_GATEWAY_CIDR=' "$ENV_FILE"; then
    executa sed -i "s|^TRUSTED_GATEWAY_CIDR=.*|TRUSTED_GATEWAY_CIDR=${SUBNET}|" "$ENV_FILE"
  else
    if [ "$MODO" = "dry-run" ]; then
      printf '  [dry-run] echo TRUSTED_GATEWAY_CIDR=%s >> %s\n' "$SUBNET" "$ENV_FILE"
    else
      printf 'TRUSTED_GATEWAY_CIDR=%s\n' "$SUBNET" >> "$ENV_FILE"
    fi
  fi
  c_ok "TRUSTED_GATEWAY_CIDR=${SUBNET}"

  # O IP do gateway precisa cair dentro da subnet: e o request.client.host que o app ve.
  IP_GW="$(docker inspect "$GATEWAY" \
    --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' 2>/dev/null | tr ' ' '\n' | grep -v '^$' | head -1)"
  if [ -n "$IP_GW" ]; then
    printf '  ip do %s: %s\n' "$GATEWAY" "$IP_GW"
    if python3 -c "import ipaddress,sys; sys.exit(0 if ipaddress.ip_address('$IP_GW') in ipaddress.ip_network('$SUBNET') else 1)"; then
      c_ok "ip do gateway dentro do CIDR"
    else
      c_bad "ip do gateway FORA do CIDR — o unlock vai negar com 401"
    fi
  else
    c_warn "nao achei o ip de $GATEWAY — confira a mao"
  fi
}

# ---------------------------------------------------------------------------
# 2 · Bloco nginx
# ---------------------------------------------------------------------------
passo_nginx() {
  titulo "2 · nginx — Remote-User e SSE no bloco $DOMINIO"

  if [ ! -r "$INGRESS_CONF" ]; then
    c_warn "$INGRESS_CONF ilegivel daqui — confira o bloco a mao"
    return 0
  fi

  PENDENTE=0
  if grep -qE 'proxy_read_timeout[[:space:]]+60s' "$INGRESS_CONF"; then
    c_bad "proxy_read_timeout 60s presente — corta o SSE da F6 a cada minuto"
    PENDENTE=1
  fi
  if ! grep -q 'proxy_buffering off' "$INGRESS_CONF"; then
    c_bad "falta proxy_buffering off"
    PENDENTE=1
  fi
  if ! grep -q 'proxy_set_header Remote-User' "$INGRESS_CONF"; then
    c_bad "falta proxy_set_header Remote-User — unlock responde 401 mesmo com CIDR certo"
    PENDENTE=1
  fi

  if [ "$PENDENTE" -eq 1 ]; then
    cat <<'BLOCO'

  O location / do bloco do cockpit tem de ficar assim:

    location / {
        set $upstream "http://docker-cockpit:8000";
        proxy_pass $upstream;

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Remote-User       $remote_user;

        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

  Edite, depois rode de novo. O script nao reescreve nginx.conf de producao.
BLOCO
    exit 1
  fi

  c_ok "bloco existente atende (Remote-User + SSE)"
  if [ "$MODO" != "dry-run" ]; then
    docker exec "$GATEWAY" nginx -t
    docker exec "$GATEWAY" nginx -s reload
    c_ok "nginx recarregado"
  fi
}

# ---------------------------------------------------------------------------
# 3 · Subir (so o servico app)
# ---------------------------------------------------------------------------
passo_subir() {
  titulo "3 · compose — validar e subir so o servico $SERVICO"

  docker compose config -q
  c_ok "docker compose config -q"

  executa docker compose up -d --build "$SERVICO"

  if [ "$MODO" = "dry-run" ]; then return 0; fi

  printf '  aguardando healthcheck de %s' "$CONTAINER"
  TENTATIVAS=0
  while [ "$TENTATIVAS" -lt 30 ]; do
    ESTADO="$(docker inspect --format '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null; true)"
    if [ "$ESTADO" = "healthy" ]; then break; fi
    printf '.'
    sleep 2
    TENTATIVAS=$((TENTATIVAS + 1))
  done
  printf '\n'

  if [ "$ESTADO" = "healthy" ]; then
    c_ok "$CONTAINER healthy"
  else
    c_bad "$CONTAINER nao ficou healthy (estado: ${ESTADO:-desconhecido})"
    printf '\n  init_db falha alto de proposito. Logs:\n'
    docker compose logs --tail 40 "$SERVICO"
    exit 1
  fi

  VERSAO="$(docker exec "$CONTAINER" python3 -c \
    "import sqlite3;print(sqlite3.connect('/data/cockpit.db').execute('SELECT MAX(version) FROM schema_version').fetchone()[0])" 2>/dev/null; true)"
  if [ "$VERSAO" = "8" ]; then
    c_ok "schema em v8"
  else
    c_bad "schema em ${VERSAO:-?}, esperado 8"
  fi
}

# ---------------------------------------------------------------------------
# 4 · Validacao — os 4 aceites
# ---------------------------------------------------------------------------
codigo_http_interno() {
  # metodo, caminho, header extra -> imprime so o status
  docker exec "$CONTAINER" python3 - "$1" "$2" "${3:-}" <<'PY'
import sys, urllib.request as u
metodo, caminho, header = sys.argv[1], sys.argv[2], sys.argv[3]
h = {}
if header:
    k, _, v = header.partition(":")
    h[k.strip()] = v.strip()
h.setdefault("Content-Type", "application/json")
req = u.Request("http://localhost:8000" + caminho, method=metodo, data=b"{}", headers=h)
try:
    print(u.urlopen(req, timeout=10).status)
except Exception as e:
    print(getattr(e, "code", "erro"))
PY
}

validar() {
  titulo "4 · Validacao — os 4 aceites (o que so a rede real prova)"

  if [ -z "${BASIC_AUTH:-}" ]; then
    USUARIO="$(grep '^BASIC_AUTH_USER=' "$ENV_FILE" | cut -d= -f2- | tr -d '"'"'"'')"
    printf '  usuario do ingress: %s\n' "${USUARIO:-?}"
    printf '  exporte BASIC_AUTH="usuario:senha" para os testes via ingress\n'
  fi

  # --- aceite 1: token estatico antigo -> 403 -----------------------------
  printf '\n  [1] token estatico em X-Cockpit-Unlock\n'
  if [ -n "$TOKEN_ANTIGO" ]; then
    ST="$(codigo_http_interno POST "/api/containers/${CONTAINER}/restart" "X-Cockpit-Unlock: ${TOKEN_ANTIGO}")"
    printf '      restart com o token antigo -> %s\n' "$ST"
    if [ "$ST" = "403" ]; then
      c_ok "token estatico negado"
    else
      c_bad "esperado 403, veio $ST — imagem antiga ainda rodando?"
    fi
  else
    c_warn "token antigo desconhecido; testando um valor arbitrario"
    ST="$(codigo_http_interno POST "/api/containers/${CONTAINER}/restart" "X-Cockpit-Unlock: token-invalido")"
    if [ "$ST" = "403" ]; then c_ok "token arbitrario negado ($ST)"; else c_bad "esperado 403, veio $ST"; fi
  fi

  # --- aceite 2: unlock so pelo ingress -----------------------------------
  printf '\n  [2] unlock via ingress 200 · direto no app 401\n'
  ST_DIRETO="$(codigo_http_interno POST /api/session/unlock)"
  printf '      direto em localhost:8000 -> %s\n' "$ST_DIRETO"
  if [ "$ST_DIRETO" = "401" ]; then
    c_ok "unlock direto negado (sem Remote-User)"
  else
    c_bad "esperado 401, veio $ST_DIRETO"
  fi

  TOKEN_SESSAO=""
  if [ -n "${BASIC_AUTH:-}" ]; then
    RESP="$(curl -s -u "$BASIC_AUTH" -X POST "https://${DOMINIO}/api/session/unlock" \
            -H 'Content-Type: application/json' -d '{"motivo":"janela de deploy"}')"
    ST_ING="$(curl -s -o /dev/null -w '%{http_code}' -u "$BASIC_AUTH" -X POST "https://${DOMINIO}/api/session/unlock" \
            -H 'Content-Type: application/json' -d '{"motivo":"janela de deploy"}')"
    printf '      via ingress -> %s\n' "$ST_ING"
    if [ "$ST_ING" = "200" ]; then
      c_ok "unlock via ingress autorizado"
      TOKEN_SESSAO="$(printf '%s' "$RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])' 2>/dev/null; true)"
      SEGUNDO="$(curl -s -u "$BASIC_AUTH" -X POST "https://${DOMINIO}/api/session/unlock" \
                 -H 'Content-Type: application/json' -d '{"motivo":"segundo"}' \
                 | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])' 2>/dev/null; true)"
      if [ -n "$TOKEN_SESSAO" ] && [ "$TOKEN_SESSAO" != "$SEGUNDO" ]; then
        c_ok "dois unlocks -> dois tokens distintos"
      else
        c_bad "tokens iguais entre chamadas — ainda ha valor derivado de config"
      fi
    else
      c_bad "esperado 200, veio $ST_ING"
      printf '      401 aqui = Remote-User (passo 2). 403 = CIDR (passo 1).\n'
      printf '      NAO restaure o backup do banco — o conserto e config de rede.\n'
    fi
  else
    c_warn "BASIC_AUTH nao exportado — pulei o teste via ingress"
  fi

  # --- aceite 3: ack sai da fila e audita o OPERADOR ----------------------
  printf '\n  [3] ack em healthcheck_never_passed\n'
  if [ -n "$TOKEN_SESSAO" ]; then
    ID="$(curl -s -u "$BASIC_AUTH" "https://${DOMINIO}/api/findings?status=open" \
         | python3 -c 'import sys,json; a=[f["id"] for f in json.load(sys.stdin) if f["rule"]=="healthcheck_never_passed"]; print(a[0] if a else "")' 2>/dev/null; true)"
    if [ -n "$ID" ]; then
      printf '      achado: %s\n' "$ID"
      curl -s -u "$BASIC_AUTH" -X POST "https://${DOMINIO}/api/findings/${ID}/ack" \
        -H "X-Cockpit-Unlock: ${TOKEN_SESSAO}" -H 'Content-Type: application/json' \
        -d '{"reason":"monitorando","note":"sonda na porta errada","until":"24h"}' >/dev/null
      RESTA="$(curl -s -u "$BASIC_AUTH" "https://${DOMINIO}/api/findings?status=open" | grep -c "$ID"; true)"
      if [ "$RESTA" = "0" ]; then
        c_ok "achado saiu da fila"
      else
        c_bad "achado continua na fila"
      fi
      QUEM="$(curl -s -u "$BASIC_AUTH" "https://${DOMINIO}/api/audit?limit=10" \
             | python3 -c 'import sys,json; a=[l for l in json.load(sys.stdin) if l["action"]=="ack"]; print(a[0]["token_label"] if a else "")' 2>/dev/null; true)"
      printf '      auditoria diz quem: %s\n' "${QUEM:-<vazio>}"
      if [ -n "$QUEM" ] && [ "$QUEM" != "unlock" ]; then
        c_ok "auditoria registra o operador"
      else
        c_bad "auditoria sem operador (veio '${QUEM}')"
      fi
    else
      c_warn "nenhum healthcheck_never_passed aberto — nada a silenciar"
    fi
  else
    c_warn "sem token de sessao — pulei o ack"
  fi

  # --- aceite 4: SSE aberto por mais de 2 min -----------------------------
  printf '\n  [4] SSE aberto por >2 min (150s)\n'
  if [ -n "${BASIC_AUTH:-}" ]; then
    INICIO="$(date +%s)"
    curl -s -N -u "$BASIC_AUTH" --max-time 150 "https://${DOMINIO}/events" >/dev/null 2>&1; true
    DUR=$(( $(date +%s) - INICIO ))
    printf '      stream durou %ss\n' "$DUR"
    if [ "$DUR" -ge 140 ]; then
      c_ok "SSE nao caiu"
    else
      c_bad "SSE caiu em ${DUR}s — bloco nginx (passo 2)"
    fi
  else
    c_warn "BASIC_AUTH nao exportado — pulei o teste de SSE"
  fi
}

# ---------------------------------------------------------------------------
# 5 · Fumaca F4/F6
# ---------------------------------------------------------------------------
fumaca() {
  titulo "5 · Fumaca F4/F6"

  conta_amostras() {
    docker exec "$CONTAINER" python3 -c \
      "import sqlite3;print(sqlite3.connect('/data/cockpit.db').execute('SELECT COUNT(*) FROM host_samples').fetchone()[0])" 2>/dev/null; true
  }

  A="$(conta_amostras)"
  printf '  host_samples agora: %s — aguardando 65s\n' "$A"
  sleep 65
  B="$(conta_amostras)"
  printf '  host_samples depois: %s\n' "$B"
  if [ -n "$A" ] && [ -n "$B" ] && [ "$B" -gt "$A" ]; then
    c_ok "F4 coletando"
  else
    c_bad "host_samples nao cresceu — sampler parado"
  fi

  printf '\n  Confira no navegador (nao da para automatizar daqui):\n'
  printf '   - Capacidade: "coletando desde hoje", SEM projecao. Correto no 1o deploy.\n'
  printf '   - docker stop num container de teste: Visao geral reflete em <2s, sem F5.\n'
  printf '     Se so mudar depois de ~30s, o SSE caiu para o polling — volte ao passo 2.\n'
}

# ---------------------------------------------------------------------------

printf '\033[1mJanela de deploy v8 — modo: %s\033[0m\n' "$MODO"

preflight
if [ "$MODO" != "validacao" ]; then
  passo_env
  passo_nginx
  passo_subir
fi
validar
if [ "$MODO" != "validacao" ]; then
  fumaca
fi

titulo "Resultado"
if [ "$FALHAS" -eq 0 ]; then
  printf '  \033[32mtodos os aceites passaram\033[0m\n'
  printf '  remova o rastro do token antigo: rm -f .unlock-token-antigo.tmp\n'
  exit 0
fi

printf '  \033[31m%s verificacao(oes) falharam\033[0m\n' "$FALHAS"
printf '  Conserto de falha de rede = CIDR (passo 1) ou bloco nginx (passo 2).\n'
printf '  NUNCA restaure cockpit-pre-v8.db para contornar: o esquema antigo devolve\n'
printf '  o furo do token estatico junto. Reexecute com --validate apos consertar.\n'
exit 1
