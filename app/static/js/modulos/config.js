/* Módulo `config` — compose efetivo do container (escopo container).
 *
 * Imagem, portas, limites, healthcheck e política de restart do inspect, que já
 * passa pela máscara de segredo no servidor (`mask_inspect`). Ganha a linha
 * "Score de segurança" com as violações nomeadas — B4 na interface (doc 11).
 */

import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';

function linha(rotulo, valor, tom) {
  return `<div class="cfg-linha${tom ? ` cfg-${tom}` : ''}">
    <span>${escapeHtml(rotulo)}</span><strong>${escapeHtml(String(valor))}</strong></div>`;
}

export default {
  id: 'config',
  nome: 'Configuração',
  escopos: ['container'],
  span: 6,

  render: (escopo, dados, corpo) => {
    let vivo = true;
    corpo.innerHTML = '<div class="skeleton" style="height:120px"></div>';

    (async () => {
      const [insp, seg] = await Promise.all([
        apiGet(`mod_cfg_${escopo.id}`, `/api/containers/${encodeURIComponent(escopo.id)}/json`),
        apiGet('mod_cfg_sec', '/api/security'),
      ]);
      if (!vivo) return;
      if (insp.error || !insp.data) {
        corpo.innerHTML = `<div class="empty">${escapeHtml(insp.error || 'Sem inspect')}</div>`;
        return;
      }
      const d = insp.data;
      const hc = d.HostConfig || {};
      const cfg = d.Config || {};
      const st = d.State || {};
      const saude = (st.Health && st.Health.Status) || null;
      const mem = Number(hc.Memory) || 0;

      let html = linha('Imagem', cfg.Image || '—')
        + linha('Usuário', cfg.User || '(vazio = root)', cfg.User ? '' : 'warn')
        + linha('Limite de memória', mem > 0 ? `${Math.round(mem / (1024 * 1024))} MB` : 'sem limite', mem > 0 ? '' : 'warn')
        + linha('Restart policy', (hc.RestartPolicy && hc.RestartPolicy.Name) || '—')
        // Sem healthcheck é ausência de medida, não saúde confirmada.
        + linha('Healthcheck', saude || 'não definido', saude === 'unhealthy' ? 'bad' : '');

      const meu = !seg.error && seg.data
        ? (seg.data.containers || []).find((c) => c.id === escopo.id || c.name === escopo.id)
        : null;
      if (meu) {
        html += linha('Score de segurança', `${meu.score}/100`,
          meu.score >= 85 ? 'ok' : (meu.score >= 60 ? 'warn' : 'bad'));
        if ((meu.violations || []).length) {
          html += `<ul class="cfg-viol">${meu.violations.map((v) =>
            `<li class="cfg-${escapeHtml(v.severity)}"><strong>${escapeHtml(v.rule)}</strong>
              <span>${escapeHtml(v.title)}</span></li>`).join('')}</ul>`;
        }
      }
      corpo.innerHTML = html;
    })();

    return () => { vivo = false; };
  },
};
