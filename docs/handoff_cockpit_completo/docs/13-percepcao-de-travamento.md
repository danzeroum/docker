# 13 · A sensação de "interface travada" — causa raiz e correção

Referência visual: **Cockpit Vivo Completo.dc.html** (na raiz do pacote). Abra no
Chrome/Edge desktop e compare com a tela. O que muda é **mecânica de render**,
não estética.

> Este documento é o par do doc 12: aquele descreve o que a tela mostra, este
> descreve o que ela faz enquanto o dado troca.

---

## 1. O diagnóstico

O pedido chegou como "a interface parece travada". Não era lentidão. As rotas
respondiam dentro do orçamento, os 935 testes passavam e o dado na tela estava
certo. Medir o backend não ia encontrar nada — e não encontrou.

A causa raiz é uma linha, repetida em cerca de 35 lugares:

```js
alvo.innerHTML = '...';   // a cada poll
```

Recriar o nó tem quatro efeitos. Eles pareciam quatro bugs diferentes e são um
só, porque o elemento que o operador estava usando deixou de existir:

| Sintoma | Por quê |
|---|---|
| `:hover` morre no meio do movimento | o ponteiro passa a pairar sobre um nó que nasceu agora e nunca recebeu `mouseenter` |
| foco e seleção somem | digitar num campo redesenhado é digitar no vazio |
| scroll interno volta a zero | `scrollTop` é estado do nó, e o nó é outro |
| **nenhuma `transition` roda** | o nó novo **nasce no valor final**: não há estado anterior de onde animar |

O quarto é o que explica por que "adicionar `transition` ao CSS" não teria
resolvido nada. Barra de CPU e chip não saltavam por falta de regra de animação
— saltavam porque a animação não tinha de onde partir.

### A medida certa

A pergunta "o HTML final é igual?" e a pergunta "quantos nós morreram no
caminho?" têm respostas diferentes, e a segunda é a que importa. Um
`innerHTML =` idempotente produz string final **idêntica** e ainda assim
destruiu toda a árvore — levando junto hover, foco, seleção e scroll.

Por isso o aceite é medido por **identidade de nó**, via `MutationObserver`, em
`tests/test_render_vivo.py`.

---

## 2. Os cinco problemas, e o que cada um virou

### (1) Rebuild por leitura → patch por linha

`app/static/js/kernel/patch.js` concentra as operações: escrever texto só se
mudou, trocar atributo só se mudou, e reconciliar lista **por chave**.

A chave é a identidade do item — `container_name` para containers, id da stack,
id do achado. Item que continua no payload mantém o mesmo nó; item que sai leva
só a própria linha; reordenar é `insertBefore`, não redesenhar.

Um detalhe que custou uma iteração: os órfãos saem **antes** do posicionamento.
Com eles saindo depois, remover um container do meio de quinze produzia quatorze
`insertBefore` — nenhum nó recriado, e ainda assim DOM mexido à toa numa lista
que só precisava perder uma linha.

O `render` de cada módulo passou a ser **montagem**, chamada uma vez, e o kernel
chama `atualizar(dados)` a cada leitura. Enquanto a grade não muda de forma
(mesmo escopo, mesmos módulos visíveis, mesmas larguras),
`app/static/js/kernel/cockpit.js` não toca no DOM da grade.

### (2) A busca de logs reconstruída → casca desenhada uma vez

`app/static/js/modulos/logs.js` recriava o próprio `<input>`. Digitar `oom`
significava perder o `o` no ciclo seguinte, com o cursor de volta ao começo de
um campo novo. Era o único campo de texto do cockpit dentro de um cartão que
atualiza sozinho — o mais fácil de flagrar e o mais irritante de usar.

De quebra: `pre.scrollTop = pre.scrollHeight` incondicional jogava de volta ao
rodapé quem tinha subido para ler a linha do erro. Agora só rola ao fim se o
operador **já estava** no fim.

### (3) Skeleton a cada recarga → skeleton só sem dado anterior

Cinco módulos apagavam um cartão já preenchido a cada leitura. O cockpit parecia
reiniciar sozinho.

Skeleton pertence à primeira carga e só a ela. Recarga preserva o conteúdo e
sinaliza a atualização pelo flash do valor que mudou.

Disso decorre uma regra maior: **erro depois de dado bom não apaga o dado bom.**
Trocar 40 eventos por "Sem timeline" porque uma leitura falhou é perder o que já
se sabia por causa de um soluço de rede — e num incidente é exatamente quando a
rede treme e a timeline importa.

### (4) Seis relógios → um

Eram seis no diagnóstico inicial. Lendo o código de perto, dez:
`main.js` (30s), `kernel/app.js` (15s), `attention.js` (10s), `auditoria.js`
(15s), `ingress.js` (5min), `projects.js` (10s), `commands.js` (60s),
`backend.js`, `executivo.js`, `plantao.js`, `tarefas.js` e `topologia.js` (30s
cada).

Dois efeitos, ambos ruins: os piscas ficam desalinhados, e o olho lê movimento
sem causa; e a pausa com aba oculta era responsabilidade de cada um —
`commands.js` não a implementava e recarregava três fontes por minuto para uma
aba que ninguém estava olhando.

`app/static/js/kernel/relogio.js` é o único dono de `setInterval` no frontend.
Módulo declara período como **múltiplo do tick** (`2 * TICK_MS`), nunca em
milissegundos soltos — é isso que mantém a fase.

**Ao voltar de aba oculta, UMA atualização por assinante.** As duas alternativas
são piores: repor os ticks perdidos entrega a rajada acumulada no instante em
que o operador olha; não fazer nada deixa a tela mostrando o estado de dez
minutos atrás sem dizer que é velho.

