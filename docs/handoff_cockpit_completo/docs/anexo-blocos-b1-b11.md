# Anexo · Blocos B1–B11 — prompts de backend (compilação do autor)

Material recebido em 2026-07-30, validado pelo autor contra a arquitetura real do repo
(FastAPI + httpx → docker-socket-proxy read-only, unlock fail-closed via
`TRUSTED_GATEWAY_CIDR`). Segue com o desenvolvedor junto dos docs 11 (face de UI) e 12
(roteiro do protótipo). Resumo:

| # | Funcionalidade | Fonte de dados | Persistência | Mudança no socket-proxy |
|---|---|---|---|---|
| 1 | Storage + recursos órfãos | `/system/df`, `/images/json`, `/volumes` | — (cache TTL) | `VOLUMES=1` e `/system/df` |
| 2 | Histórico de stats (24h raw / 30d agregado) | `/containers/{id}/stats` | SQLite | nenhuma |
| 3 | Timeline de eventos (SSE) | `/events` (stream) | SQLite (ring) | `EVENTS=1` |
| 4 | Healthcheck + score de segurança | `/containers/{id}/json` | — | nenhuma |
| 5 | Busca full-text em logs (FTS5) + follow | `/containers/{id}/logs` | SQLite FTS5 | nenhuma |
| 6 | Imagem desatualizada | Docker Hub API | SQLite (cache 24h) | nenhuma |
| 7 | Notificações Telegram/Discord/Slack | eventos internos #1–#6 | SQLite | nenhuma |
| 8 | Drift detection (compose vs runtime) | labels compose + compose files | — | nenhuma |
| 9 | `/metrics` Prometheus | cache do coletor #2 | — | nenhuma |
| 10 | Ações opt-in (restart/stop/prune) + auditoria | POST no proxy | SQLite (audit) | POST só em restart/stop/prune |
| 11 | Hardening: rate-limit auth, backup do SQLite, gzip, heartbeat SSE | — | SQLite | nenhuma |

Ordem de implementação do autor: Sprint 1 → B1, B2, B4 (B2 cria a infra SQLite/scheduler).
Sprint 2 → B3, B5. Sprint 3 → B6, B7, B9. Sprint 4 → B8, B11. Sprint 5 (decisão consciente)
→ B10. **Ordem de valor para a interface** (doc 11): B2 → B4 → B3 → B1+B10 → B5 → B6 → B8.

Notas de projeto que o autor destacou (e que a UI assume):
- B2: coleta 60s, downsampling ≤500 pontos, retenção via env — alimenta Métricas.
- B3: heartbeat SSE 15s + reconexão com backoff (o nginx do ingress corta stream ocioso).
- B4: regras como dados; score = 100 − ponderação (crítica 30, alta 15, média 5).
- B5: follow direto do daemon; busca no FTS5; sanitizar sintaxe FTS (a UI também encoda).
- B6: comparação por digest, cache 24h, `consultado_em` no payload — a UI o exibe.
- B7: dedup 30min por (regra, alvo); a UI marca "notificado hh:mm · canal" no achado.
- B8: só chaves declaradas no YAML; `${VAR}` não resolvida → "não avaliado".
- B10: fail-closed (403 sem unlock; `ENABLE_ACTIONS=0` → rotas nem existem); auditoria
  gravada ANTES de executar. A UI só renderiza os botões com a flag ligada + sessão
  destravada.
- B11: rate-limit valida X-Forwarded-For contra o gateway; backup via API do SQLite.

Os prompts XML completos B1–B11 estão com o desenvolvedor (mensagem original de
2026-07-30). Este anexo registra o resumo e as decisões que a interface referencia.
