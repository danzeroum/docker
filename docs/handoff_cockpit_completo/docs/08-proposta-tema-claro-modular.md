# 08 · Proposta — tema claro minimal + módulos ajustáveis

Protótipo: `Cockpit Claro Modular.dc.html` (raiz do projeto). Base de dados usada na validação:
estado real da `main` em 2026-07-30 — 15 containers, 12 stacks ativas (15 projetos em disco),
13 hosts públicos + 1 interno, 17 regras, fila típica de 3–8 achados.

## 1 · Validação de densidade — a interface aguenta o dado que carrega?

Veredito por tela, contra o volume real:

| Tela | Volume real | Veredito | Sugestão significativa |
|---|---|---|---|
| Visão geral | 15 containers + 12 stacks + fila + vitais | **No limite.** Grade de cartões (15 × ~120px) não cabe em 900px; o operador rola para ver o todo | Lista compacta como modo padrão a partir de ~12 containers; cartões viram opção. Uma linha por container mostra os 15 sem rolagem |
| Atenção agora | 3–8 achados (agregação já comprime 13 alvos em 1) | **Adequada** — o corte de 8 com "ver todos" está certo | Não mostrar corpo do achado em densidade compacta; título + severidade bastam para triagem |
| Projetos (stacks) | 15 cards com ações | **Adequada** até ~20; depois exige busca já existente | Cards só para stack com problema; sadias podem ser linha |
| Ingress & TLS | 13 hosts + certificados + achados | **Adequada** — agregação (`AGGREGATE=True`) é o que a salva | Manter totais só de públicos (decisão F3) |
| Topologia | 15 nós, arestas reais | **Adequada** neste porte; ilegível acima de ~30 nós | Colapsar por stack quando passar disso |
| Capacidade | série 30d + projeção | **Adequada** | Projeção continua calada com r²<0.7 (decisão F4) |
| Auditoria / Tarefas | dezenas de linhas / 6 cartões | **Adequada** | — |

Conclusões transversais:

1. **Nenhuma informação vital pode morar só dentro de um módulo.** A proposta cria uma
   **régua de status permanente** (CPU, RAM, disco, swap + um chip-resumo por módulo).
   Ocultar um módulo nunca oculta seu número.
2. **Profundidade A/B/C deve substituir conteúdo, não acumular.** A 2ª linha do container é
   *ou* imagem (dado) *ou* achado (informação) *ou* recomendação (conhecimento) — densidade
   constante em qualquer profundidade (mesma regra do `overview.js` real).
3. **Escala futura:** acima de ~30 containers a lista precisa de virtualização/paginação; o
   grid de módulos em si aguenta.

## 2 · Tema `claro-minimal`

Princípios: **cor é sinal** (cinza-azulado para tudo que é cromo; verde/âmbar/vermelho
exclusivos de estado), hairlines no lugar de sombras e gradientes, números sempre em
JetBrains Mono, brancos generosos. Nada de glow, gradiente ou borda-esquerda colorida.

Tokens no vocabulário de `app/static/css/themes.css` (substitui o `claro` atual ou entra
como 4º tema):

```css
html[data-tema="claro-minimal"]{
  --bg:#f6f7f9; --bg-2:#eef0f4; --surface:#ffffff; --surface-2:#fbfcfd;
  --border:#e7eaf0; --border-strong:#d6dce5;
  --text:#0f172a; --text-dim:#475569; --text-mute:#94a3b8;
  --accent:#2563eb; --accent-2:#1d4ed8;
  --ok:#16a34a; --ok-soft:rgba(22,163,74,.10);
  --warn:#d97706; --warn-soft:rgba(217,119,6,.10);   /* texto sobre soft: #b45309 */
  --bad:#dc2626;  --bad-soft:rgba(220,38,38,.10);    /* texto sobre soft: #b91c1c */
  --neutral:#64748b; --neutral-soft:rgba(100,116,139,.12);
  --ease-quiet:cubic-bezier(.22,1,.36,1); --ease-precise:cubic-bezier(.4,0,.2,1);
}
```

