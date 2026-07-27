# 02 · Backend — o que construir

Base: `app/app.py`, FastAPI, ~700 linhas em arquivo único, falando com
`docker-cockpit-proxy:2375` via `httpx`.

## 0 · Replanejamento antes de acrescentar

Nenhum destes é opcional se o painel vai crescer para 15 containers e 13 domínios.

| Item | Situação hoje | O que fazer |
|---|---|---|
| **Estrutura** | tudo em `app.py` | dividir em `routers/` (`containers`, `system`, `ingress`, `certs`, `findings`, `metrics`, `tasks`) + `services/` para a lógica |
| **Cache** | zero; cada cliente bate no daemon a cada 5 s | cache em memória com TTL por recurso (containers 2 s, info 30 s, ingress 60 s, certs 1 h) |
| **Polling** | frontend chama `/api/containers` a cada 5 s | consumir `/events` do daemon e empurrar via SSE; polling vira reconciliação de 30 s |
| **Persistência** | nenhuma | SQLite em volume nomeado: séries de métricas, tarefas, histórico de achados, auditoria |
| **Segredos** | `Config.Env` devolvido em texto claro | máscara no servidor, sempre |
| **Autorização** | só o basic auth do nginx; qualquer sessão pode `DELETE` | token de destravamento com TTL + log de auditoria |
| **CORS** | `allow_origins=["*"]` quando `ALLOWED_ORIGINS` está vazio | default restrito ao próprio host |
| **Limites** | `tail` sem teto; sem rate limit em escrita | teto de 5 000 linhas; rate limit por sessão nas rotas de mutação |
| **Testes** | 24 testes de API | fixtures com um `nginx.conf` real e um `inspect.json` real para o motor de achados |

## 1 · Permissões do socket-proxy

Para o que o painel precisa, acrescentar ao `docker-compose.yml`:

```yaml
environment:
  CONTAINERS: 1
  IMAGES: 1
  INFO: 1
  NETWORKS: 1
  VOLUMES: 1
  POST: 1
  DELETE: 1
  EVENTS: 1     # novo — stream de eventos, elimina o polling
  SYSTEM: 1     # novo — /system/df, uso de disco por imagem/volume/container
```

Confirmar os nomes exatos na documentação do `tecnativa/docker-socket-proxy` na versão em uso.

Montagens novas no serviço `app`:

```yaml
volumes:
  - /etc/letsencrypt:/etc/letsencrypt:ro          # só para ler fullchain.pem
  - /opt/btv/ingress/nginx:/etc/nginx-ingress:ro  # fallback de leitura do nginx.conf
  - cockpit-data:/data                            # SQLite
```

Decisão a tomar com o dono do servidor: montar `/etc/letsencrypt` inteiro dá ao container
acesso de leitura às chaves privadas. Alternativa mais segura: um job no host que escreve
`/opt/btv/ingress/certs.json` (só metadados) a cada hora, e o cockpit lê esse arquivo.
**Recomendo a segunda.**

---

## 2 · Endpoints novos

### `GET /api/overview`

Uma chamada que serve a tela inicial inteira. Evita 15 inspects e 15 stats do cliente.

```json
{
  "host": { "name": "srv1351082", "cpus": 4, "mem_total_gb": 8, "os": "Ubuntu 24.04",
            "docker": "27.1.1", "uptime_seconds": 3628800 },
  "vitals": { "cpu_pct": 34, "mem_pct": 70, "mem_used_gb": 5.6, "swap_pct": 12,
              "disk": { "mountpoint": "/", "pct": 73, "used_gb": 70, "total_gb": 96 },
              "net_rx_bps": 2100000, "net_tx_bps": 1300000 },
  "stacks": [
    { "id": "criptotrade", "running": 2, "total": 2, "worst": "ok",
      "containers": ["criptotrade-app", "criptotrade-frontend"] }
  ],
  "containers": [
    { "id": "9f2c41ab7e05", "name": "criptotrade-app", "stack": "criptotrade",
      "image": "btv/criptotrade:2.8.0", "state": "running", "health": "healthy",
      "restart_count": 0, "created": "2026-07-18T02:04:11Z", "uptime_seconds": 7920,
      "cpu_pct": 8.1, "mem_pct": 41, "mem_usage": 432013312, "mem_limit": 536870912,
      "ports": "8000/tcp", "networks": ["btv-prod-net"], "exposure": "ingress:/api/",
      "finding_ids": ["oom.criptotrade-app"] }
  ],
  "counters": { "total": 15, "running": 14, "exited": 1, "attention": 1 },
  "generated_at": "2026-07-27T16:40:02Z", "cache_ttl_s": 5
}
```

Implementação: `asyncio.gather` sobre inspect + stats dos containers, cache de 5 s
compartilhado entre clientes. `exposure` vem do cruzamento com `/api/ingress`.

### `GET /api/stats/all`

