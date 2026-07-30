/* Módulo `atencao` (registro do doc 10 §1).
 *
 * Corpo reaproveitado de `screens/attention.js` — o doc 09 §A já previa isso como 🔧:
 * "a lógica de dados não muda". A 2a entrega a estrutura de módulos; a adaptação
 * visual de cada corpo à caixa do módulo viaja com o sprint do bloco dele.
 */

import { renderAttention } from '../screens/attention.js';
import { chipDoSummary } from '../kernel/regua.js';

export default {
  id: 'atencao',
  nome: 'Atenção',
  escopos: ['host', 'stack', 'container'],
  span: 6,
  chip: (escopo, summary) => chipDoSummary(summary, 'findings', v => ({ rotulo: 'Atenção', valor: v.critical ? `${v.critical} crít +${Math.max(0, v.open - v.critical)}` : `${v.open}`, titulo: `${v.open} achados abertos` })),
  render: (escopo, dados, corpo) => renderAttention(corpo, escopo, dados),
};
