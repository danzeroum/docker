/* Módulo `ingress` (registro do doc 10 §1).
 *
 * Corpo reaproveitado de `screens/ingress.js` — o doc 09 §A já previa isso como 🔧:
 * "a lógica de dados não muda". A 2a entrega a estrutura de módulos; a adaptação
 * visual de cada corpo à caixa do módulo viaja com o sprint do bloco dele.
 */

import { renderIngress } from '../screens/ingress.js';
import { chipDoSummary } from '../kernel/regua.js';

export default {
  id: 'ingress',
  nome: 'Ingress & TLS',
  escopos: ['host', 'stack', 'container'],
  span: 6,
  chip: (escopo, summary) => chipDoSummary(summary, 'ingress', v => (v.hosts == null ? null : { rotulo: 'HTTPS', valor: `${v.https_forced}/${v.hosts}`, titulo: 'hosts públicos com redirecionamento forçado' })),
  render: (escopo, dados, corpo) => renderIngress(corpo, escopo, dados),
};
