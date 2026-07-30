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
 *
 * O skeleton é da PRIMEIRA carga e só dela (doc 13 §3). Num crash loop chega
 * evento a cada poucos segundos: apagar a timeline para mostrar um retângulo
 * cinza a cada chegada é perder o histórico justamente quando ele é lido.
 * Evento novo entra no topo por `insertBefore`; os que já estavam não são
 * tocados, e quem estava lendo a terceira linha continua lendo a terceira linha.
 */

import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { chipDoSummary } from '../kernel/regua.js';
import { classeUnica, deMolde, lista, mostrar, texto } from '../kernel/patch.js';

const TETO = 60;

const SEVERIDADES = ['ev-critical', 'ev-warn', 'ev-info'];

const MOLDE_ITEM = '<div class="mod-item">'
  + '<span class="mod-tag ev-acao"></span>'
  + '<span class="mod-nome-cel"><span data-alvo></span><span class="ev-exit" hidden></span></span>'
  + '<span class="mod-meta"></span>'
  + '</div>';

const CASCA = '<div class="skeleton" data-skeleton style="height:110px"></div>'
  + '<div class="mod-lista" data-lista hidden></div>'
  + '<div class="empty" data-vazio hidden>Nenhum evento neste escopo ainda</div>';

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

/* Chave do evento: o CONTEÚDO que o identifica — instante, ação, ator, saída.
 *
 * A posição na fila não serve: a fila anda a cada evento novo, e chavear por
 * índice faria toda linha "mudar de identidade" no instante em que a de cima
 * chega — que é reconstruir a lista inteira com outro nome.
 *
 * O `id` do banco também não serve, e por um motivo concreto: o histórico traz
 * `id`, o stream não (o evento é despachado antes de o INSERT devolver a
 * chave). Chavear pelo `id` faria toda linha vinda ao vivo ser recriada na
 * releitura seguinte do histórico.
 *
 * Colisão exata dos quatro campos é rara e ganha sufixo de ocorrência, contado
 * do topo. Sem o sufixo, duas linhas idênticas disputariam o mesmo nó e as duas
 * seriam recriadas a cada leitura.
 */
function chavesDe(itens) {
  const vistos = new Map();
  return itens.map((e) => {
    const base = `${e.ts || ''}|${e.action || ''}|${e.actor_name || ''}|${e.exit_code == null ? '' : e.exit_code}`;
    const n = vistos.get(base) || 0;
    vistos.set(base, n + 1);
    return n ? `${base}#${n}` : base;
  });
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
    let carregou = false;
    const fila = [];
    const q = query(escopo);

    corpo.innerHTML = CASCA;
    const skeleton = corpo.querySelector('[data-skeleton]');
    const recipiente = corpo.querySelector('[data-lista]');
    const vazio = corpo.querySelector('[data-vazio]');

    function pintar() {
      if (!vivo) return;
      // Skeleton some na primeira resposta e não volta: recarga preserva o que
      // já está na tela e sinaliza atualização pelo flash da linha nova.
      mostrar(skeleton, false);
      mostrar(vazio, !fila.length);
      mostrar(recipiente, !!fila.length);
      const visiveis = fila.slice(0, TETO);
      const chaves = chavesDe(visiveis);
      lista(recipiente, visiveis, {
        chave: (e, i) => chaves[i],
        criar: () => deMolde(MOLDE_ITEM),
        atualizar: (el, e) => {
          classeUnica(el, SEVERIDADES, `ev-${e.severity || 'info'}`);
          texto(el.querySelector('.ev-acao'), e.action || '?');
          texto(el.querySelector('[data-alvo]'), e.actor_name || '');
          const exit = el.querySelector('.ev-exit');
          mostrar(exit, e.exit_code != null && e.exit_code !== '');
          if (e.exit_code != null && e.exit_code !== '') texto(exit, `exit ${e.exit_code}`);
          texto(el.querySelector('.mod-meta'), idade(e.ts));
        },
      });
    }

    async function historico() {
      const url = `/api/events?limit=40${q ? `&${q}` : ''}`;
      const { data, error } = await apiGet(`mod_ev_${escopo.t}_${escopo.id || 'host'}`, url);
      if (!vivo) return;
      if (error || !data) {
        // Erro só apaga a timeline se não houver timeline. Trocar 40 eventos
        // por "Sem timeline" porque UMA leitura falhou é perder o que já se
        // sabia por causa de um soluço de rede.
        if (!carregou) {
          corpo.innerHTML = `<div class="empty">${escapeHtml(error || 'Sem timeline')}</div>`;
        }
        return;
      }
      carregou = true;
      fila.length = 0;
      fila.push(...(data.events || []));
      pintar();
      aoVivo();
    }

    function aoVivo() {
      if (fonte) return;
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

    return {
      // O histórico é releitura barata e a timeline pode ter perdido evento
      // enquanto o stream estava caído. Refazê-lo no ciclo do kernel é a
      // reconciliação — e agora ela não apaga mais nada da tela.
      atualizar: () => { if (carregou) historico(); },
      dispose: () => {
        vivo = false;
        if (fonte) { try { fonte.close(); } catch { /* já fechado */ } }
      },
    };
  },
};
