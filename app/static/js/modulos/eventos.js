/* Módulo `eventos` — B3 na interface (doc 11).
 *
 * Timeline nos 3 escopos. O filtro é do SERVIDOR, sempre: o módulo pede
 * `?container=` ou `?stack=` e recebe só o que interessa, tanto no histórico
 * quanto no stream. Filtrar no cliente significaria receber a timeline inteira
 * do host em cada cockpit aberto — e num crash loop isso é o stream todo.
 *
 * Duas fontes, um contrato: `GET /api/events` traz o passado (sobrevive a
 * restart do cockpit, que é o ponto da v11) e o SSE traz o que chega depois.
 * O histórico vem primeiro para a timeline não nascer vazia.
 */

import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { chipDoSummary } from '../kernel/regua.js';

const TETO = 60;

function idade(ts) {
  if (!ts) return '';
  const t = new Date(String(ts).replace('Z', 'Z')).getTime();
  if (!t || Number.isNaN(t)) return '';
  const seg = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (seg < 60) return `há ${seg}s`;
  if (seg < 3600) return `há ${Math.floor(seg / 60)}min`;
  if (seg < 86400) return `há ${Math.floor(seg / 3600)}h`;
  return `há ${Math.floor(seg / 86400)}d`;
}

function query(escopo) {
  if (escopo.t === 'container') return `container=${encodeURIComponent(escopo.id)}`;
  if (escopo.t === 'stack') return `stack=${encodeURIComponent(escopo.id)}`;
  return '';
}

function linhaHtml(e) {
  const sev = e.severity || 'info';
  const detalhe = e.exit_code ? ` <span class="ev-exit">exit ${escapeHtml(String(e.exit_code))}</span>` : '';
  return `<div class="mod-item ev-${escapeHtml(sev)}">
    <span class="mod-tag ev-acao">${escapeHtml(e.action || '?')}</span>
    <span class="mod-nome-cel">${escapeHtml(e.actor_name || '')}${detalhe}</span>
    <span class="mod-meta">${escapeHtml(idade(e.ts))}</span>
  </div>`;
}

export default {
  id: 'eventos',
  nome: 'Eventos',
  escopos: ['host', 'stack', 'container'],
  span: 6,

  chip: (escopo, summary) => chipDoSummary(summary, 'events', (v) => {
    if (!v.total) return { valor: 'nenhum', titulo: 'timeline vazia' };
    const c = v.last_critical;
    return {
      rotulo: 'Eventos',
      valor: c ? `${c.action} ${c.container}` : idade(v.last_at) || String(v.total),
      titulo: c
        ? `último crítico: ${c.action} em ${c.container} (${idade(c.ts)})`
        : `${v.total} evento(s) na timeline`,
    };
  }),

  render: (escopo, dados, corpo) => {
    let vivo = true;
    let fonte = null;
    const fila = [];
    const q = query(escopo);

    corpo.innerHTML = '<div class="skeleton" style="height:110px"></div>';

    function pintar() {
      if (!vivo) return;
      if (!fila.length) {
        corpo.innerHTML = '<div class="empty">Nenhum evento neste escopo ainda</div>';
        return;
      }
      corpo.innerHTML = `<div class="mod-lista">${fila.slice(0, TETO).map(linhaHtml).join('')}</div>`;
    }

    async function historico() {
      const url = `/api/events?limit=40${q ? `&${q}` : ''}`;
      const { data, error } = await apiGet(`mod_ev_${escopo.t}_${escopo.id || 'host'}`, url);
      if (!vivo) return;
      if (error || !data) {
        corpo.innerHTML = `<div class="empty">${escapeHtml(error || 'Sem timeline')}</div>`;
        return;
      }
      fila.length = 0;
      fila.push(...(data.events || []));
      pintar();
      aoVivo();
    }

    function aoVivo() {
      try {
        // O MESMO filtro do histórico vai para o stream: o servidor corta na
        // origem, e o cliente não recebe evento que não pediu.
        fonte = new EventSource(`/api/events/stream${q ? `?${q}` : ''}`);
        fonte.onmessage = (msg) => {
          if (!vivo) return;
          let payload;
          try { payload = JSON.parse(msg.data); } catch { return; }
          if (!payload || payload.type !== 'docker_event') return;
          const linha = payload.row;
          // Sem `row` o evento não virou linha (ação fora da lista do ring).
          if (!linha || typeof linha !== 'object') return;
          fila.unshift(linha);
          if (fila.length > TETO) fila.length = TETO;
          pintar();
        };
        fonte.onerror = () => {
          // O EventSource reconecta sozinho e o backend tem backoff próprio.
        };
      } catch {
        // Sem stream a timeline continua servindo o histórico já carregado.
      }
    }

    historico();

    return () => {
      vivo = false;
      if (fonte) { try { fonte.close(); } catch { /* já fechado */ } }
    };
  },
};
