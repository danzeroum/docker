/* Módulo `metricas` — B2 na interface (doc 11): o backend que faltava.
 *
 * O read model por escopo aqui é literal: host lê os vitais da amostra, stack
 * soma os containers dela, container busca a série de
 * `/api/containers/{id}/history` — a rota entregue na Sprint 1.
 *
 * Declara a janela e a amostra em toda série (doc 10 §4, análise descritiva):
 * apresentar média horária sem dizer que é média é apresentar agregado como
 * medida. A resolução vem do próprio payload.
 */

import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { definirSub } from '../kernel/cockpit.js';

function sparkline(pontos, chave) {
  const vals = pontos.map((p) => Number(p[chave]) || 0);
  if (!vals.length) return '';
  const max = Math.max(...vals, 1);
  const largura = 100 / vals.length;
  return `<div class="spark" role="img" aria-label="série de ${escapeHtml(chave)}">${
    vals.map((v) => `<span class="spark-b" style="height:${Math.max(2, (v / max) * 100)}%;width:${largura}%"></span>`).join('')
  }</div>`;
}

function mb(bytes) {
  return `${Math.round((Number(bytes) || 0) / (1024 * 1024))} MB`;
}

export default {
  id: 'metricas',
  nome: 'Métricas',
  escopos: ['host', 'stack', 'container'],
  span: 6,

  render: (escopo, dados, corpo) => {
    const overview = (dados && dados.overview) || {};

    if (escopo.t === 'host') {
      const v = overview.vitals || {};
      definirSub('metricas', 'amostra 5s');
      corpo.innerHTML = `<div class="met-grade">
        <div><span>CPU</span><strong>${v.cpu_pct != null ? `${v.cpu_pct}%` : '—'}</strong></div>
        <div><span>RAM</span><strong>${v.mem_pct != null ? `${v.mem_pct}%` : '—'}</strong></div>
        <div><span>Swap</span><strong>${v.swap_pct != null ? `${v.swap_pct}%` : '—'}</strong></div>
      </div>`;
      return null;
    }

    if (escopo.t === 'stack') {
      const daStack = (overview.containers || []).filter((c) => c.stack === escopo.id);
      const cpu = daStack.reduce((a, c) => a + (Number(c.cpu_pct) || 0), 0);
      const mem = daStack.reduce((a, c) => a + (Number(c.mem_usage) || 0), 0);
      // Soma da stack é agregado descritivo, nunca "capacidade prevista".
      definirSub('metricas', `soma de ${daStack.length} container(es) · amostra 5s`);
      corpo.innerHTML = `<div class="met-grade">
        <div><span>CPU somada</span><strong>${cpu.toFixed(1)}%</strong></div>
        <div><span>Memória</span><strong>${mb(mem)}</strong></div>
      </div>`;
      return null;
    }

    // container: série real da rota do B2, com toggle de janela
    let vivo = true;
    let janela = '24h';
    const cache = new Map();  // uma requisição por troca, com a anterior guardada

    corpo.innerHTML = `<div class="met-topo">
        <button type="button" class="met-jan met-ativo" data-range="24h">24h</button>
        <button type="button" class="met-jan" data-range="7d">7d</button>
      </div>
      <div data-serie><div class="skeleton" style="height:90px"></div></div>`;

    const alvo = corpo.querySelector('[data-serie]');

    function marcarBotoes() {
      corpo.querySelectorAll('[data-range]').forEach((b) => {
        b.classList.toggle('met-ativo', b.dataset.range === janela);
        b.setAttribute('aria-pressed', b.dataset.range === janela ? 'true' : 'false');
      });
    }

    function pintar(data) {
      if (!vivo || !alvo) return;
      const pontos = data.points || [];
      if (!pontos.length) {
        // Borda do primeiro dia de uso: todo container novo passa por ela.
        // "coletando…" é diferente de gráfico vazio quebrado.
        definirSub('metricas', 'coletando…');
        alvo.innerHTML = '<div class="empty">Coletando… a série aparece após os primeiros minutos</div>';
        return;
      }
      const resolucao = data.resolution === 'hourly' ? 'média horária' : 'leitura de 60s';
      definirSub('metricas', `${resolucao} · janela ${data.range_hours}h · ${pontos.length} pontos`);
      // Uma passada: monta o HTML inteiro e escreve uma vez. Escrever por ponto
      // provocaria 500 reflows num container com histórico cheio.
      alvo.innerHTML = `<div class="met-serie"><span>CPU</span>${sparkline(pontos, 'cpu_pct')}</div>`
        + `<div class="met-serie"><span>Memória</span>${sparkline(pontos, 'mem_bytes')}</div>`;
    }

    async function carregar() {
      if (cache.has(janela)) { pintar(cache.get(janela)); return; }
      const { data, error } = await apiGet(
        `mod_hist_${escopo.id}_${janela}`,
        `/api/containers/${encodeURIComponent(escopo.id)}/history?range=${janela}`
      );
      if (!vivo) return;
      if (error || !data) {
        if (alvo) alvo.innerHTML = `<div class="empty">${escapeHtml(error || 'Sem histórico')}</div>`;
        return;
      }
      cache.set(janela, data);
      pintar(data);
    }

    corpo.querySelectorAll('[data-range]').forEach((b) => {
      b.addEventListener('click', () => {
        if (janela === b.dataset.range) return;
        janela = b.dataset.range;
        marcarBotoes();
        carregar();
      });
    });

    carregar();
    return () => { vivo = false; };
  },
};
