# 01 · Contrato de dados — cada campo da UI e sua origem real

Legenda de status:

| Símbolo | Significado |
|---|---|
| ✅ | já existe hoje no `app.py`, é só consumir |
| 🔧 | derivável no cliente ou no servidor a partir do que já existe |
| 🆕 | precisa de código novo no backend |
| ⚠️ | precisa de fonte fora do daemon Docker (arquivo, certbot, banco) |

---

## 0 · Endpoints que já existem

```
GET  /health
GET  /api/containers                       docker /containers/json?all=1
GET  /api/containers/{id}                  inspect
GET  /api/containers/{id}/json             inspect (alias)
GET  /api/containers/{id}/logs?tail=500    texto, já desmultiplexado
GET  /api/containers/{id}/logs/stream      SSE, eventos stdout/stderr
GET  /api/containers/{id}/stats            snapshot (stream=false)
WS   /api/containers/{id}/stats/ws         cpu_percent, mem_percent, net_rx, net_tx
POST /api/containers/{id}/start|stop|restart
DEL  /api/containers/{id}
GET  /api/images
GET  /api/info
GET  /api/system                           psutil: cpu, memory, swap, disks, network, uptime, warnings
WS   /api/containers/{id}/terminal         desligado por ENABLE_TERMINAL
```

---

## 1 · Visão geral

### Coluna esquerda — stacks agrupadas

| Campo na UI | Origem | Status |
|---|---|---|
| nome da stack | `Labels["com.docker.compose.project"]` de `/api/containers` | 🔧 |
| contagem `2/2` | contagem de `State === "running"` sobre o total do grupo | 🔧 |
| cor do ponto da stack | pior estado entre os filhos (restarting/unhealthy > exited com código ≠ 0 > ok) | 🔧 |
| nome do container | `Names[0]` sem a barra inicial | ✅ |
| segunda linha (profundidade Dado) | `Image` | ✅ |
| segunda linha (Informação / Conhecimento) | `findings[].interpretation` / `.recommendation` do achado ligado a esse container; sem achado, texto neutro derivado do estado | 🆕 |
| etiqueta `up`/`off`/`loop`/`sick` | `State` + `Status` + `State.Health.Status` do inspect | ✅ |

> **Atenção:** `/api/containers` já traz `Labels`, `State`, `Status`, `Image`, `Created`,
> `Ports` e `NetworkSettings.Networks`. Quase toda a coluna sai de **uma** chamada.
> O `Health` **não** vem na lista — vem em `Status` como texto (`"Up 3 hours (healthy)"`).
> Parse esse texto ou faça inspect só dos que interessam (ver `02-backend.md`, `/api/overview`).

### Quatro KPIs

| KPI | Valor | Origem |
|---|---|---|
| Containers | `15` | `length` de `/api/containers` ✅ |
| Rodando | `14 de 15` | filtro por `State === "running"` 🔧 |
| Precisam de você | `1 serviço` | contagem de `unhealthy` + `restarting` 🔧 |
| Disco do host | `73%` | `/api/system` → `disks[]` onde `mountpoint === "/"` ✅ |

As três legendas de cada KPI (uma por profundidade) vêm do motor de achados quando existe
achado relacionado; caso contrário são geradas por regra fixa documentada em `02-backend.md`.
A legenda de Conhecimento **não pode ser string literal** — no protótipo ela é, e é o que
precisa mudar.

### Grade de containers (15 cartões)

| Campo | Origem |
|---|---|
| nome, imagem | `/api/containers` ✅ |
| linha secundária | igual à da sidebar (varia por profundidade) 🆕 |
| selo (`14× restart`, `unhealthy`, `exit 0`, `exit 1`) | `RestartCount`, `State.Health.Status`, `State.ExitCode` do inspect ✅ |
| barra de CPU | `cpu_percent` do WS de stats — ver nota de desempenho abaixo ✅/🆕 |
| barra de memória | `mem_percent` (uso / limite **do container**, não do host) ✅ |

