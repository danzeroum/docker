/* Módulo `containers` — read model por escopo (doc 10 §1).
 *
 * É o exemplo canônico de "1 registro × N escopos": no host lista os 15, no
 * escopo stack lista só os da stack. Nenhum código duplicado entre os dois — a
 * diferença é um filtro, não uma tela.
 *
 * Clicar numa linha abre a subtela do container (navegação de 3 níveis, doc 10
 * §2: nunca mais de 2 cliques entre quaisquer dois níveis).
 */

import { escapeHtml } from '../fmt.js';
import { chipDoSummary } from '../kernel/regua.js';
import { carregarUpdates, seloDeImagem } from '../updates.js';

function saude(c) {
  // Mesma regra do campo Health explícito entregue no B4: sem healthcheck é
  // ausência de medida, não saúde confirmada.
  if (!c) return null;
  if (c.health && c.health !== 'none') return c.health;
  return null;
}

function linha(c, aoAbrir) {
  const s = saude(c);
  const estado = s === 'unhealthy' ? 'unhealthy' : (c.state || 'unknown');
  const selo = (s === 'unhealthy' || s === 'starting')
    ? `<span class="item-health ${s}">${s}</span>` : '';
  return `<button type="button" class="mod-linha" data-abrir="${escapeHtml(c.name || '')}"
    data-imagem="${escapeHtml(c.image || '')}">
    <span class="item-status ${escapeHtml(estado)}"></span>
    <span class="mod-nome-cel">${escapeHtml(c.name || '')}${selo}</span>
    <span class="mod-meta">${escapeHtml(c.stack || '')}</span>
  </button>`;
}

/* O selo entra depois da lista, não junto: o estado das imagens vem de outra
 * rota e chega mais tarde que o overview. Esperar por ele para desenhar a lista
 * atrasaria os 15 containers por causa de um dado diário. */
function pintarSelos(corpo, estado) {
  corpo.querySelectorAll('[data-imagem]').forEach((el) => {
    const selo = seloDeImagem(estado, el.dataset.imagem);
    if (!selo) return;
    const alvo = el.querySelector('.mod-nome-cel');
    if (!alvo) return;
    const marca = document.createElement('span');
    marca.className = 'selo-update';
    marca.textContent = selo.texto;
    if (selo.titulo) marca.title = selo.titulo;
    alvo.appendChild(marca);
  });
}

export default {
  id: 'containers',
  nome: 'Containers',
  escopos: ['host', 'stack'],
  span: 6,

  chip: (escopo, summary) => {
    // Dois dados num chip só: quantos no ar e o pior score de segurança. O
    // score entra aqui porque o doc 11 pede "score mínimo no chip".
    const seg = summary && summary.security;
    const base = chipDoSummary(summary, 'stacks', () => ({ rotulo: 'Containers', valor: '' }));
    if (!summary) return null;
    const c = summary.counters || null;
    const pior = seg && seg.min_score != null ? ` · S${seg.min_score}` : '';
    if (!c) {
      return base && base.stale ? { rotulo: 'Containers', valor: '—', stale: true } : null;
    }
    return {
      rotulo: 'Containers',
      valor: `${c.running}/${c.total}${c.attention ? ` · ${c.attention}!` : ''}${pior}`,
      titulo: 'no ar / total · precisando de atenção · pior score de segurança',
    };
  },

  render: (escopo, dados, corpo) => {
    const overview = (dados && dados.overview) || {};
    let lista = overview.containers || [];
    if (escopo.t === 'stack') lista = lista.filter((c) => c.stack === escopo.id);

    if (!lista.length) {
      corpo.innerHTML = '<div class="empty">Nenhum container neste escopo</div>';
      return null;
    }
    const aoAbrir = dados && dados.abrirContainer;
    corpo.innerHTML = `<div class="mod-lista">${lista.map(linha).join('')}</div>`;
    if (typeof aoAbrir === 'function') {
      corpo.querySelectorAll('[data-abrir]').forEach((b) => {
        b.addEventListener('click', () => aoAbrir(b.dataset.abrir));
      });
    }

    let vivo = true;
    carregarUpdates().then((estado) => {
      if (vivo) pintarSelos(corpo, estado);
    });
    return () => { vivo = false; };
  },
};
