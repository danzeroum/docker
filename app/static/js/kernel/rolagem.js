/* Região que rola precisa receber foco de teclado.
 *
 * Roda de mouse e barra de rolagem são gestos de PONTEIRO. Uma caixa com
 * `overflow:auto` cujo conteúdo não entra na ordem de tabulação esconde tudo abaixo
 * da dobra de quem navega por teclado — e o conteúdo não fica "difícil", fica
 * inalcançável. É o que a regra `scrollable-region-focusable` do axe aponta, sob
 * WCAG 2.1.1.
 *
 * Três decisões, e cada uma existe por um motivo:
 *
 *   1. SÓ o que transborda. `tabindex` em caixa que não rola é ruído — o teclado para
 *      num lugar onde não há nada a fazer, e a navegação piora para todos.
 *
 *   2. SÓ o que não tem conteúdo focalizável dentro. Uma lista de botões já é
 *      alcançável: o Tab entra nos botões e a caixa rola sozinha atrás do foco. Marcar
 *      essa caixa acrescentaria uma parada inútil ANTES da lista. É também o que a
 *      regra do axe considera — ela passa quando a região ou seu conteúdo recebe foco.
 *
 *   3. REVERSÍVEL. Transbordar é estado, não natureza: a lista encolhe, a janela
 *      cresce, o skeleton vira botão. O tabindex tem de sair quando a condição sai.
 *
 * A varredura parte de `document.body`, não da grade: o rail e a lista lateral rolam e
 * vivem fora dela. Escopo estreito foi o primeiro erro desta implementação — media só
 * onde eu já sabia que havia problema.
 */

const MARCA = 'data-rolagem-foco';
const FOCALIZAVEL = 'a[href],button,input,select,textarea,'
  + '[tabindex]:not([tabindex="-1"]),[contenteditable="true"]';

/** Transborda de fato, no eixo em que o CSS permite rolar? */
function transborda(el) {
  const estilo = getComputedStyle(el);
  // +1px de folga: subpixel de zoom/DPI faz scrollHeight passar clientHeight por
  // frações, e marcar por causa disso encheria a interface de paradas inúteis.
  const emY = /(auto|scroll)/.test(estilo.overflowY) && el.scrollHeight > el.clientHeight + 1;
  const emX = /(auto|scroll)/.test(estilo.overflowX) && el.scrollWidth > el.clientWidth + 1;
  return emY || emX;
}

function precisaDeFoco(el) {
  return transborda(el) && el.querySelector(FOCALIZAVEL) === null;
}

/** Sincroniza o tabindex das caixas roláveis do documento inteiro. */
export function marcarRolaveis(raiz) {
  /* Sem motor de layout não há transbordo a medir: `scrollHeight` num DOM de teste é
   * zero ou inexistente, e marcar por esse número seria inventar acessibilidade. O
   * módulo se declara inerte — é por isso que o harness de node (tests/fixtures/) não
   * precisa aprender o seletor universal para os testes do kernel passarem. */
  if (typeof getComputedStyle !== 'function') return;
  const base = raiz || (typeof document !== 'undefined' ? document.body : null);
  if (!base || !base.querySelectorAll) return;
  for (const el of base.querySelectorAll('*')) {
    const nosso = el.hasAttribute(MARCA);
    if (precisaDeFoco(el)) {
      if (nosso) continue;
      if (el.hasAttribute('tabindex')) continue;   // decisão de quem fez o componente
      el.setAttribute('tabindex', '0');
      el.setAttribute(MARCA, '');
    } else if (nosso) {
      el.removeAttribute('tabindex');
      el.removeAttribute(MARCA);
    }
  }
}

let _agendado = false;

/* Medir transbordo obriga o navegador a resolver layout. No meio do render isso
 * forçaria reflow síncrono a cada módulo; num quadro seguinte o layout já está pronto
 * e a leitura é barata. A coalescência importa porque o caminho de LEITURA do cockpit
 * chama isto a cada ciclo de dados. */
export function agendarMarcacao() {
  if (_agendado) return;
  _agendado = true;
  const correr = () => { _agendado = false; marcarRolaveis(); };
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(correr);
  else setTimeout(correr, 0);
}

/* Gancho de render NÃO basta, e descobrir isso custou duas tentativas.
 *
 * Cada módulo busca o próprio dado e se preenche depois, por callback próprio — fora
 * do laço que pinta a grade. A sequência real é: a grade monta com skeleton (nada
 * transborda, nada a marcar), o dado chega, o módulo cresce, e a caixa passa a rolar
 * sem que nenhum render tenha sido chamado. Marcar ao fim da pintura media o estado
 * errado, no instante errado.
 *
 * Observar o DOM resolve na raiz: quem faz a caixa transbordar é a chegada de nós, e é
 * exatamente isso que o MutationObserver vê — venha de onde vier.
 *
 * Só `childList`: observar atributos faria o nosso próprio `setAttribute('tabindex')`
 * reentrar no observador, e o laço não teria fim.
 */
let _instalado = false;
export function instalar() {
  if (_instalado || typeof window === 'undefined') return;
  _instalado = true;

  const comecar = () => {
    agendarMarcacao();
    if (typeof MutationObserver === 'function' && document.body) {
      new MutationObserver(agendarMarcacao)
        .observe(document.body, { childList: true, subtree: true });
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', comecar, { once: true });
  } else {
    comecar();
  }
  window.addEventListener('load', agendarMarcacao, { once: true });
  window.addEventListener('resize', agendarMarcacao, { passive: true });
}