Contraste verificado para texto ≥10.5px nos pares usados (texto #0f172a/#475569 sobre
#ffffff/#f6f7f9; estados sobre *-soft usam as variantes de texto anotadas).

## 3 · Sistema de módulos da Visão geral

- Registro fixo de 7 módulos: atenção, containers, stacks, ingress, capacidade, auditoria,
  tarefas. Cada um declara nome, largura padrão (colunas de um grid de 12) e um **chip-resumo**.
- Botão **Personalizar** abre painel único com: mostrar/ocultar, mover ↑↓, largura meia/inteira,
  restaurar padrão. Sem drag na v1 — botões são suficientes e testáveis.
- **Régua de chips**: vitais do host + 1 chip por módulo. Módulo oculto → chip destacado e
  clicável (clicar re-exibe). É a garantia de acesso total com layout enxuto.
- **A faixa crítica não é módulo**: aparece sempre que houver `critical` (padrão híbrido já
  decidido em 00) e não pode ser ocultada.
- Persistência: `localStorage["cockpit.modulos.overview"]`, JSON versionado
  `{v:1, ordem:[], ocultos:[], cheios:[], modo:"lista"}` — por navegador, sem backend.
- Containers: modos **lista** (padrão, 15 linhas sem rolagem) e **cartões** (ocupa largura
  inteira automaticamente).

## 4 · Recomendações de UX aplicadas

Base: e-book *UX no Desenvolvimento de Software*, Paula Azevedo Macedo.

[RECOMENDAÇÃO — usabilidade heurística] Avalie a interface contra as heurísticas de
visibilidade do estado do sistema (régua sempre visível, idade do dado "leitura a cada 5s"),
reconhecimento em vez de memorização (chips nomeiam o que está oculto), prevenção de erro
(escrita atrás de destravamento com motivo) e consistência (mesma escala de severidade em
faixa, fila, badges e chips).

[RECOMENDAÇÃO — design centrado no usuário] Valide cada módulo contra a tarefa do perfil que
o usa: operador em incidente (faixa + fila primeiro), acompanhamento diário (containers em
lista), gestor (chips + capacidade). Nenhum módulo existe "porque o dado existe" — existe
porque uma tarefa o consome.

[RECOMENDAÇÃO — prototipação rápida] Trate `Cockpit Claro Modular.dc.html` como protótipo
descartável de alta fidelidade: teste com os 3 cenários de demo (normal, API caindo, disco
cheio) antes de codificar; o que não sobreviver ao teste não entra no `components.css`.

[RECOMENDAÇÃO — arquitetura de informação] Preserve a hierarquia faixa → régua → módulos:
o layout só se reorganiza em evento crítico; a régua é inventário completo; módulos são
aprofundamento opcional e reordenável. Rotule módulos pelo vocabulário já existente nas telas
(não inventar sinônimos).

## 5 · Prompt para o desenvolvedor

```xml
<lang>Frontend vanilla ES modules (app/static/js), CSS custom properties (themes.css), sem framework</lang>
<task>Implementar o tema claro-minimal e o sistema de módulos da Visão geral conforme doc 08</task>
<context>
Protótipo aprovado: Cockpit Claro Modular.dc.html. Tokens da seção 2 (vocabulário de
app/static/css/themes.css). Spec de módulos da seção 3: grid de 12 colunas em overview.js,
registro de 7 módulos {id, nome, span, chip()}, painel Personalizar (ocultar/ordem/largura),
régua de chips acima do grid, persistência em localStorage["cockpit.modulos.overview"]
{v:1, ordem, ocultos, cheios, modo}. Faixa crítica fora do sistema de módulos. Modo lista é
o padrão de containers; cartões força span 12.
</context>
<rules>- Seja direto. - Pense passo a passo na migração do overview.js atual (3 colunas fixas) para o grid de módulos. - Cor só para estado; nada de gradiente/glow. - Chips de módulo oculto são clicáveis e re-exibem o módulo. - :focus-visible em todo controle novo (pendência #14). - Testes: test_frontend_modulos.py continua verde; adicionar teste de que módulo oculto mantém chip na régua. - Saída: só o bloco de código.</rules>
```
