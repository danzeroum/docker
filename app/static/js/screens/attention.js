import { apiGet, apiPost, cancel } from '../data.js';
import { showToast, showAckModal } from '../notifications.js';
import { carregarNotificacoes, seloDeNotificacao } from '../notificacoes.js';
import { navigate } from '../main.js';
/* `setState` era usado e NÃO era importado: o caminho "abrir achado de ingress"
 * levantava ReferenceError e o clique não fazia nada. Passou despercebido
 * porque só dispara em achado agregado de ingress. */
import { getState, setState } from '../store.js';
import { assinar, TICK_MS } from '../kernel/relogio.js';
import { atributo, classe, classeUnica, deMolde, lista, mostrar, texto } from '../kernel/patch.js';

let _disposed = false;

function el(id) { return document.getElementById(id); }

const SEVERIDADES = ['sev-critical', 'sev-high', 'sev-medium', 'sev-low'];

function severityClass(sev) {
  return SEVERIDADES.includes(`sev-${sev}`) ? `sev-${sev}` : 'sev-low';
}

function severityLabel(sev) {
  if (sev === 'critical') return 'Crítico';
  if (sev === 'high') return 'Alto';
  if (sev === 'medium') return 'Médio';
  return 'Baixo';
}

/* A fila de achados é uma lista que muda de conteúdo sem mudar de gente: o
 * mesmo achado fica aberto por horas, com o score subindo e a idade andando.
 * Reconstruí-la a cada 10s tirava o `:hover` do cartão no meio do movimento e
 * devolvia o scroll ao topo enquanto se lia o terceiro item. Chaveada pelo `id`
 * do achado nada disso acontece — e o score que sobe pisca, em vez de saltar.
 *
 * A cor da severidade saiu do `style="border-left:3px solid …"` para a classe:
 * era o último lugar do cockpit onde a paleta vivia no JS, e ela não acompanhava
 * a troca de tema. */
const MOLDE_CARD = '<div class="atn-card">'
  + '<button type="button" class="card-open"><span class="sr-only">Abrir achado</span></button>'
  + '<div class="atn-head">'
  + '<span class="atn-sev" data-sev></span>'
  + '<span class="atn-score" data-score></span>'
  + '<span class="atn-target" data-alvo></span>'
  + '<span class="atn-occs" data-dur hidden></span>'
  + '<span class="atn-ago" data-idade></span>'
  + '<span class="atn-notificado" data-notificado></span>'
  + '</div>'
  + '<div class="atn-title" data-titulo></div>'
  + '<div class="atn-interp" data-interp hidden></div>'
  + '<div class="atn-reco" data-reco hidden></div>'
  + '<div class="atn-rel" data-rel hidden><a class="atn-link" data-link></a></div>'
  + '<div class="atn-acoes"><button type="button" class="ack-btn">Silenciar</button></div>'
  + '</div>';

const CASCA = '<div class="content"><div class="section">'
  + '<div class="section-head"><div><h2 class="section-title">Atenção</h2></div></div>'
  + '<div id="atnFilters" class="atn-filtros">'
  + '<button type="button" class="filter-pill active" data-sev="all">Todos</button>'
  + '<button type="button" class="filter-pill sev-critical" data-sev="critical">Crítico</button>'
  + '<button type="button" class="filter-pill sev-high" data-sev="high">Alto</button>'
  + '<button type="button" class="filter-pill sev-medium" data-sev="medium">Médio</button>'
  + '</div>'
  + '<div id="atnList">'
  + '<div class="skeleton" data-skeleton style="height:400px"></div>'
  + '<div class="empty" data-vazio hidden>Nenhum achado ativo</div>'
  + '<div data-cards></div>'
  + '</div></div></div>';

/* "notificado hh:mm · canal" no cartao do achado.
 *
 * A pergunta do operador as 3 da manha nao e "o que aconteceu" — e "isso ja me
 * acordou?". Sem o selo, achado ja notificado e achado que o canal engoliu tem
 * a mesma aparencia. */
