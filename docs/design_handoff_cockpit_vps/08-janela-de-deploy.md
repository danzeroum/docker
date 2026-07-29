# 08 · Janela de deploy — pre-F5 → F6 + v8

Producao esta pre-F5 e o `.env` de producao ainda tem `UNLOCK_TOKEN`. Uma janela resolve
as duas coisas. Nomes: servico compose = `app`, container = `docker-cockpit`.

**Verificacao** (os 125+13 testes passam) ja esta feita no CI e nao diz nada sobre a rede real.
**Validacao** (o gate de escrita e seguro na rede de producao) so acontece aqui, na VPS, e e
o que esta seccao cobre. Nao pule a parte 3.

---

## Atalho: `scripts/deploy-v8.sh`

A janela inteira esta encapsulada, idempotente e na ordem certa:

```bash
cd /opt/btv/docker                       # diretorio do compose do cockpit
export BASIC_AUTH="admin:SENHA"          # necessario para os testes via ingress

bash scripts/deploy-v8.sh --dry-run      # mostra o que faria
bash scripts/deploy-v8.sh                # janela completa
bash scripts/deploy-v8.sh --validate     # so revalida, sem tocar em nada
```

O script para antes de subir se o bloco nginx nao atender, e nunca reescreve o `nginx.conf`
de producao — imprime o `location /` correto e sai. O resto deste documento e o passo a passo
manual equivalente, para quando voce quiser conduzir a mao.

---

## 0 · Antes de mexer

```bash
# backup do banco — a v8 recria unlock_state e nao ha volta automatica
docker cp docker-cockpit:/data/cockpit.db ./cockpit-pre-v8.db

# estado atual, para comparar depois
docker exec docker-cockpit env | grep -E 'UNLOCK|TRUSTED'
```

Registre o resultado do `grep`: e o diagnostico do bloqueio. `UNLOCK_TOKEN=<algo>` presente
confirma o furo; `TRUSTED_GATEWAY_CIDR` ausente confirma que o unlock esta negando tudo.
Guarde o valor de `UNLOCK_TOKEN` antes de apaga-lo — e o payload do aceite 5.1.

O backup e rede de seguranca para **cockpit inoperante**, e nada mais. Se a validacao de rede
falhar, o conserto e o CIDR ou o bloco nginx; restaurar o banco devolve o esquema antigo **e o
furo junto**.

---

## 1 · Fechar o furo do UNLOCK_TOKEN

O token estatico deixou de ser aceito no codigo (v8), mas a env continua vazando um segredo
para `docker inspect`, `/proc/1/environ` e qualquer backup do `.env`. Remova.

```bash
cd /opt/btv/docker            # ajuste para o diretorio do compose do cockpit
sed -i '/^UNLOCK_TOKEN=/d' .env
grep -c UNLOCK_TOKEN .env     # tem de imprimir 0
```

## 2 · TRUSTED_GATEWAY_CIDR com a subnet real

Sem isso o unlock nega **tudo** com 403 — fail-closed por desenho, e a causa mais provavel de
"destravar nao funciona" depois do deploy.

```bash
SUBNET=$(docker network inspect btv-prod-net \
  --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')
echo "subnet real: $SUBNET"

# grava (substitui se ja existir)
if grep -q '^TRUSTED_GATEWAY_CIDR=' .env; then
  sed -i "s|^TRUSTED_GATEWAY_CIDR=.*|TRUSTED_GATEWAY_CIDR=${SUBNET}|" .env
else
  echo "TRUSTED_GATEWAY_CIDR=${SUBNET}" >> .env
fi
```

Confira que o IP do gateway cai dentro dela — e o `request.client.host` que o app vai ver:

```bash
docker inspect btv-nginx-prod \
  --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}'
```

O valor de `.env.example` (`172.19.0.0/16`) e exemplo. Nao presuma que confere.

## 3 · nginx: SSE e Remote-User no bloco `docker.danzeroum.com`

Duas coisas quebradas no bloco atual:

- `proxy_read_timeout 60s` corta o SSE da F6 a cada minuto — e o proprio cockpit disparando
  `stream_timeout` contra si mesmo;
- falta `proxy_set_header Remote-User` — sem ele `POST /api/session/unlock` responde **401** e
  nenhuma mutacao e possivel pelo painel, mesmo com o CIDR certo.

`scripts/setup-ingress.sh` **nao reescreve bloco existente** (de proposito). Rode-o para o
diagnostico e edite a mao:

```bash
bash scripts/setup-ingress.sh          # lista o que falta no bloco existente
```

O `location /` deve ficar assim:

```nginx
location / {
    set $upstream "http://docker-cockpit:8000";
    proxy_pass $upstream;

    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Remote-User       $remote_user;   # identidade do basic auth

    proxy_http_version 1.1;                            # SSE da F6
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

```bash
docker exec btv-nginx-prod nginx -t
docker exec btv-nginx-prod nginx -s reload
```

## 4 · Subir

**So o servico `app`.** Recriar o socket-proxy derruba o cockpit junto
(`depends_on: service_healthy`) e custa uma segunda janela.

```bash
docker compose config -q
docker compose up -d --build app
docker compose logs -f app | head -40      # a v8 aplica no startup
```

`init_db` falha alto de proposito: se a migration quebrar, o container reinicia em laco em vez
de subir com banco meio migrado. Nesse caso: restaure `pre-v8.db` e volte a imagem anterior
antes de diagnosticar.

---

## 5 · Validacao — os quatro aceites

### 5.1 Token estatico nao abre mais nada

```bash
TOKEN_ANTIGO='<o valor que estava em UNLOCK_TOKEN>'
docker exec docker-cockpit python3 -c "
import urllib.request as u
r = u.Request('http://localhost:8000/api/containers/docker-cockpit/restart',
              method='POST', headers={'X-Cockpit-Unlock': '$TOKEN_ANTIGO'})
