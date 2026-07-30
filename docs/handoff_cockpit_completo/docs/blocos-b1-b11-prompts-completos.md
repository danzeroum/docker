# Blocos B1–B11 — prompts de desenvolvimento completos

Complementa o `anexo-blocos-b1-b11.md` (que traz só o resumo). Cada bloco segue o padrão
XML do projeto (lang/task/context/rules/aceite/testes/recomendacao) e pode ser colado
direto em outra LLM ou usado como especificação mínima. Validado em 2026-07-30 contra a
arquitetura real do repo: FastAPI + httpx → docker-socket-proxy read-only, unlock
fail-closed via `TRUSTED_GATEWAY_CIDR`.

Ordem de implementação (backend): Sprint 1 → B1, B2, B4 · Sprint 2 → B3, B5 ·
Sprint 3 → B6, B7, B9 · Sprint 4 → B8, B11 · Sprint 5 (decisão consciente) → B10.
Ordem de valor para a interface (doc 11): B2 → B4 → B3 → B1+B10 → B5 → B6 → B8.

---

## B1 — Storage e recursos órfãos

```xml
<lang>Python 3.11 + FastAPI + httpx <!-- suposto: versão do repo --></lang>
<task>Criar GET /api/storage agregando /system/df do socket-proxy com detecção de imagens dangling, volumes órfãos e containers exited há >7 dias; card na UI com "X GB recuperáveis".</task>
<context>Cockpit read-only fala com o daemon via httpx → http://docker-cockpit-proxy:2375. Liberar VOLUMES=1 e /system/df no proxy.</context>
<rules>
- Saída: apenas o bloco de código, sem introdução.
- Cache em memória com TTL 30s; nunca uma chamada ao daemon por clique de UI.
- Volume órfão = nenhum container (mesmo parado) o referencia.
</rules>
<aceite>
- JSON com images/containers/volumes/build_cache, reclaimable_bytes e lista orphans[] tipada.
- Proxy indisponível → 503 com mensagem clara, sem stacktrace.
</aceite>
<testes>
- 2 imagens dangling no host → orphans contém as 2 com tamanho em bytes.
- Ambiente limpo → orphans=[] e reclaimable_bytes coerente com o df.
</testes>
<recomendacao>
- Cubra unidade e integração focando o limite com o socket-proxy (httpx mockado).
</recomendacao>
```

Notas do autor: o TTL é regra porque o df é a chamada mais cara do daemon e a UI tende a
fazer polling; o caso de borda "ambiente limpo" é onde a lógica de órfãos dá falso positivo.

---

## B2 — Coletor de histórico de stats (infraestrutura base)

```xml
<lang>Python 3.11 + FastAPI + aiosqlite</lang>
<task>Tarefa asyncio em background coletando /containers/{id}/stats (stream=false) a cada 60s para SQLite; retenção raw 24h + agregado horário 30d; GET /api/containers/{id}/history?range=.</task>
<context>Reaproveitar o cliente httpx existente. Este módulo cria o scheduler e o SQLite que os blocos B3, B5, B7 e B9 reutilizam.</context>
<rules>
- Pense passo a passo antes de responder.
- Coleta nunca bloqueia requests HTTP; falha em um container não interrompe os demais.
- Intervalo e retenção via variáveis de ambiente.
- Downsampling na leitura: máximo 500 pontos por resposta.
</rules>
<aceite>
- Após 3 min de execução, history retorna ≥3 pontos com cpu_pct e mem_bytes.
- range=7d retorna pontos agregados por hora; dados raw >24h são expurgados.
</aceite>
<testes>
- Container removido no meio da coleta → pulado, logado, coleta segue.
- Duas leituras no mesmo segundo → sem violação de chave (índice composto).
</testes>
<recomendacao>
- Analise a complexidade das consultas de série temporal: índice (container_id, ts) e agregação incremental, não full scan.
</recomendacao>
```

