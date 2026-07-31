/* DOM mínimo de verdade — nós com identidade, para o node.
 *
 * O `dom_stub.mjs` responde ao que os módulos CHAMAM; ele não tem nós. Isso
 * bastou enquanto a pergunta era "o módulo carrega e escreve alguma coisa".
 * Deixou de bastar no ciclo do doc 13, cuja tese inteira é sobre IDENTIDADE DE
 * NÓ: "o container que continua no payload mantém o mesmo elemento" não é
 * verificável num stub onde `querySelectorAll` devolve objetos descartáveis
 * fabricados por regex sobre uma string de HTML.
 *
 * Então aqui tem árvore: pai, filhos, `insertBefore`, `removeChild`, atributos,
 * classes, `textContent`, e um `innerHTML` que PARSEIA em vez de guardar texto.
 * Com isso `no === outroNo` passa a significar alguma coisa, e a afirmação
 * central do ciclo — "zero nós recriados por leitura" — vira um assert.
 *
 * Também tem `MutationObserver`, porque é assim que o doc 13 pede a medida: não
 * "o HTML final é igual", e sim "quantos nós nasceram e morreram no caminho".
 * As duas perguntas têm respostas diferentes num rebuild — o HTML final de um
 * `innerHTML =` idempotente é idêntico, e mesmo assim toda a árvore morreu.
 *
 * NÃO é um navegador e não tenta ser: sem layout, sem CSS aplicado, sem
 * `:hover` de verdade. O que precisa de navegador continua precisando (doc 12).
 * O que dá para afirmar sem um é o que está aqui.
 */

const VAZIOS = new Set([
  'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
  'param', 'source', 'track', 'wbr',
  // SVG que aparece nos moldes; sempre autofechado no fonte, mas tolerado aqui.
  'path', 'rect', 'circle', 'line', 'polyline', 'polygon', 'use', 'stop',
]);

const ENTIDADES = {
  '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'",
  '&larr;': '←', '&rarr;': '→', '&middot;': '·', '&mdash;': '—', '&nbsp;': ' ',
  '&eacute;': 'é', '&aacute;': 'á', '&atilde;': 'ã', '&ccedil;': 'ç',
  '&iacute;': 'í', '&oacute;': 'ó', '&otilde;': 'õ', '&uacute;': 'ú',
  '&ecirc;': 'ê', '&ocirc;': 'ô', '&acirc;': 'â', '&agrave;': 'à',
};

