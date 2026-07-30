# 14 · Plano consolidado — backend B1–B11 × face de interface

Funde três coisas que até aqui viviam separadas: os prompts de backend B1–B11
(`blocos-b1-b11-prompts-completos.md`), a face de interface dos docs 10/11/12, e o que a
Sprint 1 efetivamente entregou (`13-blocos-agregados.md`). Nada dos três se perde.

Obedece às 4 regras do `LEIA-ME.md`: zero mock, kernel invariante, chip vivo, ações
fail-closed auditadas antes de executar.

---

## 1 · Dois pré-requisitos que a Sprint 2 assume e que não existem

Este é o achado principal da revisão do protótipo. As duas coisas abaixo são **fundação**,
não detalhe, e a Sprint 2 proposta ("portar módulo Armazenamento e Eventos, registrados no
registro de módulos; summary da régua ganha 3 chaves") pressupõe as duas prontas.

### 1.1 O registro de módulos não existe

O doc 10 §1 define `Modulo = {id, nome, escopos, span, chip(escopo), render(escopo, dados)}`
e o doc 10 §4 é explícito: *"módulo novo = 1 arquivo novo, zero `if` no núcleo"*.

O que existe hoje em `app/static/js/main.js:71-85` é o oposto exato:

```js
switch (_route(screen)) {
  case '#/overview':   dispose = renderOverview(container); break;
  case '#/capacidade': dispose = renderCapacidade(container); break;
  // ... 13 cases
}
```

São **13 telas de página cheia num switch**, não 13 módulos × 3 escopos. Um `case` por tela
no núcleo é literalmente o que o doc 10 proíbe. Além disso não há escopo (`{t:'stack', id}`),
não há régua de chips, não há modo Personalizar, não há subtela central — o prompt do doc 10
§5 ("Implementar o Cockpit Vivo") nunca foi executado.

Consequência prática: **não é possível "registrar um módulo no registro de módulos" antes de
o registro existir.** O trabalho de UI da Sprint 2 tem um pré-requisito maior do que os dois
módulos que ele quer acrescentar.

Alguns nomes coincidem entre as telas atuais e os módulos do protótipo (`capacidade`,
`ingress`, `tarefas`, `auditoria`, `atencao`), mas são conceitos diferentes: tela = rota de
página cheia; módulo = read model parametrizado por escopo. A migração reaproveita o **corpo**
de cada tela (o doc 09 §A já mapeia isso como 🔧), não a estrutura.

### 1.2 `/api/overview` não tem bloco `summary`

O doc 09 §B item 1 especifica o `summary` com 6 chaves (`findings`, `stacks`, `ingress`,
`capacity`, `audit`, `tasks`) e o justifica: *"alimenta a régua inteira em 1 chamada, sem 6
fetches por poll"*. Está marcado 🆕 e **nunca foi implementado** — `grep summary
app/routers/overview.py` não devolve nada.

Isso sustenta o invariante 3 (módulo oculto mantém chip vivo) e a conta de complexidade do
doc 10 §3 ("a régua custa 1 chamada, não 10"). Sem ele, chip vivo com módulo oculto é
impossível sem N fetches.

Portanto: acrescentar `storage.reclaimable`, `security.min_score` e `updates.outdated` ao
`summary` — pedido da Sprint 2 — exige **primeiro criar o `summary`** com as 6 chaves
originais. É o "1 PR pequeno" do doc 09 §B, ainda em aberto.

### 1.3 Terceira lacuna, menor: a UI não sabe se `ENABLE_ACTIONS` está ligado

O aceite do doc 11 é mais rígido do que "renderizar cinza": *"Sem ENABLE_ACTIONS: nenhum
botão de ação existe no DOM (não é `display:none`)"*. Para cumprir isso o frontend precisa
**saber** o valor da flag, e hoje nenhuma rota o expõe.

Menor esforço coerente com o resto: a flag entra no próprio `summary`
(`summary.capabilities.actions_enabled`), junto com `unlock.active`. Um endpoint
`/api/capabilities` separado custaria mais um fetch por poll, contra a economia que motiva o
`summary`.

---

## 2 · Decisão pendente: linguagem ubíqua nas chaves novas

O doc 10 §1 fixa: *"o nome na UI = nome no código = chave da API. Sem sinônimos em nenhuma
camada."* Há um conflito real entre o que a Sprint 1 entregou e o que os docs 09/12 esperam:

| Docs 09 §B / 12 esperam | Sprint 1 entregou |
|---|---|
| `summary.storage.reclaimable` | `/api/storage` → `reclaimable_bytes` |
| `summary.security.min_score` | `/api/security` → `summary.score_minimo` |
| — | `/api/security` → `violacoes_por_severidade`, `conformes` |

O repo já é bilíngue por decisão anterior: ids de módulo e de tela são em português
(`atencao`, `capacidade`, `metricas`), mas as chaves do `summary` no doc 09 §B são em inglês
(`open`, `critical`, `days_to_90`).

**Recomendação:** as chaves do `summary` seguem os docs 09/12 **verbatim** — é o contrato que
o protótipo e os docs referenciam, e é o payload que a régua lê. Os payloads dos endpoints
`/api/storage` e `/api/security` ficam como estão; o construtor do `summary` mapeia de um para
o outro. Assim nenhum contrato já entregue quebra e a régua fica exatamente como
especificada. Reversível: é um mapeamento num único lugar.

Se a preferência for unificar tudo em português, a hora de decidir é **antes** da Sprint 2 —
depois de a régua existir, renomear chave é mudança em três camadas.

---

## 3 · Onde a Sprint 1 deixou os docs desatualizados

Dois pontos a corrigir nos docs, para não gerar trabalho duplicado:

- **Doc 10 §3** diz que sparkline por container *"exige gravar `target` no sampler 🆕
  pequeno"* e aponta para `/api/metrics/history?series=…&target=…`. Isso foi resolvido, mas
  por outro caminho: `GET /api/containers/{id}/history?range=` (rota própria, resolução
  `raw`/`hourly` no payload, teto de 500 pontos). A linha do doc 10 §3 deve apontar para a
  rota nova.
- **Doc 12** lista `/api/storage`, `/api/containers/{id}/history` e `/api/security` como
  *"novos endpoints exigidos"*. Os três **existem** desde a Sprint 1. Restam exigidos:
  `/api/events` (histórico paginado), `/api/logs/search` e `/api/updates`.
- **Anexo B1–B11** e o `LEIA-ME` dizem que os prompts XML completos "estão com o
  desenvolvedor". Eles estão no repo, em
  `docs/handoff_cockpit_completo/docs/blocos-b1-b11-prompts-completos.md`.

---

## 4 · Roadmap consolidado

Ordem de backend do autor (B3/B5 → B6/B7/B9 → B8/B11 → B10) cruzada com a ordem de valor
para a interface do doc 11 (B2 → B4 → B3 → B1+B10 → B5 → B6 → B8).

| Sprint | Backend | Design/UI |
|---|---|---|
| ~~1~~ ✅ | ~~B2 histórico/rollup · B1 storage · B4 security~~ | ~~Cards na Capacidade · badge Health na lista~~ |
| **2a — fundação** | `summary` no `/api/overview` (6 chaves do doc 09 §B + `capabilities` + as 3 novas) | **Registro de módulos** + escopos + régua de chips + Personalizar + subtela central (doc 10 §5). Migra as 13 telas para módulos reaproveitando os corpos |
| **2b** | B3-residual (ring SQLite v11 + filtros server-side + `GET /api/events`) · B10-residual (prune dry-run, `ENABLE_ACTIONS`, audit-antes, v12) | Módulo **Armazenamento** (GB recuperáveis + prune atrás da trava) · Módulo **Eventos** (3 escopos) · Subtela: sparklines de `/history` + score B4 com violações |
| **3** | B5 logs FTS5 + follow SSE | Upgrade do módulo **Logs**: busca com highlight + selo ● follow |
| **4** | B6 updates Hub · B7 notificações · B9 `/metrics` | Badge "desatualizada" com `consultado_em` · selo "notificado hh:mm · canal" no achado |
| **5** | B8 drift · B11 hardening | Módulo **Drift** + chip na régua · dívida `sw.js` (telas fora do `STATIC_ASSETS`, com teste de invalidação) |

A Sprint 2 foi partida em **2a/2b** por causa do §1: juntar a fundação do Cockpit Vivo com
dois módulos novos numa sprint só é o tipo de escopo que estoura no meio e deixa as duas
metades pela metade. 2a não entrega feature nova — entrega a estrutura que torna 2b, 3, 4 e 5
trabalho de "1 arquivo novo por módulo", que é a promessa do doc 10.

**Critério de aceitação do conjunto** (inalterado): o roteiro de 2 min do doc 12 executado
contra dados reais — cenário API caindo → subtela do container → buscar `oom` nos logs →
destravar → reiniciar → auditoria → chip Drift → Personalizar — com `grep` no JS não
encontrando nome de container, domínio nem métrica escrita à mão (doc 01).

---

## 5 · Blocos residuais da Sprint 2

### B3-residual — persistência e filtros de eventos
Prompt do revisor mantido. Duas notas de implementação:

- Migration **v11**. Vale a regra dura do doc 00: *toda migração de esquema tem teste com
  banco populado antes do deploy* — a v3 perdeu `first_seen` em produção por não ter isso.
- "Mesmo consumer" é a regra certa: `app/events.py` já mantém um único stream com backoff e
  já faz `_broadcast` + `_invalidate_caches`. Persistir é acrescentar um consumidor à
  função de broadcast, **não** abrir um segundo stream `/events`.
- Ring por contagem reaproveita `purge_samples`, que já roda a cada ciclo de 60 s do
  `sampler`. Não precisa de trigger nem de tarefa nova.

### B10-residual — prune, flag e auditoria-antes
Prompt do revisor mantido. A alegação central confere no código: `_mutate_container`
(`app/routers/containers.py:257-268`) chama `add_audit_entry` **depois** de `proxy_fn`
retornar, ou no `except`. Ação que trava o daemon não gera linha nenhuma.

Notas:
- O refactor é uma **migração** (`audit_log` ganha o par `started`→resultado). Migration
  **v12**, com teste de banco populado, mesma regra acima.
- `ENABLE_ACTIONS=0` cobrindo também as 4 rotas da F5 (`start/stop/restart`, `DELETE`) e as
  2 de stack é o ponto mais importante do bloco: uma flag que cobrisse só o `prune` daria
  falsa sensação de read-only, com a superfície de mutação da F5 aberta ao lado.
- `dry_run` fora do build cache mantém coerência com o `reclaimable_bytes` do B1, que já
  exclui build cache de propósito.

### S2-UI — módulos + régua
Prompt do revisor mantido, com o pré-requisito do §1.1 explicitado no `<context>`: o registro
de módulos é entregável da 2a, não premissa. E o `<rules>` ganha a linha do §1.3 — o botão só
não existe no DOM se a UI souber a flag, o que exige `summary.capabilities`.

### S2-UI-subtela — sparklines + score
Prompt do revisor mantido. O backend está pronto e os dois aceites amarram bem:
- score 55 para `privileged`+`root` é a aritmética já congelada no backend e coberta por
  teste (`tests/test_security.py::test_privileged_mais_root_da_55_com_duas_violacoes`);
- `history` vazio → "coletando…" é a borda do primeiro dia de uso, e o payload já entrega o
  que a UI precisa para distinguir: `points: []` com `point_count: 0`, mais `retention` para
  a tela declarar a janela (exigência do doc 10 §4, análise descritiva).

---

## 6 · Registro de validação

Revisão do protótipo `Cockpit Vivo Completo.dc.html` feita contra os docs 09–12, não linha a
linha: o arquivo é saída compilada (`<x-dc>` + `support.js`, identificadores de uma letra), o
que torna leitura de código improdutiva. O que foi conferido: os 13 ids de módulo
(`armazenamento, atencao, auditoria, capacidade, config, containers, drift, eventos, ingress,
logs, metricas, stacks, tarefas`), os 7 presets nos 3 escopos, e os dados de demo que precisam
morrer na implementação (`criptotrade-app`, `familia-web`, `giva-api`, `prompte`,
`redis-teste`, `juridico`, `docker-cockpit-proxy`) — que é exatamente o teste de `grep` do
doc 01.