> **Nota de desempenho (importante).** `GET /api/containers/{id}/stats` leva ~1,2 s por
> container porque o daemon precisa de duas amostras. Quinze chamadas em série = 18 s.
> Abrir 15 WebSockets também não serve. **Crie `GET /api/stats/all`** com fan-out
> `asyncio.gather` e cache de 5 s no servidor (ver `02-backend.md`). Sem isso a Visão geral
> não carrega em tempo aceitável.

### Faixa de host (vitais)

| Campo | Origem |
|---|---|
| CPU %, cores, load 1m | `/api/system` → `cpu` ✅ |
| Memória % e absoluto | `/api/system` → `memory` ✅ |
| Disco / | `/api/system` → `disks[]` ✅ |
| Swap | `/api/system` → `swap` ✅ |
| Rede MB/s | derivar de dois pontos de `/api/system.network.bytes_sent/recv` 🔧 |
| nome do host, vCPU, RAM, SO | `/api/system` + `/api/info` (`Name`, `NCPU`, `MemTotal`, `OperatingSystem`) ✅ |
| "13 domínios" | `/api/ingress` 🆕 |

### Coluna direita — fila "Precisa da sua atenção"

Cada item = um achado aberto, ordenado por severidade e depois por recência.

| Campo | Origem |
|---|---|
| severidade, título, corpo | `/api/findings` 🆕 |
| título/corpo em linguagem simples | mesmo achado, campos `title_plain` / `interpretation_plain` 🆕 |
| "há 26 min" | `finding.first_seen` 🆕 |
| botão de próximo passo | `finding.screen` + `finding.targets[0]` 🆕 |

### Resumo de tarefas

`GET /api/tasks` agrupado por coluna 🆕.

---

## 2 · Atenção agora (causa-raiz)

Tela inteira renderizada a partir de **um** achado expandido:
`GET /api/findings/{id}`.

| Campo | Origem |
|---|---|
| severidade, título, resumo | achado 🆕 |
| impacto (`/api/ fora do ar`) | `finding.impact` 🆕 |
| "desde 04:12 · 26 min" | `finding.first_seen` 🆕 |
| cadeia de causa (5 eventos) | `finding.chain[]` — cada item `{at, type, title, text, evidence}` 🆕 |
| evidências (6 cartões) | `finding.facts[]` — `{key, value, tone}` 🆕 |
| ações (3) | `finding.actions[]` — `{title, detail, command, risk}` 🆕 |
| caixa de aprendizado | `finding.explainer` — só renderiza em profundidade Conhecimento ou perfil Aprendiz 🆕 |

**De onde a cadeia sai de verdade**, no caso OOMKill:

| Evento da cadeia | Fonte real |
|---|---|
| deploy da versão | `inspect.Created` + `Config.Image` (tag) ✅ |
| consumo antes do estouro | série de `mem_percent` em `/api/metrics/history` 🆕 |
| primeiro OOMKill | `inspect.State.OOMKilled` + `State.FinishedAt` + `ExitCode 137` ✅ |
| laço de reinício | `RestartCount` + `HostConfig.RestartPolicy.Name` ✅ |
| efeito no gateway | contagem de 502 no `access.log` do nginx ⚠️ (ver `02-backend.md`) |

---

## 3 · Dossiê do container

Substitui as 10 abas atuais. Tudo de **um** inspect + um snapshot de stats.

| Bloco | Campo | Origem |
|---|---|---|
| Hero | nome, imagem, id curto, criado em | `inspect.Name`, `Config.Image`, `Id[:12]`, `Created` ✅ |
| Hero | pílulas de status e health | `State.Status`, `State.Health.Status` ✅ |
| Hero | "leitura em uma frase" | `finding.interpretation` do achado ligado, ou regra padrão 🆕 |
| Estado | status, health, reinícios, no ar há, exit code, política | `State.*`, `RestartCount`, `HostConfig.RestartPolicy` ✅ |
| Consumo | cpu, memória, limite | stats + `HostConfig.Memory` (0 = sem limite) ✅ |
| Rede | portas, redes, exposição, IP | `NetworkSettings.Ports`, `.Networks`, IP por rede ✅ |
| Rede | "exposição" (internet / via ingress / interna) | cruzamento com `/api/ingress`: o container é upstream de algum host? 🆕 |
| Volumes | montagens | `Mounts[]` ✅ |
| Volumes | driver de log e rotação | `HostConfig.LogConfig` ✅ |
| Config | digest, comando, working dir | `Image`, `Config.Cmd`, `Config.WorkingDir` ✅ |
| Config | variáveis de ambiente **mascaradas** | `Config.Env` + máscara no **servidor** — ver aviso 🆕 |
| Últimas linhas | 5 linhas | `/api/containers/{id}/logs?tail=5` ✅ |

