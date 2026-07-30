/* Módulo `eventos` — B3 na interface (doc 11).
 *
 * O stream SSE já existe (`/api/events/stream`, F6). O que falta é a
 * persistência e o filtro no servidor — B3-residual, Sprint 2b. Até lá o módulo
 * mostra a janela ao vivo, e filtra no cliente pelo escopo.
 *
 * Sem chip: não há chave `eventos` no summary. Chip sem fonte seria dado
 * inventado, o que o doc 01 proíbe. Entra quando o B3-residual expuser
 * `summary.events`.
 */

import { escapeHtml } from '../fmt.js';

const LIMITE = 40;

export default {
  id: 'eventos',
  nome: 'Eventos',
  escopos: ['host', 'stack', 'container'],
  span: 6,

  render: (escopo, dados, corpo) => {
    const fila = [];
    let vivo = true;
    let fonte = null;

    corpo.innerHTML = '<div class="empty">Aguardando eventos…</div>';

    const interessa = (ev) => {
      if (escopo.t === 'host') return true;
      const alvo = (ev && ev.actor_name) || '';
      if (escopo.t === 'container') return alvo === escopo.id;
      return (ev && ev.stack) === escopo.id;
    };

    const pintar = () => {
      if (!vivo) return;
      if (!fila.length) {
        corpo.innerHTML = '<div class="empty">Nenhum evento neste escopo ainda</div>';
        return;
      }
      corpo.innerHTML = `<div class="mod-lista">${fila.map((e) =>
        `<div class="mod-item">
          <span class="mod-tag ev-${escapeHtml(e.action || '')}">${escapeHtml(e.action || '?')}</span>
          <span class="mod-nome-cel">${escapeHtml(e.actor_name || '')}</span>
          <span class="mod-meta">${escapeHtml(e.hora || '')}</span>
        </div>`).join('')}</div>`;
    };

    try {
      fonte = new EventSource('/api/events/stream');
      fonte.onmessage = (msg) => {
        let payload;
        try { payload = JSON.parse(msg.data); } catch { return; }
        if (!payload || payload.type !== 'docker_event') return;
        const ev = {
          action: payload.action || (payload.event && payload.event.Action),
          actor_name: payload.name || '',
          stack: payload.stack || '',
          hora: new Date().toLocaleTimeString('pt-BR'),
        };
        if (!interessa(ev)) return;
        fila.unshift(ev);
        if (fila.length > LIMITE) fila.length = LIMITE;
        pintar();
      };
      fonte.onerror = () => {
        // O EventSource do navegador reconecta sozinho; o backend já tem
        // backoff. Nada a fazer aqui além de não gritar.
      };
    } catch {
      corpo.innerHTML = '<div class="empty">Stream de eventos indisponível</div>';
    }

    return () => {
      vivo = false;
      if (fonte) { try { fonte.close(); } catch { /* já fechado */ } }
    };
  },
};
