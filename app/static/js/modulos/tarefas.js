/* Módulo `tarefas` (registro do doc 10 §1).
 *
 * Corpo reaproveitado de `screens/tarefas.js` — o doc 09 §A já previa isso como 🔧:
 * "a lógica de dados não muda". A 2a entrega a estrutura de módulos; a adaptação
 * visual de cada corpo à caixa do módulo viaja com o sprint do bloco dele.
 */

import { renderTarefas } from '../screens/tarefas.js';
import { chipDoSummary } from '../kernel/regua.js';

export default {
  id: 'tarefas',
  nome: 'Tarefas',
  escopos: ['host', 'stack'],
  span: 6,
  chip: (escopo, summary) => chipDoSummary(summary, 'tasks', v => ({ rotulo: 'Tarefas', valor: `${v.total} · ${v.todo}`, titulo: `${v.total} tarefas, ${v.todo} a fazer` })),
  render: (escopo, dados, corpo) => renderTarefas(corpo, escopo, dados),
};