> **Aviso de segurança.** Hoje `/api/containers/{id}/json` devolve `Config.Env` inteiro,
> com segredos em texto claro, para qualquer sessão autenticada. A máscara precisa ser
> aplicada **no backend**, não no JS. Regra sugerida: mascarar o valor quando a chave casar
> `(?i)(pass|secret|token|key|dsn|url|auth|credential)` e sempre mascarar a parte de
> credencial de qualquer valor com forma de URI. Ver `02-backend.md`.

---

## 4 · Logs & métricas

| Campo | Origem |
|---|---|
| linhas, timestamp, stdout/stderr | `GET /api/containers/{id}/logs/stream` (SSE) ✅ |
| eventos `sys` (exited, restarting) | `GET /events` do daemon ⚠️ exige `EVENTS: 1` no socket-proxy 🆕 |
| filtros tudo/stderr/sys | client-side 🔧 |
| sparklines de CPU, memória, rede (24 barras) | `/api/metrics/history?container=<id>&range=12m&step=30s` 🆕 (hoje o WS só dá o instante) |
| valor grande de cada métrica | último ponto do WS ✅ |

---

## 5 · Ingress & TLS

Nenhum dado desta tela existe hoje. Duas fontes novas.

### Tabela de hosts — `GET /api/ingress`

| Campo | Como obter |
|---|---|
| `server_name` | parse do `nginx.conf` 🆕 |
| `internal: true` | bloco que compartilha `server_name` com `localhost` — é o `server` do healthcheck do gateway (`btv.buildtovalue.cloud`), não um domínio servido ao público. **São 14 blocos, 13 públicos**; os totais da tela contam só os públicos 🆕 |
| comportamento da porta 80 | há `return 301`? há `proxy_pass`? há `return 200/444`? 🆕 |
| porta 443 presente, `ssl`, `http2` | diretivas `listen` 🆕 |
| HSTS | existe `add_header Strict-Transport-Security` no bloco 🆕 |
| filtro de bots | existe `location ~* (wp-login...)` no bloco 🆕 |
| autenticação | existe `auth_basic` no bloco 🆕 |
| upstream | `proxy_pass` / `set $upstream` resolvido 🆕 |
| certificado | caminho de `ssl_certificate` 🆕 |
| `proxy_read_timeout`, `proxy_buffering`, `client_max_body_size` | por `location` 🆕 |

**Use um parser de verdade, não regex:** `crossplane` (Nginx Inc., `pip install crossplane`)
devolve a árvore completa de diretivas. Alimente-o com a saída de `nginx -T` do container do
gateway — assim `include`s e o arquivo efetivamente carregado são resolvidos. Fallback: ler
`/opt/btv/ingress/nginx/nginx.conf` montado somente-leitura.

### Certificados — `GET /api/certificates`

| Campo | Como obter |
|---|---|
| validade, emissor, SANs | ler o `fullchain.pem` e extrair `notAfter`/`notBefore`/`issuer`/SAN com `cryptography` ⚠️ |
| dias restantes | `not_after - now` 🔧 |
| usado por | cruzar com `ssl_certificate` de cada bloco 🆕 |
| status `ok/renovar/expirado/ausente/mismatch` | regras em `02-backend.md` 🆕 |

Exige montar `/etc/letsencrypt:/etc/letsencrypt:ro` no container do cockpit **ou** um endpoint
no host. Leia apenas `*/fullchain.pem`; nunca abra `privkey.pem`.

**No protótipo os dias restantes são inventados.** É o item mais visível a ligar em dado real.

### Achados de configuração — `GET /api/findings?scope=ingress`

As 11 regras que o protótipo mostra, com a verificação exata a implementar:

