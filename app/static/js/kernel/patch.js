/* Patch de DOM — escrever no nó que já existe em vez de recriar a árvore.
 *
 * A causa raiz da sensação de interface travada (doc 13 §1) é `alvo.innerHTML =`
 * a cada leitura. Recriar o nó tem quatro efeitos que nenhum ajuste de estilo
 * conserta, porque o nó que o usuário estava usando deixou de existir:
 *
 *   1. `:hover` morre no meio do movimento — o ponteiro passa a pairar sobre um
 *      nó que nasceu agora e ainda não recebeu `mouseenter`;
 *   2. foco e seleção somem; digitar num campo redesenhado é digitar no vazio;
 *   3. `scrollTop` de qualquer área interna volta a zero;
 *   4. `transition` nunca roda: o nó novo NASCE no valor final, então não há
 *      estado anterior de onde animar. É por isso que barra e número saltam.
 *
 * As funções aqui são a alternativa: comparam antes de escrever, escrevem só o
 * que mudou, e devolvem se mudou — para quem quiser sinalizar a mudança.
 *
 * `innerHTML` continua legítimo em três lugares e só neles: desenho inicial da
 * casca, estado vazio e estado de erro. Nenhum dos três acontece por leitura.
 */

/* Duas classes alternadas em vez de remover-e-readicionar uma só. Reiniciar
 * animação pelo caminho clássico exige ler `offsetWidth` para forçar reflow —
 * um reflow síncrono POR ITEM alterado, que numa lista de 15 containers é
 * exatamente o custo que este ciclo veio remover. Trocar o nome da classe
 * reinicia a animação sem medir nada. */
const FLASH = ['flash-a', 'flash-b'];

/**
 * Escreve texto só se mudou.
 * @returns {boolean} true se o valor era outro
 */
export function texto(el, valor, opcoes) {
  if (!el) return false;
  const novo = valor == null ? '' : String(valor);
  if (el.textContent === novo) return false;
  const primeira = el.textContent === '';
  el.textContent = novo;
  // Primeira escrita não é mudança de valor, é chegada do dado. Piscar aqui
  // faria a tela inteira piscar na carga inicial, que é ruído, não sinal.
  if (opcoes && opcoes.flash && !primeira) piscar(el);
  return true;
}

/** Reinicia o flash de 0,9s no nó. */
export function piscar(el) {
  if (!el || !el.classList) return;
  const atual = el.classList.contains(FLASH[0]) ? 0 : 1;
  el.classList.remove(FLASH[atual]);
  el.classList.add(FLASH[1 - atual]);
}

/** Escreve um atributo só se mudou; `null`/`undefined`/`false` removem. */
export function atributo(el, nome, valor) {
  if (!el) return false;
  if (valor == null || valor === false) {
    if (!el.hasAttribute || !el.hasAttribute(nome)) return false;
    el.removeAttribute(nome);
    return true;
  }
  const novo = String(valor);
  if (el.getAttribute && el.getAttribute(nome) === novo) return false;
  el.setAttribute(nome, novo);
  return true;
}

/** Liga/desliga uma classe. */
export function classe(el, nome, ligado) {
  if (!el || !el.classList || !nome) return false;
  const tem = el.classList.contains(nome);
  if (tem === !!ligado) return false;
  if (ligado) el.classList.add(nome);
  else el.classList.remove(nome);
  return true;
}

/** Troca a classe de um grupo mutuamente exclusivo (estado, severidade, tom). */
export function classeUnica(el, grupo, escolhida) {
  if (!el || !el.classList) return false;
  let mudou = false;
  for (const nome of grupo) {
    if (nome === escolhida) continue;
    if (classe(el, nome, false)) mudou = true;
  }
  if (escolhida && classe(el, escolhida, true)) mudou = true;
  return mudou;
}

/**
 * Valor numérico que a CSS anima — largura de barra, altura de coluna.
 *
 * Vai por propriedade customizada, não por `style.width`: a apresentação
 * (transição, cor, altura) continua inteira no components.css e o JS entrega só
 * o NÚMERO. Escrever `style.width` no JS devolveria a regra de movimento para
 * dentro do módulo, que é o que a regra "nenhum estilo inline novo" evita.
 */
export function medida(el, nome, valor) {
  if (!el || !el.style || !el.style.setProperty) return false;
  const novo = valor == null ? '' : String(valor);
  if (el.style.getPropertyValue && el.style.getPropertyValue(nome) === novo) return false;
  el.style.setProperty(nome, novo);
  return true;
}

/** Mostra/esconde sem recriar. */
export function mostrar(el, visivel) {
  if (!el) return false;
  const alvo = !visivel;
  if (el.hidden === alvo) return false;
  el.hidden = alvo;
  return true;
}

/** Atalho de criação — mantém os módulos sem `document.createElement` solto. */
export function no(tag, className, textoInicial) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (textoInicial != null) el.textContent = String(textoInicial);
  return el;
}

/**
 * Molde: o HTML de UMA linha, instanciado quando a identidade aparece.
 *
 * Duas coisas se ganham escrevendo a linha como markup em vez de uma pilha de
 * `createElement`:
 *
 * - a estrutura continua legível — dá para ver a linha inteira num lugar só, e
 *   `grep` continua achando o `button` com a classe `mod-linha` no fonte, que
 *   é como o guarda de acessibilidade confere que alvo clicável não regrediu
 *   para elemento não focável;
 * - o molde é parseado na CRIAÇÃO, e criação só acontece quando um item novo
 *   entra na lista. Nenhuma leitura passa por aqui: o caminho da leitura é
 *   `texto`/`atributo`/`classe` sobre o nó que já está na tela.
 *
 * O molde nunca interpola dado. Ele nasce com os campos vazios e o valor entra
 * por `textContent` — o que também significa que nenhum payload vira markup.
 */