function pintarNotificados(recipiente, estado) {
  recipiente.querySelectorAll('[data-rule]').forEach((card) => {
    const alvo = card.querySelector('[data-notificado]');
    if (!alvo) return;
    const selo = seloDeNotificacao(estado, card.dataset.rule, card.dataset.target);
    // Sem notificacao o selo fica AUSENTE, e nao "nao notificado": o motor pode
    // simplesmente nao ter canal configurado, e afirmar ausencia de aviso onde
    // ha ausencia de motor seria inventar estado.
    if (!selo) return;
    texto(alvo, selo.texto);
    atributo(alvo, 'title', selo.titulo || null);
  });
}

function idadeDe(f) {
  const age = f.first_seen ? Math.round((Date.now() - new Date(f.first_seen).getTime()) / 1000) : 0;
  if (age < 60) return `há ${age}s`;
  if (age < 3600) return `há ${Math.floor(age / 60)}min`;
  return `há ${Math.floor(age / 3600)}h`;
}

function duracaoDe(f) {
  const d = f.first_seen && f.last_seen
    ? Math.round((new Date(f.last_seen).getTime() - new Date(f.first_seen).getTime()) / 1000)
    : 0;
  if (d > 60) return `${Math.floor(d / 60)}min`;
  return d > 0 ? `${d}s` : '';
}

