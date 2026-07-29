#!/usr/bin/env bash
#
# Janela de deploy do cockpit: producao pre-F5 -> F0..F6 acumuladas,
# com as migrations v8 (token de sessao) e v9 (tarefas) na MESMA janela.
# Roda NA VPS srv1351082, no diretorio do compose do cockpit.
#
#   bash scripts/deploy-cockpit.sh              janela completa (deploy + validacao)
#   bash scripts/deploy-cockpit.sh --validate   so revalida, nao mexe em nada
#   bash scripts/deploy-cockpit.sh --dry-run    mostra o que faria, sem escrever nada
#
# Ordem fixa: CIDR no .env -> bloco nginx -> compose config -q -> up -d --build app
#             -> validacao dos aceites da v8 -> validacao do board da v9.
#
# init_db aplica as duas migrations de uma vez. Por isso o passo de subida exige
# schema 9 E a tabela tasks: parar na v8 significa migration incompleta, e o
# board falharia depois por um motivo que nao e dele.
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
# A rota real do SSE da F6. Era "/events" aqui e 404 na VPS.
ROTA_SSE="/api/events/stream"

MODO="completo"
if [ "${1:-}" = "--validate" ]; then MODO="validacao"; fi
if [ "${1:-}" = "--dry-run" ]; then MODO="dry-run"; fi

FALHAS=0
TOKEN_ANTIGO=""
TOKEN_SESSAO=""
# sim | nao | ausente | indefinido — preenchido pelo passo 3c, lido por ingress_ok
CRED_OK="indefinido"

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

# Validar de verdade escreve: unlock cria sessao, ack mexe em achado, PATCH move
# cartao — os tres deixam linha de auditoria. Em --dry-run nada disso pode rodar,
# entao os checks que escrevem sao anunciados e pulados.
escreve_ok() {
  if [ "$MODO" = "dry-run" ]; then
    return 1
  fi
  return 0
}

pula_dry_run() {
  printf '  [dry-run] pularia: %s\n' "$1"
}

# Aceite que atravessa o ingress so vale se a credencial ja foi provada no 3c.
# Sem isso, senha errada reprova o aceite e o diagnostico culpa o cabecalho.
ingress_ok() {
  if [ -z "${BASIC_AUTH:-}" ]; then
    return 1
  fi
  if [ "$CRED_OK" != "sim" ]; then
    return 1
  fi
  return 0
}

# Consulta o banco do cockpit de dentro do container.
sql() {
  docker exec "$CONTAINER" python3 -c \
    "import sqlite3;print(sqlite3.connect('/data/cockpit.db').execute(\"$1\").fetchone()[0])" 2>/dev/null
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
    # Guardar em disco e escrita, e escrita de um segredo: nao acontece em dry-run.
    if escreve_ok; then
      printf '%s' "$TOKEN_ANTIGO" > .unlock-token-antigo.tmp
      chmod 600 .unlock-token-antigo.tmp
    else
      pula_dry_run "gravar o token antigo em .unlock-token-antigo.tmp"
    fi
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
      executa docker cp "$CONTAINER:/data/cockpit.db" ./cockpit-pre-v8v9.db
      c_ok "backup em ./cockpit-pre-v8v9.db (so para cockpit inoperante)"
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

  checa_schema
}

# ---------------------------------------------------------------------------
# 3b · Schema: as duas migrations da janela
#
# Roda ANTES de qualquer check do board. Se a v9 nao subiu, o board vai falhar
# em cascata por um motivo que nao e dele — e o diagnostico util e a migration.
# ---------------------------------------------------------------------------
checa_schema() {
  VERSAO="$(sql 'SELECT MAX(version) FROM schema_version'; true)"
  if [ "$VERSAO" = "9" ]; then
    c_ok "schema em v9 (v8 + v9 aplicadas)"
  else
    c_bad "schema em ${VERSAO:-?}, esperado 9"
    printf '    a janela sobe DUAS migrations: v8 (sessao) e v9 (tarefas).\n'
    printf '    parar em 8 e migration incompleta — veja: docker compose logs app\n'
    return 0
  fi

  TEM_TASKS="$(sql "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='tasks'"; true)"
  if [ "$TEM_TASKS" = "1" ]; then
    c_ok "tabela tasks existe"
  else
    c_bad "tabela tasks AUSENTE — a v9 nao aplicou"
    printf '    nao e problema do board: e a migration. docker compose logs app\n'
  fi

  UM_OITO="$(sql 'SELECT COUNT(*) FROM schema_version WHERE version = 8'; true)"
  if [ "$UM_OITO" = "1" ]; then
    c_ok "um unico schema_version 8"
  else
    c_bad "schema_version 8 aparece ${UM_OITO:-?} vezes — merge fora de ordem"
  fi
}

