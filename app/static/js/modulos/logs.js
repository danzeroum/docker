/* Módulo `logs` — tail + follow por SSE. A busca FTS5 é o B5 (Sprint 3).
 *
 * O tail e o follow vinham da tela de Logs do main.js e foram portados inteiros.
 * Duas coisas precisam sobreviver ao porte, porque cada uma corrigiu um bug real:
 *
 * - `apiGetText`, não `apiGet`: log é text/plain. Ler como JSON deixava a tela
 *   vazia sem erro visível.
 * - o follow é rota própria por EventSource (`/logs/stream`), não repoll do
 *   tail: reler 80 linhas por segundo para descobrir que nada mudou é I/O
 *   jogado fora, e perde linha entre duas leituras.
 *
 * No escopo stack o protótipo faz merge dos containers da stack; isso chega com
 * o B5, que traz busca no servidor — fazer merge no cliente agora significaria
 * N fetches por render, o oposto da economia do doc 10 §3.
 */

import { apiGetText } from '../data.js';
import { escapeHtml } from '../fmt.js';

const TETO_LINHAS = 400;

export default {
  id: 'logs',
  nome: 'Logs',
  escopos: ['stack', 'container'],
  span: 12,

  render: (escopo, dados, corpo) => {
    if (escopo.t !== 'container') {
      corpo.innerHTML = '<div class="empty">Busca de logs por stack chega com o B5 '
        + '(FTS5 no servidor). Abra um container para ver o tail e o follow dele.</div>';
      return null;
    }

    const id = escopo.id;
    let vivo = true;
    let fonte = null;
    let seguindo = false;
    const linhas = [];

    corpo.innerHTML = `<div class="logs-topo">
        <button type="button" class="logs-follow" data-acao="follow" aria-pressed="false">&#9679; follow</button>
        <span class="logs-nota" data-nota></span>
      </div>
      <pre class="logs-pre" data-pre></pre>`;

    const pre = corpo.querySelector('[data-pre]');
    const nota = corpo.querySelector('[data-nota]');
    const btn = corpo.querySelector('[data-acao="follow"]');

    function pintar() {
      if (!vivo || !pre) return;
      // textContent, não innerHTML: log é conteúdo hostil por natureza.
      pre.textContent = linhas.join('\n');
      pre.scrollTop = pre.scrollHeight;
    }

    async function fetchLines() {
      const { data, error } = await apiGetText(
        `mod_logs_${id}`, `/api/containers/${encodeURIComponent(id)}/logs?tail=80`
      );
      if (!vivo) return { aborted: true };
      if (error) {
        if (pre) pre.innerHTML = `<span class="empty">${escapeHtml(error)}</span>`;
        return { aborted: false };
      }
      const texto = String(data || '').trim();
      linhas.length = 0;
      if (texto) linhas.push(...texto.split('\n'));
      if (!linhas.length) {
        if (pre) pre.innerHTML = '<span class="empty">Sem linhas de log</span>';
        return { aborted: false };
      }
      pintar();
      return { aborted: false };
    }

    function pararFollow() {
      seguindo = false;
      if (fonte) { try { fonte.close(); } catch { /* já fechado */ } fonte = null; }
      if (btn) btn.setAttribute('aria-pressed', 'false');
      if (nota) nota.textContent = '';
    }

    function iniciarFollow() {
      seguindo = true;
      if (btn) btn.setAttribute('aria-pressed', 'true');
      if (nota) nota.textContent = 'ao vivo, direto do daemon';
      fonte = new EventSource(`/api/containers/${id}/logs/stream`);
      fonte.onmessage = (ev) => {
        if (!vivo) return;
        const texto = String((ev && ev.data) || '');
        if (!texto) return;
        linhas.push(texto);
        if (linhas.length > TETO_LINHAS) linhas.splice(0, linhas.length - TETO_LINHAS);
        pintar();
      };
      fonte.onerror = () => {
        // O EventSource reconecta sozinho e o backend tem backoff; só avisa.
        if (nota) nota.textContent = 'reconectando…';
      };
    }

    if (btn) {
      btn.addEventListener('click', () => {
        if (seguindo) pararFollow();
        else iniciarFollow();
      });
    }

    fetchLines();

    return () => {
      vivo = false;
      pararFollow();
    };
  },
};
