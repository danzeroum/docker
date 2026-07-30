/* Módulo `executivo` (registro do doc 10 §1).
 *
 * Corpo reaproveitado de `screens/executivo.js` — o doc 09 §A já previa isso como 🔧:
 * "a lógica de dados não muda". A 2a entrega a estrutura de módulos; a adaptação
 * visual de cada corpo à caixa do módulo viaja com o sprint do bloco dele.
 */

import { renderExecutivo } from '../screens/executivo.js';

export default {
  id: 'executivo',
  nome: 'Resumo executivo',
  escopos: ['host'],
  span: 12,
  render: (escopo, dados, corpo) => renderExecutivo(corpo, escopo, dados),
};
