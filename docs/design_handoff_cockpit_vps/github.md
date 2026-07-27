repo: danzeroum/docker
branch: main
path: app/

## Last sync
date: 2026-07-27T16:05:00Z
commit: 6a1d66a46d9d

### Updated in this project
- Protótipo de redesenho do cockpit criado a partir do código real (FastAPI + static/js).
- Inventário trocado pelos 15 containers reais da VPS srv1351082 (12 stacks, 13 domínios).
- Novos painéis Ingress & TLS e Capacidade, derivados do nginx.conf de /opt/btv/ingress.
- Três temas (cockpit, escritório, claro) a partir de base.css e inspect-educativo.html.
- Nenhum arquivo do repo foi alterado — o protótipo é uma proposta paralela.

## Screen map
| Tela do protótipo | Arquivos de origem |
|---|---|
| Visão geral | app/static/index.html, app/static/js/containers.js, app/static/js/system.js, app/app.py (/api/system) |
| Atenção agora (causa-raiz) | app/static/inspect-educativo.html, app/app.py (inspect, stats) |
| Dossiê do container | app/static/index.html (abas Overview→Env), app/app.py (/api/containers/{id}/json) |
| Logs & métricas | app/app.py (SSE /logs/stream, WS /stats/ws), app/static/js/logs.js, js/stats.js |
| Topologia | README.md, docker-compose.yml, nginx/nginx.conf |
| Backend & API | app/app.py (rotas), docker-compose.yml (socket-proxy), .github/workflows/ci.yml |
| Tarefas | derivado dos achados de diagnóstico (sem origem direta no repo) |
| Resumo executivo | app/app.py (/api/system warnings), docker-compose.yml |
| Plantão mobile | app/static/index.html (breakpoint 780px), js/notifications.js |
| Ingress & TLS | /opt/btv/ingress/nginx/nginx.conf + docker-compose.yml (colados pelo usuário, fora do repo) |
| Capacidade | mesmo nginx.conf + app/app.py (/api/system) — projeções lineares |

## Fora do repo
O nginx.conf real da VPS (13 hosts, 12 certificados) foi fornecido por colagem, não está
neste repositório. A validade dos certificados é simulada: ligar a `certbot certificates`.

## Visual tokens usados
bg #0a1020 · surface #141f3a · surface-2 #1a2747 · accent #2496ED · ok #22c55e · warn #f59e0b · bad #ef4444 · Inter + JetBrains Mono (de app/static/css/base.css)