# ---------------------------------------------------------------------------
# 4 · Validacao — os 4 aceites
# ---------------------------------------------------------------------------
# metodo, caminho, header extra -> imprime o status HTTP, ou uma palavra quando
# nao houve resposta nenhuma.
#
# A distincao importa. Antes, qualquer excecao sem `.code` virava "erro", e a
# mensagem do aceite dizia "esperado 403, veio erro — imagem antiga ainda
# rodando?". Isso le como se o gate de escrita tivesse falhado. Nao tinha:
# ninguem respondeu. Reprovar um aceite de seguranca por app fora do ar e
# exatamente o tipo de diagnostico que manda consertar o lugar errado.
codigo_http_interno() {
  docker exec -i "$CONTAINER" python3 - "$1" "$2" "${3:-}" <<'PY'
import sys, socket, urllib.error, urllib.request as u
metodo, caminho, header = sys.argv[1], sys.argv[2], sys.argv[3]
h = {}
if header:
    k, _, v = header.partition(":")
    h[k.strip()] = v.strip()
h.setdefault("Content-Type", "application/json")
corpo = None if metodo == "GET" else b"{}"
req = u.Request("http://localhost:8000" + caminho, method=metodo, data=corpo, headers=h)
try:
    print(u.urlopen(req, timeout=10).status)
except urllib.error.HTTPError as e:
    # resposta HTTP de verdade, inclusive 401/403/404
    print(e.code)
except (socket.timeout, TimeoutError):
    print("timeout")
except urllib.error.URLError:
    # connection refused, app ainda subindo, ou processo caiu no meio
    print("sem-resposta")
except Exception:
    print("sem-resposta")
PY
}

# O app pode nao estar ouvindo ainda: em --validate logo depois de
# `up -d --build app`, o container aparece Started muito antes de o uvicorn
# aceitar conexao (init_db aplica migrations, o sampler tira a primeira
# amostra). Sem esta espera, os primeiros aceites reprovavam por corrida.
APP_RESPONDE="nao"
# Segundos de espera. 30s cobre init_db + primeira amostra numa VPS carregada.
# Sobrescrito nos testes, que nao tem app nenhum para esperar.
ESPERA_APP_S="${ESPERA_APP_S:-30}"

espera_app() {
  titulo "3d · App ouvindo em localhost:8000"
  local i st
  i=0
  while [ "$i" -lt "$ESPERA_APP_S" ]; do
    st="$(codigo_http_interno GET /api/tasks)"
    case "$st" in
      sem-resposta|timeout) : ;;
      *)
        APP_RESPONDE="sim"
        printf '      respondeu em %ss (status %s)\n' "$i" "$st"
        c_ok "app ouvindo"
        return 0
        ;;
    esac
    i=$((i + 1))
    sleep 1
  done
  c_bad "app nao respondeu em ${i}s — os aceites internos nao dizem nada"
  printf '      docker compose logs app --tail 50\n'
  printf '      isto NAO e falha do gate de escrita: nada foi exercitado.\n'
}

