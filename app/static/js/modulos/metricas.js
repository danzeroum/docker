/* Módulo `metricas` — B2 na interface (doc 11): o backend que faltava.
 *
 * O read model por escopo aqui é literal: host lê os vitais da amostra, stack
 * soma os containers dela, container busca a série de
 * `/api/containers/{id}/history` — a rota entregue na Sprint 1.
 *
 * Declara a janela e a amostra em toda série (doc 10 §4, análise descritiva):
 * apresentar média horária sem dizer que é média é apresentar agregado como
 * medida. A resolução vem do próprio payload.
 *
 * Os números do host e da stack são os que mais mudam no cockpit, e eram os que
 * mais saltavam: um `innerHTML` por leitura fazia CPU passar de 12% para 31%
 * sem passar por nenhum valor no meio. Agora a barra tem de onde animar e o
 * número que mudou pisca — o olho vê a mudança em vez de descobri-la (doc 13).
 */

import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { definirSub } from '../kernel/cockpit.js';
import { deMolde, lista, medida, mostrar, texto } from '../kernel/patch.js';

const MOLDE_VITAL = '<div class="met-cel">'
  + '<span data-rot></span>'
  + '<strong data-val></strong>'
  + '<span class="met-barra" aria-hidden="true"><span class="met-barra-fill"></span></span>'
  + '</div>';

const CASCA_GRADE = '<div class="met-grade" data-grade></div>';

function pctTexto(v) {
  return v != null ? `${v}%` : '—';
}

function largura(v) {
  const n = Number(v);
  return Number.isFinite(n) ? `${Math.max(0, Math.min(100, n)).toFixed(1)}%` : '0%';
}

function mb(bytes) {
  return `${Math.round((Number(bytes) || 0) / (1024 * 1024))} MB`;
}

/* Sparkline: uma barra por ponto, chaveada pelo índice. Aqui o índice É a
 * identidade — a barra 7 é sempre a sétima leitura da janela, e trocar a janela
 * troca a série inteira de propósito. */
function pintarSpark(recipiente, pontos, chave) {
  const vals = pontos.map((p) => Number(p[chave]) || 0);
  const max = Math.max(...vals, 1);
  lista(recipiente, vals, {
    chave: (v, i) => String(i),
    criar: () => {
      const b = document.createElement('span');
      b.className = 'spark-b';
      return b;
    },
    atualizar: (el, v) => {
      medida(el, '--altura', `${Math.max(2, (v / max) * 100).toFixed(1)}%`);
      medida(el, '--larg', `${(100 / Math.max(1, vals.length)).toFixed(3)}%`);
    },
  });
}