Notas do autor: "pense passo a passo" ficou por causa da concorrência asyncio + ciclo de
retenção; o aceite fixa o expurgo porque sem ele o SQLite cresce até encher o disco que o
B1 monitora.

---

## B3 — Eventos em tempo real

```xml
<lang>Python 3.11 + FastAPI (SSE) + JS vanilla <!-- suposto: frontend sem framework --></lang>
<task>Consumir o stream /events do daemon, persistir em SQLite (ring de 10k eventos) e reexpor via SSE em GET /api/events/stream; timeline na UI filtrável por container e tipo.</task>
<context>Requer EVENTS=1 no socket-proxy. Usa o SQLite do B2.</context>
<rules>
- Reconexão ao stream do daemon com backoff exponencial (máx 60s).
- SSE com heartbeat a cada 15s para atravessar o nginx do ingress.
- Filtros aplicados no servidor, não no cliente.
</rules>
<aceite>
- Parar um container reflete o evento na UI em menos de 2s.
- Reinício do cockpit preserva os eventos já persistidos.
</aceite>
<testes>
- 3 restarts em 5min → timeline mostra a sequência die→start ordenada.
- Queda do proxy por 30s → reconecta sozinho e registra gap no log.
</testes>
```

Notas do autor: o heartbeat é regra porque o tráfego passa pelo `btv-nginx-prod`, que
derruba SSE ocioso — o bug nº 1 dessa feature nessa arquitetura.

---

## B4 — Healthcheck + score de segurança

```xml
<lang>Python 3.11 + FastAPI</lang>
<task>Enriquecer /api/containers com State.Health e criar GET /api/security: avaliar cada container via inspect e retornar score 0–100 com lista de violações e severidade.</task>
<context>Regras: usuário root, privileged, sem mem_limit, /var/run/docker.sock montado, network_mode=host, cap_add perigosas (SYS_ADMIN, NET_ADMIN). Tudo já disponível no inspect existente.</context>
<rules>
- Saída: apenas o bloco de código, sem introdução.
- Regras declaradas como dados (lista de checks), não como if encadeados.
- Score = 100 − soma ponderada por severidade (crítica 30, alta 15, média 5).
</rules>
<aceite>
- Container com docker.sock montado → violação crítica identificada por nome de regra.
- Todos conformes → score 100 e violations=[].
- Badge unhealthy visível na listagem quando State.Health.Status=unhealthy.
</aceite>
<testes>
- Container sem healthcheck definido → campo health=null, sem erro.
- privileged=true + root → score 55 com 2 violações.
</testes>
<recomendacao>
- Separe verificação (a regra avalia o campo certo do inspect?) de validação (a regra detecta risco real?).
</recomendacao>
```

Notas do autor: "regras como dados" porque a lista de checks vai crescer — é o ponto de
extensão do módulo; o teste de score fixa a aritmética (100−30−15=55).

---

## B5 — Logs: busca FTS5 + follow

```xml
<lang>Python 3.11 + FastAPI + SQLite FTS5</lang>
<task>Ingestão incremental de logs por container (since=último ts) em tabela FTS5; GET /api/logs/search?q= com highlight e SSE de follow em /api/containers/{id}/logs/stream.</task>
<context>Endpoint /containers/{id}/logs já liberado no proxy. Usa scheduler do B2. Retenção padrão 7 dias via env.</context>
<rules>
- Escapar HTML no highlight e sanitizar sintaxe FTS da query (injeção/XSS).
- Ingestão a cada 30s; follow em tempo real vem direto do daemon, não do banco.
- q com menos de 3 caracteres → 400.
</rules>
<aceite>
- Busca por "error" retorna trechos com container, timestamp e termo destacado.
- Linha nova aparece no follow em menos de 3s; logs >7d são expurgados.
</aceite>
<testes>
- q com aspas e operadores FTS ("erro NEAR/2") → tratado como literal, sem exception.
- Container sem logs → resultado vazio, 200.
</testes>
<recomendacao>
- Cubra integração com logs sintéticos multiline (stack traces são o caso real de uso).
</recomendacao>
```

