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
| F5 — destravamento + auditoria + 4 UIs de operação | #7 (F5) | em produção na `main` |
| F4 — capacidade | — | **concluída** (coletor 60s, history+OLS, capacity, tela real) |
| F6 — tempo real | — | **concluída** (SSE /events fan-out único, telemetria por rota-template, ⌘K ampliada) |

| Sprint 1 — B1/B2/B4 | [#25](https://github.com/danzeroum/docker/pull/25) | na `main` |
| Sprint 2a — fundação do Cockpit Vivo | [#26](https://github.com/danzeroum/docker/pull/26) | na `main` |
| Sprint 2b — B3 + B10 residuais | [#27](https://github.com/danzeroum/docker/pull/27) | na `main` |

Pendências: deploy na VPS (validar `TRUSTED_GATEWAY_CIDR` real + `ack`/`unlock` end-to-end).

## Decisões da Sprint 2b

Quatro decisões que passam a valer como regra. Cada uma com o porquê em uma
frase — quem ler isto daqui a seis meses não terá tido esta conversa.

**(a) A auditoria-antes cobre também `projects.py`.** · dev, ratificado pelo
revisor · 2026-07-30
O bloco citava só `_mutate_container`, mas é `projects.py` que roda
`docker compose up` com timeout de 60 s — o candidato número 1 a travar, e
portanto o que mais precisa da linha `running` órfã. Cumprir a letra deixando-o
de fora contradiria o motivo da regra.

**(b) O prune remove SÓ imagem dangling.** · dev, elevado a princípio pelo
revisor · 2026-07-30
Recuperar espaço não pode destruir o que não se reconstrói: volume órfão guarda
**dado** e container parado há 8 dias pode ser religado na segunda. Imagem sem
tag é a única categoria em que a remoção é reversível na prática.
**Remoção de volume ou container órfão é pedido próprio, opt-in, e fica fora de
qualquer housekeeping automático.** Registrado aqui explicitamente porque sem
isso algum "melhorar o prune" bem-intencionado de uma sprint futura reintroduz
exatamente o que foi recusado com razão.

**(c) `die` com exit 0 é `info`, não `warn`.** · dev · 2026-07-30
`docker stop` emite `die` com exit 0 — parada limpa, pedida por alguém. Marcar
isso como alerta encheria a timeline de alarme falso toda vez que o operador
desliga um serviço, e alarme que sempre toca deixa de ser lido. Só `die` com
exit != 0 e `oom` são críticos.

**(d) Ao fechar a Sprint 3, executar o roteiro do doc 12 INTEIRO contra dados
reais e registrar o resultado datado aqui.** · revisor · 2026-07-30
É a primeira execução integral do critério de aceitação do conjunto: cenário API
caindo → subtela → buscar `oom` → destravar → reiniciar → auditoria → chip Drift
→ Personalizar. Até a Sprint 2b o roteiro fecha em tudo menos o `buscar oom`,
que é o B5.

## Sprint 3 — roteiro do doc 12, execução contra dados reais

· dev · pendente de execução na VPS

O item (d) das decisões da 2b. Com o B5 na tela, o roteiro executa inteiro pela
primeira vez. Estado de cada passo **no código** (verificado por teste
automatizado; a execução manual na VPS é o que falta):

| Passo do roteiro | Estado |
|---|---|
| Cenário API caindo → faixa crítica + achado | ✅ |
| Subtela do container → métricas em serra | ✅ sparklines de `/api/containers/{id}/history`, toggle 24h/7d |
| Subtela → eventos die→start | ✅ timeline filtrada no servidor por container |
| **Subtela → buscar `oom` nos logs** | ✅ **B5, esta sprint** — índice FTS5, highlight, `<script>` sai como texto |
| Destravar → reiniciar → auditoria | ✅ com auditoria gravada antes de executar |
| Esc → chip Drift na régua | ⏳ o chip se cala enquanto o B8 não tem fonte (`drift.count: null`) |
| Personalizar → arrastar, presets, restaurar | ✅ |

**O que falta para fechar o item (d):** rodar o roteiro na VPS, com os 15
containers reais, e registrar aqui o resultado datado. Só isso transforma
"passa nos testes" em "executa contra dados reais", que é o que o critério de
aceitação do conjunto pede.

O chip Drift é ausência esperada, não falha: ele não aparece porque não há
fonte, e chip sem fonte seria dado inventado (doc 01). Fecha na Sprint 5 com o
B8.

## Regra nova: versão de schema não se escreve como literal em teste

· dev + revisor · 2026-07-30

O mesmo erro apareceu **três vezes em duas sprints** — a terceira num teste
escrito por quem já o tinha corrigido nas outras duas. Quando um erro sobrevive
a quem já o consertou, o problema não é atenção.

`tests/test_guarda_schema_literal.py` é a versão executável da correção: varre
`tests/` e falha apontando arquivo:linha, com a correção na mensagem. Fixture
que monta banco numa versão antiga de propósito tem escape por marcador
comentado **com motivo** (`# schema-literal-ok: <motivo>`) — por marcador e não
por caminho, para a próxima fixture nascer documentando por que pode em vez de
herdar isenção por morar na pasta certa.

A quarta ocorrência morre no CI, não na revisão.

## Aprendido na revisão do unlock (migration v8)

**O `UNLOCK_TOKEN` estático não contornava o token de sessão — ele ERA o token de sessão.** O
endpoint devolvia a env e o guard comparava contra ela. TTL de 30 min protegia a janela, nunca
a credencial; `unlock_state` era flag global, não sessão; a auditoria gravava a string `"unlock"`
onde devia estar o operador.

Correção: token por sessão, `sha256` no banco, guard validando **só** contra `unlock_state` —
sem nenhuma comparação com configuração. A v8 recria a tabela **vazia de propósito**: migrar as
linhas preservaria a credencial que a migração revoga. Sem downgrade — restaurar backup devolve
o furo.

**Corolário:** kill switch nunca é credencial reciclada. Se for preciso um freio global, é uma
flag booleana explícita (`COCKPIT_READONLY=1` negando todo unlock), nunca um token em env — token
compartilhado é exatamente o defeito que a v8 removeu.

**Um caminho de mutação sem guard passa por 125 testes verdes.** O `ack` era mutação sem unlock
e sem auditoria, e o modal de silenciar nunca funcionou end-to-end (corpo enviado como *options*
do `fetch` → 422). Toda rota de escrita nova precisa de teste de guard **e** de um end-to-end.

## Aprendido durante a F6

**Uma conexão ao daemon, fan-out para os clientes.** Um `/events` por cliente multiplicaria a
carga que a fase elimina — mesmo padrão do sampler (4,4s → 21ms). Backoff exponencial
(1→30s), reset em 200; sem EVENTS no proxy, o painel explica o que habilitar e o resto vive.

**Telemetria por rota-TEMPLATE, nunca path cru** — `/containers/{id}` como uma série, não mil.

**⌘K busca containers, hosts, achados e projetos a partir do cache** (com estado "carregando
fontes…"); seleção navega, nenhuma mutação pela paleta. É a resposta direta à queixa
original de navegabilidade.

## Aprendido durante a F4

**Projeção só fala quando o dado sustenta.** `r² < 0.7` → "tendência instável", sem data;
menos de 7 dias de coleta → "coletando desde X", sem projetar. Projeção bonita sobre 3 pontos
é o pior resultado possível num painel de operação.

**Todo item de postura carrega `source` verificável** (finding, cert, sample, inspect). O item
"CVEs" foi removido por não ter fonte — virou "containers com reinício frequente (≥5)", lido
de `RestartCount`. Mesma regra da latência por salto e da disponibilidade 30d: sem fonte, o
campo sai.

**Migration com banco populado é teste obrigatório** (v6 testada com findings + audit +
unlock preexistentes). O fresh-db nunca falhou neste projeto; o populado pegou a v3 e a v5.

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


## Sprint 2a aprovada + 2b autorizada (2026-07-30)

- **2a merged**: kernel de módulos + `app/summary.py` (`montar()`/`aquecer_loop()`/`peek`) com
  `capabilities.actions_enabled`; `main.js` sem o switch de rotas (18 módulos; órfão
  `projetos` anotado); dívidas pagas: sw.js v3, `mod-linha`→`mod-item`, follow SSE; 8 testes
  migrados. Correções do dev à spec (capacity nas fontes certas, `stacks` sem subprocessos
  por poll, `aquecer_loop` para chip de módulo oculto) aceitas como melhorias legítimas —
  viabilizam o invariante 3 (chip vivo).
- **`certs_expiring`/`cert_window_days` = backlog de fonte**: ou o certbot entra montado
  read-only numa sprint futura, ou a chave sai do contrato — decisão na Sprint 5 junto do
  B11. Até lá a UI degrada com "—"; nunca inventa prazo.
- **Regra do "mesmo commit"** (doc 14 do dev, §15): inversão do padrão `ENABLE_ACTIONS`→0
  no código + pin `=1` explícito no compose de produção no MESMO commit — nenhum estado
  intermediário onde produção perde ações ou instalação nova nasce aberta.
- **v11** (ring de eventos 10k no ciclo de retenção da v10) e **v12** (audit grava "started"
  ANTES de executar; entrada órfã é rastro legítimo de travamento — nunca limpar): a regra
  deste doc de migration só com teste de banco populado subiu de lembrete para aceite.
- **UX do prune virou contrato**: a confirmação sempre parte da lista do dry-run — o
  protótipo `Cockpit Vivo Completo.dc.html` foi atualizado para exigir dry-run antes do
  prune real.
- `summary.events` via `peek`: o chip do módulo Eventos oculto nasce junto com a fonte.
- Pós-2b, o roteiro do doc 12 executa contra dados reais, exceto a busca `oom` (B5, Sprint 3).


## Decisões da Sprint 4

· dev · 2026-07-30 · pendentes de validação do revisor

**(a) `/metrics` autentica no app, e não só no ingress.** O bloco 4-B9 pedia "o
mesmo basic auth do app". O app não tem basic auth — ela vive no nginx, e a
dívida já estava registrada aqui. Mas `/metrics` é exatamente a rota que o
scraper busca **direto** em `http://docker-cockpit:8000/metrics`, sem passar
pelo ingress: herdar a proteção do nginx significaria não ter proteção nenhuma.
A verificação passou a ser no app, contra `BASIC_AUTH_USER`/`BASIC_AUTH_PASS`,
com `compare_digest` nos dois campos. Sem as env: **503, não 200** — instalação
que esqueceu de configurar não publica o inventário de containers.

**(b) Container parado sai com `estado=0`, a série não desaparece.** Série que
some entre scrapes dispara `absent()` no alertmanager a cada `docker compose
up`. O `0` é a afirmação "medi e está parado"; a ausência seria "não sei", e as
duas acordam pessoas diferentes.

Pelo mesmo raciocínio invertido: container **sem healthcheck** não ganha série
de saúde. `0` ali afirmaria saúde onde não há medida.

**(c) Labels só `name` e `image`.** Id de container como label incha o TSDB a
cada recreate — séries novas que nunca mais recebem amostra ficam na memória até
o retention. Há teste que varre a exposição e falha em qualquer chave fora
dessas duas.

**(d) Imagem desatualizada compara DIGEST, nunca nome de tag.** `nginx:1.25`
local e remoto têm o mesmo nome sempre, inclusive depois de a tag ser
republicada — que é o caso que a verificação existe para pegar. `latest` é o
extremo: nome imutável, conteúdo semanal.

**(e) `pendente` é um estado, e existe só para o 429.** Uma VPS com 20 imagens
estoura o rate limit anônimo do Hub com facilidade. Marcar tudo como
`desconhecido` na primeira negativa apagaria o resultado bom que já estava no
banco; `pendente` preserva o digest remoto conhecido e tenta amanhã.

**(f) Imagem construída localmente fica FORA da listagem**, e não dentro como
`desconhecido`. Registry privado idem. O operador não tem o que fazer com essas
linhas, e uma lista com 12 "desconhecido" esconde as 2 que importam.

**(g) `summary.updates` e `summary.notifications` são `null` quando o job nunca
rodou** — mesmo padrão de `certs_expiring`, agora aplicado três vezes. Zero
afirma "nada desatualizado" / "nada digno de nota"; a verdade pode ser "o job
não rodou" ou "nenhum canal está configurado". Sem summary, sem selo na tela.

**(h) `die` com exit 0 NUNCA notifica** — a decisão da 2b agora tem uma segunda
implementação e um segundo teste. `docker stop` emite `die` com exit 0, e um
alerta a cada parada pedida por alguém treina o operador a ignorar o canal.
Exit **vazio** também não notifica: é o daemon não tendo informado, e não dá
para afirmar falha.

**(i) Dedup de notificação é PERSISTIDO (v15), por `(regra, alvo)`.** Em
memória ele sumiria no restart — e o restart é exatamente quando tudo reavalia
junto: o stream reconecta, o sampler colhe a primeira amostra e o job de imagens
roda. Por par e não por regra: dois containers em crash loop são dois
incidentes.

**(j) Falha total de entrega NÃO abre a janela de silêncio.** Se nenhum canal
aceitou, o operador não recebeu nada; deduplicar ali trocaria o alerta por 30
min de silêncio. A tentativa é gravada mesmo assim — canal quebrado e ausência
de problema não podem ter a mesma aparência.

**(k) Segredo jamais em log ou banco.** A URL do webhook do Discord **é** a
credencial, e `str(exc)` do httpx a imprime. O motivo gravado é curto e sem URL
(`rede: ConnectError`, `HTTP 500`). Há teste que passa a URL inteira por dentro
de um erro e varre a linha gravada e o retorno da função atrás dela.

**(l) Fila entre detecção e entrega, com teto.** A detecção roda dentro do
`async for` do stream de eventos; um webhook lento ali seguraria a timeline
inteira. Fila cheia **descarta** em vez de bloquear: um crash loop gera centenas
de `die` por minuto, e travar o stream para entregar todos seria trocar a
timeline por notificação.

**(m) `brute_force` está reservada, não implementada.** O nome existe no motor e
no dedup para a regra entrar no B11 sem migração de banco nem mudança de
contrato na tela. Um teste conta as ocorrências e falha se alguém a ligar antes
da hora.

**Mensagem enviada:** host, alvo, regra, instante — e, quando existe, um detalhe
curto escrito pelo próprio motor (um exit code, um percentual). Nunca payload
bruto: inspect e log passam por env, cmdline e header, e um webhook de chat é o
lugar menos controlado por onde esse conteúdo poderia sair. Há teste que lê a
função pelo AST — só o código, sem a prosa que explica a regra.

**Continua pendente:** o item (d) das decisões da 2b (rodar o roteiro do doc 12
na VPS, com os 15 containers reais). É trabalho de quem opera a VPS, e o bloco
`4-runbook` é dele.