try: print(u.urlopen(r).status)
except Exception as e: print(getattr(e, 'code', e))
"
```

**Esperado: 403.** Um 200 aqui significa que a imagem antiga ainda esta rodando.

### 5.2 Unlock so pelo ingress

```bash
# pelo ingress, com basic auth → 200 + token de sessao
curl -s -u admin:SENHA -X POST https://docker.danzeroum.com/api/session/unlock \
     -H 'Content-Type: application/json' -d '{"motivo":"janela de deploy"}' -w '\n%{http_code}\n'

# direto no app, de dentro da rede, sem passar pelo gateway → 401
docker run --rm --network btv-prod-net curlimages/curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://docker-cockpit:8000/api/session/unlock \
  -H 'Content-Type: application/json' -d '{}'
```

**Esperado: 200 e 401.** Os dois tokens de duas chamadas seguidas tem de ser **diferentes** —
se forem iguais, ainda ha valor derivado de config em algum lugar.

Se o ingress der 401 com credencial certa, e o `Remote-User` do passo 3.
Se der 403 "origem nao autorizada", e o CIDR do passo 2.

### 5.3 SSE nao cai a cada minuto

```bash
curl -N -u admin:SENHA https://docker.danzeroum.com/events   # deixe rodando > 3 min
```

Sem reconexao a cada 60 s. Em seguida o achado `stream_timeout` de `docker.danzeroum.com` deve
resolver sozinho no proximo ciclo do motor (10 s).

### 5.4 ack sai da fila e aparece na auditoria

Caso canonico: os dois `healthcheck_never_passed` do criptotrade.

```bash
TOK=$(curl -s -u admin:SENHA -X POST https://docker.danzeroum.com/api/session/unlock \
      -H 'Content-Type: application/json' -d '{"motivo":"ack pos-deploy"}' \
      | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')

ID=$(curl -s -u admin:SENHA 'https://docker.danzeroum.com/api/findings?status=open' \
     | python3 -c 'import sys,json; print([f["id"] for f in json.load(sys.stdin) if f["rule"]=="healthcheck_never_passed"][0])')

curl -s -u admin:SENHA -X POST "https://docker.danzeroum.com/api/findings/$ID/ack" \
     -H "X-Cockpit-Unlock: $TOK" -H 'Content-Type: application/json' \
     -d '{"reason":"monitorando","note":"sonda na porta errada","until":"24h"}'

curl -s -u admin:SENHA 'https://docker.danzeroum.com/api/findings?status=open' | grep -c "$ID"   # 0
curl -s -u admin:SENHA 'https://docker.danzeroum.com/api/audit?limit=5'                          # linha ack
```

A linha de auditoria tem de trazer **o usuario do basic auth** em `token_label` — nao a string
`unlock`, que era o comportamento anterior.

---

## 6 · Testes de fumaca da F4/F6

```bash
# host_samples cresce entre dois minutos (F4 coletando)
for i in 1 2; do
  docker exec docker-cockpit python3 -c \
    "import sqlite3;print(sqlite3.connect('/data/cockpit.db').execute('SELECT COUNT(*) FROM host_samples').fetchone()[0])"
  sleep 65
done
```

- Tela **Capacidade** no primeiro deploy: "coletando desde hoje", **sem projecao**. Correto,
  nao e bug — menos de 7 dias de serie.
- `docker stop` de um container de teste: a Visao geral reflete em **< 2 s** sem F5 no
  navegador (SSE da F6). Se so mudar depois de ~30 s, o SSE caiu para o polling de
  reconciliacao — volte ao passo 3.

## 7 · Teste negativo do fail-closed

Vale rodar uma vez, para ver o guard negando por conta propria:

```bash
cp .env .env.bak
sed -i '/^TRUSTED_GATEWAY_CIDR=/d' .env
docker compose up -d app

# qualquer unlock, mesmo pelo ingress com credencial certa
curl -s -o /dev/null -w '%{http_code}\n' -u admin:SENHA \
  -X POST https://docker.danzeroum.com/api/session/unlock \
  -H 'Content-Type: application/json' -d '{}'          # esperado: 403

docker compose logs --tail 20 app | grep -i "nao configurado"

cp .env.bak .env
docker compose up -d app
```

Config ausente nega e loga — nunca libera. Se esse teste devolver 200, o fail-closed quebrou e
a janela nao deve seguir.

---

## 8 · Rollback

**Falha de validacao de rede nao e caso de rollback.** 401 no unlock via ingress e
`Remote-User` (passo 3); 403 "origem nao autorizada" e o CIDR (passo 2). Conserte a config e
rode `bash scripts/deploy-v8.sh --validate` de novo.

Restaurar o banco so se o cockpit estiver **inoperante**:

```bash
docker compose down app
docker cp ./cockpit-pre-v8.db docker-cockpit:/data/cockpit.db
# suba a imagem anterior
```

A v8 nao tem downgrade automatico: ela recria `unlock_state` vazia. Restaurar o backup devolve
o esquema antigo **e o furo do token estatico junto** — e a janela precisa ser refeita inteira
em seguida, nao adiada.

---

## Kill switch

`UNLOCK_TOKEN` **nao volta** como kill switch. Se a necessidade de "travar tudo" reaparecer, a
forma decidida e uma flag booleana (`COCKPIT_READONLY=1`) que nega toda mutacao — nunca um
token em env, que e credencial disfarcada de configuracao e foi exatamente o defeito que a v8
fechou. Ainda nao implementada; hoje o fail-closed e o `TRUSTED_GATEWAY_CIDR`.
