# 10 · Cockpit Vivo — validação profunda (UI + frontend fluido, modelado como DDD)

Protótipo: `Cockpit Vivo.dc.html`. Evolução do doc 08/09: **todo objeto da interface é um
módulo**, cada nível (host → projeto → container) é um cockpit montável, e os vitais do
kernel são invariante — nunca saem da tela.

## 1 · O modelo de domínio da interface (DDD)

A validação pedida — "como se fosse DDD no código" — vira este mapa. A UI copia o domínio,
não o contrário.

**Contextos delimitados** (= abas/módulos, e no backend = routers já existentes):
Orquestração (containers/stacks) · Borda (ingress/TLS) · Observabilidade (logs/métricas) ·
Governança (achados, tarefas, auditoria, trava) · Capacidade.

**Agregados e raízes:**

| Agregado (raiz) | Identidade | Cockpit correspondente |
|---|---|---|
| Host `srv1351082` | hostname | Visão geral |
| Stack | nome do projeto compose | Mini cockpit do projeto |
| Container | `container_name` | Subtela central |

**A regra central: módulo = read model parametrizado por escopo.** O mesmo módulo
"Métricas" renderiza CPU do host no escopo host, soma da stack no escopo stack, série do
container no escopo container. É isso que dá o "mini cockpit para cada projeto" de graça:
não existem 3 telas — existe **1 registro de módulos × 3 escopos**.

```
Modulo = { id, nome, escopos: [host|stack|container],
           span, chip(escopo), render(escopo, dados) }
Escopo = { t: 'host' } | { t:'stack', id } | { t:'container', id }
```

**Invariantes de domínio (não negociáveis na UI):**
1. **Kernel sempre aparente** — os vitais do host são *chrome*, não módulo: não podem ser
   ocultados, arrastados nem cobertos pela subtela. No protótipo a régua fica fora da área
   rolável e a subtela abre abaixo dela.
2. A **faixa crítica** é do host inteiro: aparece em qualquer escopo, inclusive dentro do
   cockpit de um container de outra stack.
3. **Módulo oculto nunca oculta o dado** — o chip-resumo continua na régua, vivo e clicável.
4. **Layout pertence ao tipo de cockpit, não à instância** — um arranjo para todos os
   projetos, um para todos os containers (15 layouts distintos por stack seria caos de
   manutenção mental; é a mesma decisão do doc 00 sobre densidade constante).

**Linguagem ubíqua** — o nome na UI = nome no código = chave da API: `atencao`,
`containers`, `stacks`, `ingress`, `capacidade`, `metricas`, `logs`, `config`, `tarefas`,
`auditoria`. Sem sinônimos ("workloads", "serviços") em nenhuma camada.

## 2 · Validação de designer UI