# Status HTTP e presenca do desafio de basic auth, em uma linha "status|desafio".
# O desafio (WWW-Authenticate) e o que separa 401 do nginx de 401 do app: o nginx
# convida a autenticar, o app so nega.
codigo_e_desafio() {
  local cred="$1"
  local resposta
  resposta="$(curl -s -i --max-time 15 -u "$cred" "https://${DOMINIO}/api/system" 2>/dev/null; true)"
  local status
  status="$(printf '%s' "$resposta" | head -1 | awk '{print $2}'; true)"
  local desafio="nao"
  if printf '%s' "$resposta" | grep -qi '^WWW-Authenticate:'; then
    desafio="sim"
  fi
  printf '%s|%s\n' "${status:-000}" "$desafio"
}

# ---------------------------------------------------------------------------
# 3c · Credencial do ingress — ANTES dos aceites
#
# Por que antes: os aceites 2, 3, 4 e o board todos atravessam o basic auth. Se
# a senha estiver errada, o nginx devolve 401 e o aceite 2 imprimia
# "401 aqui = Remote-User (passo 2)" — mandando consertar o bloco nginx, que
# estava certo. Aconteceu: BASIC_AUTH foi exportado com um SHA de git stash no
# lugar da senha, e o diagnostico acusou o cabecalho.
#
# 401 do nginx e 401 do app sao o MESMO numero por caminhos diferentes. O que os
# separa e o desafio WWW-Authenticate, que so o nginx manda. Este passo le isso
# em uma rota de leitura livre — sem unlock, sem escrita — e so entao deixa os
# aceites rodarem.
# ---------------------------------------------------------------------------
checa_credencial() {
  titulo "3c · Credencial do ingress (antes dos aceites)"

  if [ -z "${BASIC_AUTH:-}" ]; then
    USUARIO="$(grep '^BASIC_AUTH_USER=' "$ENV_FILE" | cut -d= -f2- | tr -d '"'"'"''; true)"
    printf '  usuario do ingress: %s\n' "${USUARIO:-?}"
    printf '  exporte BASIC_AUTH="usuario:senha" para os testes via ingress\n'
    c_warn "BASIC_AUTH nao exportado — os aceites via ingress serao pulados, nao reprovados"
    CRED_OK="ausente"
    return 0
  fi

  # A credencial nunca e impressa. So o usuario, que ja esta no .env.
  printf '  usuario informado em BASIC_AUTH: %s\n' "${BASIC_AUTH%%:*}"

  local r st desafio
  r="$(codigo_e_desafio "$BASIC_AUTH")"
  st="${r%%|*}"
  desafio="${r##*|}"
  printf '      GET /api/system com a credencial -> %s\n' "$st"

  case "$st" in
    200)
      c_ok "credencial aceita pelo ingress"
      ;;
    401)
      CRED_OK="nao"
      c_bad "credencial REJEITADA pelo ingress — a senha (ou o usuario) esta errada"
      if [ "$desafio" = "sim" ]; then
        printf '      o 401 traz WWW-Authenticate: veio do nginx, nao do cockpit.\n'
      fi
      printf '      NAO e Remote-User e NAO e o CIDR: nada disso foi exercitado ainda.\n'
      printf '      Confira o par usuario:senha em /opt/btv/ingress/.htpasswd.\n'
      printf '      O arquivo e bind-mount: acrescente com >> para preservar o inode.\n'
      printf '      Hash com: openssl passwd -apr1\n'
      return 0
      ;;
    000)
      CRED_OK="nao"
      c_bad "https://${DOMINIO} nao respondeu — DNS, TLS ou o ingress fora do ar"
      printf '      os aceites via ingress nao dizem nada enquanto isto nao resolver.\n'
      return 0
      ;;
    502|503|504)
      CRED_OK="nao"
      c_bad "ingress respondeu $st — nginx de pe, cockpit atras dele nao"
      printf '      passo 3 (subir o app) antes de qualquer aceite.\n'
      return 0
      ;;
    *)
      CRED_OK="nao"
      c_bad "resposta inesperada ($st) na rota de leitura livre"
      return 0
      ;;
  esac

  # Credencial boa. Falta provar que o basic auth esta REALMENTE protegendo a
  # rota — se estiver desligado, qualquer credencial passa e o 200 acima nao
  # significa nada. Uma credencial deliberadamente falsa tem de ser recusada.
  r="$(codigo_e_desafio 'cred-invalida-de-teste:senha-invalida-de-teste')"
  st="${r%%|*}"
  printf '      GET /api/system com credencial falsa -> %s\n' "$st"
  if [ "$st" = "401" ]; then
    c_ok "basic auth ativo: credencial falsa recusada"
    CRED_OK="sim"
  else
    CRED_OK="nao"
    c_bad "credencial falsa NAO foi recusada ($st) — basic auth nao protege esta rota"
    printf '      o cockpit esta aberto a quem alcancar o dominio. Isto e mais grave\n'
    printf '      que qualquer aceite abaixo: corrija o auth_basic antes de seguir.\n'
  fi
}