Fan-out concorrente de `stats?stream=false`, cache de 5 s. Existe separado de `/api/overview`
porque a tela de Capacidade precisa dele sem o resto.

### `GET /api/ingress`

```json
{
  "source": { "method": "nginx -T", "container": "btv-nginx-prod",
              "parsed_at": "...", "parser": "crossplane 0.5.8" },
  "http": { "ssl_protocols": ["TLSv1.2","TLSv1.3"], "gzip": false, "server_tokens": "off",
            "resolver": "127.0.0.11", "connection_upgrade": "static",
            "client_max_body_size": null },
  "hosts": [
    { "server_name": "docker.danzeroum.com",
      "port_80":  { "present": true, "behavior": "redirect_301", "acme": true },
      "port_443": { "present": true, "ssl": true, "http2": false, "hsts": true,
                    "bot_filter": true, "auth": "basic" },
      "certificate": { "name": "docker.danzeroum.com",
                       "fullchain": "/etc/letsencrypt/live/docker.danzeroum.com/fullchain.pem" },
      "locations": [ { "match": "/", "upstream": "http://docker-cockpit:8000",
                       "proxy_read_timeout": 60, "proxy_buffering": null,
                       "client_max_body_size": null, "line": 268 } ],
      "upstream_containers": ["docker-cockpit"],
      "finding_ids": ["nginx.stream_timeout"] }
  ],
  "mounts": [ { "host": "/opt/portfolio", "container": "/usr/share/nginx/portfolio",
                "ro": true, "referenced_by": [] } ],
  "totals": { "hosts": 13, "with_tls": 12, "http_plain": 2, "http2": 0,
              "hsts": 12, "bot_filter": 9, "auth": 2 }
}
```

Como obter o arquivo efetivo: `docker exec btv-nginx-prod nginx -T`. Com o socket-proxy sem
`EXEC`, use a montagem somente-leitura do arquivo. Reparse quando o mtime mudar.

### `GET /api/certificates`

```json
[{ "name": "docker.danzeroum.com", "not_before": "2026-06-12T04:11:00Z",
   "not_after": "2026-09-10T04:11:00Z", "days_left": 45, "issuer": "Let's Encrypt R11",
   "san": ["docker.danzeroum.com"], "used_by": ["docker.danzeroum.com"],
   "status": "ok", "source": "/etc/letsencrypt/live/docker.danzeroum.com/fullchain.pem" }]
```

Regras de `status`:

| status | condição |
|---|---|
| `ok` | `days_left > 21` e usado por pelo menos um host |
| `renovar` | `days_left <= 21` |
| `expirado` | `days_left <= 0` |
| `ausente` | host com `listen 443` cujo arquivo não existe |
| `mismatch` | `server_name` do host não está nos SANs do certificado |
| `emprestado` | certificado de um host nomeado usado também no `default_server` |
| `orfao` | certificado existe em `/etc/letsencrypt/live` e nenhum bloco o referencia |

### `GET /api/findings` · `GET /api/findings/{id}`

O núcleo do produto. Três fontes de regras: containers (inspect), ingress (árvore do nginx),
host (`/api/system` + histórico).

```json
{
  "id": "oom.criptotrade-app",
  "severity": "critical",
  "scope": "container",
  "targets": ["criptotrade-app"],
  "screen": "incidente",
  "title": "criptotrade-app em ciclo de reinício — OOMKilled",
  "title_plain": "O painel de trading parou de operar",
  "interpretation": "morto pelo kernel 14 vezes em 26 min",
  "interpretation_plain": "O site abre, mas nenhuma ordem é processada desde as 04:12",
  "recommendation": "reiniciar não resolve — subir o limite de memória para 1 GB",
  "impact": "/api/ fora do ar",
  "first_seen": "2026-07-27T04:12:08Z",
  "last_seen": "2026-07-27T04:38:41Z",
  "requires_approval": true,
  "auto_task": true,
  "chain":  [ { "at": "2026-07-27T02:04:00Z", "type": "info", "title": "...",
                "text": "...", "evidence": "image btv/criptotrade:2.8.0 · mem_limit 512m" } ],
  "facts":  [ { "key": "Exit code", "value": "137", "tone": "bad" } ],
  "actions":[ { "title": "Subir o limite para 1 GB e reiniciar",
                "detail": "...", "command": "mem_limit: 1g",
                "risk": "reinício de ~8s", "applies_via": "manual" } ],
  "explainer": { "title": "O que é exit 137", "text": "..." }
}
```

`applies_via`: `manual` (só mostra o comando) ou `api` (o painel pode executar, exigindo
sessão destravada). **Comece tudo como `manual`.**

Catálogo mínimo de regras — 11 de ingress (listadas em `01-contrato-de-dados.md`) mais:

