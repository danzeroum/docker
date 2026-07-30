/* Cockpit = grade de módulos para um escopo (doc 10 §1).
 *
 * O núcleo NÃO conhece módulo nenhum pelo nome. Ele itera o registro, filtra
 * por escopo, ordena pelo layout e chama `render(escopo, dados)`. É o teste de
 * aberto/fechado do doc 10 §4: acrescentar módulo é registrar um arquivo.
 *
 * Strategy é o padrão aqui (doc 10 §3): o render por escopo é a estratégia, e o
 * cockpit é quem a aplica sem saber qual é.
 */

import { escapeHtml } from '../fmt.js';
import { porId } from './registry.js';

/* Um dispose por módulo montado. Vazar dispose é vazar poller — foi assim que
 * o `let pollTimer` duplicado matou o main.js antes. */
let _disposes = new Map();

export function desmontar() {
  for (const [, fn] of _disposes) {
    try {
      if (typeof fn === 'function') fn();
    } catch { /* dispose que levanta não impede os outros */ }
  }
  _disposes = new Map();
}

function caixaHtml(mod, span) {
  return `<section class="mod" data-modulo="${escapeHtml(mod.id)}" style="grid-column:span ${span}">`
    + `<header class="mod-head"><h2 class="mod-nome">${escapeHtml(mod.nome)}</h2>`
    + `<span class="mod-sub" data-sub="${escapeHtml(mod.id)}"></span></header>`
    + `<div class="mod-corpo" id="mod-${escapeHtml(mod.id)}"></div>`
    + `</section>`;
}

/**
 * Pinta a grade de um escopo.
 * @param {HTMLElement} alvo
 * @param {object} escopo
 * @param {object} estado  layout reconciliado
 * @param {object} dados   payload compartilhado (overview, findings, ...)
 */
export function pintarCockpit(alvo, escopo, estado, dados) {
  if (!alvo) return;
  desmontar();

  const ocultos = new Set(estado.ocultos || []);
  const cheios = new Set(estado.cheios || []);

  const visiveis = (estado.ordem || [])
    .map((id) => porId(id))
    .filter((m) => m && !ocultos.has(m.id) && m.escopos.includes(escopo.t));

  if (!visiveis.length) {
    alvo.innerHTML = '<div class="empty">Nenhum módulo visível neste cockpit. '
      + 'Abra Personalizar para exibir módulos.</div>';
    return;
  }

  alvo.innerHTML = `<div class="grade">${
    visiveis.map((m) => caixaHtml(m, cheios.has(m.id) ? 12 : m.span)).join('')
  }</div>`;

  // Render por módulo, isolado: módulo que levanta mostra erro no próprio card
  // e não derruba os outros (degradação por módulo, doc 12 §testes).
  for (const mod of visiveis) {
    const corpo = document.getElementById(`mod-${mod.id}`);
    if (!corpo) continue;
    try {
      const dispose = mod.render(escopo, dados, corpo);
      if (typeof dispose === 'function') _disposes.set(mod.id, dispose);
    } catch (e) {
      corpo.innerHTML = `<div class="empty">Falha ao desenhar este módulo</div>`;
      // eslint-disable-next-line no-console
      console.error(`módulo ${mod.id}:`, e);
    }
  }
}

/** Subtítulo de um módulo (ex.: "raw 24h · agregado 30d" nas Métricas). */
export function definirSub(id, texto) {
  const el = document.querySelector(`[data-sub="${id}"]`);
  if (el) el.textContent = texto || '';
}