validar() {
  titulo "4 · Validacao — os 4 aceites (o que so a rede real prova)"

  if [ "$CRED_OK" = "nao" ]; then
    c_warn "credencial do ingress reprovada no 3c — pulando os aceites que passam por ela"
    printf '  Rodar esses aceites agora produziria falhas que apontam para o lugar\n'
    printf '  errado. Conserte a credencial e reexecute com --validate.\n'
  fi

  # --- aceite 1: token estatico antigo -> 403 -----------------------------
  #
  # A rota usada aqui era POST /api/containers/docker-cockpit/restart: o script
  # pedia ao cockpit que reiniciasse a si mesmo. Se o gate REJEITA, da 403 e nao
  # acontece nada — mas se o gate ACEITA, o cockpit cai no meio da validacao,
  # a conexao morre, o status vira "sem-resposta" e o proximo aceite tambem
  # falha. Ou seja: no unico caso em que o teste tinha algo a dizer, ele
  # destruia a propria evidencia e culpava outra coisa.
  #
  # PATCH /api/tasks/<id inexistente> passa pelo MESMO require_unlock e nao
  # muda nada em nenhum desfecho:
  #   403 = gate recusou o token (o que se quer provar)
  #   404 = gate ACEITOU e so nao achou o cartao -> furo, e o alarme aparece
  # Nada e escrito de qualquer forma, e o cockpit continua de pe para responder.
  printf '\n  [1] token estatico em X-Cockpit-Unlock\n'
  if [ "$APP_RESPONDE" != "sim" ]; then
    c_warn "app nao respondeu no 3d — pulei o aceite (nao ha o que concluir)"
  else
    ROTA_GUARDADA="/api/tasks/cartao-que-nao-existe"
    if [ -n "$TOKEN_ANTIGO" ]; then
      QUAL="o token antigo"
      TOKEN_TESTE="$TOKEN_ANTIGO"
    else
      c_warn "token antigo desconhecido; testando um valor arbitrario"
      QUAL="um valor arbitrario"
      TOKEN_TESTE="token-invalido"
    fi
    ST="$(codigo_http_interno PATCH "$ROTA_GUARDADA" "X-Cockpit-Unlock: ${TOKEN_TESTE}")"
    printf '      PATCH em rota guardada com %s -> %s\n' "$QUAL" "$ST"
    case "$ST" in
      403)
        c_ok "token estatico negado pelo gate"
        ;;
      404)
        c_bad "o gate ACEITOU $QUAL (404 = passou e so nao achou o cartao)"
        printf '      isto e o furo da v8 de volta: require_unlock validando algo\n'
        printf '      que nao e sessao. Nao siga com a janela.\n'
        ;;
      sem-resposta|timeout)
        c_bad "sem resposta do app ($ST) — aceite inconclusivo, nao aprovado"
        ;;
      *)
        c_bad "esperado 403, veio $ST"
        ;;
    esac
  fi

  # --- aceite 2: unlock so pelo ingress -----------------------------------
  printf '\n  [2] unlock via ingress 200 · direto no app 401\n'
  if [ "$APP_RESPONDE" != "sim" ]; then
    c_warn "app nao respondeu no 3d — pulei o teste direto em localhost:8000"
  else
    ST_DIRETO="$(codigo_http_interno POST /api/session/unlock)"
    printf '      direto em localhost:8000 -> %s\n' "$ST_DIRETO"
    case "$ST_DIRETO" in
      401) c_ok "unlock direto negado (sem Remote-User)" ;;
      sem-resposta|timeout)
        c_bad "sem resposta do app ($ST_DIRETO) — inconclusivo, nao aprovado"
        ;;
      *) c_bad "esperado 401, veio $ST_DIRETO" ;;
    esac
  fi

  if ingress_ok && escreve_ok; then
    RESP="$(curl -s -u "$BASIC_AUTH" -X POST "https://${DOMINIO}/api/session/unlock" \
            -H 'Content-Type: application/json' -d '{"motivo":"janela de deploy"}'; true)"
    ST_ING="$(curl -s -o /dev/null -w '%{http_code}' -u "$BASIC_AUTH" -X POST "https://${DOMINIO}/api/session/unlock" \
            -H 'Content-Type: application/json' -d '{"motivo":"janela de deploy"}'; true)"
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
      # A credencial ja passou no 3c, entao 401 aqui NAO e senha errada — e a
      # unica leitura honesta que sobra e o cabecalho.
      printf '      credencial ja validada no 3c, logo:\n'
      printf '      401 = falta proxy_set_header Remote-User (passo 2).\n'
      printf '      403 = TRUSTED_GATEWAY_CIDR nao cobre o ip do gateway (passo 1).\n'
      printf '      NAO restaure o backup do banco — o conserto e config de rede.\n'
    fi
  else
    if ! escreve_ok; then
      pula_dry_run "unlock via ingress (criaria sessao em unlock_state)"
    elif [ "$CRED_OK" = "ausente" ]; then
      c_warn "BASIC_AUTH nao exportado — pulei o teste via ingress"
    else
      c_warn "credencial reprovada no 3c — pulei o teste via ingress"
    fi
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
    if ! escreve_ok; then
      pula_dry_run "ack de achado (mexeria em findings e audit_log)"
    elif [ "$CRED_OK" = "sim" ]; then
      c_warn "sem token de sessao — pulei o ack"
    else
      c_warn "credencial do ingress nao provada no 3c — pulei o ack"
    fi
  fi

  # --- aceite 4: SSE aberto por mais de 2 min -----------------------------
  printf '\n  [4] SSE aberto por >2 min (150s)\n'
  if ingress_ok; then
    # Confere o status ANTES de medir. Stream que morre em 0s quase sempre e
    # 404 ou 401, nao timeout do proxy — e culpar o nginx nesse caso manda o
    # operador reeditar um bloco que estava certo.
    ST_SSE="$(curl -s -o /dev/null -w '%{http_code}' -u "$BASIC_AUTH" \
      --max-time 5 "https://${DOMINIO}${ROTA_SSE}"; true)"
    if [ "$ST_SSE" != "200" ] && [ "$ST_SSE" != "000" ]; then
      c_bad "${ROTA_SSE} respondeu ${ST_SSE} — credencial ja validada no 3c, logo e a rota"
    else
      INICIO="$(date +%s)"
      curl -s -N -u "$BASIC_AUTH" --max-time 150 "https://${DOMINIO}${ROTA_SSE}" >/dev/null 2>&1; true
      DUR=$(( $(date +%s) - INICIO ))
      printf '      stream durou %ss\n' "$DUR"
      if [ "$DUR" -ge 140 ]; then
        c_ok "SSE nao caiu"
      else
        c_bad "SSE caiu em ${DUR}s — bloco nginx (passo 2)"
      fi
    fi
  elif [ "$CRED_OK" = "ausente" ]; then
    c_warn "BASIC_AUTH nao exportado — pulei o teste de SSE"
  else
    c_warn "credencial reprovada no 3c — pulei o teste de SSE"
  fi
}

