import { getState, setState, subscribe } from './store.js';
import { apiGet, apiGetText, apiPost, apiDelete, cancel, cancelAll } from './data.js';
import { fmtBytes, fmtDuration, fmtDate, shortId, escapeHtml, jsonHighlight } from './fmt.js';
import { showToast, showConfirmModal } from './notifications.js';
import { initCommandPalette } from './commands.js';
// O núcleo do Cockpit Vivo assumiu a área de tela. Este arquivo cuida do chrome
// (barra lateral, filtros, trava, tema, paleta) e NÃO conhece módulo nenhum:
// a única lista de módulos do sistema está em `modulos/index.js`.
import { iniciar as iniciarCockpit, _interno as cockpit } from './kernel/app.js';
import { container as escopoContainer } from './kernel/escopo.js';
import { assinar, TICK_MS } from './kernel/relogio.js';
import { instalar as instalarRolagem } from './kernel/rolagem.js';
import { atributo, casca, classe, classeUnica, deMolde, lista, mostrar, texto } from './kernel/patch.js';

// --- Theme ---
function applyTheme(tema) {
  document.documentElement.setAttribute('data-tema', tema);
}
applyTheme(getState().tema);
subscribe((s) => {
  if (s.tema) applyTheme(s.tema);
});

/* `navigate` continua exportado porque três corpos de tela o importam. A
 * implementação virou uma ponte no kernel, que deriva o módulo do hash de forma
 * genérica (`#/x` revela o módulo de id `x`). O roteador de rotas em si saiu:
 * escopo é o que navega agora, e o kernel é dono da hash.
 *
 * O dispose por tela e o `schedule` também saíram — o kernel guarda um dispose
 * por módulo montado, que é o que impede vazar poller (o bug do `let pollTimer`
 * duplicado nasceu justamente de dois donos para o mesmo timer). */
export { navegarPorHash as navigate } from './kernel/app.js';

/* Aqui vivia o roteador por tela: uma cadeia de 13 desvios, um por rota, que
 * escolhia o render. Era o oposto exato da regra do doc 10 §4 — "módulo novo =
 * 1 arquivo novo, zero desvio no núcleo". Acrescentar tela exigia editar este
 * arquivo, e este arquivo conhecia cada tela pelo nome.
 *
 * No lugar dele, o kernel monta a grade iterando o registro. `grep` neste
 * arquivo não encontra o id de nenhum módulo — o que é o critério de pronto da
 * Sprint 2a. */

subscribe((s, changed) => {
  if (changed.includes('depth')) cockpit.repintar();
  if (changed.includes('tema') || changed.includes('perfil')) {
    renderContainerList();
  }
});

// --- Shared polling (paused when tab hidden) ---
let pollTimer = null;

function pollAll() {
  if (document.hidden) return;
  apiGet('containers_list', '/api/containers').then(({ data, error }) => {
    if (error && error !== 'abortado') showToast(error, 'error');
    if (data) { setState({ containers: data }); renderContainerList(); }
  });
  apiGet('system', '/api/system').then(({ data }) => {
    if (data) setState({ system: data });
  });
  apiGet('findings_count', '/api/findings?status=open').then(({ data }) => {
    const badge = document.getElementById('findingsBadge');
    if (!badge) return;
    if (data && data.length) {
      // textContent com flash em vez de reescrever o nó: o selo que muda de 3
      // para 4 se anuncia, e o `:hover` do item de nav não é interrompido.
      texto(badge, String(data.length), { flash: true });
      const sevOrder = { critical: 4, high: 3, medium: 2, low: 1 };
      const maxSev = data.reduce((a, f) => sevOrder[f.severity] > sevOrder[a] ? f.severity : a, 'low');
      // Cor por classe, não por `style.background`: a paleta fica em
      // components.css com os tokens de themes.css, e o selo acompanha o tema.
      classeUnica(badge, SEV_CLASSES, `sev-${maxSev}`);
      mostrar(badge, true);
    } else {
      mostrar(badge, false);
    }
  });
}