Notas do autor: ingestão (busca histórica) separada do follow (direto do daemon) para não
dobrar o I/O; o caso de borda é injeção de sintaxe FTS, a falha clássica que trava a busca.

---

## B6 — Verificação de atualização via Docker Hub

```xml
<lang>Python 3.11 + FastAPI + httpx</lang>
<task>Job diário que compara o digest local de cada imagem em uso com o digest da mesma tag no Docker Hub e expõe GET /api/updates com status atualizado/desatualizado/desconhecido.</task>
<context>API externa: hub.docker.com/v2/repositories/{ns}/{repo}/tags/{tag}. Imagens sem namespace usam library/. Somente registry docker.io nesta fase.</context>
<rules>
- Cache de 24h por imagem; respeitar rate limit do Hub.
- Registry privado ou imagem sem RepoTag → status "desconhecido", nunca erro.
</rules>
<aceite>
- Imagem com digest divergente do Hub → desatualizada, com data da tag remota.
- Resposta traz consultado_em para o operador saber a idade do dado.
</aceite>
<testes>
- HTTP 429 do Hub → backoff e status "pendente", job não aborta.
- Imagem construída localmente (sem repo) → ignorada da listagem.
</testes>
```

Notas do autor: comparação por digest, não por nome de tag (`latest` só é comparável por
digest); o 429 é o teste central — 20 imagens estouram o rate limit anônimo do Hub.

---

## B7 — Motor de notificações

```xml
<lang>Python 3.11 + FastAPI + httpx</lang>
<task>Motor de regras com webhooks Telegram, Discord e Slack. Regras iniciais: container die, unhealthy, disco >80% (B1), imagem desatualizada (B6). Dedup de 30min por (regra, alvo).</task>
<context>Consome eventos internos dos módulos B1–B6 via fila asyncio. URLs e tokens via variáveis de ambiente.</context>
<rules>
- Falha em um canal é logada e não bloqueia os demais nem o coletor.
- Mensagem inclui host, container, regra e timestamp — sem payload bruto.
- Segredos nunca aparecem em log.
</rules>
<aceite>
- Matar um container → mensagem no canal em menos de 1min.
- Mesmo evento dentro da janela de 30min → não renotifica.
</aceite>
<testes>
- URL de webhook inválida → erro logado, outros canais entregam.
- Dois containers diferentes caindo → 2 notificações (dedup é por alvo).
</testes>
<recomendacao>
- Siga 12-Factor: config e segredos no ambiente, notificação logada como evento estruturado.
</recomendacao>
```

Notas do autor: dedup por (regra, alvo) e não global — um crash loop não pode silenciar o
alerta de disco; a fila asyncio evita que webhook lento atrase o coletor de stats.

---

## B8 — Drift detection

```xml
<lang>Python 3.11 + FastAPI + PyYAML</lang>
<task>Comparar compose files (caminho via label com.docker.compose.project.config_files) com os containers em execução: imagem/tag, portas e env declaradas; listar containers fora de qualquer projeto Compose.</task>
<context>Compose files vivem no host (ex: /opt/btv/*). Montar diretório read-only no container do cockpit. <!-- suposto: montagem a definir no compose.yml --></context>
<rules>
- Comparar apenas chaves declaradas no YAML (env extra do runtime não é drift).
- Compose file inacessível → aviso no resultado, nunca exception.
</rules>
<aceite>
- docker run manual → aparece em "fora de projeto".
- Tag divergente → item de drift com {esperado, atual, serviço}.
- Projeto íntegro → drift=[] para aquele projeto.
</aceite>
<testes>
- YAML com variáveis ${VAR} não resolvidas → comparação ignora a chave e sinaliza "não avaliado".
- Label ausente (container antigo) → classificado como fora de projeto.
</testes>
```

Notas do autor: "só chaves declaradas" evita falsos positivos com env que o Docker injeta
sozinho (PATH, HOSTNAME); `${VAR}` com interpolação é a borda que quebra parser ingênuo.