function decodificar(s) {
  return String(s).replace(/&[a-zA-Z#0-9]+;/g, (m) => (m in ENTIDADES ? ENTIDADES[m] : m));
}

function escapar(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
}

/* --- observadores --------------------------------------------------------- */

const _observadores = new Set();

function notificar(alvo, adicionados, removidos) {
  if (!_observadores.size) return;
  for (const obs of _observadores) {
    if (!obs._alcanca(alvo)) continue;
    obs._registros.push({ type: 'childList', target: alvo, addedNodes: adicionados, removedNodes: removidos });
    obs._agendar();
  }
}

export class MutationObserver {
  constructor(callback) {
    this._cb = callback;
    this._alvos = [];
    this._registros = [];
    this._agendado = false;
  }

  observe(alvo, opcoes) {
    this._alvos.push({ alvo, subtree: !!(opcoes && opcoes.subtree) });
    _observadores.add(this);
  }

  disconnect() {
    _observadores.delete(this);
    this._alvos = [];
  }

  takeRecords() {
    const r = this._registros;
    this._registros = [];
    return r;
  }

  _alcanca(no) {
    for (const { alvo, subtree } of this._alvos) {
      if (alvo === no) return true;
      if (!subtree) continue;
      for (let p = no; p; p = p.parentNode) if (p === alvo) return true;
    }
    return false;
  }

  _agendar() {
    if (this._agendado) return;
    this._agendado = true;
    queueMicrotask(() => {
      this._agendado = false;
      const r = this.takeRecords();
      if (r.length) this._cb(r, this);
    });
  }
}

/* --- seletores ------------------------------------------------------------ */

/* Suporta o que o cockpit usa: `tag`, `.classe`, `#id`, `[attr]`,
 * `[attr="v"]`, combinações delas num mesmo composto, e descendência por
 * espaço. Não suporta `>`, `+`, `~`, `:pseudo` nem vírgula — se algum dia o
 * frontend precisar de um desses, este parser falha alto em vez de casar
 * errado, que é o comportamento que se quer de um harness. */
function compilarComposto(txt) {
  const testes = [];
  const re = /([.#]?[\w-]+)|\[([\w-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]*)))?\]/g;
  let m;
  let consumido = 0;
  while ((m = re.exec(txt)) !== null) {
    consumido += m[0].length;
    if (m[1]) {
      const t = m[1];
      if (t[0] === '.') testes.push((el) => el.classList.contains(t.slice(1)));
      else if (t[0] === '#') testes.push((el) => el.id === t.slice(1));
      else testes.push((el) => el.tagName === t.toUpperCase());
    } else {
      const attr = m[2];
      const valor = m[3] !== undefined ? m[3] : (m[4] !== undefined ? m[4] : m[5]);
      if (valor === undefined) testes.push((el) => el.hasAttribute(attr));
      else testes.push((el) => el.getAttribute(attr) === valor);
    }
  }
  if (consumido !== txt.length) {
    throw new Error(`seletor não suportado pelo harness: ${txt}`);
  }
  return (el) => testes.every((t) => t(el));
}

function compilar(seletor) {
  const partes = String(seletor).trim().split(/\s+/).map(compilarComposto);
  const ultimo = partes[partes.length - 1];
  if (partes.length === 1) return ultimo;
  return (el) => {
    if (!ultimo(el)) return false;
    let i = partes.length - 2;
    for (let p = el.parentNode; p && i >= 0; p = p.parentNode) {
      if (p.nodeType === 1 && partes[i](p)) i -= 1;
    }
    return i < 0;
  };
}

/* --- nós ------------------------------------------------------------------ */

class TextoNo {
  constructor(dado) {
    this.nodeType = 3;
    this.data = String(dado);
    this.parentNode = null;
  }

  get textContent() { return this.data; }

  set textContent(v) { this.data = String(v); }

  get outerHTML() { return escapar(this.data); }
}

class Elemento {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = String(tag).toUpperCase();
    this.childNodes = [];
    this.parentNode = null;
    this._attrs = new Map();
    this._handlers = new Map();
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.clientHeight = 0;
    this.disabled = false;

    const self = this;
    this.style = {
      _props: new Map(),
      setProperty(nome, valor) { self.style._props.set(nome, String(valor)); },
      getPropertyValue(nome) { return self.style._props.get(nome) || ''; },
      removeProperty(nome) { self.style._props.delete(nome); },
    };
    this.classList = {
      contains: (c) => self._classes().includes(c),
      add: (...cs) => { const l = self._classes(); for (const c of cs) if (!l.includes(c)) l.push(c); self.setAttribute('class', l.join(' ')); },
      remove: (...cs) => { self.setAttribute('class', self._classes().filter((c) => !cs.includes(c)).join(' ')); },
      toggle: (c, forcar) => {
        const quer = forcar === undefined ? !self.classList.contains(c) : !!forcar;
        if (quer) self.classList.add(c); else self.classList.remove(c);
        return quer;
      },
    };
    this.dataset = new Proxy({}, {
      get: (_, k) => {
        if (typeof k !== 'string') return undefined;
        const v = self.getAttribute(`data-${camelParaTraco(k)}`);
        return v === null ? undefined : v;
      },
      set: (_, k, v) => { self.setAttribute(`data-${camelParaTraco(k)}`, v); return true; },
      has: (_, k) => self.hasAttribute(`data-${camelParaTraco(k)}`),
      deleteProperty: (_, k) => { self.removeAttribute(`data-${camelParaTraco(k)}`); return true; },
      ownKeys: () => [...self._attrs.keys()]
        .filter((a) => a.startsWith('data-'))
        .map((a) => tracoParaCamel(a.slice(5))),
      getOwnPropertyDescriptor: () => ({ enumerable: true, configurable: true }),
    });
  }

  _classes() {
    const c = this._attrs.get('class');
    return c ? c.split(/\s+/).filter(Boolean) : [];
  }

  get id() { return this.getAttribute('id') || ''; }

  set id(v) { this.setAttribute('id', v); indexar(this); }

  get className() { return this.getAttribute('class') || ''; }

  set className(v) { this.setAttribute('class', v); }

  get hidden() { return this.hasAttribute('hidden'); }

  set hidden(v) { if (v) this.setAttribute('hidden', ''); else this.removeAttribute('hidden'); }

  get title() { return this.getAttribute('title') || ''; }

  set title(v) { this.setAttribute('title', v); }

  get type() { return this.getAttribute('type') || ''; }

  set type(v) { this.setAttribute('type', v); }

  get value() { return this._valor === undefined ? (this.getAttribute('value') || '') : this._valor; }

  set value(v) { this._valor = String(v); }

  setAttribute(nome, valor) { this._attrs.set(nome, String(valor)); if (nome === 'id') indexar(this); }

  getAttribute(nome) { return this._attrs.has(nome) ? this._attrs.get(nome) : null; }

  hasAttribute(nome) { return this._attrs.has(nome); }

  removeAttribute(nome) { this._attrs.delete(nome); }

  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }

  get firstElementChild() { return this.children[0] || null; }

  get parentElement() { return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null; }

  get nextElementSibling() {
    if (!this.parentNode) return null;
    const irmaos = this.parentNode.children;
    return irmaos[irmaos.indexOf(this) + 1] || null;
  }

  appendChild(no) { return this.insertBefore(no, null); }

  insertBefore(no, ref) {
    // Sair de um pai para entrar em OUTRO é remoção de verdade e é notificada;
    // trocar de posição dentro do mesmo pai é movimento, e não conta como saída.
    if (no.parentNode) no.parentNode.removeChild(no, no.parentNode === this);
    const i = ref ? this.childNodes.indexOf(ref) : this.childNodes.length;
    this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, no);
    no.parentNode = this;
    notificar(this, [no], []);
    return no;
  }

  removeChild(no, mudando) {
    const i = this.childNodes.indexOf(no);
    if (i < 0) return no;
    this.childNodes.splice(i, 1);
    no.parentNode = null;
    // Movimentação (`insertBefore` de nó já na árvore) não é remoção: contar as
    // duas juntas faria reordenar parecer recriar, e é justamente a diferença
    // entre as duas que este harness existe para medir.
    if (!mudando) notificar(this, [], [no]);
    return no;
  }

  remove() { if (this.parentNode) this.parentNode.removeChild(this); }

  get textContent() {
    return this.childNodes.map((n) => n.textContent).join('');
  }

  set textContent(v) {
    const antigos = this.childNodes.slice();
    for (const n of antigos) n.parentNode = null;
    this.childNodes = [];
    const txt = v == null ? '' : String(v);
    if (txt !== '') this.childNodes.push(Object.assign(new TextoNo(txt), { parentNode: this }));
    notificar(this, this.childNodes.slice(), antigos);
  }

  get innerHTML() { return this.childNodes.map((n) => n.outerHTML).join(''); }

  set innerHTML(html) {
    const antigos = this.childNodes.slice();
    for (const n of antigos) n.parentNode = null;
    this.childNodes = [];
    for (const filho of parsear(String(html))) {
      filho.parentNode = this;
      this.childNodes.push(filho);
    }
    notificar(this, this.childNodes.slice(), antigos);
  }

  get outerHTML() {
    const attrs = [...this._attrs.entries()]
      .map(([k, v]) => (v === '' ? ` ${k}` : ` ${k}="${escapar(v)}"`)).join('');
    const tag = this.tagName.toLowerCase();
    if (VAZIOS.has(tag)) return `<${tag}${attrs}>`;
    return `<${tag}${attrs}>${this.innerHTML}</${tag}>`;
  }

  querySelectorAll(seletor) {
    const casa = compilar(seletor);
    const achados = [];
    const anda = (no) => {
      for (const f of no.children) {
        if (casa(f)) achados.push(f);
        anda(f);
      }
    };
    anda(this);
    return achados;
  }

  querySelector(seletor) { return this.querySelectorAll(seletor)[0] || null; }

  closest(seletor) {
    const casa = compilar(seletor);
    for (let p = this; p; p = p.parentElement) if (p.nodeType === 1 && casa(p)) return p;
    return null;
  }

  matches(seletor) { return compilar(seletor)(this); }

  addEventListener(tipo, fn) {
    if (!this._handlers.has(tipo)) this._handlers.set(tipo, []);
    this._handlers.get(tipo).push(fn);
  }

  removeEventListener(tipo, fn) {
    const l = this._handlers.get(tipo);
    if (l) this._handlers.set(tipo, l.filter((f) => f !== fn));
  }

  /** Dispara com BOLHA — é o que torna a delegação testável. */
  dispatchEvent(ev) {
    const evento = { ...ev, target: ev.target || this };
    for (let no = this; no; no = no.parentElement) {
      for (const fn of no._handlers.get(evento.type) || []) fn(evento);
    }
    return true;
  }

  click() {
    this.dispatchEvent({ type: 'click', target: this, stopPropagation() {}, preventDefault() {} });
  }

  focus() { documento.activeElement = this; }

  scrollIntoView() {}

  getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; }
}