export default {
  id: 'metricas',
  nome: 'Métricas',
  escopos: ['host', 'stack', 'container'],
  span: 6,

  render: (escopo, dados, corpo) => {
    if (escopo.t === 'host' || escopo.t === 'stack') {
      corpo.innerHTML = CASCA_GRADE;
      const grade = corpo.querySelector('[data-grade]');

      function celulas(novos) {
        const overview = (novos && novos.overview) || {};
        if (escopo.t === 'host') {
          const v = overview.vitals || {};
          definirSub('metricas', 'amostra 5s');
          return [
            { chave: 'CPU', rot: 'CPU', val: pctTexto(v.cpu_pct), barra: v.cpu_pct },
            { chave: 'RAM', rot: 'RAM', val: pctTexto(v.mem_pct), barra: v.mem_pct },
            { chave: 'Swap', rot: 'Swap', val: pctTexto(v.swap_pct), barra: v.swap_pct },
          ];
        }
        const daStack = (overview.containers || []).filter((c) => c.stack === escopo.id);
        const cpu = daStack.reduce((a, c) => a + (Number(c.cpu_pct) || 0), 0);
        const mem = daStack.reduce((a, c) => a + (Number(c.mem_usage) || 0), 0);
        // Soma da stack é agregado descritivo, nunca "capacidade prevista".
        definirSub('metricas', `soma de ${daStack.length} container(es) · amostra 5s`);
        return [
          { chave: 'CPU', rot: 'CPU somada', val: `${cpu.toFixed(1)}%`, barra: cpu },
          { chave: 'MEM', rot: 'Memória', val: mb(mem), barra: null },
        ];
      }

      function atualizar(novos) {
        lista(grade, celulas(novos), {
          chave: (c) => c.chave,
          criar: () => deMolde(MOLDE_VITAL),
          atualizar: (el, c) => {
            texto(el.querySelector('[data-rot]'), c.rot);
            texto(el.querySelector('[data-val]'), c.val, { flash: true });
            const barra = el.querySelector('.met-barra');
            mostrar(barra, c.barra != null);
            if (c.barra != null) medida(el.querySelector('.met-barra-fill'), '--barra', largura(c.barra));
          },
        });
      }

      atualizar(dados);
      return { atualizar };
    }

    // container: série real da rota do B2, com toggle de janela
    let vivo = true;
    let janela = '24h';
    let carregou = false;
    const cache = new Map();  // uma requisição por troca, com a anterior guardada

    corpo.innerHTML = `<div class="met-topo">
        <button type="button" class="met-jan met-ativo" data-range="24h">24h</button>
        <button type="button" class="met-jan" data-range="7d">7d</button>
      </div>
      <div data-serie>
        <div class="skeleton" data-skeleton style="height:90px"></div>
        <div data-series hidden>
          <div class="met-serie"><span>CPU</span><div class="spark" data-spark-cpu role="img" aria-label="série de CPU"></div></div>
          <div class="met-serie"><span>Memória</span><div class="spark" data-spark-mem role="img" aria-label="série de memória"></div></div>
        </div>
        <div class="empty" data-vazio hidden>Coletando… a série aparece após os primeiros minutos</div>
      </div>`;

    const alvo = corpo.querySelector('[data-serie]');
    const skeleton = corpo.querySelector('[data-skeleton]');
    const series = corpo.querySelector('[data-series]');
    const vazio = corpo.querySelector('[data-vazio]');

    function marcarBotoes() {
      corpo.querySelectorAll('[data-range]').forEach((b) => {
        b.classList.toggle('met-ativo', b.dataset.range === janela);
        b.setAttribute('aria-pressed', b.dataset.range === janela ? 'true' : 'false');
      });
    }

    function pintar(data) {
      if (!vivo || !alvo) return;
      const pontos = data.points || [];
      // Skeleton é da primeira carga e só dela: a partir daqui ele nunca
      // reaparece, nem em erro nem em série vazia (doc 13 §3).
      mostrar(skeleton, false);
      if (!pontos.length) {
        // Borda do primeiro dia de uso: todo container novo passa por ela.
        // "coletando…" é diferente de gráfico vazio quebrado.
        definirSub('metricas', 'coletando…');
        mostrar(series, false);
        mostrar(vazio, true);
        return;
      }
      mostrar(vazio, false);
      mostrar(series, true);
      const resolucao = data.resolution === 'hourly' ? 'média horária' : 'leitura de 60s';
      definirSub('metricas', `${resolucao} · janela ${data.range_hours}h · ${pontos.length} pontos`);
      pintarSpark(corpo.querySelector('[data-spark-cpu]'), pontos, 'cpu_pct');
      pintarSpark(corpo.querySelector('[data-spark-mem]'), pontos, 'mem_bytes');
    }

    async function carregar() {
      if (cache.has(janela)) { pintar(cache.get(janela)); return; }
      const { data, error } = await apiGet(
        `mod_hist_${escopo.id}_${janela}`,
        `/api/containers/${encodeURIComponent(escopo.id)}/history?range=${janela}`
      );
      if (!vivo) return;
      if (error || !data) {
        // Erro depois de uma série boa não apaga a série: o que se tinha
        // continua na tela, porque perder o histórico por um soluço de rede é
        // pior que mostrá-lo um ciclo atrasado.
        if (!carregou && alvo) alvo.innerHTML = `<div class="empty">${escapeHtml(error || 'Sem histórico')}</div>`;
        return;
      }
      carregou = true;
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
    return {
      atualizar: () => {
        // A janela escolhida sobrevive à leitura — era ela que voltava para
        // "24h" sozinha a cada remontagem. O cache evita repetir a requisição
        // enquanto o operador está olhando o mesmo recorte.
        if (carregou) { cache.delete(janela); carregar(); }
      },
      dispose: () => { vivo = false; },
    };
  },
};
