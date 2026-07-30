# 09 · Handoff — Visão geral modular + tema claro-minimal, sem dado mockado

Par do doc 08 (proposta visual). Este documento diz **o que muda no código real** e **de onde
vem cada dado** da tela proposta (`Cockpit Claro Modular.dc.html`). Regra herdada do doc 01:
*grep no JS final não pode encontrar nome de container, domínio ou número de métrica escrito
à mão.* Legenda: ✅ existe hoje · 🔧 derivável do que existe · 🆕 código novo.

## A · O que muda no frontend

| Hoje (`app/static/js`) | Vira |
|---|---|
| `overview.js`: layout fixo `.ov-left / .ov-center / .ov-right` | Grid de 12 colunas; cada bloco vira **módulo** `{id, nome, span, render(), chip()}` com `order` e `grid-column:span` vindos do estado 🆕 |
| `renderStacks / renderKpis / renderRightFindings / renderContainers` | Reaproveitadas como corpo dos módulos `stacks`, chips, `atencao`, `containers` — a lógica de dados não muda 🔧 |
| Grade de cartões única (15 × ~120px, rola em 900px) | Modo **lista** (padrão, 15 linhas sem rolagem) + cartões como opção; cartões forçam span 12 🆕 |
| `renderVitals` (bloco no centro) | **Régua de chips** fixa acima do grid: vitais + 1 chip-resumo por módulo 🆕 |
| — | Painel **Personalizar**: ocultar / mover ↑↓ / largura meia-inteira / restaurar. Persistência `localStorage["cockpit.modulos.overview"]` = `{v:1, ordem, ocultos, cheios, modo}` 🆕 |
| Banner de crítico (padrão híbrido, doc 00) | Mantido, **fora** do sistema de módulos — não ocultável 🔧 |
| `themes.css`: 3 temas | + `claro-minimal` (tokens no doc 08 §2). `components.css`: onde houver sombra/gradiente/hex literal, trocar por token 🆕 |
| Polling: loop compartilhado que pausa com aba oculta (doc 00) | Mantido. **Um fetch por módulo visível**; módulo oculto não busca — o chip vive do `summary` (seção B) 🔧 |
| Pendência #14 | `:focus-visible` e `aria-pressed` em todos os controles novos do painel 🆕 |

## B · O que muda no backend (pequeno, 1 PR)

1. **`GET /api/overview` ganha bloco `summary`** — alimenta a régua inteira em 1 chamada,
   sem 6 fetches por poll: 🆕
   ```json
   "summary": {
     "findings":  {"open": 3, "critical": 1},
     "stacks":    {"up": 12, "total": 15, "stopped_with_domain": 3},
     "ingress":   {"hosts": 13, "https_forced": 11, "certs_expiring": 3, "cert_window_days": 18},
     "capacity":  {"days_to_90": 24, "r2": 0.86, "disk_pct": 71.0},
     "audit":     {"last_at": "...", "last_actor": "dz"},
     "tasks":     {"total": 6, "todo": 2}
   }
   ```
   Tudo é consulta barata: findings/audit/tasks no SQLite; stacks do scan de projects;
   ingress/capacity dos caches já existentes (single-flight, doc 00). Nada de nova leitura
   do daemon.
2. **`started_at` por container** no payload de `/api/overview` (de `State.StartedAt`, já
   disponível no fan-out) — a coluna "no ar há" da lista deriva disso no cliente 🔧.

## C · Mapa dado → fonte (tela proposta, campo a campo)

**Régua de chips**
| Chip | Fonte |
|---|---|
| CPU · RAM · Disco · Swap | `/api/overview.vitals` (`cpu_pct`, `mem_pct`, `disk.pct`, `swap_pct`) ✅ |
| Atenção `1 crít +2` | `summary.findings` 🆕 (hoje: contagem de `/api/findings?status=open` ✅) |
| Containers `14/15 · 1!` | `/api/overview.counters` (`total`, `running`, `attention`) ✅ |
| Stacks `12/15` | `summary.stacks` 🆕 (hoje: `/api/projects` ✅) |
| HTTPS `11/13` | `summary.ingress` 🆕 (derivado do parse F3: porta 80 com `return 301`) |
| Projeção `~24d` | `summary.capacity` 🆕 (hoje: `/api/capacity` ✅ — cala com r²<0.7, doc 00) |
| Auditoria `há 2h` | `summary.audit` 🆕 (hoje: `/api/audit?limit=1` ✅) |
| Tarefas `6 · 2` | `summary.tasks` 🆕 (hoje: `/api/tasks` agrupado ✅) |

