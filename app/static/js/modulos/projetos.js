/* Módulo `projetos` — gerenciador de stacks compose (escopo host).
 *
 * NÃO estava no protótipo, e por isso quase virou funcionalidade perdida no
 * porte: é a tela que faz start/stop de stack por HTTP, atrás de
 * `require_unlock`, e foi ela que obrigou a F5 a existir. Registrada como os
 * outros extras — fora dos presets, disponível no Personalizar.
 *
 * Sem chip: não há chave `projetos` no summary. O chip de `stacks` já cobre a
 * pergunta "quantas no ar", e dois chips para o mesmo dado violaria "um dado,
 * uma origem" (doc 10 §4).
 */

import { renderProjects } from '../screens/projects.js';

export default {
  id: 'projetos',
  nome: 'Projetos (compose)',
  escopos: ['host'],
  span: 12,
  render: (escopo, dados, corpo) => renderProjects(corpo, escopo, dados),
};
