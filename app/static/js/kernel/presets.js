/* Presets nomeados por tipo de cockpit — extraídos do protótipo completo.
 *
 * Preset = ponto de partida nomeado, não modo (doc 10 §2). Qualquer ajuste
 * manual vira "personalizado" sem perder o preset de origem.
 *
 * Cada preset amarra um objetivo, não um gosto (doc 10 §4, recomendação de OKR):
 * Operação → MTTR (o crítico a 0 cliques) · Capacidade → antecedência da
 * projeção · Executivo → resultado por projeto. Módulo que não alimenta a
 * decisão do preset sai dele.
 *
 * DECISÃO DE ESCOPO: os presets referenciam apenas os 13 módulos do protótipo.
 * Plantão, Executivo, Backend & API e Topologia estão registrados (nada se
 * perde) mas ficam fora de qualquer preset padrão — só aparecem via
 * Personalizar. Registrado no doc 14.
 */

export const PRESETS = {
  host: [
    {
      id: 'operacao',
      label: 'Operação',
      ordem: ['atencao', 'containers', 'stacks', 'ingress', 'capacidade', 'armazenamento', 'eventos', 'drift', 'tarefas', 'auditoria', 'metricas', 'logs'],
      ocultos: ['drift', 'logs'],
    },
    {
      id: 'capacidade',
      label: 'Capacidade',
      ordem: ['capacidade', 'armazenamento', 'metricas', 'containers', 'atencao', 'stacks', 'ingress', 'eventos', 'drift', 'tarefas', 'auditoria', 'logs'],
      ocultos: ['logs', 'auditoria', 'eventos'],
    },
    {
      id: 'executivo',
      label: 'Executivo',
      ordem: ['atencao', 'tarefas', 'capacidade', 'armazenamento', 'stacks', 'ingress', 'drift', 'eventos', 'containers', 'metricas', 'logs', 'auditoria'],
      // Executivo esconde 4 — e os chips continuam vivos na régua (doc 12 §5).
      ocultos: ['containers', 'metricas', 'logs', 'auditoria'],
    },
  ],
  stack: [
    {
      id: 'operacao',
      label: 'Operação',
      ordem: ['atencao', 'containers', 'metricas', 'ingress', 'eventos', 'drift', 'tarefas', 'auditoria', 'logs'],
      ocultos: ['auditoria', 'logs'],
    },
    {
      id: 'deploy',
      label: 'Deploy',
      ordem: ['auditoria', 'eventos', 'containers', 'logs', 'drift', 'tarefas', 'atencao', 'metricas', 'ingress'],
      ocultos: ['metricas', 'ingress'],
    },
  ],
  container: [
    {
      id: 'diagnostico',
      label: 'Diagnóstico',
      ordem: ['metricas', 'atencao', 'config', 'ingress', 'eventos', 'tarefas', 'logs', 'auditoria'],
      ocultos: ['tarefas', 'auditoria'],
    },
    {
      id: 'configuracao',
      label: 'Configuração',
      ordem: ['config', 'ingress', 'metricas', 'atencao', 'eventos', 'tarefas', 'logs', 'auditoria'],
      ocultos: ['tarefas', 'auditoria', 'eventos'],
    },
  ],
};

export function doTipo(tipo) {
  return PRESETS[tipo] || PRESETS.host;
}

export function padraoDoTipo(tipo) {
  return doTipo(tipo)[0] || null;
}

export function porId(tipo, id) {
  return doTipo(tipo).find((p) => p.id === id) || null;
}
