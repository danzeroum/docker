/* Módulo `capacidade` (registro do doc 10 §1).
 *
 * Corpo reaproveitado de `screens/capacidade.js` — o doc 09 §A já previa isso como 🔧:
 * "a lógica de dados não muda". A 2a entrega a estrutura de módulos; a adaptação
 * visual de cada corpo à caixa do módulo viaja com o sprint do bloco dele.
 */

import { renderCapacidade } from '../screens/capacidade.js';
import { chipDoSummary } from '../kernel/regua.js';

export default {
  id: 'capacidade',
  nome: 'Capacidade',
  escopos: ['host'],
  span: 12,
  chip: (escopo, summary) => chipDoSummary(summary, 'capacity', v => ({ rotulo: 'Projeção', valor: v.days_to_90 != null ? `~${v.days_to_90}d` : (v.disk_pct != null ? `${Math.round(v.disk_pct)}%` : '—'), titulo: v.days_to_90 != null ? `disco em 90% em ~${v.days_to_90} dias (r²=${v.r2})` : 'sem tendência sustentada — projeção calada' })),
  render: (escopo, dados, corpo) => renderCapacidade(corpo, escopo, dados),
};
