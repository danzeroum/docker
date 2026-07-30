/* Módulo `stacks` — agregado por projeto compose (escopo host).
 *
 * Clicar numa stack abre o mini cockpit dela: mesmo registro de módulos, escopo
 * `{t:'stack', id}`. É de graça — não existe tela de stack, existe escopo.
 */

import { escapeHtml } from '../fmt.js';
import { chipDoSummary } from '../kernel/regua.js';

export default {
  id: 'stacks',
  nome: 'Stacks',
  escopos: ['host'],
  span: 6,

  chip: (escopo, summary) => chipDoSummary(summary, 'stacks', (v) => ({
    rotulo: 'Stacks',
    valor: `${v.up}/${v.total}`,
    // stopped_with_domain null = ingress indisponível, não "nenhuma exposta".
    titulo: v.stopped_with_domain == null
      ? 'stacks inteiras no ar / total (exposição não avaliada)'
      : `${v.stopped_with_domain} parada(s) com domínio publicado`,
  })),

  render: (escopo, dados, corpo) => {
    const stacks = ((dados && dados.overview) || {}).stacks || [];
    if (!stacks.length) {
      corpo.innerHTML = '<div class="empty">Nenhuma stack encontrada</div>';
      return null;
    }
    const tom = { ok: 'ok', warn: 'warn', bad: 'bad' };
    corpo.innerHTML = `<div class="mod-lista">${stacks.map((s) =>
      `<button type="button" class="mod-linha" data-stack="${escapeHtml(s.id)}">
        <span class="item-status ${tom[s.worst] || 'exited'}"></span>
        <span class="mod-nome-cel">${escapeHtml(s.id)}</span>
        <span class="mod-meta">${s.running}/${s.total}</span>
      </button>`).join('')}</div>`;

    const abrir = dados && dados.abrirStack;
    if (typeof abrir === 'function') {
      corpo.querySelectorAll('[data-stack]').forEach((b) => {
        b.addEventListener('click', () => abrir(b.dataset.stack));
      });
    }
    return null;
  },
};