**Módulos**
| Elemento | Fonte |
|---|---|
| Faixa crítica (título/corpo/desde) | achado `critical` mais severo: `title`/`_plain`, `interpretation`, `first_seen` ✅ |
| Atenção: sev, título, corpo, "há 26 min" | `/api/findings?status=open` (corte 8 + "ver todos") ✅ |
| Atenção: título simples ↔ técnico | `title_plain` ↔ `title` por profundidade — **nunca** string no JS ✅ |
| Containers: nome, estado, health, exposição | `/api/overview.containers` (`name`, `state`, `health`, `exposure`) ✅ |
| Containers: cpu/mem + limite | `cpu_pct`, `mem_pct`, `mem_limit` (fan-out `/api/stats/all` já embutido) ✅ |
| Containers: "no ar há" | `started_at` novo (seção B.2) 🔧 |
| Containers: linha 2 por profundidade | dado→`image` ✅ · informação→`finding.interpretation_plain` ✅ · conhecimento→`finding.recommendation` ✅ (mapa por `target`, igual ao overview.js atual) |
| Stacks: nome, n/n, pior estado | `/api/overview.stacks` (`id`, `running`, `total`, `worst`) ✅ |
| Stacks: paradas com domínio apontado | cruzamento `/api/projects` × `/api/ingress` (upstream sem container) 🔧 |
| Ingress: hosts, HTTPS, certificados, achados | `/api/ingress` + `/api/findings?scope=ingress` ✅ (dias de cert: metadados do job do host, doc 00) |
| Capacidade: %, barra, projeção | `/api/capacity` (`disk_pct`, `days_to_90`, `r2`) ✅ |
| Capacidade: sparkline 30d | `/api/metrics/history?series=disk_pct&range=30` ✅ |
| Auditoria: 3 últimas ações | `/api/audit?limit=3` (`at`, `actor`, `action`, `note`) ✅ |
| Tarefas: contagem por coluna + próxima | `/api/tasks` (agrupar por `column`; próxima = menor prazo em `todo`) ✅ |
| Trava (somente leitura / destravada) | `POST /api/unlock` + estado de sessão existente (F5/v8) ✅ |
| Subtítulo do header (host, contagens) | `/api/system` + `/api/info` + `summary` ✅ |

**Morre do protótipo** (mesma lista do doc 01): `base[]`, `cenarios{}`, `filas{}`,
números da régua — os 3 cenários de demonstração só sobrevivem atrás de `?demo=1`.

## D · Plano de entrega

1. **PR backend** — `summary` no `/api/overview` + `started_at`. Teste: summary com banco
   populado e com banco vazio (lição das migrations, doc 00).
2. **PR frontend** — tema `claro-minimal` (só `themes.css`/`components.css`) e, na sequência,
   o grid de módulos no `overview.js`. `test_frontend_modulos.py` precisa continuar verde.
3. Deploy via `scripts/deploy-cockpit.sh` (produção segue cinco merges atrás — validar junto).

## E · Prompt para o desenvolvedor

```xml
<lang>Vanilla JS ES modules (app/static/js) + FastAPI Python 3.11 + CSS custom properties</lang>
<task>Portar a Visão geral para o grid modular + tema claro-minimal do doc 09, sem dado mockado: todo campo vem dos endpoints da seção C.</task>
<context>Tela atual: overview.js (3 colunas fixas; /api/overview + /api/findings). Novo: grid 12 col com 7 módulos {id,nome,span,render,chip}, régua de chips, painel Personalizar, localStorage["cockpit.modulos.overview"]={v:1,ordem,ocultos,cheios,modo}. Backend: bloco summary em /api/overview + started_at por container (doc 09 §B).</context>
<rules>
- Pense passo a passo na migração overview.js → módulos.
- Um fetch por módulo visível, no loop de polling compartilhado; a régua usa só overview.summary.
- Módulo oculto mantém chip clicável (re-exibe); faixa crítica fora do sistema de módulos.
- Saída: apenas os blocos de código, sem introdução.
</rules>
<aceite>
- grep no JS final não encontra nome de container, domínio ou métrica escrita à mão.
- Ocultar módulo tira o card e mantém o chip com número vivo; ordem/largura/visibilidade sobrevivem a reload.
- Tema claro-minimal usa só tokens de themes.css; nenhuma cor literal nova no JS.
- :focus-visible e aria-pressed em todos os controles do painel (pendência #14).
</aceite>
<testes>
- /api/overview com 15 containers → lista renderiza 15 linhas sem rolagem em 900px.
- summary.findings.critical: 1→faixa aparece; 0→some sem reordenar módulos.
- localStorage ausente ou corrompido → layout padrão, console limpo.
- Módulo capacidade oculto → zero fetch a /api/capacity; chip segue atualizando via summary.
</testes>
<recomendacao>
- Cubra unidade (registro de módulos), integração (summary com banco populado e vazio) e aceitação (fluxo personalizar completo).
- Siga clean code e 12-Factor: nenhum número de negócio no código; configuração no ambiente.
</recomendacao>
```

**Por que assim:**
- "Pense passo a passo" ficou: é migração de layout com estado persistido e dois PRs encadeados, não tarefa de uma função.
- O 1º aceite é o critério de pronto do doc 01 — é o que o usuário pediu ("nada mockado") em forma verificável por grep.
- O teste de localStorage corrompido é a borda que já matou esta interface uma vez (SyntaxError no main.js = tela morta; ver `test_frontend_modulos.py`).
- `summary` existe para o chip de módulo oculto não custar 6 fetches por poll — mesma economia do fan-out do sampler (doc 00).
