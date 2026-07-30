/* Módulo `auditoria` (registro do doc 10 §1).
 *
 * Corpo reaproveitado de `screens/auditoria.js` — o doc 09 §A já previa isso como 🔧:
 * "a lógica de dados não muda". A 2a entrega a estrutura de módulos; a adaptação
 * visual de cada corpo à caixa do módulo viaja com o sprint do bloco dele.
 */

import { renderAuditoria } from '../screens/auditoria.js';
import { chipDoSummary } from '../kernel/regua.js';

export default {
  id: 'auditoria',
  nome: 'Auditoria',
  escopos: ['host', 'stack', 'container'],
  span: 6,
  chip: (escopo, summary) => chipDoSummary(summary, 'audit', v => (v.last_at ? { rotulo: 'Auditoria', valor: v.last_actor || 'registrada', titulo: `última ação em ${v.last_at}` } : { rotulo: 'Auditoria', valor: 'vazia', titulo: 'nenhuma mutação registrada' })),
  render: (escopo, dados, corpo) => renderAuditoria(corpo, escopo, dados),
};