| id | Severidade | Condição |
|---|---|---|
| `oom.<container>` | crítico | `State.OOMKilled` ou `ExitCode == 137` |
| `restart_loop.<container>` | crítico | `RestartCount` cresceu ≥ 3 em 30 min |
| `unhealthy.<container>` | alto | `Health.Status == "unhealthy"` |
| `no_healthcheck.<container>` | médio | serviço de longa duração sem `Healthcheck` no inspect |
| `no_mem_limit.<container>` | médio | `HostConfig.Memory == 0` |
| `log_no_rotation.<container>` | médio | `LogConfig.Type == "json-file"` sem `max-size` |
| `exit_nonzero.<container>` | médio | `State.ExitCode != 0` em container parado |
| `disk_pressure` | crítico/alto | `disk.pct > 90` / `> 80` |
| `disk_forecast` | alto | projeção cruza 90% em menos de 14 dias |
| `mem_pressure` | alto | `mem_pct > 85` sustentado por 15 min |
| `cert_expiring` | alto/médio | `days_left <= 7` / `<= 21` |
| `no_backup` | alto | nenhum container com rótulo/imagem de backup e nenhum job detectado |
| `socket_write_enabled` | médio | `POST`/`DELETE` habilitados no socket-proxy |

Cada regra é uma função pura `(estado) -> Finding | None`, testável isoladamente. Guarde
`first_seen` em SQLite para que "há 26 min" seja verdade entre reinícios do app.

### `GET /api/metrics/history`

```
GET /api/metrics/history?series=disk_pct,mem_pct&range=30d&step=1d
GET /api/metrics/history?container=<id>&series=cpu_pct,mem_pct&range=12m&step=30s
```

```json
{ "range": "30d", "step": "1d",
  "series": { "disk_pct": [ { "ts": "2026-06-28", "v": 48.2 } ] },
  "projection": { "disk_pct": { "method": "ols", "slope_per_day": 1.21, "r2": 0.96,
                                "days_to_80": 6, "days_to_90": 15, "days_to_100": 22,
                                "confidence": "media" } } }
```

Coletor: tarefa assíncrona a cada 60 s gravando em SQLite. Retenção: 30 dias em 60 s,
1 ano agregado por dia. Duas tabelas (`host_samples`, `container_samples`) com índice por
`ts`. Isso é ~500 KB/mês — cabe folgado.

Projeção: mínimos quadrados sobre os últimos 20 pontos diários. Devolva `r2`; se `r2 < 0.7`,
o frontend rotula "tendência instável" e não mostra a data.

### `GET /api/capacity`

Monta os três horizontes juntando projeções, certificados e achados abertos. Devolve
`{ "windows": [ { "label": "24h", "severity": "critical", "items": [ { "text": "...",
"source": "finding:disk_pressure" } ] } ] }`.

### `GET|POST|PATCH /api/tasks`

```json
{ "id": "t_7f3a", "title": "Trocar proxy_pass por 301 nos blocos :80",
  "why": "executagent e familia-web atendem em texto claro",
  "column": "todo", "origin": "finding:nginx.http_plain",
  "target": "ingress/nginx/nginx.conf", "owner": "DZ",
  "due": "2026-08-03", "urgent": true, "created_at": "...", "finding_id": "nginx.http_plain" }
```

### `GET /api/api-metrics`

Middleware ASGI que registra `(rota_template, método, status, duração)` em histograma na
memória, com flush por hora para SQLite. Devolve chamadas em 24 h, p95 e taxa de erro por
rota. Sem isso a tela "Backend & API" não tem fonte.

### `POST /api/session/unlock` · `GET /api/audit`

```json
POST → { "token": "...", "expires_at": "...", "scope": ["start","stop","restart","remove"] }
```

TTL de 30 min. Toda rota de mutação passa a exigir `X-Cockpit-Unlock`. Cada mutação grava em
`audit(ts, user_from_basic_auth, action, target, result)` e aparece em `/api/audit`.

---

## 3 · O que **não** construir

- **Latência por salto na topologia** — não há fonte confiável; ou meça de verdade, ou o
  campo sai da tela.
- **Disponibilidade de 30 dias** — só depois que o coletor tiver 30 dias de dado. Até lá,
  mostre "coletando desde <data>".
- **Terminal web** — `ENABLE_TERMINAL` continua desligado. Com `POST` já habilitado no
  socket-proxy, exec é o caminho mais curto entre um cookie vazado e a VPS inteira.

---

## 4 · Ordem sugerida de implementação

1. `GET /api/overview` (cache + fan-out) — desbloqueia a tela principal.
2. Máscara de segredos + token de destravamento — dívida de segurança que já existe hoje.
3. `services/nginx.py` (crossplane) → `/api/ingress`.
4. `services/certs.py` → `/api/certificates`.
5. `services/findings.py` com as regras de container; depois as de ingress.
6. Coletor + SQLite → `/api/metrics/history` → `/api/capacity`.
7. `/api/tasks` com criação automática a partir de achados.
8. Middleware de telemetria → `/api/api-metrics`.
9. `/events` em SSE substituindo o polling.