function camelParaTraco(s) { return s.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`); }

function tracoParaCamel(s) { return s.replace(/-([a-z])/g, (_, c) => c.toUpperCase()); }

/* --- parser de HTML ------------------------------------------------------- */

function parsear(html) {
  const raiz = new Elemento('root');
  let atual = raiz;
  const pilha = [];
  const re = /<!--[\s\S]*?-->|<\/([\w-]+)\s*>|<([\w-]+)((?:\s+[^\s/>"']+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]*))?)*)\s*(\/?)>|([^<]+)/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    if (m[0].startsWith('<!--')) continue;
    if (m[1]) {
      if (pilha.length && atual.tagName === m[1].toUpperCase()) atual = pilha.pop();
      continue;
    }
    if (m[2]) {
      const el = new Elemento(m[2]);
      for (const a of (m[3] || '').matchAll(/([^\s=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) {
        if (!a[1]) continue;
        const v = a[2] !== undefined ? a[2] : (a[3] !== undefined ? a[3] : (a[4] !== undefined ? a[4] : ''));
        el.setAttribute(a[1], decodificar(v));
      }
      el.parentNode = atual;
      atual.childNodes.push(el);
      if (!m[4] && !VAZIOS.has(m[2].toLowerCase())) { pilha.push(atual); atual = el; }
      continue;
    }
    if (m[5] !== undefined) {
      const txt = decodificar(m[5]);
      if (txt.trim() === '' && atual.childNodes.length === 0) continue;
      const no = new TextoNo(txt);
      no.parentNode = atual;
      atual.childNodes.push(no);
    }
  }
  const filhos = raiz.childNodes.slice();
  for (const f of filhos) f.parentNode = null;
  return filhos;
}

/* --- documento ------------------------------------------------------------ */

const _porId = new Map();

function indexar(el) {
  if (el.id) _porId.set(el.id, el);
}

const documento = {
  nodeType: 9,
  hidden: false,
  activeElement: null,
  createElement: (tag) => new Elemento(tag),
  createTextNode: (t) => new TextoNo(t),
  getElementById: (id) => {
    const cache = _porId.get(id);
    if (cache && ancorado(cache)) return cache;
    const achado = documento.body.querySelector(`#${id}`);
    if (achado) _porId.set(id, achado);
    return achado;
  },
  querySelector: (s) => documento.body.querySelector(s),
  querySelectorAll: (s) => documento.body.querySelectorAll(s),
  _handlers: new Map(),
  addEventListener(tipo, fn) {
    if (!this._handlers.has(tipo)) this._handlers.set(tipo, []);
    this._handlers.get(tipo).push(fn);
  },
  removeEventListener(tipo, fn) {
    const l = this._handlers.get(tipo);
    if (l) this._handlers.set(tipo, l.filter((f) => f !== fn));
  },
  disparar(tipo) {
    for (const fn of (this._handlers.get(tipo) || []).slice()) fn({ type: tipo });
  },
};

function ancorado(el) {
  for (let p = el; p; p = p.parentNode) if (p === documento.body) return true;
  return false;
}

documento.documentElement = new Elemento('html');
documento.body = new Elemento('body');
documento.documentElement.appendChild(documento.body);

/* --- instalação ----------------------------------------------------------- */

function armazenamento() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    clear: () => m.clear(),
  };
}

export function instalar() {
  globalThis.document = documento;
  globalThis.localStorage = armazenamento();
  globalThis.sessionStorage = armazenamento();
  globalThis.MutationObserver = MutationObserver;
  globalThis.location = { hash: '', href: 'http://localhost/' };
  globalThis.window = {
    addEventListener() {}, removeEventListener() {},
    matchMedia: () => ({ matches: false, addEventListener() {} }),
  };
  globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
  globalThis.EventSource = class {
    constructor() { this.readyState = 0; EventSource._abertos.push(this); }

    addEventListener() {}

    close() { this.readyState = 2; }
  };
  globalThis.EventSource._abertos = [];
  return documento;
}

export { documento, Elemento, TextoNo };
