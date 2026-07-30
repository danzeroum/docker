# 09 · Blocos agregados — o que fica depois da F6

Compilação validada contra o repositório real, não contra o protótipo. Vários itens da
proposta original já existiam em produção; este documento registra o que **de fato** faltava,
o que foi entregue e o que sobra.

Leia junto com `00-decisoes-de-revisao.md` (as regras que corrigem os outros documentos) e
`../../design_handoff_cockpit_vps/05-prompt-para-o-desenvolvedor.md` (as regras inegociáveis:
sem framework novo, zero dado fixo no frontend, campo sem fonte real sai da tela).

O roadmap que continua daqui, já cruzado com a face de interface dos docs 10/11/12, está em
`14-plano-consolidado.md` — inclusive os dois pré-requisitos de fundação que a Sprint 2
assume e que ainda não existem (registro de módulos e bloco `summary`).

## Correções à proposta original

A proposta presumia um cockpit "FastAPI + httpx" cru. Não é o caso, e três premissas caíram:

| Premissa da proposta | Realidade no repo |
|---|---|
| "B2 cria a infra SQLite/scheduler que os demais usam" | Já existia: `app/db.py` (9 migrations), `app/sampler.py` (coletor de 60 s), `host_samples`/`container_samples` desde a v6, `purge_samples` com 30 d, `GET /api/metrics/history`, `GET /api/capacity` |
| "liberar `VOLUMES=1` e `/system/df` no proxy" | `docker-compose.yml` já concede `CONTAINERS/IMAGES/INFO/NETWORKS/VOLUMES/EVENTS/SYSTEM/POST/DELETE: 1`. **Nenhuma mudança no socket-proxy foi necessária** |
| "B3 requer `EVENTS=1`" | Já concedido, e o stream já existe (`app/events.py`, `GET /api/events/stream`), com backoff e invalidação de cache |

Consequência prática: a Sprint 1 deixou de ser "construir a infraestrutura" e passou a ser
"fechar as lacunas reais dela". O que faltava mesmo era retenção em dois níveis, leitura por
container, e os dois endpoints novos.

## Entregue nesta sprint

### B2 — retenção em dois níveis e histórico por container
Migration **v10**: `container_samples_hourly` + índice `(container_id, sampled_at)`.

- O índice existe porque a PK da v6 é `(sampled_at, container_id)` — serve a escrita e o purge
  por tempo, mas perguntar "histórico do container X" com ela varre a tabela inteira.
- Raw a cada 60 s por 30 dias são ~43 mil linhas **por container**: o banco cresce justamente
  no disco que o B1 monitora. Raw agora vive `RETENTION_RAW_HOURS` (24 h) e o que passa disso
  sobrevive agregado em `RETENTION_ROLLUP_DAYS` (30 d).
- `host_samples` ficou **fora** dos dois níveis, de propósito: é a fonte da projeção por
  mínimos quadrados da F4, que precisa de 30 dias de série. Cortar o raw dela em 24 h mataria
  `/api/metrics/history` sem erro nenhum — falha silenciosa, o modo de errar mais caro daqui.
- `rollup_container_samples()` roda **antes** de `purge_samples()`, sempre. A primeira passada
  após o boot usa a janela cheia do raw, para cobrir as horas em que o cockpit esteve fora.
- `GET /api/containers/{id}/history?range=24h` — resolução (`raw`/`hourly`) vai no payload,
  porque apresentar média horária como se fosse leitura de 60 s é mentir sobre a medida.
  Downsampling com teto de 500 pontos preservando o **último ponto real**, não uma média que
  suaviza justamente o pico que o operador abriu a tela para ver.
- `range` fora do formato responde **422**, não 24 h por omissão: adivinhar faria a tela
  rotular uma janela que ninguém pediu.

### B1 — `GET /api/storage`
`app/routers/storage.py`. Agrega `/system/df` + `/containers/json?all=1`, cache de 30 s.

- Volume órfão é decidido por `Mounts` de `/containers/json?all=1`, **não** pelo `RefCount` do
  `/system/df`: o RefCount conta referência viva, e um volume preso a container parado
  apareceria como órfão — apagar seria perder o dado do serviço que o operador só desligou.
- Seções vazias vêm como `null` (não `[]`) do daemon; normalizadas, senão um host limpo estoura
  com `TypeError` — exatamente o caso de borda do aceite.
- Build cache fica **fora** do `reclaimable_bytes`: `docker builder prune` é outro comando com
  outro risco, e somar os dois faria a tela prometer espaço que um `image prune` não entrega.
- Proxy fora do ar → **503** com motivo legível. A tela precisa distinguir "não consegui
  perguntar" de "perguntei e o host está vazio".

### B4 — `GET /api/security` + saúde explícita na listagem
`app/routers/security.py`. Regras como **dados** (`CHECKS`), não `if` encadeado — a lista cresce
(a do motor F2 já passou de 17) e o ponto de extensão tem de ser "acrescentar uma linha".

Score `100 − Σ peso` (crítica 30, alta 15, média 5). Seis regras: `docker_socket_mounted`,
`privileged`, `network_host`, `cap_add_dangerous`, `run_as_root`, `no_memory_limit`.

- Fonte é o inspect que o `sampler` já coleta. Zero chamada extra ao daemon — avaliar 15
  containers por inspect próprio custaria ~18 s (regra 5 do prompt do desenvolvedor).