const SEV_CLASSES = ['sev-critical', 'sev-high', 'sev-medium', 'sev-low'];

// --- SSE events (real-time from daemon) ---
let eventSource = null;
let lastEventTime = null;

function connectSSE() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource('/api/events/stream');
  eventSource.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      lastEventTime = new Date();
      if (msg.type === 'invalidate') {
        pollAll();
      }
      if (msg.type === 'docker_event') {
        const ev = msg.data;
        if (ev && ev.Type === 'container' && ['start', 'stop', 'die', 'restart', 'oom'].includes(ev.Action)) {
          pollAll();
        }
      }
      if (msg.type === 'error' && msg.detail) {
        console.warn('SSE:', msg.detail);
      }
    } catch (_) {}
  };
  eventSource.onerror = () => {
    eventSource.close();
    setTimeout(connectSSE, 3000);
  };
}

function disconnectSSE() {
  if (eventSource) { eventSource.close(); eventSource = null; }
}

// --- Reconciliação de 30s no relógio compartilhado ---
// pollTimer ja e declarado junto de pollAll(), acima. Redeclarar com `let` no
// mesmo escopo de modulo e SyntaxError: o main.js inteiro deixa de carregar e
// a interface fica no "carregando" para sempre, sem pintar nada.
//
// 30s deixou de ser um `setInterval` proprio e virou "6 ticks" do relogio do
// kernel. A pausa com aba oculta tambem saiu daqui: e do relogio, e um so.
function startPolling() {
  pollAll();
  pollTimer = assinar(pollAll, 6 * TICK_MS);
}

function stopPolling() {
  if (typeof pollTimer === 'function') pollTimer();
  pollTimer = null;
}

// O SSE continua com ciclo proprio: e conexao, nao leitura periodica — nao ha
// periodo para declarar ao relogio, e derrubar/reabrir o stream custa mais que
// mante-lo aberto.
document.addEventListener('visibilitychange', () => {
  if (document.hidden) disconnectSSE(); else connectSSE();
});



function getStackName(c) {
  return (c.Labels && c.Labels['com.docker.compose.project']) || null;
}

// Saude do container a partir do campo explicito que /api/containers passou a
// devolver (B4). O sniff em `Status` fica como fallback porque um cockpit
// recem-subido serve a listagem antes do coletor preencher o inspect — mas ele
// e fallback, nao a fonte: "Up 2 hours (unhealthy)" e texto de UI do daemon e
// muda de formato entre versoes.
export function saudeDe(c) {
  if (!c) return null;
  if (c.Health) return c.Health;
  if (c.State === 'unhealthy') return 'unhealthy';
  if (c.Status && c.Status.includes('unhealthy')) return 'unhealthy';
  return null;
}

/* Barra lateral: a lista mais repintada do cockpit (a cada 30s, e a cada evento
 * do daemon). Era ela que perdia o scroll no meio de uma rolagem e engolia o
 * clique quando o nó sumia debaixo do ponteiro.
 *
 * A chave é o `container_name`, não o `Id`: recriar um container muda o Id mas
 * não a identidade que o operador vê. Trocar o nó porque o Docker gerou outro
 * hash seria recriar por motivo nenhum — e a linha ainda é a mesma linha.
 *
 * O bloco de stack é um nó só (cabeçalho + grupo) porque a lista chaveada
 * reconcilia FILHOS diretos: com header e grupo soltos como irmãos, remover uma
 * stack exigiria casar dois nós por posição, que é como se perde a conta. */
const MOLDE_BLOCO = '<div class="stack-bloco">'
  + '<button type="button" class="stack-header" aria-expanded="true">'
  + '<span class="stack-toggle">▼</span><span class="stack-name"></span>'
  + '<span class="stack-count"></span></button>'
  + '<div class="stack-group"></div></div>';

