# Handoff — Cockpit Docker / VPS srv1351082

## Visão geral

Redesenho completo do painel `docker-cockpit` (repo `danzeroum/docker`), ampliado para cobrir
a VPS inteira: 15 containers, 12 stacks, 13 domínios servidos por um único gateway nginx.

O protótipo entrega, além do que existe hoje:

- **5 perfis de leitura** (Operador/SRE, Desenvolvedor, Aprendiz, Gestor, Auditoria) que mudam
  o conteúdo, não só a permissão.
- **Camada Dado → Informação → Conhecimento**: um controle global de profundidade reescreve
  as legendas de toda a tela. É a espinha dorsal do produto — ver seção "O contrato que sustenta tudo".
- **Visão geral sem rolagem** em 1440×900.
- **Dois painéis novos**: Ingress & TLS (análise do `nginx.conf` e dos certificados) e
  Capacidade (projeção de 24 h / 7 d / 30 d).
- **3 temas** (cockpit escuro, escritório claro, claro) via tokens CSS.
- **Modo leitura por padrão** com destravamento explícito de sessão para ações destrutivas.

## Sobre os arquivos deste pacote

`Cockpit Docker.dc.html` é uma **referência de design em HTML** — um protótipo que mostra
aparência e comportamento pretendidos. **Não é código de produção para copiar.** Todos os
dados dentro dele são simulados (ver `01-contrato-de-dados.md`, seção "Símbolos a eliminar").

A tarefa é **recriar essas telas no ambiente que já existe no repositório**: HTML + CSS + JS
puro, sem bundler, servido pelo FastAPI em `app/static/`. Não introduza React, build step ou
framework — o projeto hoje roda com `<script src>` simples e isso funciona bem para o caso.

Se em algum momento a decisão for migrar para um framework, faça isso como projeto separado,
não como efeito colateral desta entrega.

## Fidelidade

**Alta fidelidade.** Cores, tipografia, espaçamentos e estados são finais e devem ser
reproduzidos exatamente. Os valores estão tokenizados — ver "Design tokens" abaixo e o bloco
`<style>` no topo do `.dc.html`.

## O contrato que sustenta tudo

Cada dado exibido tem **três formas**, e o seletor de profundidade escolhe qual aparece:

| Camada | O que é | Exemplo real |
|---|---|---|
| **Dado** | o valor cru, como a fonte devolve | `exit 137 · OOMKilled: true · RestartCount 14` |
| **Informação** | o valor comparado ao esperado | `morto pelo kernel 14 vezes em 26 min` |
| **Conhecimento** | o que isso exige de você | `reiniciar não resolve — subir o limite de memória` |

**Consequência arquitetural:** as camadas de informação e conhecimento **não podem ser strings
no frontend**. Elas nascem do motor de achados no backend (`GET /api/findings`), que devolve
`{evidence, interpretation, recommendation}` por achado. O frontend só escolhe qual campo
renderizar conforme a profundidade ativa. Se isso for hardcoded no JS, o produto vira um
painel de números com legenda decorativa — que é exatamente o que ele não deve ser.

O perfil define a profundidade **inicial**, nunca a final (o usuário sempre pode trocar):

| Perfil | Profundidade inicial | Tela inicial |
|---|---|---|
| Operador / SRE | Informação | Visão geral |
| Desenvolvedor | Dado | Visão geral |
| Aprendiz | Conhecimento | Visão geral |
| Gestor / cliente | Conhecimento | Resumo executivo |
| Auditoria | Dado | Ingress & TLS |

## Telas

Onze telas, todas em um canvas fixo de **1440 × 900** com rail de 214 px e topbar de 60 px.
A área de conteúdo tem `padding: 14px 16px 16px` e `gap: 12px`.

| # | Tela | Propósito | Estrutura |
|---|---|---|---|
| 1 | **Visão geral** | tudo de relance, sem rolar | 3 colunas: stacks 262 px · centro 1fr · atenção 300 px |
| 2 | **Atenção agora** | causa-raiz de um incidente | 1fr + 350 px; cadeia temporal + evidências + ações |
| 3 | **Dossiê do container** | substitui as 10 abas atuais | chips de seleção + hero + 3 colunas de blocos |
| 4 | **Logs & métricas** | stream ao vivo | console 1fr + 3 cartões de métrica 330 px |
| 5 | **Ingress & TLS** | análise do nginx.conf | 5 KPIs + tabela de hosts 1fr + certificados/achados 360 px |
| 6 | **Topologia** | caminho da requisição | cadeia vertical 1fr + exposição/notas 320 px |
| 7 | **Backend & API** | saúde da própria API | 4 KPIs + tabela de rotas + permissões/streams/CI 340 px |
| 8 | **Capacidade** | antecipar problemas | 3 horizontes + projeção/consumo 1fr + evolução/postura 372 px |
| 9 | **Tarefas** | board vindo do diagnóstico | 4 colunas kanban |
| 10 | **Resumo executivo** | sem jargão, uma página | hero + 4 KPIs + serviços/riscos |
| 11 | **Plantão mobile** | 4h da manhã, do celular | 2 frames de 300 × 640 |

