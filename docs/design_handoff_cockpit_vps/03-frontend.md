# 03 · Frontend — o que construir

Ambiente atual: HTML + CSS + JS puro em `app/static/`, carregado por `<script src>` em ordem,
servido pelo FastAPI. **Mantenha assim.** Não há bundler e o projeto não precisa de um.

## 0 · Replanejamento

| Item | Situação hoje | O que fazer |
|---|---|---|
| **Navegação** | 10 abas na topbar + `scrollIntoView` por âncora | rail de 11 destinos; uma tela ativa por vez; sem scroll programático |
| **Estado** | 4 `let` globais em `state.js` | store único com `subscribe`, persistido em `localStorage` |
| **Fetch** | `fetch` espalhado, sem tratamento de erro | `data.js`: uma função por recurso, com cache, retry e estado `loading/error/empty` |
| **Erro** | um fetch que falha quebra a tela | cada painel renderiza seu próprio estado de erro sem derrubar os vizinhos |
| **Tema** | `html.light` + `localStorage['cockpit-theme']` | `[data-tema]` com 3 temas; migrar o valor antigo (`light` → `claro`) |
| **`scrollIntoView`** | usado em `main.js` | remover — quebra o layout de tela fixa |
| **Acessibilidade** | sem foco visível, sem rótulos | `:focus-visible`, `aria-current` no rail, `role="status"` na fila |

## 1 · Arquitetura de arquivos

```
app/static/
  css/
    base.css          reset + layout (existe)
    themes.css        NOVO — os 27 tokens × 3 temas
    components.css    aparar o que virou tela nova
  js/
    store.js          NOVO — estado + subscribe + persistência
    data.js           NOVO — camada de rede (fetch, cache, SSE, WS)
    fmt.js            helpers (existe como helpers.js)
    screens/
      overview.js  incidente.js  dossie.js  logs.js  ingress.js
      topologia.js backend.js    capacidade.js tarefas.js executivo.js
    ui/
      rail.js  topbar.js  kpi.js  finding-card.js  panel.js
    main.js           roteamento por hash + boot
```

Uma tela = um módulo com `render(container, dados)` e `dispose()`. O roteador troca a tela
ativa e cancela assinaturas (SSE/WS) da anterior — sem isso, sair da tela de Logs deixa o
stream aberto.

## 2 · Estado

```js
{
  screen: 'overview',        // hash da URL, fonte da verdade
  perfil: 'sre',             // localStorage cockpit-perfil
  depth: null,               // null = herda do perfil; localStorage cockpit-depth
  tema: 'cockpit',           // localStorage cockpit-tema
  selectedContainer: null,   // ?c= na URL
  selectedFinding: null,     // ?f= na URL
  unlock: { token: null, expiresAt: null },  // sessionStorage, nunca localStorage
  search: '', filter: 'all'
}
```

Regras:

- **URL é o estado compartilhável**: `#/ingress`, `#/dossie?c=criptotrade-app`,
  `#/incidente?f=oom.criptotrade-app`. Colar o link no chat do plantão tem que abrir a mesma tela.
- `depth` volta a `null` quando o perfil muda (o perfil redefine o padrão).
- **Persista exatamente três chaves**: `cockpit-perfil`, `cockpit-depth`, `cockpit-tema`.
  `screen` e `selectedContainer` não persistem — a URL é a fonte da verdade e um valor salvo
  briga com o hash no reload.
- O token de destravamento vive em `sessionStorage` e expira sozinho; ao expirar, os botões
  voltam para o estado travado sem recarregar a página. **Nunca** em `localStorage`: lá ele
  sobrevive a fechar o navegador e a sessão de 30 min vira ficção.
- **Nunca** apagar chaves de `localStorage` que não sejam as três acima.

## 3 · Camada de dados

| Recurso | Método | Frequência |
|---|---|---|
| `/api/overview` | fetch + cache 5 s | 5 s enquanto a Visão geral estiver aberta |
| `/api/findings` | fetch | 15 s, ou push por evento |
| `/api/ingress`, `/api/certificates` | fetch | 5 min (dado de arquivo, não muda sozinho) |
| `/api/metrics/history` | fetch | ao abrir a tela |
| logs | SSE | só com a tela de Logs aberta |
| stats de 1 container | WS | só com o Dossiê aberto |
| eventos do daemon | SSE | sempre, quando existir |

Toda chamada tem timeout de 10 s e devolve `{data, error, stale}`. Painel com erro mostra o
último dado bom com a etiqueta "desatualizado há Xs" em vez de sumir.

### Polling

Um **único loop compartilhado** no `main.js`, não um `setInterval` por tela — e ele pausa em
`visibilitychange` quando `document.hidden`. Sem isso, uma aba esquecida bate no daemon a cada
5 s a noite inteira, e o cockpit vira a maior fonte de carga que ele mesmo mede.

`dispose()` de cada tela aborta fetch em voo (`AbortController`) e fecha SSE/WS — sem isso, a
resposta de uma tela morta chega e sobrescreve o DOM da tela nova.

### Service worker

O `sw.js` cacheia estáticos. Três regras:

1. **Nome de cache estático e versionado** (`cockpit-v2`), nunca gerado em runtime — nome
   dinâmico cria um cache novo a cada ativação e órfãos que ninguém apaga.
