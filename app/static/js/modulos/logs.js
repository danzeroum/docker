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
 * A busca (B5) e do INDICE, nao do tail: ela responde sobre 7 dias de log de
 * todos os containers, e o tail so tem as ultimas 80 linhas de um. Por isso o
 * campo funciona nos dois escopos, e no de stack ele e o unico conteudo — o
 * merge de tail por stack continua fora, porque seriam N fetches por render.
 *
 * Highlight NUNCA injeta HTML do log. O servidor devolve o trecho com
 * marcadores que nao sao markup; aqui o texto e escapado e a marcacao entra por
 * cima. Uma linha com `<script>` e DADO — e este e o unico lugar do cockpit que
 * renderiza texto arbitrario vindo de dentro dos containers.
 */

import { apiGet, apiGetText } from '../data.js';
import { escapeHtml } from '../fmt.js';

const TETO_LINHAS = 400;

export default {
  id: 'logs',
  nome: 'Logs',
  escopos: ['stack', 'container'],
  span: 12,

  render: (escopo, dados, corpo) => {
    const soBusca = escopo.t !== 'container';
    const id = soBusca ? null : escopo.id;
    let vivo = true;
    let fonte = null;
    let seguindo = false;
    const linhas = [];

    corpo.innerHTML = `<div class="logs-topo">
        <input type="search" class="logs-busca" data-busca placeholder="buscar nos logs…"
               aria-label="Buscar nos logs" />
        ${soBusca ? '' : '<button type="button" class="logs-follow" data-acao="follow" aria-pressed="false">&#9679; follow</button>'}
        <span class="logs-nota" data-nota></span>
      </div>
      <div data-resultados hidden></div>
      ${soBusca ? '' : '<pre class="logs-pre" data-pre></pre>'}`;

    const pre = corpo.querySelector('[data-pre]');
    const nota = corpo.querySelector('[data-nota]');
    const btn = corpo.querySelector('[data-acao="follow"]');
    const campo = corpo.querySelector('[data-busca]');
    const painel = corpo.querySelector('[data-resultados]');

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

    /* --- busca no indice (B5) -------------------------------------------- */

    function trechoSeguro(texto, marcas) {
      // Escapa PRIMEIRO, marca DEPOIS: os marcadores do servidor nao sao HTML,
      // entao sobrevivem ao escape e so entao viram <mark>. Uma linha de log
      // com `<script>alert(1)</script>` sai como texto visivel.
      const escapado = escapeHtml(String(texto || ''));
      const ini = escapeHtml(marcas.start);
      const fim = escapeHtml(marcas.end);
      return escapado.split(ini).join('<mark>').split(fim).join('</mark>');
    }

    function pintarResultados(data) {
      if (!vivo || !painel) return;
      painel.hidden = false;
      if (pre) pre.hidden = true;
      const achados = data.results || [];
      if (!achados.length) {
        painel.innerHTML = '<div class="empty">Nenhuma linha encontrada nos ultimos 7 dias</div>';
        return;
      }
      painel.innerHTML = `<div class="mod-lista">${achados.map((r) =>
        `<button type="button" class="log-achado" data-ir="${escapeHtml(r.container || '')}">
          <span class="mod-tag">${escapeHtml(r.container || '')}</span>
          <span class="log-trecho">${trechoSeguro(r.trecho, data.marks || {})}</span>
          <span class="mod-meta">${escapeHtml(String(r.ts || '').slice(11, 19))}</span>
        </button>`).join('')}</div>`;

      const abrir = dados && dados.abrirContainer;
      if (typeof abrir === 'function') {
        painel.querySelectorAll('[data-ir]').forEach((b) => {
          b.addEventListener('click', () => abrir(b.dataset.ir));
        });
      }
    }

    function limparBusca() {
      if (painel) { painel.hidden = true; painel.innerHTML = ''; }
      if (pre) pre.hidden = false;
      if (nota && !seguindo) nota.textContent = '';
    }

    async function buscar(termo) {
      if (termo.length < 3) {
        // Mesmo piso do servidor, dito na tela antes de gastar a requisicao.
        if (nota) nota.textContent = 'digite ao menos 3 caracteres';
        limparBusca();
        return;
      }
      if (nota) nota.textContent = 'buscando…';
      // encodeURIComponent no operador FTS: defesa em profundidade com a
      // sanitizacao do servidor, que e quem de fato garante.
      const escopoQuery = id ? `&container=${encodeURIComponent(id)}` : '';
      const { data, error } = await apiGet(
        'logs_busca', `/api/logs/search?q=${encodeURIComponent(termo)}${escopoQuery}`
      );
      if (!vivo) return;
      if (error) {
        if (nota) nota.textContent = error;
        return;
      }
      if (nota) {
        // A expressao efetiva na tela: quem digitou `erro NEAR/2` precisa ver
        // que virou busca por duas palavras, nao achar que o log e que nao tem.
        nota.textContent = `${data.count} resultado(s) · ${data.expression}`;
      }
      pintarResultados(data);
    }

    if (campo) {
      let debounce = null;
      campo.addEventListener('input', () => {
        clearTimeout(debounce);
        const termo = campo.value.trim();
        if (!termo) { if (nota) nota.textContent = ''; limparBusca(); return; }
        debounce = setTimeout(() => buscar(termo), 300);
      });
    }

    if (!soBusca) fetchLines();

    return () => {
      vivo = false;
      pararFollow();
    };
  },
};