### (5) Nada sinalizava vida → a pílula "ao vivo"

Sem indicador, o olho não distingue "parado" de "atualizando", e a primeira
leitura de uma tela sem sinal de vida é sempre "travou".

A pílula vive na régua, ao lado dos vitais: ponto pulsante + varredura de 2,2s
que **reinicia a cada leitura** — é o que diferencia "atualizando" de "parado com
um ponto verde". Vira `pausado` (cinza) durante o arraste do Personalizar e
enquanto a aba está oculta. `ao vivo` enquanto nada é lido seria a única coisa
pior que não ter indicador nenhum.

---

## 3. `prefers-reduced-motion`

Movimento periférico é gatilho documentado de enxaqueca vestibular, e um cockpit
é uma tela que fica aberta o dia inteiro. Quem pediu menos movimento ao sistema
operacional pediu de verdade.

A regra tem um limite explícito: **desligar animação não pode desligar
informação.** O flash some, o valor continua trocando; o pulso some, a pílula
continua verde e dizendo "ao vivo". Nenhum estado deste cockpit é comunicado só
por movimento — e é isso que torna a regra segura de aplicar sem exceção.

---

## 4. O contrato visual, com os números do protótipo

Os quatro tempos são do `Cockpit Vivo Completo.dc.html`, não escolhidos na
implementação. Estão como tokens em `app/static/css/components.css` e travados
em `tests/test_render_vivo.py`:

| Token | Valor | Onde |
|---|---|---|
| `--t-hover` | 140ms | toda superfície clicável |
| `--t-valor` | 700ms | barra de CPU, memória, colunas do gráfico |
| `--t-flash` | 900ms | valor que acabou de mudar |
| `--t-vivo` | 2200ms | pulso e varredura da pílula |

A curva é `cubic-bezier(.22,1,.36,1)`, que já existia como `--ease-quiet` em
`app/static/css/themes.css`.

**Nenhuma cor nova, e nenhuma cor no JS.** `style="border-left:3px solid ${cor}"`
nos cartões de achado era o último lugar onde a paleta vivia no JavaScript — e
não acompanhava a troca de tema. Descobriu-se de quebra que
`app/static/js/screens/capacidade.js` pintava com `var(--tx2)`, `var(--bd0)` e
`var(--sf)`: tokens do protótipo que **nunca existiram** no themes.css. Metade
das bordas e dos textos secundários daquela tela vinha caindo no valor inicial do
navegador desde o porte.

Uma exceção declarada: valor numérico que a CSS anima (largura de barra, altura
de coluna) vai por **propriedade customizada** — `--barra`, `--altura`. A
apresentação inteira continua no CSS; o JS entrega só o número. Escrever
`style.width` devolveria a regra de movimento para dentro do módulo.

---

## 5. Como isso é verificado

`tests/test_render_vivo.py`, em três níveis:

- **unidade** — `lista()` e `texto()`: a linha que sobrevive, a que sai, a que
  entra e a que reordena;
- **integração** — o módulo `containers` sob 20 leituras seguidas com 15
  containers: zero nós criados, zero destruídos, zero movidos;
- **aceitação** — o roteiro do doc 12 sem perder foco nem scroll, o relógio com
  a aba oculta, e a pílula dizendo a verdade.

Mais quatro guardas de fonte: teto de `innerHTML` por arquivo, nenhum
`setInterval` fora do relógio, `prefers-reduced-motion` presente, e nenhuma cor
de severidade montada no JS.

O harness mudou junto. `tests/fixtures/dom_stub.mjs` responde ao que os módulos
**chamam** — ele não tem nós, e patch sobre um objeto descartável fabricado por
regex não é observável. `tests/fixtures/dom_min.mjs` é uma árvore de verdade,
com `MutationObserver`. Não é um navegador e não tenta ser: `:hover` real,
contraste e reflow medido continuam no roteiro manual do doc 12. O que se afirma
sem um navegador é que o nó sobreviveu — e se o nó sobrevive, o resto é CSS.

---

## 6. O que ficou de fora, e por quê

Quatro telas continuam redesenhando por `innerHTML` quando o dado muda:
`app/static/js/screens/backend.js`, `app/static/js/screens/executivo.js`,
`app/static/js/screens/plantao.js` e `app/static/js/screens/topologia.js`.

As quatro estão **fora de todo preset padrão** (decisão de escopo do doc 14):
só aparecem se o operador as acrescentar pelo Personalizar. O que já vale para
elas é `redesenharSeMudou` — a leitura compara a assinatura do payload e só toca
no DOM quando o dado mudou de fato, o que numa tela de leitura é o caso raro.

O teto de `innerHTML` de cada uma está travado no teste: **baixá-lo é o trabalho
pendente, subi-lo é regressão.**

Converter pela metade seria pior que declarar: um módulo com metade das listas
chaveadas tem exatamente o mesmo sintoma do original e a aparência de resolvido.

---

## 7. O que isto deixa como regra

Registrado no doc 00 como atributo de qualidade, com a redação que permite
falhar:

> **Nenhuma reconstrução de árvore por leitura.** Uma leitura com o mesmo
> payload não pode criar nem destruir nó nenhum. Uma leitura com payload
> diferente só pode tocar nos nós cuja identidade mudou.

Percepção de desempenho é atributo de qualidade como disponibilidade ou
latência, e entra no registro pelo mesmo motivo que elas: atributo que não é
declarado não é projetado, e o que não é projetado volta como reclamação. Tem
uma propriedade desconfortável que as outras não têm — é o único em que o
sistema pode estar objetivamente rápido e subjetivamente quebrado ao mesmo
tempo, que foi exatamente o caso aqui.
