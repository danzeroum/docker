/* Stub minimo de DOM para importar modulos de tela no node.
 *
 * O frontend nao tem bundler nem runner de teste — de proposito. Mas as telas
 * tem logica que nao da para conferir lendo: ordenacao de fila, cruzamento de
 * upstream com inventario. Regex sobre o fonte diz que a funcao existe, nao que
 * ela ordena certo.
 *
 * Este stub cobre so o que os modulos tocam no nivel de MODULO (main.js registra
 * listeners e pinta o tema ao carregar). Nada aqui simula layout ou eventos: o
 * que precisa de navegador continua precisando de navegador.
 */
function armazenamento() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    clear: () => m.clear(),
  };
}

const noop = () => {};

const elementoVazio = {
  setAttribute: noop,
  addEventListener: noop,
  removeEventListener: noop,
  appendChild: noop,
  remove: noop,
  querySelectorAll: () => [],
  querySelector: () => null,
  classList: { add: noop, remove: noop, contains: () => false },
  style: {},
  dataset: {},
  textContent: '',
  innerHTML: '',
};

globalThis.localStorage = armazenamento();
globalThis.sessionStorage = armazenamento();
globalThis.document = {
  documentElement: { ...elementoVazio },
  // getElementById devolve null: todo uso no frontend e opcional-chained ou
  // testado. Se algum dia nao for, o teste quebra aqui — e esse e o ponto.
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: () => ({ ...elementoVazio }),
  addEventListener: noop,
  removeEventListener: noop,
  activeElement: null,
  hidden: false,
};
globalThis.window = {
  addEventListener: noop,
  removeEventListener: noop,
  matchMedia: () => ({ matches: false, addEventListener: noop }),
};
globalThis.location = { hash: '#/overview', href: 'http://localhost/' };
globalThis.EventSource = class {
  constructor() { this.readyState = 0; }
  addEventListener() {}
  close() {}
};