---

## B9 — Métricas Prometheus

```xml
<lang>Python 3.11 + FastAPI</lang>
<task>Expor GET /metrics no formato exposition (text/plain 0.0.4) com gauges por container: cpu_pct, mem_bytes, estado (1/0), unhealthy_total — lendo do cache do coletor B2.</task>
<context>Scrape não pode tocar o daemon: usa o último snapshot em memória do B2. Protegido pelo mesmo basic auth do app.</context>
<rules>
- Labels: name e image. Sem label de alta cardinalidade (id completo, ts).
- Saída: apenas o bloco de código, sem introdução.
</rules>
<aceite>
- curl -u user:pass /metrics → 200 com métricas nomeadas cockpit_container_*.
- Sem credenciais → 401.
- Container parado → estado=0 (não some entre scrapes).
</aceite>
<testes>
- Snapshot ainda vazio (boot) → 200 com exposição vazia válida, não 500.
</testes>
```

Notas do autor: "estado=0 em vez de sumir" evita falso `absent()` no alertmanager;
cardinalidade é regra porque id de container como label incha o Prometheus a cada recreate.

---

## B10 — Ações opt-in com auditoria (Fase 3 — decisão arquitetural)

```xml
<lang>Python 3.11 + FastAPI</lang>
<task>POST /api/containers/{id}/restart|stop e POST /api/prune?dry_run= — habilitados apenas com ENABLE_ACTIONS=1 e unlock ativo (gateway em TRUSTED_GATEWAY_CIDR); toda ação gravada em audit log (ip, ação, alvo, resultado, ts).</task>
<context>Quebra deliberada do read-only: liberar no socket-proxy somente POST de restart, stop e prune. dry_run=true é o padrão do prune.</context>
<rules>
- Pense passo a passo antes de responder.
- Fail-closed: sem unlock → 403; ENABLE_ACTIONS=0 → rotas nem registradas (404).
- Auditoria gravada antes de executar e atualizada com o resultado.
</rules>
<aceite>
- restart com unlock → container reinicia e audit contém ip+ts+resultado.
- prune com dry_run=true lista candidatos sem remover nada.
</aceite>
<testes>
- Requisição de IP fora do CIDR → 403 e tentativa registrada na auditoria.
- prune real → remove apenas dangling; volumes intactos.
</testes>
<recomendacao>
- Cubra unidade, integração e aceitação focando os limites de autorização — é código de produção com privilégio.
</recomendacao>
```

Notas do autor: auditoria ANTES de executar garante rastro mesmo se a ação travar o daemon;
registrar a tentativa de IP fora do CIDR transforma a auditoria em detecção de abuso.

---

## B11 — Hardening (melhorias adicionais)

```xml
<lang>Python 3.11 + FastAPI</lang>
<task>Três reforços: rate-limit no basic auth (5 falhas/min por IP → 429 + evento para o B7), backup diário rotativo do SQLite do cockpit (7 cópias) e gzip nas respostas JSON.</task>
<context>Auth atual é basic auth simples atrás do ingress; usar o IP do X-Forwarded-For validado contra o gateway confiável.</context>
<rules>
- Contador de falhas em memória com janela deslizante; nunca bloquear IP do próprio ingress.
- Backup via API de backup do SQLite (não cp de arquivo quente).
</rules>
<aceite>
- 6ª falha de senha em 60s → 429 e notificação de brute-force.
- Backup gera arquivo datado e mantém exatamente 7.
</aceite>
<testes>
- Login correto após 4 falhas → 200 e contador zera.
- Backup durante escrita do coletor → arquivo íntegro (abre sem erro).
</testes>
```

Notas do autor: X-Forwarded-For validado contra o gateway é o detalhe crítico — rate-limit
por IP atrás de proxy sem essa validação bloqueia o ingress inteiro; backup pela API do
SQLite (e não `cp`) porque o coletor B2 escreve continuamente.
