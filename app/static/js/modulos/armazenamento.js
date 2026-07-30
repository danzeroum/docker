/* Módulo `armazenamento` — B1 na interface (doc 11).
 *
 * Escopo host só: órfão é propriedade do daemon, não de uma stack. O botão de
 * prune é da 2b (B10-residual); aqui a leitura já fica de pé, e o chip vive do
 * summary mesmo com o módulo oculto.
 */

import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { chipDoSummary } from '../kernel/regua.js';

const ROTULO = { image: 'imagem', volume: 'volume', container: 'container' };

function gb(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(0)} MB`;
  return `${n} B`;
}

export default {
  id: 'armazenamento',
  nome: 'Armazenamento',
  escopos: ['host'],
  span: 6,

  chip: (escopo, summary) => chipDoSummary(summary, 'storage', (v) => ({
    rotulo: 'Recuperável',
    valor: v.reclaimable_gb != null ? `${v.reclaimable_gb} GB` : '—',
    titulo: `${v.orphans} recurso(s) órfão(s)`,
  })),

  render: (escopo, dados, corpo) => {
    let vivo = true;
    corpo.innerHTML = '<div class="skeleton" style="height:110px"></div>';

    (async () => {
      const { data, error } = await apiGet('mod_storage', '/api/storage');
      if (!vivo) return;
      if (error || !data) {
        // Degrada o cartão, não a tela. E diz a idade do dado em vez de zero.
        corpo.innerHTML = `<div class="empty">${escapeHtml(error || 'Sem leitura de storage')}</div>`;
        return;
      }
      const orfaos = data.orphans || [];
      corpo.innerHTML = `<div class="stg-total">${gb(data.reclaimable_bytes)}<span> recuperáveis</span></div>`
        + (orfaos.length
          ? `<div class="mod-lista">${orfaos.slice(0, 6).map((o) =>
              `<div class="mod-item">
                <span class="mod-tag">${escapeHtml(ROTULO[o.type] || o.type)}</span>
                <span class="mod-nome-cel" title="${escapeHtml(o.reason || '')}">${escapeHtml(o.name || '')}</span>
                <span class="mod-meta">${gb(o.size_bytes)}</span>
              </div>`).join('')}</div>`
          : '<div class="empty ok">Nenhum recurso órfão</div>');
    })();

    return () => { vivo = false; };
  },
};
