/* Módulo `drift` — B8 na interface (doc 11).
 *
 * O backend do B8 é da Sprint 5. Este módulo existe agora por uma razão de
 * contrato: o chip lê `summary.drift`, que já sai no payload com `count: null`.
 * Assim a régua não muda de forma quando o drift chegar, e o módulo declara
 * ausência de fonte em vez de mostrar "0 divergências" — que seria uma
 * afirmação falsa sobre a infraestrutura.
 */

import { chipDoSummary } from '../kernel/regua.js';

export default {
  id: 'drift',
  nome: 'Drift',
  escopos: ['host', 'stack'],
  span: 6,

  chip: (escopo, summary) => chipDoSummary(summary, 'drift', (v) => (
    v.count == null ? null : { rotulo: 'Drift', valor: String(v.count), titulo: 'divergências compose × runtime' }
  )),

  render: (escopo, dados, corpo) => {
    corpo.innerHTML = '<div class="empty">Comparação compose × runtime ainda não coletada '
      + '(B8). Nenhuma divergência foi avaliada — não é o mesmo que nenhuma existir.</div>';
    return null;
  },
};
