/* Registro de módulos — o único ponto de extensão da UI (doc 10 §1).
 *
 * A regra que este arquivo existe para cumprir é do doc 10 §4:
 * "módulo novo = 1 arquivo novo, zero `if` no núcleo".
 *
 * O que havia antes era um `switch` com um `case` por tela em main.js — o
 * oposto exato. Acrescentar tela significava editar o núcleo, e o núcleo
 * conhecia cada tela pelo nome.
 *
 * Contrato (doc 10 §1):
 *   Modulo = { id, nome, escopos: ['host'|'stack'|'container'],
 *              span, chip(escopo, summary), render(escopo, dados) }
 *
 * `chip` é opcional: módulo sem chip simplesmente não aparece na régua.
 * `render` devolve opcionalmente uma função de dispose, como as telas já fazem.
 */

const _modulos = new Map();

const ESCOPOS_VALIDOS = new Set(['host', 'stack', 'container']);

/** Registra um módulo. Idempotente por id: re-registrar substitui. */
export function registrar(mod) {
  if (!mod || typeof mod !== 'object') throw new TypeError('módulo precisa ser objeto');
  if (!mod.id || typeof mod.id !== 'string') throw new TypeError('módulo precisa de id');
  if (typeof mod.render !== 'function') throw new TypeError(`módulo ${mod.id} precisa de render()`);
  const escopos = Array.isArray(mod.escopos) ? mod.escopos : ['host'];
  for (const e of escopos) {
    if (!ESCOPOS_VALIDOS.has(e)) throw new RangeError(`escopo inválido em ${mod.id}: ${e}`);
  }
  _modulos.set(mod.id, {
    id: mod.id,
    nome: mod.nome || mod.id,
    escopos,
    // 12 colunas é a grade do doc 09 §A; 6 = meia largura.
    span: Number(mod.span) || 6,
    chip: typeof mod.chip === 'function' ? mod.chip : null,
    render: mod.render,
  });
  return _modulos.get(mod.id);
}

export function todos() {
  return [..._modulos.values()];
}

export function porId(id) {
  return _modulos.get(id) || null;
}

/** Módulos que declaram suportar um tipo de escopo. */
export function doEscopo(tipo) {
  return todos().filter((m) => m.escopos.includes(tipo));
}

export function existe(id) {
  return _modulos.has(id);
}

/** Só para teste: o registro é global por desenho (Registry, doc 10 §3). */
export function limpar() {
  _modulos.clear();
}
