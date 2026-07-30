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
      badge.textContent = data.length;
      const sevOrder = { critical: 4, high: 3, medium: 2, low: 1 };
      const maxSev = data.reduce((a, f) => sevOrder[f.severity] > sevOrder[a] ? f.severity : a, 'low');
      const sevColors = { critical: 'var(--bad)', high: 'var(--warn)', medium: 'var(--accent)', low: 'var(--text-mute)' };
      badge.style.background = sevColors[maxSev] || 'var(--bad)';
      badge.style.display = '';
    } else {
      badge.style.display = 'none';
    }
  });
}

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

// --- Shared polling (30s reconciliation, paused when tab hidden) ---
// pollTimer ja e declarado junto de pollAll(), acima. Redeclarar com `let` no
// mesmo escopo de modulo e SyntaxError: o main.js inteiro deixa de carregar e
// a interface fica no "carregando" para sempre, sem pintar nada.
function startPolling() {
  pollAll();
  pollTimer = setInterval(pollAll, 30000);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) { stopPolling(); disconnectSSE(); } else { startPolling(); connectSSE(); }
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

  if (!filtered.length) {
    listEl.innerHTML = '<div class="empty">Nenhum container encontrado</div>';
    return;
  }

  const groups = {};
  filtered.forEach(c => {
    const s = getStackName(c) || '__ungrouped__';
    if (!groups[s]) groups[s] = [];
    groups[s].push(c);
  });
  const hasGroups = Object.keys(groups).length > 1 || !groups['__ungrouped__'];

  let html = '';
  Object.entries(groups).sort(([a], [b]) => {
    if (a === '__ungrouped__') return 1;
    if (b === '__ungrouped__') return -1;
    return a.localeCompare(b);
  }).forEach(([stack, ctrs]) => {
    if (hasGroups && stack !== '__ungrouped__') {
      const running = ctrs.filter(c => c.State === 'running').length;
      html += `<button type="button" class="stack-header" data-stack="${escapeHtml(stack)}" aria-expanded="true">
        <span class="stack-toggle">▼</span><span class="stack-name">${escapeHtml(stack)}</span>
        <span class="stack-count">${running}/${ctrs.length}</span></button>`;
    }
    html += `<div class="stack-group" data-stack="${escapeHtml(stack)}">`;
    ctrs.forEach(c => {
      const id = c.Id;
      const name = (c.Names && c.Names[0] || '').replace(/^\//, '');
      const saude = saudeDe(c);
      let statusCls = c.State || 'unknown';
      if (saude === 'unhealthy') statusCls = 'unhealthy';
      // Badge so aparece com healthcheck falhando ou em partida. Container sem
      // healthcheck nao ganha selo nenhum: nao ha saude medida para afirmar.
      const badge = (saude === 'unhealthy' || saude === 'starting')
        ? `<span class="item-health ${saude}" title="Healthcheck: ${saude}">${saude === 'unhealthy' ? 'unhealthy' : 'starting'}</span>`
        : '';
      html += `<button type="button" class="list-item ${id === selId ? 'active' : ''}" data-id="${id}" data-nome="${escapeHtml(name)}"${id === selId ? ' aria-current="true"' : ''}>
        <div class="item-status ${statusCls}"></div>
        <div class="item-info">
          <div class="item-name" title="${escapeHtml(name)}">${escapeHtml(name)}${badge}</div>
          <div class="item-image" title="${escapeHtml(c.Image || '')}">${escapeHtml(c.Image || '')}</div>
        </div>
      </button>`;
    });
    html += '</div>';
  });
  listEl.innerHTML = html;

  listEl.querySelectorAll('.stack-header').forEach(h => {
    h.addEventListener('click', () => {
      const g = h.nextElementSibling;
      if (g && g.classList.contains('stack-group')) {
        const hidden = g.style.display === 'none';
        g.style.display = hidden ? '' : 'none';
        h.querySelector('.stack-toggle').textContent = hidden ? '▼' : '▶';
      }
    });
  });
  listEl.querySelectorAll('.list-item').forEach(el => {
    el.addEventListener('click', () => {
      const nome = el.dataset.nome || el.dataset.id;
      setState({ selectedContainer: el.dataset.id });
      // A barra lateral deixa de ser rota e passa a ser atalho de escopo: abre a
      // subtela do container. O kernel e a faixa crítica seguem visíveis.
      cockpit.irPara(escopoContainer(nome));
    });
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