const MOLDE_ITEM = '<button type="button" class="list-item">'
  + '<div class="item-status"></div>'
  + '<div class="item-info">'
  + '<div class="item-name"><span data-rotulo></span><span class="item-health" hidden></span></div>'
  + '<div class="item-image"></div>'
  + '</div></button>';

const ESTADOS_ITEM = ['running', 'exited', 'created', 'dead', 'paused', 'restarting', 'unhealthy', 'unknown'];
const SAUDES_ITEM = ['unhealthy', 'starting'];

const CASCA_LISTA = '<div data-blocos></div>'
  + '<div class="empty" data-vazio hidden>Nenhum container encontrado</div>';

function agruparPorStack(filtrados) {
  const grupos = new Map();
  for (const c of filtrados) {
    const s = getStackName(c) || '__ungrouped__';
    if (!grupos.has(s)) grupos.set(s, []);
    grupos.get(s).push(c);
  }
  return [...grupos.entries()].sort(([a], [b]) => {
    if (a === '__ungrouped__') return 1;
    if (b === '__ungrouped__') return -1;
    return a.localeCompare(b);
  });
}

function pintarItem(el, c, selId) {
  const id = c.Id;
  const nome = ((c.Names && c.Names[0]) || '').replace(/^\//, '');
  const saude = saudeDe(c);
  const estado = saude === 'unhealthy' ? 'unhealthy' : (c.State || 'unknown');

  atributo(el, 'data-id', id);
  atributo(el, 'data-nome', nome);
  classe(el, 'active', id === selId);
  atributo(el, 'aria-current', id === selId ? 'true' : null);
  classeUnica(el.querySelector('.item-status'), ESTADOS_ITEM, estado);

  const rotulo = el.querySelector('[data-rotulo]');
  texto(rotulo, nome);
  atributo(el.querySelector('.item-name'), 'title', nome);

  // Selo só aparece com healthcheck falhando ou em partida. Container sem
  // healthcheck não ganha selo nenhum: não há saúde medida para afirmar.
  const selo = el.querySelector('.item-health');
  const mostraSelo = saude === 'unhealthy' || saude === 'starting';
  mostrar(selo, mostraSelo);
  if (mostraSelo) {
    texto(selo, saude);
    atributo(selo, 'title', `Healthcheck: ${saude}`);
    classeUnica(selo, SAUDES_ITEM, saude);
  }

  const img = el.querySelector('.item-image');
  texto(img, c.Image || '');
  atributo(img, 'title', c.Image || '');
}

function renderContainerList() {
  const listEl = document.getElementById('containerList');
  if (!listEl) return;
  const { containers, filter: curFilter, search: curSearch, selectedContainer: selId } = getState();

  let filtered = [...containers];
  if (curFilter === 'running') filtered = filtered.filter(c => c.State === 'running');
  else if (curFilter === 'exited') filtered = filtered.filter(c => ['exited', 'created', 'dead'].includes(c.State));
  else if (curFilter === 'unhealthy') filtered = filtered.filter(c => saudeDe(c) === 'unhealthy');

  if (curSearch) {
    const t = curSearch.toLowerCase();
    filtered = filtered.filter(c => ((c.Names && c.Names[0]) || '').toLowerCase().includes(t) || (c.Image || '').toLowerCase().includes(t));
  }

  // A casca (e a delegação de clique) nasce uma vez e sobrevive a tudo. É a
  // primeira e última escrita de `innerHTML` desta lista: substitui o skeleton
  // do index.html e nunca mais é reescrita.
  casca(listEl, 'lista-v1', (el) => {
    el.innerHTML = CASCA_LISTA;
    el.addEventListener('click', (ev) => {
      const cabeca = ev.target.closest ? ev.target.closest('.stack-header') : null;
      if (cabeca) {
        const grupo = cabeca.nextElementSibling;
        if (!grupo) return;
        const fechado = cabeca.getAttribute('aria-expanded') === 'false';
        atributo(cabeca, 'aria-expanded', fechado ? 'true' : 'false');
        mostrar(grupo, fechado);
        texto(cabeca.querySelector('.stack-toggle'), fechado ? '▼' : '▶');
        return;
      }
      const item = ev.target.closest ? ev.target.closest('.list-item') : null;
      if (!item) return;
      const nome = item.dataset.nome || item.dataset.id;
      setState({ selectedContainer: item.dataset.id });
      // A barra lateral deixa de ser rota e passa a ser atalho de escopo: abre a
      // subtela do container. O kernel e a faixa crítica seguem visíveis.
      cockpit.irPara(escopoContainer(nome));
    });
  });

  const blocos = listEl.querySelector('[data-blocos]');
  mostrar(listEl.querySelector('[data-vazio]'), !filtered.length);
  if (!filtered.length) {
    lista(blocos, [], { chave: () => '', criar: () => null });
    return;
  }

  const grupos = agruparPorStack(filtered);
  const comCabeca = grupos.length > 1 || grupos[0][0] !== '__ungrouped__';

  lista(blocos, grupos, {
    chave: ([stack]) => stack,
    criar: () => deMolde(MOLDE_BLOCO),
    atualizar: (bloco, [stack, ctrs]) => {
      const cabeca = bloco.querySelector('.stack-header');
      const mostraCabeca = comCabeca && stack !== '__ungrouped__';
      mostrar(cabeca, mostraCabeca);
      if (mostraCabeca) {
        texto(cabeca.querySelector('.stack-name'), stack);
        texto(cabeca.querySelector('.stack-count'),
          `${ctrs.filter(c => c.State === 'running').length}/${ctrs.length}`);
      }
      lista(bloco.querySelector('.stack-group'), ctrs, {
        chave: (c) => ((c.Names && c.Names[0]) || c.Id || '').replace(/^\//, ''),
        criar: () => deMolde(MOLDE_ITEM),
        atualizar: (el, c) => pintarItem(el, c, selId),
      });
    },
  });
}



/* O Dossiê e a tela de Logs viviam aqui, ~275 linhas de renderização de
 * detalhe de container. Foram substituídos pela subtela central + os módulos
 * `config`, `metricas` e `logs`, que renderizam no escopo {t:'container'}.
 *
 * Não é remoção de funcionalidade, é a mesma informação vinda do registro em
 * vez de uma tela dedicada — que é o ponto do doc 10: não existem 3 telas,
 * existe 1 registro × 3 escopos. O tail de logs migrou para `modulos/logs.js`
 * preservando `apiGetText` (log é texto, não JSON) e o follow por SSE. */


// --- Filter pills ---
document.getElementById('filters')?.addEventListener('click', (e) => {
  const pill = e.target.closest('.filter-pill');
  if (!pill) return;
  document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
  pill.classList.add('active');
  setState({ filter: pill.dataset.filter });
});

// --- Search ---
document.getElementById('searchInput')?.addEventListener('input', (e) => {
  setState({ search: e.target.value });
});

// --- Depth toggle ---
const DEPTH_CYCLE = ['dado', 'informacao', 'conhecimento'];
function updateDepthLabel(d) {
  const lbl = document.getElementById('depthLabel');
  if (lbl) {
    const names = { dado: 'DADO', informacao: 'INFO', conhecimento: 'CONH' };
    lbl.textContent = names[d] || 'DADO';
  }
}
updateDepthLabel(getState().depth || 'dado');
document.getElementById('depthToggle')?.addEventListener('click', () => {
  const current = getState().depth || 'dado';
  const idx = DEPTH_CYCLE.indexOf(current);
  const next = DEPTH_CYCLE[(idx + 1) % DEPTH_CYCLE.length];
  setState({ depth: next });
  updateDepthLabel(next);
});

// --- Unlock ---
function updateUnlockUI() {
  const unlock = getState().unlock;
  if (unlock?.token && unlock?.expiresAt && Date.now() >= new Date(unlock.expiresAt).getTime()) {
    setState({ unlock: { token: null, expiresAt: null } });
    return;
  }
  const token = getState().unlock?.token;
  const icon = document.getElementById('unlockIcon');
  const label = document.getElementById('unlockLabel');
  if (token) {
    if (icon) icon.innerHTML = '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0"/>';
    if (label) { label.textContent = 'Travado'; label.style.color = 'var(--ok)'; }
  } else {
    if (icon) icon.innerHTML = '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/>';
    if (label) { label.textContent = 'Destravar'; label.style.color = ''; }
  }
}
updateUnlockUI();
subscribe((s) => {
  if (s.unlock !== undefined) updateUnlockUI();
});

document.getElementById('unlockBtn')?.addEventListener('click', async () => {
  const { showUnlockModal } = await import('./notifications.js');
  const result = await showUnlockModal();
  if (result) {
    showToast('Destravado com sucesso', 'success');
  }
});

// --- Theme toggle ---
document.getElementById('themeToggle')?.addEventListener('click', () => {
  const current = getState().tema;
  const next = current === 'cockpit' ? 'claro' : current === 'claro' ? 'escritorio' : 'cockpit';
  setState({ tema: next });
});

// --- Global summary ---
subscribe((s) => {
  const total = s.containers.length;
  const running = s.containers.filter(c => c.State === 'running').length;
  const unhealthy = s.containers.filter(c => saudeDe(c) === 'unhealthy').length;
  const el = document.getElementById('globalSummary');
  if (el) el.textContent = unhealthy > 0 ? `${running}/${total} UP · ${unhealthy} unhealthy` : `${running}/${total} UP`;
});

// --- Boot ---
function boot() {
  /* Antes de qualquer dado: o rail e a lista lateral já rolam com o skeleton, e
   * skeleton não é focalizável. Amarrar isto ao primeiro render deixaria a janela
   * inteira de carregamento sem acesso por teclado — é o que uma auditoria que mede
   * logo após `load` enxerga, e o que o usuário de teclado encontra ao chegar antes
   * dos dados. */
  instalarRolagem();

  // O kernel assume a área de tela: régua (chrome, não ocultável), faixa
  // crítica (global em qualquer escopo), grade de módulos, painel Personalizar
  // e a subtela central.
  iniciarCockpit({
    regua: document.getElementById('kernelReguaSlot'),
    faixa: document.getElementById('kernelFaixa'),
    grade: document.getElementById('screenContainer'),
    painel: document.getElementById('kernelPainel'),
    subtela: document.getElementById('kernelSubtela'),
  });
  startPolling();
  connectSSE();

  initCommandPalette([
    { id: 'personalizar', label: 'Personalizar cockpit', icon: '⋮⋮', action: () => {
      document.getElementById('personalizarBtn')?.click();
    }},
    { id: 'filter-all', label: 'Filtrar: Todos', icon: '⊞', action: () => setState({ filter: 'all' }) },
    { id: 'filter-running', label: 'Filtrar: Rodando', icon: '▶', action: () => setState({ filter: 'running' }) },
    { id: 'filter-exited', label: 'Filtrar: Parados', icon: '■', action: () => setState({ filter: 'exited' }) },
    { id: 'filter-unhealthy', label: 'Filtrar: Unhealthy', icon: '⚠', action: () => setState({ filter: 'unhealthy' }) },
    { id: 'theme-cycle', label: 'Trocar tema', icon: '☀', action: () => {
      const cur = getState().tema;
      setState({ tema: cur === 'cockpit' ? 'claro' : cur === 'claro' ? 'escritorio' : 'cockpit' });
    }},
  ]);

  window.addEventListener('beforeunload', () => { stopPolling(); cancelAll(); });
}

document.addEventListener('DOMContentLoaded', boot);
