# 06 · Telas de operação — Projetos, Auditoria e os dois modais

Quatro UIs que o backend já suporta (ou quase) mas que ainda não existem no frontend. O
protótipo `Cockpit Docker.dc.html` traz o desenho final das quatro. Contrato campo a campo
abaixo; símbolos como em `01-contrato-de-dados.md` (✅ existe · 🔧 derivável · 🆕 backend novo).

---

## 1 · Projetos (stacks) — `#/projetos`

Lente de **compose-em-disco**, diferente da Visão geral (containers rodando). Um projeto pode
existir em `/opt/btv/<nome>/docker-compose.yml` e estar parado — e é exatamente esse o caso
que gera os achados `upstream_missing`.

Fonte: `GET /api/projects` ✅ (router `projects.py` já criado).

| Campo na UI | Origem | Status |
|---|---|---|
| nome do projeto | nome da pasta em `/opt/btv/*` | ✅ |
| caminho | `/opt/btv/<nome>` | ✅ |
| estado (no ar / parado / degradado) | `no ar` = todos os serviços running; `parado` = nenhum; `degradado` = alguns, ou um em restart/unhealthy | 🔧 |
| containers `on/total` | contagem de serviços do compose vs. rodando | 🔧 |
| memória da stack | soma de `mem_usage` dos containers da stack (de `/api/stats/all`) | 🔧 |
| aviso "domínio X aponta para stack parada" | cruzamento com `/api/ingress`: existe host cujo upstream resolve para container desta stack e a stack está parada | 🆕 |
| marcação "infraestrutura — não desligar" | allowlist de projetos de sistema (`docker-cockpit`, `global-ingress`) | 🔧 |
| botão Iniciar / Parar / Reiniciar | `POST /api/projects/{nome}/start|stop` ✅ — **exige `X-Cockpit-Unlock`** | ✅ |
| botão "Ver domínio" (parado com host) | navega para `#/ingress?host=<dominio>` | 🔧 |

Regras de tela:
- Ordenar **parado/degradado primeiro** — é o que precisa de ação.
- Sem sessão destravada, o botão de ação mostra "Destravar para agir" e abre o modal de
  destravamento (não executa nada).
- O aviso de domínio publicado sem upstream é o elo com `upstream_missing`: iniciar a stack
  daqui é o conserto do achado. Ao concluir, o achado deve resolver sozinho no próximo ciclo.
- Badge do rail = número de projetos parados que têm domínio ativo (não o total de parados).

---

## 2 · Auditoria — `#/auditoria`

Fonte: `GET /api/audit` 🆕 (tabela `audit`, já gravada pelas mutações; falta o endpoint de
leitura e a tela).

| Campo | Origem |
|---|---|
| quando | `audit.ts` (ISO UTC → relativo no cliente) |
| quem | usuário do basic auth do ingress, ou `ci-bot`/`—` |
| ação | `restart / start / stop / remove / unlock / ack / deploy` |
| alvo | container, stack, sessão ou id de achado |
| resultado | `ok`, `403` (negado sem unlock), prazo (para `ack`) |

Regras de tela:
- A linha **`403`** (tentativa de mutação sem destravar) é destaque proposital, em vermelho —
  é a prova visual de que o guard funciona. Não esconda.
- Painel "o que é auditado": lista explícita de que **toda mutação** é registrada e **nenhuma
  leitura** é. Deixa o limite de confiança visível para o perfil auditor.
- Card de sessão reflete o estado atual (destravada até ~HH:MM, ou em leitura).
- Só mutações aparecem aqui; inspects, logs e métricas não geram linha.

---

## 3 · Modal Destravar — dispara do rail e de qualquer ação de projeto/container

Fonte: `POST /api/session/unlock` 🆕 (TTL 30 min, devolve token para `X-Cockpit-Unlock`).

| Campo | Comportamento |
|---|---|
| motivo | **opcional**, texto livre — vai para o registro (`audit` da própria ação de unlock) |
| validade | fixa em 30 min; renova a cada ação |
| confirmar | grava o unlock, fecha o modal, libera os botões de mutação na sessão |

Ao expirar (30 min), a UI volta a travar sozinha sem recarregar — o token em `sessionStorage`
expira e o estado de leitura retorna. Nunca em `localStorage`.

---

## 4 · Modal Silenciar achado (ack) — botão "silenciar" em cada item da fila

Fonte: `POST /api/findings/{id}/ack` 🆕 — **a última pendência da F2**, ainda não implementada.

Corpo do POST:
```json
{ "reason": "aceito_estrutural | monitorando | falso_positivo",
  "note": "texto opcional",
  "until": "4h | 24h | 7d | 30d" }
```

| Campo na UI | Regra |
|---|---|
| motivo | **select obrigatório** de 3 opções; confirmar desabilitado até escolher |
| nota | texto livre opcional |
| prazo | 4h / 24h / 7d / 30d |
| efeito | achado sai da fila (`status = acked`, `ack_until` preenchido), continua no histórico, volta sozinho no prazo |

Regras já decididas (ver `00-decisoes-de-revisao.md`):
- `falso_positivo` conta **por regra** e alimenta a tela Backend & API (regra a revisar).
- Silenciar **não** é resolver — o texto do modal deixa isso explícito.
- Caso de uso canônico: os dois `healthcheck_never_passed` do criptotrade, quando a decisão
  for corrigir o Dockerfile depois em vez de agora.

---

## Onde cada uma encaixa nas fases

| UI | Fase | Backend | Frontend |
|---|---|---|---|
| Projetos | F5 (antecipada) | ✅ pronto | 🆕 desenhar a tela |
| Auditoria | F5 | 🆕 `GET /api/audit` | 🆕 desenhar a tela |
| Modal Destravar | F5 | ✅ `POST /session/unlock` | 🆕 modal + estado de sessão |
| Modal Silenciar | F2 (fatia final) | 🆕 `POST /findings/{id}/ack` | 🆕 modal + botão na fila |

O protótipo é a referência visual das quatro: tokens dos 3 temas, mono para valor/id/caminho,
cores de estado fixas. Abrir `Cockpit Docker.dc.html`, trocar perfil/tema/cenário nos controles.