export function deMolde(html) {
  const caixa = document.createElement('div');
  caixa.innerHTML = html;
  return caixa.firstElementChild;
}

/**
 * Lista chaveada: recria SÓ quando a identidade muda.
 *
 * Regra do doc 13: a chave é a identidade do item (`container_name`, id da
 * stack, id do achado). Item que continua no payload mantém o MESMO nó — com o
 * hover, o foco e o scroll que ele carregava. Item que sai leva só o próprio nó;
 * os vizinhos não são tocados. Reordenar é `insertBefore`, não redesenhar.
 *
 * @param {HTMLElement} recipiente
 * @param {Array} itens
 * @param {object} opcoes
 * @param {(item:any, i:number) => string} opcoes.chave
 * @param {(item:any, chave:string) => HTMLElement} opcoes.criar
 * @param {(no:HTMLElement, item:any, chave:string) => void} [opcoes.atualizar]
 * @returns {{criados:number, removidos:number, movidos:number}}
 */
export function lista(recipiente, itens, opcoes) {
  const relatorio = { criados: 0, removidos: 0, movidos: 0 };
  if (!recipiente) return relatorio;
  const { chave, criar, atualizar } = opcoes || {};
  if (typeof chave !== 'function' || typeof criar !== 'function') {
    throw new TypeError('lista precisa de chave() e criar()');
  }

  const anteriores = new Map();
  for (const filho of Array.from(recipiente.children)) {
    const k = filho.dataset ? filho.dataset.chave : null;
    // Nó sem chave é resto de um desenho anterior (skeleton, estado vazio):
    // sai agora para não competir por posição com as linhas de verdade.
    if (k == null || k === '') recipiente.removeChild(filho);
    else anteriores.set(k, filho);
  }

  /* Os que saíram do payload saem do DOM ANTES do posicionamento, não depois.
   *
   * A ordem importa e custa: com os órfãos ainda na lista, cada um deles empurra
   * todos os seguintes para o lado no laço abaixo, e remover UM container do
   * meio de quinze vira quatorze `insertBefore` — nenhum nó recriado, mas sete
   * movimentos de DOM para uma linha que só precisava sumir. Removendo antes,
   * as posições já batem e o laço não move nada. */
  const desejadas = new Set();
  for (let i = 0; i < itens.length; i++) desejadas.add(String(chave(itens[i], i)));
  for (const [k, orfao] of anteriores) {
    if (desejadas.has(k)) continue;
    recipiente.removeChild(orfao);
    anteriores.delete(k);
    relatorio.removidos += 1;
  }

  let posicao = 0;
  for (let i = 0; i < itens.length; i++) {
    const item = itens[i];
    const k = String(chave(item, i));
    let alvo = anteriores.get(k);
    if (alvo) {
      anteriores.delete(k);
    } else {
      alvo = criar(item, k);
      if (!alvo) continue;
      alvo.dataset.chave = k;
      relatorio.criados += 1;
    }
    const ocupante = recipiente.children[posicao] || null;
    if (ocupante !== alvo) {
      recipiente.insertBefore(alvo, ocupante);
      relatorio.movidos += 1;
    }
    if (atualizar) atualizar(alvo, item, k);
    posicao += 1;
  }

  /* O que sobra aqui só existe se o mesmo item aparecer duas vezes no payload:
   * a segunda ocorrência não encontra nó livre, cria o seu, e o anterior fica
   * órfão. Chave duplicada é bug de quem chama — a lista não tenta adivinhar
   * qual das duas linhas é a verdadeira, mas também não deixa nó pendurado. */
  for (const [, orfao] of anteriores) {
    recipiente.removeChild(orfao);
    relatorio.removidos += 1;
  }
  return relatorio;
}

/**
 * Redesenha só quando o payload mudou.
 *
 * É o meio-termo honesto para uma tela que ainda não foi convertida para patch
 * por linha: não conserta o rebuild, mas para de fazê-lo por nada. Numa tela de
 * leitura — inventário de rotas, resumo executivo, topologia — o payload muda
 * por deploy, não por minuto, então o caso comum passa a não tocar no DOM.
 *
 * Não substitui `lista()`: quando o dado MUDA, a árvore ainda morre e leva
 * junto hover, foco e scroll. Onde isso importa, a lista é chaveada.
 *
 * @returns {boolean} true se redesenhou agora
 */
export function redesenharSeMudou(el, dados, desenhar) {
  if (!el) return false;
  let assinatura;
  try {
    assinatura = JSON.stringify(dados);
  } catch {
    // Payload com ciclo: sem assinatura confiável, redesenha — é o
    // comportamento anterior, e errar para o lado de mostrar o dado novo.
    desenhar(el);
    return true;
  }
  if (el.dataset.assinatura === assinatura) return false;
  el.dataset.assinatura = assinatura;
  desenhar(el);
  return true;
}

/**
 * Casca desenhada UMA vez.
 *
 * Guarda a assinatura do que foi desenhado no próprio nó: chamada seguinte com
 * a mesma assinatura não toca em nada e devolve `false`. É o que garante que a
 * casca de um módulo (o campo de busca dos logs, os botões de janela das
 * métricas) não seja reconstruída por leitura.
 *
 * @returns {boolean} true se desenhou agora
 */
export function casca(el, assinatura, desenhar) {
  if (!el) return false;
  if (el.dataset.casca === assinatura) return false;
  desenhar(el);
  el.dataset.casca = assinatura;
  return true;
}