export function renderAttention(container) {
  _disposed = false;
  let carregou = false;
  let ultimos = [];
  let pollTimer = null;
  let currentSev = 'all';

  container.innerHTML = CASCA;

  const cards = container.querySelector('[data-cards]');
  const skeleton = container.querySelector('[data-skeleton]');
  const vazio = container.querySelector('[data-vazio]');

  function pintarCard(card, f) {
    const depth = getState().depth || 'dado';
    const showPlain = depth === 'informacao' || depth === 'conhecimento';
    const isAgg = Array.isArray(f.targets);

    atributo(card, 'data-id', f.id);
    atributo(card, 'data-rule', f.rule || '');
    atributo(card, 'data-scope', f.scope || 'container');
    atributo(card, 'data-target', f.target || '');
    atributo(card, 'data-targets', isAgg ? JSON.stringify(f.targets) : '');
    classeUnica(card, SEVERIDADES, severityClass(f.severity));

    texto(card.querySelector('[data-sev]'), severityLabel(f.severity));
    texto(card.querySelector('[data-score]'), String(f.score), { flash: true });
    texto(card.querySelector('[data-alvo]'), isAgg ? `${f.targets.length} hosts` : (f.target || ''));

    const dur = card.querySelector('[data-dur]');
    const durStr = duracaoDe(f);
    mostrar(dur, !!durStr);
    if (durStr) texto(dur, durStr);

    texto(card.querySelector('[data-idade]'), idadeDe(f));
    texto(card.querySelector('[data-titulo]'), showPlain && f.title_plain ? f.title_plain : f.title);

    const interp = card.querySelector('[data-interp]');
    const interpTxt = showPlain && f.interpretation_plain
      ? f.interpretation_plain : (f.interpretation || '');
    mostrar(interp, !!interpTxt);
    if (interpTxt) texto(interp, interpTxt);

    const reco = card.querySelector('[data-reco]');
    mostrar(reco, !!f.recommendation);
    if (f.recommendation) texto(reco, f.recommendation);

    const rel = card.querySelector('[data-rel]');
    mostrar(rel, !!f.related_container);
    if (f.related_container) {
      const link = card.querySelector('[data-link]');
      atributo(link, 'href', `#/dossie?c=${encodeURIComponent(f.related_container)}`);
      texto(link, `→ Dossiê: ${f.related_container}`);
    }
  }

  async function fetchFindings() {
    const { data, error } = await apiGet('atn_data', '/api/findings?status=open');
    if (_disposed) return;
    if (error || !data) {
      // Erro só apaga a fila enquanto não houve fila. Depois disso, os achados
      // na tela são o melhor que se sabe — e num incidente é justamente quando
      // a rede treme e a fila importa.
      if (!carregou) {
        mostrar(skeleton, false);
        mostrar(vazio, true);
        texto(vazio, error ? 'Erro ao carregar achados' : 'Nenhum achado ativo');
      }
      return;
    }
    carregou = true;
    ultimos = data;

    const filtered = currentSev === 'all' ? data : data.filter(f => f.severity === currentSev);
    mostrar(skeleton, false);
    texto(vazio, 'Nenhum achado ativo');
    mostrar(vazio, !filtered.length);

    lista(cards, filtered, {
      chave: (f) => String(f.id),
      criar: () => deMolde(MOLDE_CARD),
      atualizar: pintarCard,
    });

    // O selo entra depois: vem de outra rota, e esperar por ele para desenhar
    // a fila atrasaria os achados por causa de um dado auxiliar.
    carregarNotificacoes().then((estado) => {
      if (_disposed) return;
      pintarNotificados(cards, estado);
    });
  }

  async function silenciar(card) {
    const findingId = card.dataset.id;
    const f = ultimos.find(d => d.id === findingId);
    const btn = card.querySelector('.ack-btn');
    if (!f || !btn) return;
    const ack = await showAckModal(f);
    if (!ack) return;
    btn.disabled = true;
    btn.textContent = '...';
    const payload = { reason: ack.reason };
    if (ack.note) payload.note = ack.note;
    if (ack.until) payload.until = ack.until;
    const send = () => apiPost('ack-' + findingId, `/api/findings/${findingId}/ack`, {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    let { error } = await send();
    if (error && (error.includes('403') || error.includes('Unlock') || error.includes('ausente') || error.includes('destravamento'))) {
      const { showUnlockModal } = await import('../notifications.js');
      if (await showUnlockModal()) ({ error } = await send());
    }
    if (error) { showToast(error, 'error'); btn.disabled = false; btn.textContent = 'Silenciar'; return; }
    showToast('Achado silenciado', 'success');
    fetchFindings();
  }

  function abrir(card) {
    const scope = card.dataset.scope;
    const target = card.dataset.target;
    const targetsRaw = card.dataset.targets;
    if (scope === 'ingress') {
      if (targetsRaw) {
        try {
          const targets = JSON.parse(targetsRaw);
          if (targets.length) {
            setState({ highlightedTargets: targets });
            navigate(`#/ingress`);
            return;
          }
        } catch {}
      }
      if (target) {
        navigate(`#/ingress?host=${encodeURIComponent(target)}`);
        return;
      }
    }
    setState({ selectedFinding: card.dataset.id });
    navigate('#/atencao');
  }

  /* Delegação: dois handlers para a fila inteira, instalados uma vez. Antes eram
   * dois POR CARTÃO, religados a cada leitura — e um clique que começasse
   * durante a repintura caía num nó que já não existia. */
  cards.addEventListener('click', (ev) => {
    const ack = ev.target.closest ? ev.target.closest('.ack-btn') : null;
    if (ack) {
      ev.stopPropagation();
      const card = ack.closest('.atn-card');
      if (card) silenciar(card);
      return;
    }
    const aberto = ev.target.closest ? ev.target.closest('.card-open') : null;
    if (!aberto || (ev.target.closest && ev.target.closest('a'))) return;
    const card = aberto.closest('.atn-card');
    if (card) abrir(card);
  });

  fetchFindings();
  // 10s = 2 ticks. Sem `setInterval` próprio e sem `visibilitychange` próprio:
  // a fase é a mesma da régua, então os dois piscam juntos em vez de se
  // alternarem sem causa visível.
  pollTimer = assinar(fetchFindings, 2 * TICK_MS);

  el('atnFilters')?.addEventListener('click', (e) => {
    const btn = e.target.closest('.filter-pill');
    if (!btn) return;
    currentSev = btn.dataset.sev;
    el('atnFilters').querySelectorAll('.filter-pill').forEach(p => classe(p, 'active', p === btn));
    fetchFindings();
  });

  return () => {
    _disposed = true;
    if (typeof pollTimer === 'function') pollTimer();
    pollTimer = null;
    cancel('atn_data');
  };
}
