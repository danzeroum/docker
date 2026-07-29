# 00 · Registro de decisões de revisão

O que foi decidido durante a implementação, com o motivo. Leia antes de discordar de algo nos
outros documentos — vários pontos aqui **corrigem** a primeira versão deles.

## Estado

| Fase | PR | Situação |
|---|---|---|
| F0a — backend | [#3](https://github.com/danzeroum/docker/pull/3) | em produção |
| F0b — frontend | [#4](https://github.com/danzeroum/docker/pull/4) | em produção |
| F1 — visão geral | #5 | em produção |
| F2 — motor de achados | #6 | em produção |
| F3 — ingress & TLS | #7 | em produção |
| F5 — destravamento + auditoria | — | **antecipada** (ver abaixo) |
| F4 — capacidade | — | não iniciada |
| F6 — tempo real | — | não iniciada |

Pendências: `ack` (endpoint e tela) da F2 continua sendo a última fatia em aberto.

## F5 saiu fora de ordem

Destravamento (`X-Cockpit-Unlock`, TTL 30 min) e auditoria nasceram junto com o **gerenciador
de projetos** (não previsto no plano original): um scan de `/opt/btv/*/docker-compose.yml` com
start/stop de stack por HTTP. Como isso adicionou mutação de 12 stacks à superfície, o guard
da F5 teve de vir junto — não dava para expor stop de produção sem credencial.

Na mesma leva, as 4 rotas de mutação de container que estavam **abertas desde a F0a**
(`start/stop/restart`, `DELETE`) entraram sob o mesmo guard. A remoção do basic auth do app
("o ingress cuida") deixou de ser dívida latente e virou exposição ativa no instante em que a
mutação de stack foi adicionada — qualquer container em `btv-prod-net` alcançava os endpoints.

Guard único em `auth.require_unlock` (dependência FastAPI), compartilhado por `projects` e
`containers`; toda mutação grava em `audit`. Falta da F5: token com nota de motivo na UI e a
tela de auditoria — o backend já persiste, o frontend ainda não mostra.

Débito registrado: um header compartilhado injetado pelo ingress para todo `/api/*` continua
recomendado — o `require_unlock` cobre escrita, mas leitura (inspect, env mascarada) segue
alcançável de dentro da rede interna sem credencial.

## F3 — ingress & TLS, o que a produção revelou

- **13 hosts públicos + 1 interno** (`btv.buildtovalue.cloud`, que compartilha `server_name`
  com `localhost` e sustenta o healthcheck do gateway). Totais contam só públicos.
- Achados reais que o protótipo não previa: `docs_public` também em `juridico` (não só
  `criptotrade`); `http_plain` em dois hosts subiu para **crítico** ao confirmar-se tela de
  login (WordPress/CMS) — credencial trafega em texto claro.
- **Agregação**: `no_http2`, `no_gzip`, `body_size_default` são UM achado com N alvos, não N
  achados — senão a fila afoga com 13 linhas do mesmo conserto. `AGGREGATE = True` no módulo,
  id sem sufixo de alvo, alvos filtrados por `public_servers`.
- **Migração custou dado duas vezes**: a v3 com `SELECT *` embaralhou colunas e perdeu
  `first_seen` de achados em produção (corrigido em `4dd3699` com colunas explícitas). Regra
  nova: toda migração de esquema tem teste com banco populado antes do deploy.
- `stream_timeout` no `docker.danzeroum.com` é auto-diagnóstico: `proxy_read_timeout 60`
  corta o SSE de logs e o WS de stats do próprio cockpit.

## O `UNLOCK_TOKEN` estático era o furo, e o furo era maior que a env

O token de sessão da F5 **era** o `UNLOCK_TOKEN`: `POST /api/session/unlock` devolvia
`os.environ["UNLOCK_TOKEN"]` e `require_unlock` comparava o header com essa mesma env. Três
consequências que o diagnóstico "remova a env" não cobre sozinho:

- **O TTL de 30 min não protegia o token, só a janela.** Quem lesse a env uma vez (`docker
  inspect`, `/proc/1/environ`, backup do `.env`) tinha a credencial **para sempre** — bastava
  esperar qualquer operador destravar para ter 30 min de escrita em produção.
- **`unlock_state` nunca teve mais de uma linha.** `PRIMARY KEY (token)` + `INSERT OR REPLACE`
  sobre um valor constante = flag global liga/desliga, não sessão. Unlock de um operador
  reiniciava o prazo do outro.
- **A auditoria não sabia quem agiu.** Toda mutação gravava a string literal `"unlock"` em
  `token_label`, então a tela Auditoria mostrava "unlock" na coluna "quem" — o campo que o
  `06-telas-operacao.md` define como "usuário do basic auth do ingress".

Correção (**migration v8**): o token nasce em `secrets.token_urlsafe(32)` por sessão, o banco
guarda só `sha256` + `expires_at` explícito, e `require_unlock` valida **exclusivamente** contra
`unlock_state` — não existe mais comparação com configuração. Sessões concorrentes coexistem, e
`remote_user` da sessão vira o "quem" da auditoria.

**A v8 recria `unlock_state` vazia de propósito.** Migrar as linhas antigas preservaria
exatamente a credencial que a migração revoga. Isso é o oposto do defeito de v3/v5 (que
perderam `first_seen` sem querer) e por isso o teste de banco populado afirma as duas coisas ao
mesmo tempo: `findings`/`audit_log`/`host_samples` intactos, `unlock_state` zerada.

Achados de borda encontrados no mesmo caminho, todos com teste:

- `POST /findings/{id}/ack` era mutação **sem guard e sem auditoria** — violava a regra "toda
  mutação atrás de destravamento + auditoria". Agora exige unlock, valida `reason` contra as 3
  opções do modal e grava `motivo · prazo` na auditoria.
- `apiPost` montava `headers` **antes** de `...options`, então qualquer chamada que passasse
  `headers` apagava o `X-Cockpit-Unlock` e caía em 403.
- A tela Atenção chamava `apiPost(key, url, body)` passando o corpo como *options* do `fetch`:
  o ack ia sem corpo nenhum e voltava 422. O modal de silenciar nunca funcionou de ponta a ponta.
- O bloco nginx gerado por `setup-ingress.sh` nunca teve `proxy_set_header Remote-User` — com
  ele ausente o unlock responde 401 mesmo com CIDR correto. O script também não reescreve bloco
  existente (correto), então em produção o `proxy_read_timeout 60s` continuava lá: agora ele
  **diagnostica** o bloco existente em vez de passar em silêncio.

Runbook da janela em `08-janela-de-deploy.md` (encapsulado em `scripts/deploy-v8.sh`), com a
separação verificação × validação.

**Kill switch não volta como token.** Remover `UNLOCK_TOKEN` também removeu o efeito colateral
de "env vazia = ninguém escreve". Se essa capacidade for necessária de novo, ela é uma flag
booleana (`COCKPIT_READONLY=1`) que nega toda mutação — nunca um token em env. Um segredo em
configuração é credencial disfarçada de config, e é precisamente o que a v8 fechou. Hoje o
fail-closed é o `TRUSTED_GATEWAY_CIDR`; a flag ainda não está implementada.

---

## Correções à primeira versão do handoff

**1. CORS não pode derivar a origem da requisição.** `CORSMiddleware` é configurado no
startup; não existe `request` naquele ponto. E como o frontend é servido pelo próprio FastAPI,
é mesma origem: `allow_origins = ALLOWED_ORIGINS or []`.

**2. `psutil` estava travando o event loop.** `cpu_percent(interval=0.1)` dentro de rota async
custa 100 ms de loop parado por requisição. Resolvido com sampler em background usando
`asyncio.to_thread`, mais uma amostra síncrona antes do `yield` do lifespan — mover a chamada
para dentro de uma task **não** resolve sozinho, porque a task roda no mesmo loop.

**3. Nomes de token: os do repositório, não os do protótipo.** Importar `--sf`/`--txd`
obrigaria a reescrever os 12,8 KB de `components.css`. Mapeamento em `03-frontend.md`.

**4. Service worker precisava de mais que um bump.** Nome de cache gerado em runtime não força
reinstalação (o navegador compara bytes do arquivo) e ainda acumula caches órfãos. Solução:
versão estática, limpeza no `activate`, network-first, `skipWaiting()` + `clients.claim()`.

**5. Cache exige single-flight.** Sem lock por chave, 20 clientes no instante do vencimento
geram 20 fan-outs — exatamente o pico que o cache deveria evitar. O lock mora dentro da
entrada, para sumir junto na evicção LRU.

**6. Máscara de segredos tem quatro portas, não uma.** As duas rotas de inspect
(`/{id}` e `/{id}/json`), mais `Cmd`, `Entrypoint` e `Labels`. Em valores com forma de URI,
mascare só `user:senha@` e preserve host e path — senão você perde o diagnóstico de "está
apontando para o banco errado". Teste negativo obrigatório: `SITE_URL` e `LOG_LEVEL` **não**
podem ser mascarados; sobre-máscara é regressão que ninguém reporta.

**7. "24 testes" no critério da F0 era dado falso.** Veio da tela simulada do protótipo, não
do repositório. Use `pytest --collect-only -q`.

**8. São 11 telas, não 9.** Faltavam `#/tarefas` e o plantão mobile.

**9. Polling: um loop compartilhado que pausa com a aba oculta.** Não um `setInterval` por
tela.

---

## Aprendido durante a F2

**Janela de recência é obrigatória em regra baseada em estado.** A primeira versão da regra de
OOM produziu 5 críticos falsos: `State.ExitCode == 137` permanece no inspect de containers que
morreram semanas atrás e nunca mais subiram. Arqueologia apresentada como incidente aberto é
pior que ausência de achado — cinco críticos que o operador aprende a ignorar tornam o sexto
invisível. Toda regra de estado precisa perguntar "isso é agora?".

**`occurrences` era contagem de ciclos, não de acontecimentos.** "105 ocorrências" para um
problema contínuo observado 105 vezes em 17 minutos. Renomeado para `observations`, mantido
no banco para depuração e **nunca exibido**. Na tela vai duração (`last_seen - first_seen`) e,
quando fizer sentido, transições distintas.

**`SUPERSEDES` no motor, não `caused_by`.** `oom` e `restart_loop` disparam sempre juntos no
mesmo alvo — são dois sintomas de um problema, não dois problemas. A regra declara
`SUPERSEDES = ["restart_loop"]` e o motor suprime o suplantado no mesmo alvo, promovendo-o a
fato dentro do achado que sobrou. Serve de novo em `cert_expiring` × `cert_expired` e
`disk_pressure` × `disk_forecast`.

**Badge do rail:** conta as linhas de topo da fila (não o total do banco), cor pela maior
severidade aberta, e zero não desenha badge — nunca "0".

**Inicialização de estado falha alto.** `init_db` dentro de `try/except` largo derrubaria o
produto em silêncio; o certo é matar o startup. Aconteceu de verdade (`ProgrammingError:
You can only execute one statement at a time`) e o app entrou em laço de reinício — caso que
a própria regra `restart_loop` existe para pegar, e ninguém foi avisado. Ordem de resposta:
produzão de volta na `main` primeiro, diagnóstico depois.

**Cobertura do caminho de inicialização.** 24 testes verdes e nenhum chamava `init_db()`.
Teste de inicialização roda **duas vezes seguidas** — é a idempotência que falta quando o
banco fica meio criado.

---

## Motor de achados (F2) — decisões de desenho

**Ciclo de vida é do motor, não da regra.** A regra declara `DEBOUNCE` e `MIN_INTERVAL`;
anti-flapping, `first_seen` e dedupe são aplicados igualmente para todas. Treze regras
implementando cada uma a sua histerese = treze comportamentos e nenhuma previsibilidade.

**Causalidade por aresta declarada, não por proximidade.** Rejeitada a inferência por
`com.docker.compose.project` + rede: 12 dos 15 containers estão em `btv-prod-net`, então
co-participação de rede não informa nada, e dentro de um projeto a proximidade não diz qual
causa qual. Só valem arestas reais: upstream do nginx (F3), `depends_on` e volume
compartilhado (F2). Causalidade errada manda o operador começar pelo lugar errado com ar de
certeza.

**`_plain` fica.** Não é o texto técnico com outro escape — é outra frase para outro leitor
("exit 137" versus "o painel de trading parou"). Virou campo opcional com fallback para o
texto técnico; obrigatório só nas regras que chegam ao Resumo executivo.

**`ack` com select obrigatório** (`aceito_estrutural` / `monitorando` / `falso_positivo`) e
nota livre opcional — texto livre sozinho às 4h vira `asdf`. `falso_positivo` é contado por
regra e vira sinal na tela Backend & API.

**Loop próprio para as regras**, separado do sampler, mesmo intervalo de 10 s.

**Um banco só: `/data/cockpit.db`** (SQLite/aiosqlite, WAL, `schema_version` desde o primeiro
commit). Achados, séries da F4, tarefas e auditoria da F5 no mesmo arquivo — bancos separados
impediriam transação entre um achado e a tarefa que ele gera.

**Descoberta de regras por filesystem** (`app/findings/rules/*.py`), sem lista registrada.

---

## Decisões de arquitetura tomadas

**`EXEC` no socket-proxy: não.** Para ler o nginx, o arquivo é montado `:ro`. O `nginx.conf`
atual só tem um `include` (`mime.types`), então ler o arquivo dá o mesmo resultado que
`nginx -T`. Guarda a implementar: se o parser encontrar `include` fora de `mime.types`, emitir
achado "parse pode estar incompleto".

**`EVENTS: 1` e `SYSTEM: 1` habilitados já na F0a**, mesmo sem uso até F4/F6. São permissões
de leitura, e recriar o socket-proxy derruba o cockpit junto (`depends_on: service_healthy`) —
não vale uma segunda janela de manutenção.

**Montagem do ingress: `/opt/btv/ingress/nginx`, nunca o diretório pai.** O pai contém o
`.htpasswd` do gateway e do squad.

**Confiança do Remote-User por CIDR, não por IP fixo.** O header `Remote-User` é texto livre
que qualquer container em `btv-prod-net` pode forjar (`curl app:8000 -H "Remote-User: admin"`).
A correção original (exigir `X-Forwarded-For` junto) é igualmente forjável — o cliente escreve
os dois headers. A decisão: validar `request.client.host` contra o **CIDR da rede do ingress**
(`TRUSTED_GATEWAY_CIDR`). O IP do gateway muda a cada recriação do container; CIDR da rede
Docker é estável. Sem a env configurada o unlock nega com 403 (fail-closed) e loga o motivo.

**Certificados: job no host escrevendo metadados**, em vez de montar `/etc/letsencrypt` no
container. O cockpit nunca precisa de acesso de leitura a chave privada.

**Terminal web: permanece desligado, e `terminal.js` foi removido do frontend.** Decisão
consciente — com `POST` habilitado no socket-proxy, `exec` é o caminho mais curto entre um
cookie vazado e a VPS inteira. Se alguém reencontrar o endpoint atrás do `ENABLE_TERMINAL`,
isto aqui é a explicação.

**Padrão de alerta: híbrido.** Fila priorizada sempre visível; a faixa no topo só aparece
quando existe achado `critical`. O layout só se mexe quando é grave de verdade.

**Seletor de cenário: atrás de `?demo=1`.** Sai do caminho em produção e continua útil para
treinar plantonista.

---

## Mudanças quebradas de contrato

| Quando | O quê | Impacto |
|---|---|---|
| F0a (PR #3) | `/api/system`: `memory.used_gb/total_gb/free_gb` → `used/total/free` em bytes; mesmo padrão em `disks[]` | único consumidor (`system.js`) corrigido no mesmo PR. Script ou alerta externo batendo nesse endpoint quebra em silêncio |
| F0b (PR #4) | frontend migrado para módulos ES; `helpers.js`, `state.js`, `api.js`, `containers.js`, `system.js`, `logs.js`, `stats.js`, `terminal.js` removidos | qualquer patch local sobre esses arquivos precisa ser reescrito |

---

## Bug preexistente encontrado na revisão

`system.js` chamava `fmtBytes(sys.memory.used)` enquanto a API devolvia `used_gb` — os
subtítulos de memória e disco renderizavam "—" desde sempre. Corrigido junto da padronização
de unidades da F0a.
