/* Módulo `containers` — read model por escopo (doc 10 §1).
 *
 * É o exemplo canônico de "1 registro × N escopos": no host lista os 15, no
 * escopo stack lista só os da stack. Nenhum código duplicado entre os dois — a
 * diferença é um filtro, não uma tela.
 *
 * Clicar numa linha abre a subtela do container (navegação de 3 níveis, doc 10
 * §2: nunca mais de 2 cliques entre quaisquer dois níveis).
 *
 * A lista é CHAVEADA por `name` (doc 13): container que continua no payload
 * mantém o mesmo nó, com o `:hover` e o foco que ele carregava; container que
 * sai leva só a própria linha, e as vizinhas nem sabem. A barra de CPU anima
 * até o novo valor porque o nó é o mesmo — num nó recriado a `transition` não
 * tem de onde partir, e o valor salta.
 */

import { chipDoSummary } from '../kernel/regua.js';
import { carregarUpdates, seloDeImagem } from '../updates.js';
import {
  atributo, classe, classeUnica, deMolde, lista, medida, mostrar, texto,
} from '../kernel/patch.js';

const ESTADOS = ['running', 'exited', 'created', 'dead', 'paused', 'restarting', 'unhealthy', 'unknown'];
const SAUDES = ['unhealthy', 'starting'];

/* O molde traz a linha como `button` com a classe `mod-linha`, escrita por
 * extenso: linha que abre um escopo é botão, e o guarda de acessibilidade
 * confere isso lendo o fonte. Instanciado só quando um nome novo aparece. */
const MOLDE_LINHA = '<button type="button" class="mod-linha" data-abrir="" data-imagem="">'
  + '<span class="item-status"></span>'
  + '<span class="mod-nome-cel">'
  + '<span data-rotulo></span>'
  + '<span class="item-health" hidden></span>'
  + '<span class="selo-update" hidden></span>'
  + '</span>'
  + '<span class="mod-barra" aria-hidden="true"><span class="mod-barra-fill"></span></span>'
  + '<span class="mod-meta" data-meta></span>'
  + '</button>';

const CASCA = '<div class="mod-lista" data-lista></div>'
  + '<div class="empty" data-vazio hidden>Nenhum container neste escopo</div>';

function saude(c) {
  // Mesma regra do campo Health explícito entregue no B4: sem healthcheck é
  // ausência de medida, não saúde confirmada.
  if (!c) return null;
  if (c.health && c.health !== 'none') return c.health;
  return null;
}

function daEscala(cpu) {
  // 100% da barra = 16% de CPU. Um container que come 16% de um host inteiro já
  // é o assunto da tela; escalar até 100% deixaria toda a lista em 2px e a
  // barra deixaria de informar.
  const v = Number(cpu);
  if (!Number.isFinite(v)) return null;
  return `${Math.max(0, Math.min(100, v * 6.25)).toFixed(1)}%`;
}

function pintarLinha(el, c) {
  const s = saude(c);
  const estado = s === 'unhealthy' ? 'unhealthy' : (c.state || 'unknown');
  atributo(el, 'data-abrir', c.name || '');
  atributo(el, 'data-imagem', c.image || '');
  classeUnica(el.querySelector('.item-status'), ESTADOS, estado);
  texto(el.querySelector('[data-rotulo]'), c.name || '');

  const selo = el.querySelector('.item-health');
  const mostraSelo = s === 'unhealthy' || s === 'starting';
  mostrar(selo, mostraSelo);
  if (mostraSelo) {
    texto(selo, s);
    classeUnica(selo, SAUDES, s);
  }

  // A largura vai por propriedade customizada: a transição de .7s e a cor
  // ficam no components.css, e o módulo entrega só o número.
  const barra = el.querySelector('.mod-barra');
  const largura = daEscala(c.cpu_pct);
  mostrar(barra, largura !== null);
  if (largura !== null) {
    medida(el.querySelector('.mod-barra-fill'), '--barra', largura);
    classe(barra, 'mod-barra-alta', Number(c.cpu_pct) > 6);
    atributo(el, 'title', `CPU ${Number(c.cpu_pct).toFixed(1)}%`);
  }

  texto(el.querySelector('[data-meta]'), c.stack || '');
}

/* O selo entra depois da lista, não junto: o estado das imagens vem de outra
 * rota e chega mais tarde que o overview. Esperar por ele para desenhar a lista
 * atrasaria os 15 containers por causa de um dado diário. */
function pintarSelos(corpo, estado) {
  corpo.querySelectorAll('[data-imagem]').forEach((el) => {
    const marca = el.querySelector('.selo-update');
    if (!marca) return;
    const selo = seloDeImagem(estado, el.dataset.imagem);
    mostrar(marca, !!selo);
    if (!selo) return;
    texto(marca, selo.texto);
    atributo(marca, 'title', selo.titulo || null);
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
    let vivo = true;
    let ultimoUpdates = null;

    corpo.innerHTML = CASCA;
    const recipiente = corpo.querySelector('[data-lista]');
    const vazio = corpo.querySelector('[data-vazio]');

    /* Um listener na lista inteira, instalado no monte. Religar handler por
     * linha a cada leitura era o que trocava o alvo debaixo de um clique. */
    recipiente.addEventListener('click', (ev) => {
      const linha = ev.target.closest ? ev.target.closest('[data-abrir]') : null;
      if (!linha) return;
      const abrir = dados && dados.abrirContainer;
      if (typeof abrir === 'function') abrir(linha.dataset.abrir);
    });

    function atualizar(novos) {
      if (!vivo) return;
      const overview = (novos && novos.overview) || {};
      let itens = overview.containers || [];
      if (escopo.t === 'stack') itens = itens.filter((c) => c.stack === escopo.id);

      mostrar(vazio, !itens.length);
      lista(recipiente, itens, {
        chave: (c) => c.name || c.id || '',
        criar: () => deMolde(MOLDE_LINHA),
        atualizar: pintarLinha,
      });
      // Linha nova precisa do selo que as antigas já têm — sem repetir a
      // requisição: `carregarUpdates` tem cache de 5 min e o estado fica aqui.
      if (ultimoUpdates) pintarSelos(recipiente, ultimoUpdates);
    }

    atualizar(dados);

    carregarUpdates().then((estado) => {
      if (!vivo) return;
      ultimoUpdates = estado;
      pintarSelos(recipiente, estado);
    });

    return { atualizar, dispose: () => { vivo = false; } };
  },
};