2. **`activate` apaga tudo que não casa com a versão atual.**
3. **Network-first para navegação.** Durante a fase que reescreve `index.html` e os módulos,
   network-first para **tudo** (HTML, JS e CSS): servir HTML novo com JS velho do cache dá
   erro incompreensível. Volte a cache-first só depois de estabilizar.

Mais `skipWaiting()` + `clients.claim()` na release que troca o shell, para não depender de o
usuário fechar todas as abas.

## 4 · Profundidade — como o frontend usa

```js
const CAMPO = { dado: 'evidence', informacao: 'interpretation', conhecimento: 'recommendation' };
function textoDe(finding, depth, simples) {
  const base = CAMPO[depth];
  return simples ? (finding[base + '_plain'] ?? finding[base]) : finding[base];
}
```

`simples` é verdadeiro para os perfis Gestor e Aprendiz. **Nenhum texto de interpretação ou
recomendação é escrito no frontend.** Se o backend não mandou, o campo fica vazio — e isso é
um bug de backend visível, não um buraco disfarçado com texto genérico.

## 5 · Temas

**Os nomes de token do repositório mandam — não importe os nomes curtos do protótipo.** O
`components.css` (12,8 KB) inteiro depende de `--surface`, `--text-dim`, `--accent`,
`--border`; trocar os nomes obrigaria a reescrever o arquivo sem ganho nenhum. Mapeamento:

`--sf`→`--surface` · `--sf2`→`--surface-2` · `--bg2`→`--bg-2` · `--tx`→`--text` ·
`--txd`→`--text-dim` · `--txm`→`--text-mute` · `--ac`→`--accent` · `--bd1`→`--border` ·
`--bd3`→`--border-strong`. Acrescente os que faltam: `--rail-1/2`, `--radius`,
`--radius-card`, e os tints `--ok-t` / `--bad-t` / `--warn-t` / `--accent-t`.

Os três blocos `html[data-tema="..."]` vão para `themes.css` e **substituem** o `:root{}` e o
`html.light{}` do `base.css` — substituem, não convivem. Migração da chave antiga:

```js
const antigo = localStorage.getItem('cockpit-theme');   // 'light' | 'dark'
const tema = localStorage.getItem('cockpit-tema') ?? (antigo === 'light' ? 'claro' : 'cockpit');
```

Cores de estado (`#22c55e`, `#f59e0b`, `#ef4444`, `#64748b`) **não** entram no tema.

## 6 · O que sai do protótipo antes de ir para produção

| Elemento | Motivo |
|---|---|
| Seletor **Cenário** (Normal / API caindo / Disco cheio) | recurso de demonstração. Ou remova, ou deixe atrás de `?demo=1` para treinamento — nunca visível em produção |
| Seletor **A · Faixa / B · Fila / C · Discreto** | era exploração de design. **Decida um** e deixe fixo. Recomendação: **B (fila priorizada)** como padrão, promovendo para faixa (A) automaticamente quando houver achado `critical` — o layout só se mexe quando é grave de verdade |
| Latência por salto na Topologia | sem fonte real |
| "Disponibilidade 99.8%" no executivo | sem histórico até o coletor rodar 30 dias |

## 7 · Estados que faltam no protótipo e precisam existir

- **Carregando**: esqueleto por painel (o `index.html` atual já tem `.skeleton`, reaproveite).
- **Vazio**: "nenhum achado aberto" é um resultado bom — desenhe com verde discreto, não como
  erro.
- **Erro por painel**: título do painel + "não foi possível ler /api/ingress" + botão tentar
  de novo.
- **Permissão**: se o socket-proxy não tiver `EVENTS`/`SYSTEM`, os painéis dependentes
  explicam o que habilitar em vez de mostrar zero.
- **Primeira execução**: sem histórico, a tela de Capacidade mostra "coletando desde hoje —
  projeção disponível em 7 dias".

## 8 · Acessibilidade e detalhes de acabamento

- Contraste: o tema **escritório** foi ajustado para AA em texto normal; ao criar variações,
  verifique `--txd` sobre `--sf` (hoje 4.6:1).
- Foco visível em todo elemento clicável — no protótipo há muitos `<div onClick>`; na
  implementação, use `<button>` real com `background: none; border: 0` e `:focus-visible`.
- O rail é navegação: `<nav>` + `<a href="#/ingress">` + `aria-current="page"`.
- `⌘K` abre a busca (o `commands.js` atual já tem a paleta — reaproveite e amplie para hosts
  e achados, não só containers).
- Nada abaixo de 9 px, nada abaixo de 4.5:1 em texto informativo.

## 9 · Responsividade

O canvas é 1440 × 900. Regras de degradação:

| Largura | Comportamento |
|---|---|
| ≥ 1440 | layout do protótipo |
| 1200–1439 | coluna direita (atenção) desce para baixo do centro; grade vira 2 colunas |
| 900–1199 | rail colapsa para 56 px (só ícones); stacks viram acordeão |
| < 900 | layout mobile do protótipo: fila de atenção em pilha, sem grade |

O mobile de plantão não é uma versão reduzida do desktop — é a fila de achados e a ação. Só
isso.
