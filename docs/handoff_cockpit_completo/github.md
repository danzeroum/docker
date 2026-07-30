repo: danzeroum/docker
branch: main
path: app/

## Last sync
date: 2026-07-30T17:00:00Z
commit: b0b7ef5 (`feat(5): drift (B8), fonte real para certs_expiring e hardening (B11) (#30)`)
nota: sincronizado com a `main` real. O plano B1–B11 está **concluído** — este arquivo
descrevia o estado de antes da Sprint 1 e ficou cinco sprints atrás.

## O ciclo B1–B11, por PR

Todo merge foi squash: os commits individuais de cada sprint **não existem mais no
remoto**, e o número da PR é o único índice permanente. É por ele que se recupera o diff, a
discussão e o corpo com o racional de cada decisão.

| Sprint | Blocos | PR | Merge |
|---|---|---|---|
| 1 | B1 storage · B2 retenção · B4 segurança | #25 | `adfa88a` |
| 2a | kernel de módulos + bloco `summary` | #26 | `ddfec62` |
| 2b | B3 eventos · B10 prune | #27 | `e5f315b` |
| 3 | B5 busca em logs + guarda de schema | #28 | `93efa5d` |
| 4 | B6 updates · B7 notificações · B9 métricas | #29 | `23d6b90` |
| 5 | B8 drift · B11 hardening · certs | #30 | `b0b7ef5` |

Estado: **894 testes**, `SCHEMA_VERSION = 15`, migrações v10 a v15 todas com teste sobre
banco populado.

## Rotas novas neste ciclo

| Rota | Bloco | Observação |
|---|---|---|
| `GET /api/storage` | B1 | órfãos identificados, remoção fora de qualquer housekeeping |
| `GET /api/containers/{id}/history` | B2 | retenção em dois níveis (raw 24h, agregado 30d) |
| `GET /api/security` | B4 | score + violações nomeadas |
| `GET /api/events` | B3 | timeline persistida (v11), filtros no servidor, SSE + histórico |
| `POST /api/prune` | B10 | dry-run → lista → confirmar; atrás de `ENABLE_ACTIONS` |
| `GET /api/logs/search` | B5 | FTS5 (v13), highlight, operadores encodados. Mora em `containers.py` como `busca_router`: a busca é por HOST, não por container |
| `GET /api/updates` | B6 | lê do banco (v14); o Hub é consultado só pelo job diário |
| `GET /api/notifications` | B7 | o que o motor entregou (v15); nunca a mensagem enviada |
| `GET /metrics` | B9 | exposition 0.0.4, auth no app, servido do snapshot em memória |
| `GET /api/drift` | B8 | compose declarado × runtime; sem migração, drift é derivado |
| `GET /api/certs` | certs | `notAfter` do X.509; `null` quando não há mount |

## Screen map
| Tela do protótipo | Arquivos de origem no repo |
|---|---|
| Visão geral | app/routers/overview.py, app/summary.py, app/sampler.py, app/static/js/kernel/* |
| Atenção agora | app/findings/engine.py, app/findings/rules/*, app/routers/findings.py |
| Dossiê do container | app/routers/containers.py, app/masking.py, app/static/js/kernel/subtela.js |
| Logs & métricas | app/logs_ingest.py, app/routers/containers.py (`busca_router`), app/static/js/modulos/logs.js |
| Ingress & TLS | app/ingress/parser.py, app/routers/ingress.py, app/certs.py |
| Topologia | README.md, docker-compose.yml |
| Backend & API | app/routers/*, docker-compose.yml (socket-proxy) |
| Capacidade | app/sampler.py + app/routers/metrics.py (série real) |
| Projetos (stacks) | app/routers/projects.py, app/drift.py |
| Auditoria | app/routers/session.py, app/db.py (audit, unlock_state), app/hardening.py |
| Armazenamento | app/routers/storage.py, app/routers/prune.py |
| Eventos | app/events.py, app/routers/events.py |
| Drift | app/drift.py, app/routers/drift.py |
| Tarefas | derivado dos achados (auto_task) |
| Resumo executivo | app/routers/executive.py + findings _plain |

## Estado das fases
- F0–F6, v8, v9, deploy, no_backup — todas na `main` (PRs #3 a #12)
- **B1–B11 — todas na `main`** (PRs #25 a #30). Plano concluído.
- Roteiro do doc 12: executa **inteiro no código**, verificado por teste. **Pendente na
  VPS** — item (d) do doc 00, dono: operador.

## Pendências abertas (nenhuma é de código)
1. **Runbook na VPS** — dono: operador. Critério de fechamento: rodar os 7 passos do doc 12
   com os 15 containers reais e registrar o resultado datado no doc 00. Vale mais agora:
   drift e certs dependem do que existe no disco daquele host.
2. **Acabamento visual de 9 módulos** — dono: dono do produto. Dado real desde a 2a; falta
   forma. Ou Sprint 6 módulo a módulo, ou dívida declarada aceita em definitivo.

## Sync history
- 2026-07-30 — Sprint 5 (#30) mergeada; **plano B1–B11 concluído**; pacote sincronizado com
  o estado real (este arquivo e o LEIA-ME estavam cinco sprints atrás).
- 2026-07-30 — Sprints 1 a 4 (#25, #26, #27, #28, #29) mergeadas.
- 2026-07-30 — leitura de main (18 commits à frente) para a proposta 08; sem rebuild.
- 2026-07-29 — F6 (#8) mergeada; plano F0–F6 completo.
- 2026-07-28 — F5 (4 UIs + segurança do unlock) mergeada; github.md e handoff atualizados.
- 2026-07-27 — F0–F2 construídas e revisadas a partir do código real; commit inicial 6a1d66a.

## Visual tokens
bg #0a1020 · surface #141f3a · surface-2 #1a2747 · accent #2496ED · ok #22c55e · warn #f59e0b · bad #ef4444 · Inter + JetBrains Mono · 3 temas (cockpit/escritorio/claro) em app/static/css/themes.css