# ---------------------------------------------------------------------------
# 4b · Board de Tarefas (v9)
#
# O board e a unica tela nova que ESCREVE. O que precisa de rede real aqui e o
# mesmo do resto: o guard de escrita so vale se o unlock funcionar de verdade.
# ---------------------------------------------------------------------------
validar_board() {
  titulo "4b · Board de Tarefas (v9)"

  # Sem a tabela nao ha o que validar — e o diagnostico e a migration, nao o board.
  TEM_TASKS="$(sql "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='tasks'"; true)"
  if [ "$TEM_TASKS" != "1" ]; then
    c_bad "tabela tasks ausente — a v9 nao aplicou; nada do board e conclusivo"
    printf '    docker compose logs app | grep -i migration\n'
    return 0
  fi

  # --- leitura livre ------------------------------------------------------
  printf '\n  [5] GET /api/tasks (leitura livre)\n'
  ST="$(codigo_http_interno GET /api/tasks)"
  printf '      /api/tasks -> %s\n' "$ST"
  case "$ST" in
    200) c_ok "board responde" ;;
    sem-resposta|timeout) c_bad "sem resposta do app ($ST) — nao e o board, e o processo" ;;
    *) c_bad "esperado 200, veio $ST" ;;
  esac

  # --- guard de escrita ---------------------------------------------------
  printf '\n  [6] PATCH /api/tasks sem unlock\n'
  ST="$(codigo_http_interno PATCH /api/tasks/nao-existe)"
  printf '      PATCH sem X-Cockpit-Unlock -> %s\n' "$ST"
  case "$ST" in
    403) c_ok "escrita negada sem destravamento" ;;
    sem-resposta|timeout)
      # "o board escreve sem guard" seria acusacao grave e errada: nada respondeu.
      c_bad "sem resposta do app ($ST) — guard nao exercitado, aceite inconclusivo"
      ;;
    *) c_bad "esperado 403, veio $ST — o board esta escrevendo sem guard" ;;
  esac

  # --- escrita autorizada + auditoria -------------------------------------
  printf '\n  [7] PATCH com unlock -> 200 e linha em /api/audit\n'
  if [ -n "$TOKEN_SESSAO" ]; then
    ID_CARTAO="$(curl -s -u "$BASIC_AUTH" "https://${DOMINIO}/api/tasks" \
      | python3 -c 'import sys,json; c=json.load(sys.stdin)["columns"]; t=[x for col in c for x in col["tasks"]]; print(t[0]["id"] if t else "")' 2>/dev/null; true)"
    if [ -n "$ID_CARTAO" ]; then
      COL_ANTES="$(curl -s -u "$BASIC_AUTH" "https://${DOMINIO}/api/tasks" \
        | python3 -c "import sys,json; c=json.load(sys.stdin)['columns']; print([x['col'] for col in c for x in col['tasks'] if x['id']=='$ID_CARTAO'][0])" 2>/dev/null; true)"
      DESTINO="doing"
      if [ "$COL_ANTES" = "doing" ]; then DESTINO="todo"; fi
      ST="$(curl -s -o /dev/null -w '%{http_code}' -u "$BASIC_AUTH" \
        -X PATCH "https://${DOMINIO}/api/tasks/${ID_CARTAO}" \
        -H "X-Cockpit-Unlock: ${TOKEN_SESSAO}" -H 'Content-Type: application/json' \
        -d "{\"col\":\"${DESTINO}\"}"; true)"
      printf '      PATCH %s %s -> %s -> %s\n' "$ID_CARTAO" "$COL_ANTES" "$DESTINO" "$ST"
      if [ "$ST" = "200" ]; then
        c_ok "movimento autorizado persiste"
      else
        c_bad "esperado 200, veio $ST"
      fi
      QUEM="$(curl -s -u "$BASIC_AUTH" "https://${DOMINIO}/api/audit?limit=10" \
        | python3 -c 'import sys,json; a=[l for l in json.load(sys.stdin) if l["action"]=="task_move"]; print(a[0]["token_label"] if a else "")' 2>/dev/null; true)"
      printf '      auditoria diz quem: %s\n' "${QUEM:-<vazio>}"
      if [ -n "$QUEM" ] && [ "$QUEM" != "unlock" ]; then
        c_ok "task_move auditado com o operador"
      else
        c_bad "task_move sem operador na auditoria (veio '${QUEM}')"
      fi
    else
      c_warn "board vazio — nenhum cartao para mover"
    fi
  else
    if ! escreve_ok; then
      pula_dry_run "PATCH de cartao (moveria tarefa e gravaria auditoria)"
    elif [ "$CRED_OK" = "sim" ]; then
      c_warn "sem token de sessao — pulei o PATCH autorizado"
    else
      c_warn "credencial do ingress nao provada no 3c — pulei o PATCH autorizado"
    fi
  fi

  # --- ciclo achado -> cartao ---------------------------------------------
  printf '\n  [8] cartao automatico a partir de achado\n'
  N_AUTO="$(sql "SELECT COUNT(*) FROM tasks WHERE origem='auto'"; true)"
  N_RESTART="$(sql "SELECT COUNT(*) FROM tasks WHERE origem='auto' AND finding_id LIKE 'restart_loop.%'"; true)"
  printf '      cartoes automaticos: %s (restart_loop: %s)\n' "${N_AUTO:-?}" "${N_RESTART:-?}"
  if [ "${N_RESTART:-0}" -gt 0 ]; then
    c_ok "restart_loop real gerou cartao"
  else
    c_warn "nenhum restart_loop aberto agora — sem cartao automatico a conferir"
    printf '        esperado numa VPS saudavel; nao e falha.\n'
  fi

  # oom NAO declara AUTO_TASK: ele suplanta restart_loop, e dois cartoes para o
  # mesmo problema e o que SUPERSEDES existe para evitar.
  N_OOM="$(sql "SELECT COUNT(*) FROM tasks WHERE origem='auto' AND finding_id LIKE 'oom.%'"; true)"
  if [ "${N_OOM:-0}" -eq 0 ]; then
    c_ok "achado supersedente (oom) nao gerou segundo cartao"
  else
    c_bad "existe cartao automatico de oom — AUTO_TASK ligado onde nao devia"
  fi

  # O indice unico parcial e a rede contra duplicacao no ciclo de 10s.
  DUP="$(sql "SELECT COUNT(*) FROM (SELECT finding_id FROM tasks WHERE origem='auto' AND finding_id IS NOT NULL GROUP BY finding_id HAVING COUNT(*) > 1)"; true)"
  if [ "${DUP:-0}" -eq 0 ]; then
    c_ok "nenhum achado com dois cartoes automaticos"
  else
    c_bad "${DUP} achado(s) com cartao duplicado — indice unico parcial nao pegou"
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

