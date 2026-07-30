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
import { atributo, deMolde, lista, mostrar, texto } from '../kernel/patch.js';

const TETO_LINHAS = 400;

/* A casca — e o campo de busca dentro dela — nasce no monte e nunca mais é
 * reescrita (doc 13 §2). Antes o módulo inteiro era remontado a cada leitura do
 * kernel, e com ele o `<input>`: digitar `oom` significava perder o `o` no
 * ciclo seguinte, com o cursor voltando para o começo de um campo novo. É o
 * único campo de texto do cockpit que fica dentro de um cartão que atualiza
 * sozinho, e por isso era o mais fácil de flagrar e o mais irritante de usar. */
const MOLDE_ACHADO = '<button type="button" class="log-achado" data-ir="">'
  + '<span class="mod-tag" data-container></span>'
  + '<span class="log-trecho" data-trecho></span>'
  + '<span class="mod-meta" data-hora></span>'
  + '</button>';

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
      <div data-resultados hidden>
        <div class="empty" data-sem-achado hidden>Nenhuma linha encontrada nos ultimos 7 dias</div>
        <div class="mod-lista" data-achados></div>
      </div>
      ${soBusca ? '' : '<pre class="logs-pre" data-pre></pre>'}`;

    const pre = corpo.querySelector('[data-pre]');
    const nota = corpo.querySelector('[data-nota]');
    const btn = corpo.querySelector('[data-acao="follow"]');
    const campo = corpo.querySelector('[data-busca]');
    const painel = corpo.querySelector('[data-resultados]');
    const semAchado = corpo.querySelector('[data-sem-achado]');
    const listaAchados = corpo.querySelector('[data-achados]');

    // Delegação numa lista que nasce vazia: o handler existe antes do primeiro
    // resultado e sobrevive a todos os seguintes.
    if (listaAchados) {
      listaAchados.addEventListener('click', (ev) => {
        const b = ev.target.closest ? ev.target.closest('[data-ir]') : null;
        const abrir = dados && dados.abrirContainer;
        if (b && typeof abrir === 'function') abrir(b.dataset.ir);
      });
    }

    function pintar() {
      if (!vivo || !pre) return;
      /* Rolar para o fim só se o operador JÁ estava no fim.
       *
       * O `scrollTop = scrollHeight` incondicional era o pior caso de scroll
       * roubado do cockpit: quem subia para ler a linha do erro era jogado de
       * volta ao rodapé na linha seguinte do stream. A margem de 24px é o que
       * separa "está acompanhando o vivo" de "parou para ler". */
      const noFim = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 24;
      // textContent, não innerHTML: log é conteúdo hostil por natureza.
      pre.textContent = linhas.join('\n');
      if (noFim) pre.scrollTop = pre.scrollHeight;
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

    function pintarTrecho(alvo, bruto, marcas) {
      /* Escapa PRIMEIRO, marca DEPOIS — mas agora sem montar string de markup:
       * o trecho e fatiado nos marcadores do servidor e cada pedaco entra por
       * `textContent`, dentro de um `span` ou de um `mark` criados aqui. Uma
       * linha com um `script` dentro sai como texto visivel porque nunca houve
       * um caminho em que ela fosse parseada como markup.
       *
       * Os pedacos NAO sao chaveados como as listas de cima, e de proposito: o
       * trecho e uma folha, sem hover, foco nem scroll a preservar. O que
       * importa aqui e nao reescrever quando nada mudou — dai a assinatura. */
      const texto_ = String(bruto || '');
      const assinatura = `${marcas.start || ''}|${marcas.end || ''}|${texto_}`;
      if (alvo.dataset.trecho === assinatura) return;
      alvo.dataset.trecho = assinatura;
      alvo.textContent = '';

      const ini = marcas.start;
      const fim = marcas.end;
      const pedacos = [];
      if (!ini || !fim) {
        pedacos.push({ marcado: false, txt: texto_ });
      } else {
        for (const bloco of texto_.split(ini)) {
          const corte = bloco.indexOf(fim);
          if (corte < 0) { pedacos.push({ marcado: false, txt: bloco }); continue; }
          pedacos.push({ marcado: true, txt: bloco.slice(0, corte) });
          pedacos.push({ marcado: false, txt: bloco.slice(corte + fim.length) });
        }
      }
      for (const p of pedacos) {
        if (p.txt === '') continue;
        const el = document.createElement(p.marcado ? 'mark' : 'span');
        el.textContent = p.txt;
        alvo.appendChild(el);
      }
    }

    function pintarResultados(data) {
      if (!vivo || !painel) return;
      mostrar(painel, true);
      if (pre) pre.hidden = true;
      const achados = data.results || [];
      mostrar(semAchado, !achados.length);
      lista(listaAchados, achados, {
        // Chave por (container, instante): a mesma linha de log continua sendo
        // a mesma linha entre duas buscas do mesmo termo.
        chave: (r) => `${r.container || ''}|${r.ts || ''}`,
        criar: () => deMolde(MOLDE_ACHADO),
        atualizar: (el, r) => {
          atributo(el, 'data-ir', r.container || '');
          texto(el.querySelector('[data-container]'), r.container || '');
          pintarTrecho(el.querySelector('[data-trecho]'), r.trecho, data.marks || {});
          texto(el.querySelector('[data-hora]'), String(r.ts || '').slice(11, 19));
        },
      });
    }

    function limparBusca() {
      if (painel) mostrar(painel, false);
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

    return {
      /* Reler o tail é o que mantém o log fresco sem follow ligado. Não relê em
       * dois casos, e cada um é uma forma de não atropelar o operador:
       * com o follow ligado o stream já traz cada linha, e com o painel de
       * busca aberto o `pre` nem está visível — reler seria I/O para ninguém. */
      atualizar: () => {
        if (soBusca || seguindo) return;
        if (painel && !painel.hidden) return;
        fetchLines();
      },
      dispose: () => {
        vivo = false;
        pararFollow();
      },
    };
  },
};