- Socket montado é detectado em `HostConfig.Binds` **e** em `Mounts`: compose popula o segundo,
  e olhar só o primeiro deixaria passar o caminho mais comum nesta infraestrutura.
- `/api/containers` ganhou campo `Health` explícito. O frontend farejava
  `Status.includes('unhealthy')` — texto de UI do daemon, que muda de formato entre versões.
  O sniff ficou como fallback para o boot, antes do coletor preencher o inspect.
- **Sem healthcheck é `null`, não "saudável".** Ausência de medida não é saúde confirmada, e
  container sem healthcheck não ganha selo na listagem.

### Fora do escopo, corrigido no caminho
- `db.SCHEMA_VERSION` derivado de `_MIGRATIONS[-1][0]`. Quatro testes afirmavam `== 9`
  literal e quebraram juntos com a v10; eles queriam dizer "banco totalmente migrado".
- `tests/fixtures/renderiza_telas.mjs` fixava `2026-07-28` e o teste cobrava o texto
  renderizado "há 1d" — concordavam só no dia em que a fixture foi escrita. Passou a falhar
  sozinho quando o calendário virou. Datas agora derivam de `Date.now()`, como a tela.

## O que sobra

Ordem por dependência. `EVENTS=1` e `VOLUMES=1` já estão concedidos, então nenhum bloco abaixo
pede mudança no socket-proxy — **exceto o B10**.

| # | Bloco | Fonte | Persistência | Observação |
|---|---|---|---|---|
| B3 | Timeline de eventos persistida (ring 10k) + filtro no servidor | `/events` | SQLite | O stream SSE já existe; falta **persistir e consultar**. Nenhum doc descrevia isso |
| B5 | Busca full-text em logs (FTS5) + follow | `/containers/{id}/logs` | SQLite FTS5 | Ingestão (histórico) separada do follow (direto do daemon): gravar todo follow dobraria o I/O sem valor |
| B6 | Imagem desatualizada por digest | Docker Hub API | SQLite (24 h) | Comparar por digest, não por nome de tag. 429 do Hub é o caso central: 20 imagens estouram o limite anônimo |
| B7 | Notificações Telegram/Discord/Slack | eventos internos | SQLite | Dedup por `(regra, alvo)`, não global — um crash loop não pode calar o alerta de disco cheio |
| B9 | `/metrics` Prometheus | cache do sampler | — | Estado `0` em vez de a série desaparecer, senão o `absent()` do alertmanager dispara falso a cada recreate. Sem label de alta cardinalidade |
| B8 | Drift detection (compose vs runtime) | labels + compose files | — | Só chaves declaradas no YAML; `${VAR}` não resolvida sinaliza "não avaliado". `/opt/btv` já está montado `:ro` |
| B11 | Hardening: rate-limit no auth, backup do SQLite, gzip | — | — | `X-Forwarded-For` validado contra o gateway, senão o rate-limit por IP bloqueia o ingress inteiro. Backup pela API do SQLite, não `cp` de arquivo quente |
| B10 | Ações opt-in (restart/stop/prune) com auditoria | POST no proxy | SQLite | **Único que muda o proxy.** Ver abaixo |

### B10 e o read-only

Vale registrar que a superfície de mutação **já existe** e já está sob guarda: `start`, `stop`,
`restart`, `DELETE` de container e start/stop de stack passam por `auth.require_unlock` e vão
para `audit_log` (F5, antecipada). `POST: 1` e `DELETE: 1` já estão concedidos no compose.

Ou seja, o que o B10 acrescenta não é "quebrar o read-only" — isso aconteceu na F5. É:
`POST /api/prune` com `dry_run=true` por padrão, `ENABLE_ACTIONS` para não registrar as rotas
(404, não 403), e **auditoria gravada antes de executar**, atualizada com o resultado depois.
Auditar só no fim perde exatamente os casos graves: a ação que travou o daemon.

O teste que importa é o de IP fora do `TRUSTED_GATEWAY_CIDR` registrando a **tentativa** — é o
que transforma a auditoria em detecção de abuso em vez de só histórico. Alinhado com o débito
já registrado em `00-decisoes-de-revisao.md`: leitura segue alcançável de dentro da rede interna
sem credencial, e um header compartilhado injetado pelo ingress para todo `/api/*` continua
recomendado.

### Backlog sem bloco
Docker Scout como job semanal opcional — depende de CLI plugin e login no Hub, o que
contradiz o `EXEC: 0` deliberado do socket-proxy. Precisaria rodar fora do container do cockpit.

## Variáveis de ambiente novas

Documentadas em `.env.example`. Todas com padrão seguro e piso no código: um
`RETENTION_RAW_HOURS=0` num `.env` mal editado apagaria a série no primeiro ciclo do coletor.

| Variável | Padrão | Piso |
|---|---|---|
| `RETENTION_RAW_HOURS` | 24 | 1 |
| `RETENTION_ROLLUP_DAYS` | 30 | 1 |
| `RETENTION_HOST_DAYS` | 30 | 7 (abaixo disso a projeção da F4 não roda) |
| `ORPHAN_EXITED_DAYS` | 7 | — |

## Dívida conhecida, não tocada aqui

`app/static/sw.js` não lista `js/screens/*.js` em `STATIC_ASSETS`. As telas — inclusive a
Capacidade, que ganhou os dois cartões novos — ficam fora do cache do service worker. Não foi
corrigido nesta sprint porque muda a semântica de cache de todas as telas de uma vez e merece
uma passada própria, com teste de invalidação.
