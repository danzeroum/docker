/* Módulo `backend` (registro do doc 10 §1).
 *
 * Corpo reaproveitado de `screens/backend.js` — o doc 09 §A já previa isso como 🔧:
 * "a lógica de dados não muda". A 2a entrega a estrutura de módulos; a adaptação
 * visual de cada corpo à caixa do módulo viaja com o sprint do bloco dele.
 */

import { renderBackend } from '../screens/backend.js';

export default {
  id: 'backend',
  nome: 'Backend & API',
  escopos: ['host'],
  span: 6,
  render: (escopo, dados, corpo) => renderBackend(corpo, escopo, dados),
};