| Ponto | Veredito · racional |
|---|---|
| Navegação em 3 níveis | Host → stack por clique no módulo Stacks; qualquer container → subtela central por clique na linha/cartão. Volta: breadcrumb "← Visão geral", chip `stack:` na subtela, Esc, clique no fundo. Nunca mais de 2 cliques entre quaisquer dois níveis |
| Subtela central vs página | Central (grid vira painel sobre fundo escurecido) mantém o kernel e a faixa visíveis **por construção** — atende o requisito "informações do kernel sempre aparentes". Página cheia esconderia a régua sob scroll |
| Densidade por escopo | Host: 15 linhas sem rolagem (doc 08). Stack: 1–2 containers → módulos de 6 col não ficam vazios porque mostram agregados, não listas. Container: 7 módulos ≈ 820px — cabe em 1 tela com logs em largura inteira |
| Drag & drop | Só no modo Personalizar (outline tracejado + alça ⋮⋮): não conflita com cliques de navegação nas linhas; ↑↓ continuam no painel (a11y, pendência #14). Troca por swap ao pairar — sem flicker de inserção |
| Presets ("sugestões prontas") | Host: Operação / Capacidade / Executivo · Stack: Operação / Deploy · Container: Diagnóstico / Configuração. Preset = ponto de partida nomeado; qualquer ajuste vira "personalizado" sem perder o preset de origem |
| Reconhecimento vs memorização | Chips nomeiam o que está oculto; painel único lista tudo com olho/largura/ordem; nota do painel explica o contrato ("oculto continua na régua") |
| Cor | Inalterada do doc 08: cor é sinal (estado), cromo é cinza-azulado. A subtela não introduz cores novas — só elevação (sombra + backdrop) |

**Riscos apontados (honestos):** drag por HTML5 não funciona em touch — mitigado pelos ↑↓;
swap (em vez de inserção) surpreende em movimentos longos — aceito na v1, medir; a subtela
sobre cenário "disco cheio" empilha faixa + régua + painel (~180px de chrome) — validado:
sobra 720px úteis, os 7 módulos cabem com scroll interno só no cenário de pior caso.

## 3 · Validação de frontend fluido (dados reais, zero mock)

Tudo da seção C do doc 09 continua valendo; o que o Cockpit Vivo acrescenta:

| Necessidade nova | Fonte real |
|---|---|
| Containers/achados/tarefas/auditoria **por escopo** | Mesmos endpoints com filtro: `/api/findings?target=`, `/api/tasks?stack=`, `/api/audit?target=` — hoje filtram no cliente ✅; query param é otimização 🔧 |
| Módulo Logs | `/api/logs/{name}?tail=50` ✅ (SSE já existente; stack = merge dos containers da stack no cliente) |
| Módulo Config (compose efetivo) | `/api/inspect/{name}` — imagem, portas, limites, healthcheck, restart policy ✅ via socket-proxy (somente GET) |
| Módulo Métricas por escopo | container: `/api/stats/{name}` ✅ · stack: soma no cliente 🔧 · host: `/api/overview.vitals` ✅ |
| Séries (sparklines) | `/api/metrics/history?series=…&target=…` ✅ (host) · por container exige gravar `target` no sampler 🆕 pequeno |
| `summary` da régua | doc 09 §B — inalterado; chips de escopo derivam dos payloads já carregados pelos módulos visíveis |

**Complexidade (Big-O honesto):** reorder = swap O(1) + re-render de ≤10 cards; render de
lista 15 linhas = trivial; polling = 1 fetch/módulo visível (módulo oculto: zero fetch, chip
vive do summary — a régua custa 1 chamada, não 10). Persistência: 1 write de ~200 bytes por
gesto concluído. Nada disso justifica virtual-dom framework novo — o vanilla atual aguenta.

**Padrões aplicados (nomes para o dev):** Registry (módulos), Strategy (render por escopo),
Observer (loop de polling → módulos inscritos), Memento (layout salvo/restaurado por tipo).
SRP: módulo não conhece módulo; só o registro conhece todos.

## 4 · Recomendações dos e-books

[RECOMENDAÇÃO — Métricas na Gestão de Projetos, Raphael Donaire Albino · OKR e alinhamento]
Cada preset de cockpit deve responder a um objetivo, não a um gosto: Operação → MTTR (o
crítico está a 0 cliques), Capacidade → antecedência da projeção (dias até 90%), Executivo →
resultado por projeto (tarefas/achados). Se um módulo não alimenta a decisão do preset, sai
dele. Meça effectiveness (achado→tarefa→feito), não vaidade (nº de módulos abertos).

[RECOMENDAÇÃO — Algoritmos e Padrões de Projetos, Renan de Oliveira · SOLID/Patterns/Big-O]
Trate o registro de módulos como contrato (interface única `render(escopo)`), aberto para
extensão e fechado para modificação: módulo novo = 1 arquivo novo, zero `if` no núcleo.
Valide a complexidade declarada: reorder O(1), render O(n) com n=15, nenhum O(n²) escondido
em "filtrar achados por alvo" (indexe por alvo uma vez por poll).

[RECOMENDAÇÃO — Sistemas de Uso Intensivo de Dados, Etienne Cartolano · Qualidade dos dados]
Um dado, uma origem: chips e módulos leem o MESMO payload (summary/read models) — nunca duas
consultas que possam divergir na mesma tela. Exiba a idade do dado ("leitura a cada 5s") e
degrade explicitamente quando o sampler falhar; módulo sem dado mostra ausência, não zero.

[RECOMENDAÇÃO — Analytics em Negócios, Marcelo H. de Araujo · Análise descritiva/Amostragem]
Sparklines e projeções são análise descritiva sobre amostra (5s, janelas 24h/30d): declare a
janela em cada módulo (como "amostra 5s · janela 24h"), não extrapole além do que o r²
sustenta (a projeção já se cala com r²<0.7 — manter no escopo container), e some CPUs de
stack apenas como agregado descritivo, nunca como "capacidade prevista".

## 5 · Prompt para o desenvolvedor

```xml
<lang>Vanilla JS ES modules (app/static/js) + FastAPI Python 3.11 + CSS custom properties</lang>
<task>Implementar o Cockpit Vivo (doc 10): registro único de módulos com render por escopo (host/stack/container), drag no modo personalizar, presets nomeados e subtela central de container — sem nenhum dado mockado (fontes na §3 e no doc 09 §C).</task>
<context>Protótipo: Cockpit Vivo.dc.html. Contrato: Modulo={id,nome,escopos,span,chip(escopo),render(escopo,dados)}; Escopo={t:'host'}|{t:'stack',id}|{t:'container',id}. Persistência localStorage["cockpit.layout.{host|stack|container}"]={v:1,ordem,ocultos,cheios,preset}. Invariantes: régua do kernel fora da área rolável e sem ocultação; faixa crítica global em todo escopo; módulo oculto mantém chip vivo via overview.summary; layout por tipo de cockpit, não por instância. Endpoints: /api/overview(+summary), /api/findings, /api/tasks, /api/audit, /api/logs/{name}, /api/inspect/{name}, /api/stats/{name}, /api/metrics/history.</context>
<rules>
- Pense passo a passo: (1) registro de módulos, (2) escopos e read models, (3) régua, (4) personalizar+drag+presets, (5) subtela.
- Drag só com personalizar ativo; ↑↓ e olho permanecem (a11y #14: :focus-visible, aria-pressed).
- 1 fetch por módulo visível no loop de polling compartilhado; oculto = zero fetch.
- Subtela central: overlay abaixo do header+régua; Esc, ✕ e clique no fundo fecham.
- Saída: apenas os blocos de código.
</rules>
<aceite>
- grep no JS não encontra container, domínio ou métrica escrita à mão.
- Mesmo módulo renderiza nos 3 escopos sem código duplicado (1 registro, N escopos).
- Kernel visível em 100% dos estados (host, stack, container, personalizar aberto).
- Preset aplicado → ajuste manual → rótulo vira "personalizado"; restaurar volta ao padrão.
</aceite>
<testes>
- Layout corrompido no localStorage → padrão + console limpo.
- Stack com 1 container → módulos agregados renderizam sem estado vazio quebrado.
- Container sem domínio → módulo ingress mostra "rede interna", não erro.
- Ocultar capacidade → zero fetch a /api/capacity; chip segue via summary.
- Reorder por drag e por ↑↑ produzem o mesmo estado persistido.
</testes>
<recomendacao>
- SOLID: registro aberto a extensão (módulo novo sem tocar o núcleo); indexar achados por alvo 1× por poll (nada de O(n²)).
- Dados: chips e módulos leem o mesmo payload; exibir idade do dado; ausência ≠ zero.
- Analytics: declarar janela/amostra em todo gráfico; projeção continua calada com r²<0.7.
- Métricas de projeto: cada preset amarrado a um objetivo (MTTR, antecedência, resultado) — revisar depois com dados de uso.
</recomendacao>
```

Fontes das recomendações: e-books da série (Raphael Donaire Albino; Renan de Oliveira;
Etienne Cartolano; Marcelo H. de Araujo), aplicados via skills `recomendacoes-*`.