| id | Severidade | Verificação sobre a árvore do nginx |
|---|---|---|
| `nginx.http_plain` | **alto** | bloco `listen 80` cujo `location /` tem `proxy_pass` em vez de `return 301`. Um achado por host (ids separados) — cada um se resolve sozinho. Sobe para crítico se o upstream tiver autenticação, porque a credencial trafega legível |
| `nginx.docs_public` | alto | `location` que serve `/docs`, `/redoc` ou `/openapi.json` sem `auth_basic` no bloco. Detectado em `criptotrade` **e `juridico`** (este último não estava previsto no protótipo). Recomendação é `auth_basic`, não desligar os docs |
| `nginx.stream_timeout` | alto | bloco cujo upstream é um container que expõe SSE/WS e tem `proxy_read_timeout < 300` ou não tem `proxy_buffering off` |
| `nginx.default_cert_borrowed` | médio | `default_server` 443 usando `ssl_certificate` de um host nomeado (hoje o de `prompte`). Dano de confiança, não de serviço: aviso de certificado em domínio não configurado. Recomendação é cert autoassinado ou `return 444` |
| `nginx.env_unescaped` | médio | regex de `location` contendo `env` sem `\.` antes |
| `nginx.connection_upgrade_global` | médio | `proxy_set_header Connection "upgrade"` no nível `http` sem `map $http_upgrade` |
| `nginx.body_size_default` | médio | blocos sem `client_max_body_size` (padrão 1 MB) |
| `nginx.no_http2` | médio | `listen 443 ssl` sem `http2` |
| `nginx.no_gzip` | baixo | ausência de `gzip on` no nível `http` |
| `nginx.orphan_mount` | baixo | volume montado no gateway sem nenhum `root`/`alias` que o referencie |
| `nginx.healthcheck_coupling` | baixo | healthcheck do compose aponta para um `server_name` específico |

Cada achado carrega `evidence.file`, `evidence.line` e `evidence.snippet` — o parser dá isso
de graça. **Não invente números de linha.**

---

## 6 · Topologia

| Nó | Origem |
|---|---|
| Navegador → gateway | estático, mais contagem de hosts de `/api/ingress` 🆕 |
| btv-nginx-prod | `/api/containers` + `/api/ingress` ✅🆕 |
| container de aplicação | resolvido pelo upstream do host selecionado 🆕 |
| docker-cockpit-proxy | `/api/containers` ✅ |
| Docker daemon | `/api/info` (`Containers`, `ServerVersion`) ✅ |
| latência por salto | ⚠️ não existe fonte; ou medir no backend com um `HEAD` interno, ou **remover o número** |
| superfície exposta | `/api/ingress` + `HostConfig.Binds` do socket-proxy 🆕 |

> Se não houver medição real de latência, tire o campo. Número inventado em painel de
> operação é pior que campo ausente.

---

## 7 · Backend & API

| Campo | Origem |
|---|---|
| lista de rotas | introspecção do próprio FastAPI (`app.routes`) 🔧 |
| chamadas em 24 h, p95, taxa de erro | middleware de telemetria + armazenamento 🆕 |
| disponibilidade, erros 5xx | mesma fonte 🆕 |
| permissões do socket-proxy | ler as env do container `docker-cockpit-proxy` via inspect ✅ 🔧 |
| streams abertos | contador em memória do próprio app 🆕 |
| execuções de CI | API do GitHub Actions com token ⚠️ (opcional; se não houver token, esconder o painel) |
| testes `24/24` | último run do CI ⚠️ |

---

## 8 · Capacidade

| Campo | Origem |
|---|---|
| série de 20 dias de disco/CPU/memória | `/api/metrics/history` 🆕 — **hoje não há persistência nenhuma** |
| projeção de 10 dias | regressão linear sobre a série; devolver `slope`, `r²`, `days_to_90` 🆕 |
| "chega a 90% em N dias" | do mesmo cálculo — o protótipo usa 1,2 ponto/dia fixo, trocar 🆕 |
| memória por stack | soma de `mem_usage` agrupada por label de projeto (via `/api/stats/all`) 🔧🆕 |
| horizontes 24 h / 7 d / 30 d | montados no backend a partir de: projeções, `days_left` de certificados, achados abertos 🆕 |
| evolução da VPS (maio/junho/julho) | **derivável de dado real**: contagem acumulada de containers por mês via `inspect.Created`, e de domínios via `not_before` dos certificados 🔧 |
| postura de segurança (10 linhas) | contagens agregadas de `/api/ingress` + `/api/findings` 🆕 |