printf '\033[1mJanela de deploy do cockpit (v8 + v9) — modo: %s\033[0m\n' "$MODO"

preflight
if [ "$MODO" != "validacao" ]; then
  passo_env
  passo_nginx
  passo_subir
fi
if [ "$MODO" = "validacao" ]; then
  titulo "3b · Schema"
  checa_schema
fi
if [ "$MODO" = "dry-run" ]; then
  titulo "4 · Validacao"
  printf '  [dry-run] pulada por inteiro.\n'
  printf '  Os aceites afirmam estado POS-deploy (schema v9, token antigo negado,\n'
  printf '  unlock pelo ingress, SSE aberto). Rodar isso antes da janela so\n'
  printf '  produziria falhas que significam "ainda nao subiu".\n'
else
  # Ordem: primeiro o app tem de estar ouvindo, senao todo aceite interno
  # reprova por corrida com a subida. Depois a credencial, senao todo aceite via
  # ingress reprova por senha errada apontando o Remote-User. Os dois passos
  # existem para que uma falha adiante signifique o que diz significar.
  espera_app
  checa_credencial
  validar
  validar_board
fi
if [ "$MODO" = "completo" ]; then
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
printf '  NUNCA restaure cockpit-pre-v8v9.db para contornar: o esquema antigo devolve\n'
printf '  o furo do token estatico junto. Reexecute com --validate apos consertar.\n'
exit 1
