repo: danzeroum/docker
branch: main
path: app/

## Last sync
date: 2026-07-30T02:32:30Z
commit: 7f33a40
nota: main está 18 commits / 39 arquivos à frente de 7f33a40 — leitura apenas (themes.css, overview.js, test_frontend_modulos.py) para fundamentar a proposta 08; telas não foram rebuildadas.

### Updated in this project
- Proposta 08: tema `claro-minimal` + módulos ajustáveis — novo DC `Cockpit Claro Modular.dc.html` + `design_handoff_cockpit_vps/08-proposta-tema-claro-modular.md` (validação de densidade com volumes reais).
- Handoff 09: `design_handoff_cockpit_vps/09-handoff-claro-modular.md` — diff frontend/backend da Visão geral modular, mapa dado→endpoint (zero mock, endpoints reais da `main`), plano de 2 PRs e prompt padrão para o dev.
- Proposta 10 "Cockpit Vivo": `Cockpit Vivo.dc.html` + `design_handoff_cockpit_vps/10-cockpit-vivo-validacao.md` — módulos como read models por escopo (host/projeto/container), drag+presets, subtela central de container, kernel como invariante; validação DDD + UI + frontend.
- Doc 11: análise dos blocos B1–B11 (compilação do backend) contra a UI — 8 aparecem na tela (3 módulos novos: Armazenamento, Eventos, Drift), B9/B11 só dev; prompt de integração UI.
- Protótipo completo: `Cockpit Vivo Completo.dc.html` + doc 12 (roteiro de validação B1–B11 na tela) + anexo com o resumo dos prompts de backend; pacote final em `handoff_cockpit_completo/`.
- Produção está **cinco merges atrás** — `scripts/deploy-cockpit.sh` sobe e valida v8+v9; executivo pede `servicos.json` + `COST_MONTHLY`.

## Screen map
| Tela do protótipo | Arquivos de origem no repo |
|---|---|
| Visão geral | app/routers/overview.py, app/sampler.py, app/static/js/screens/overview.js |
| Atenção agora | app/findings/engine.py, app/findings/rules/*, app/routers/findings.py |
| Dossiê do container | app/routers/containers.py, app/masking.py |
| Logs & métricas | app/app.py (SSE/WS), app/static/js/screens/logs.js |
| Ingress & TLS | app/ingress/parser.py, app/routers/ingress.py, app/findings/rules/nginx_*/no_* |
| Topologia | README.md, docker-compose.yml, nginx.conf |
| Backend & API | app/routers/*, docker-compose.yml (socket-proxy) |
| Capacidade | app/sampler.py (série) — F4, ainda simulada no protótipo |
| Projetos (stacks) | app/routers/projects.py, app/static/js/screens/projects.js |
| Auditoria | app/routers/session.py, app/db.py (audit, unlock_state), app/static/js/screens/auditoria.js |
| Tarefas | derivado dos achados (auto_task) |
| Resumo executivo | app/routers/overview.py + findings _plain |
| Plantão mobile | app/static/js/screens/* (breakpoint) |

## Estado das fases
- F0a (#3) · F0b (#4) · F1 (#5) · F2 (#6) · F3+F5 (#7) · F4 · F6 (#8) · v8 (#9) · v9 Tarefas (#10) · deploy (#11) · no_backup (#12) — todas na `main`; 181 testes, 17 regras
- Produção na VPS: pré-F5, duas migrations atrás (deploy nunca rodou)
- Backlog restante: Resumo executivo (servicos.json + COST_MONTHLY), acessibilidade (`:focus-visible`, 25 handlers de clique)

## Sync history
- 2026-07-30 — leitura de main (18 commits à frente) para a proposta 08; sem rebuild.
- 2026-07-29 — F6 (#8) mergeada; plano F0–F6 completo.
- 2026-07-28 — F5 (4 UIs + segurança do unlock) mergeada; github.md e handoff atualizados.
- 2026-07-27 — F0–F2 construídas e revisadas a partir do código real; commit inicial 6a1d66a (tree).

## Visual tokens
bg #0a1020 · surface #141f3a · surface-2 #1a2747 · accent #2496ED · ok #22c55e · warn #f59e0b · bad #ef4444 · Inter + JetBrains Mono · 3 temas (cockpit/escritorio/claro) em app/static/css/themes.css