---

## 9 · Tarefas

| Campo | Origem |
|---|---|
| colunas, cartões, dono, prazo | `GET /api/tasks` 🆕 — precisa de persistência |
| etiqueta "do diagnóstico" | tarefa criada automaticamente a partir de um achado com `auto_task: true` 🆕 |
| alvo (container, arquivo, domínio) | `finding.targets` 🆕 |
| mover de coluna | `PATCH /api/tasks/{id}` 🆕 |

Regra de sincronia: quando um achado é resolvido (deixa de aparecer em `/api/findings`), a
tarefa gerada por ele vai para `done` automaticamente, com nota `"resolvido: achado não
reincide desde <data>"`. Tarefa manual nunca é movida pelo sistema.

---

## 10 · Resumo executivo

| Campo | Origem |
|---|---|
| título e texto do hero | achado de maior severidade, campos `_plain` 🆕 |
| serviços no ar | contagem de `/api/containers` 🔧 |
| disponibilidade 30 d | ⚠️ exige histórico de uptime — ou vem de `/api/metrics/history`, ou o campo sai |
| precisa de decisão | achados com `requires_approval: true` 🆕 |
| custo do servidor | ⚠️ constante de configuração (`COST_MONTHLY` no `.env`) — não há fonte automática |
| serviços que o cliente enxerga | mapa `domínio → nome de negócio`, arquivo de configuração 🆕 |
| riscos e decisões | achados com horizonte, ordenados por prazo 🆕 |

> O mapa "domínio → nome de negócio" (`criptotrade.buildtovalue.cloud` → "Painel de trading")
> não existe em lugar nenhum do sistema. Crie `app/config/servicos.yml`. Sem isso a tela do
> gestor volta a falar em nome de container.

---

## 11 · Plantão mobile

Mesmas fontes da fila de atenção e do dossiê, em viewport de 390 × 844. Sem endpoint próprio.
O botão de ação respeita o destravamento de sessão (`POST /api/session/unlock`).

---

## Símbolos a eliminar do protótipo

Tudo abaixo é dado simulado dentro do `.dc.html`. Ao portar, cada um vira uma chamada:

| Símbolo no arquivo | O que é | Substituir por |
|---|---|---|
| `base = [...]` | 15 containers fixos | `GET /api/overview` |
| `cenarios = {...}` | 3 cenários de demonstração | **remover** (ou manter atrás de `?demo=1`) |
| `fmtFila()` | fila de atenção fixa | `GET /api/findings?open=1` |
| `incidenteDados()` | 3 narrativas de causa-raiz | `GET /api/findings/{id}` |
| `logsBase` | 12 linhas de log fixas | SSE de logs |
| `endpointsDef` | tabela de rotas com p95 | `GET /api/api-metrics` |
| `hostsDef` | 14 hosts do nginx | `GET /api/ingress` |
| `certDef` | 13 certificados com validade | `GET /api/certificates` |
| `achadoDef` | 11 achados | `GET /api/findings` |
| `consumoDef` | memória por stack | `GET /api/stats/all` agrupado |
| `horizDef` | horizontes 24 h/7 d/30 d | `GET /api/capacity` |
| `evolucao` | 4 marcos de crescimento | derivar de `Created` + `not_before` |
| `posturaDef` | 10 linhas de postura | agregação de `/api/ingress` |
| `tarefas` | 10 cartões | `GET /api/tasks` |
| `projecao` / `taxa = 1.2` | projeção linear fixa | `metrics/history.projection` |
| `serie(...)`, `cpuSerie`, `memSerie` | sparklines | histórico por container |
| `'srv1351082 · 4 vCPU · 8 GB'` | identificação do host | `/api/system` + `/api/info` |
| `'R$ 340'` | custo mensal | `.env` |

Critério de pronto: **`grep` no JS final não pode encontrar nenhum nome de container, domínio
ou número de métrica escrito à mão.**