A descrição detalhada de cada componente (posição, tamanho, cor, tipografia, estados) está no
próprio `.dc.html` em estilos inline — é a fonte mais precisa possível e deve ser lida junto
com este documento. Nenhuma classe CSS é usada: cada elemento carrega seu estilo.

## Design tokens

27 tokens, definidos por tema em `[data-tema="..."]` no `<style>` do protótipo. Copie o bloco
inteiro para `app/static/css/themes.css` e troque o atributo `data-tema` no elemento raiz.

| Token | cockpit (escuro) | escritorio (claro) | claro |
|---|---|---|---|
| `--bg` | `#0a1020` | `#f4f6f8` | `#f1f5f9` |
| `--bg2` | `#0f1830` | `#eef1f5` | `#e2e8f0` |
| `--sf` | `#141f3a` | `#e5e9ef` | `#ffffff` |
| `--sf2` | `#1a2747` | `#d0d7de` | `#f8fafc` |
| `--rail1` / `--rail2` | `#0c1428` / `#080e1c` | `#e5e9ef` / `#dfe4ea` | `#ffffff` / `#f8fafc` |
| `--tx` | `#e6edf7` | `#1f2937` | `#0f172a` |
| `--tx2` | `#c8d4e6` | `#334155` | `#334155` |
| `--txd` | `#9aa7bd` | `#5b6b7f` | `#475569` |
| `--txm` | `#475569` | `#7c8899` | `#8592a5` |
| `--txf` | `#5b6880` | `#a3aebd` | `#a3aebd` |
| `--nt` | `#334768` | `#cbd5e1` | `#cbd5e1` |
| `--ac` | `#2496ED` | `#2563eb` | `#2563eb` |
| `--bd0`…`--bd3` | brancos .05→.16 | slate .2→.6 | slate .06→.22 |
| `--ok-t` | `#86efac` | `#0f8f63` | `#15803d` |
| `--bad-t` | `#fca5a5` | `#dc2626` | `#b91c1c` |
| `--wn-t` | `#fcd34d` | `#b45309` | `#b45309` |
| `--ac-t` | `#7dd3fc` | `#2563eb` | `#1d4ed8` |
| `--vi-t` | `#c4b5fd` | `#7c3aed` | `#6d28d9` |
| `--bezel` | `#1a2340` | `#cbd5e1` | `#cbd5e1` |
| `--r2` / `--r` / `--rc2` / `--rc` | 5 / 7 / 9 / 12 px | 4 / 4 / 8 / 8 px | 5 / 7 / 10 / 12 px |

**Cores de estado são fixas nos três temas**, de propósito: a leitura de gravidade não pode
mudar quando o tema muda.

`#22c55e` ok · `#f59e0b` atenção · `#ef4444` crítico · `#64748b` neutro · `#60a5fa` informativo
· `#a78bfa` rede. Tints com alfa hexadecimal: `+'1f'` (12%) para fundo de etiqueta, `+'22'`
(13%) para fundo de selo, `+'14'` para faixas.

### Tipografia

- **Inter** 400/500/600/650/700/800 — interface.
- **JetBrains Mono** 400/500/600 — todo valor numérico, id, rota, comando, nome de container.
  Essa separação é regra, não decoração: se é um dado do sistema, é monoespaçado.
- Escala usada: 8.5 / 9 / 9.5 / 10 / 10.5 / 11 / 11.5 / 12 / 12.5 / 13 / 13.5 / 14 / 15 / 17 /
  18 / 19 / 20 / 22 / 26 px.
- Rótulos de seção: 9–9.5 px, `letter-spacing: .14em`, `text-transform: uppercase`, peso 700,
  cor `#64748b`.

## Assets

Nenhum. Todos os ícones são SVG inline com `stroke="currentColor"`, `stroke-width` 2–2.5.
As fontes vêm do Google Fonts, como já acontece no `index.html` atual.

## Arquivos deste pacote

| Arquivo | Conteúdo |
|---|---|
| `README.md` | este documento |
| `01-contrato-de-dados.md` | **o mais importante** — cada campo da UI e sua origem real |
| `02-backend.md` | endpoints e módulos novos, com esquemas JSON |
| `03-frontend.md` | arquitetura, estado, camada de dados, temas, acessibilidade |
| `04-plano-de-entrega.md` | 6 fases, com critério de aceite por fase |
| `05-prompt-para-o-desenvolvedor.md` | prompt pronto para colar no Claude Code |
| `Cockpit Docker.dc.html` | o protótipo navegável (referência de design) |

Para abrir o protótipo: qualquer navegador. Troque perfil, tema e cenário pelos controles do
rail e da topbar — os três cenários (Normal, API caindo, Disco cheio) existem só para mostrar
o comportamento sob pressão e **não devem ir para produção** (ver `03-frontend.md`).
