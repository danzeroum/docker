import { getState, setState, subscribe } from './store.js';
import { apiGet, apiPost, apiDelete, cancel, cancelAll } from './data.js';
import { fmtBytes, fmtDuration, fmtDate, shortId, escapeHtml, jsonHighlight } from './fmt.js';
import { showToast, showConfirmModal } from './notifications.js';
import { initCommandPalette } from './commands.js';
import { renderOverview } from './screens/overview.js';
import { renderAttention } from './screens/attention.js';

// --- Theme ---
function applyTheme(tema) {
  document.documentElement.setAttribute('data-tema', tema);
}
applyTheme(getState().tema);
subscribe((s) => {
  if (s.tema) applyTheme(s.tema);
});

// --- Hash router ---
let _writingHash = false;

export function navigate(hash) {
  if (location.hash === hash) return;
  _writingHash = true;
  location.hash = hash;
  _writingHash = false;
}

window.addEventListener('hashchange', () => {
  if (_writingHash) return;
  const hash = location.hash || '#/overview';
  setState({ screen: hash });
});

// --- Dispose ---
let currentDispose = null;
let activePollers = [];

function schedule(fn, ms, key) {
  let id = setTimeout(async () => {
    const result = await fn();
    if (!result || result.aborted) return;
    id = setTimeout(arguments.callee, ms);
  }, ms);
  activePollers.push(() => clearTimeout(id));
  return () => { clearTimeout(id); };
}

function renderScreen(screen) {
  cancelAll();
  if (currentDispose) { currentDispose(); currentDispose = null; }
  activePollers.forEach(fn => fn());
  activePollers = [];

  const container = document.getElementById('screenContainer');
  if (!container) return;

  let dispose;
  switch (screen) {
    case '#/overview': dispose = renderOverview(container); break;
    case '#/dossie': renderDossie(container); break;
    case '#/logs': renderLogs(container); break;
    case '#/plantao': renderPlaceholder(container, 'Plantão', '/api/findings', 'F1'); break;
    case '#/incidente': dispose = renderAttention(container); break;
    case '#/ingress': renderPlaceholder(container, 'Ingress & TLS', '/api/ingress', 'F3'); break;
    case '#/topologia': renderPlaceholder(container, 'Topologia', '/api/topology', 'F3'); break;
    case '#/capacidade': renderPlaceholder(container, 'Capacidade', '/api/metrics/history', 'F4'); break;
    case '#/tarefas': renderPlaceholder(container, 'Tarefas', '/api/tasks', 'F5'); break;
    case '#/executivo': renderPlaceholder(container, 'Executivo', '/api/executive', 'F5'); break;
    case '#/backend': renderPlaceholder(container, 'Backend', '/api/backend', 'F6'); break;
    default: dispose = renderOverview(container); break;
  }
  if (dispose) currentDispose = dispose;
}

subscribe((s, changed) => {
  if (changed.includes('screen')) renderScreen(s.screen);
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

function startPolling() {
  pollAll();
  pollTimer = setInterval(pollAll, 5000);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) { stopPolling(); } else { startPolling(); }
});

function getStackName(c) {
  return (c.Labels && c.Labels['com.docker.compose.project']) || null;
}

function renderContainerList() {
  const listEl = document.getElementById('containerList');
  if (!listEl) return;
  const { containers, filter: curFilter, search: curSearch, selectedContainer: selId } = getState();

  let filtered = [...containers];
  if (curFilter === 'running') filtered = filtered.filter(c => c.State === 'running');
  else if (curFilter === 'exited') filtered = filtered.filter(c => ['exited', 'created', 'dead'].includes(c.State));
  else if (curFilter === 'unhealthy') filtered = filtered.filter(c => c.State === 'unhealthy' || (c.Status && c.Status.includes('unhealthy')));

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
      html += `<div class="stack-header" data-stack="${escapeHtml(stack)}">
        <span class="stack-toggle">▼</span><span class="stack-name">${escapeHtml(stack)}</span>
        <span class="stack-count">${running}/${ctrs.length}</span></div>`;
    }
    html += `<div class="stack-group" data-stack="${escapeHtml(stack)}">`;
    ctrs.forEach(c => {
      const id = c.Id;
      const name = (c.Names && c.Names[0] || '').replace(/^\//, '');
      let statusCls = c.State || 'unknown';
      if (c.Status && c.Status.includes('unhealthy')) statusCls = 'unhealthy';
      html += `<div class="list-item ${id === selId ? 'active' : ''}" data-id="${id}">
        <div class="item-status ${statusCls}"></div>
        <div class="item-info">
          <div class="item-name" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
          <div class="item-image" title="${escapeHtml(c.Image || '')}">${escapeHtml(c.Image || '')}</div>
        </div>
      </div>`;
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
      setState({ selectedContainer: el.dataset.id });
      navigate('#/dossie');
    });
  });
}



// --- Screen: Dossiê ---
function parseInspect(data) {
  const c = Array.isArray(data) ? data[0] : data;
  const state = c.State || {};
  const config = c.Config || {};
  const host = c.HostConfig || {};
  const net = c.NetworkSettings || {};
  const health = state.Health || null;
  let status = state.Status || 'unknown';
  if (health && health.Status === 'unhealthy' && state.running) status = 'unhealthy';
  return {
    name: c.Name ? c.Name.replace(/^\//, '') : '',
    id: c.Id || '', image: config.Image || '',
    state: { status, running: !!state.Running, exitCode: state.ExitCode ?? null,
      startedAt: state.StartedAt ? new Date(state.StartedAt) : null,
      uptimeMs: state.Status === 'running' && state.StartedAt ? (new Date() - new Date(state.StartedAt)) : 0,
      restartCount: state.RestartCount ?? 0, pid: state.Pid ?? null, error: state.Error || null,
      health: health ? { status: health.Status || 'none', failingStreak: health.FailingStreak ?? 0,
        log: (health.Log || []).map(l => ({ start: l.Start, exitCode: l.ExitCode, output: l.Output }))
      } : null
    },
    config: { env: config.Env || [] },
    host: { portBindings: host.PortBindings || {}, restartPolicy: host.RestartPolicy || {} },
    net: { ip: net.IPAddress || '', networks: net.Networks || {} },
    mounts: c.Mounts || []
  };
}

function renderDossie(container) {
  const id = getState().selectedContainer;
  if (!id) {
    container.innerHTML = '<div class="content"><div class="empty">Selecione um container na lista à esquerda.</div></div>';
    return;
  }

  container.innerHTML = '<div class="content"><div class="skeleton" style="width:100%;height:400px"></div></div>';

  const ac = new AbortController();

  async function load() {
    const { data, error } = await apiGet('inspect', `/api/containers/${id}/json`);
    if (error) {
      container.innerHTML = `<div class="content"><div class="empty">Erro ao carregar: ${escapeHtml(error)}</div></div>`;
      showToast(error, 'error');
      return;
    }
    if (ac.signal.aborted) return;

    const c = parseInspect(data);
    let healthHtml = '<div class="empty-field">Nenhum HEALTHCHECK definido.</div>';
    if (c.state.health) {
      const logs = c.state.health.log.slice().reverse().map(l => `
        <div style="margin-bottom:.75rem;padding:.75rem 1rem;border:1px solid var(--border);border-radius:10px;border-left:3px solid ${l.exitCode===0?'var(--ok)':'var(--bad)'}">
          <div style="display:flex;gap:.5rem;align-items:center;margin-bottom:.25rem">
            <span style="font-family:'JetBrains Mono';font-size:.7rem;padding:.15rem .4rem;border-radius:4px;background:${l.exitCode===0?'var(--ok-soft)':'var(--bad-soft)'};color:${l.exitCode===0?'#86efac':'#fca5a5'}">exit ${l.exitCode}</span>
            <span style="font-size:.7rem;color:var(--text-mute)">${fmtDate(l.start)}</span>
          </div>
          ${l.output ? `<pre style="margin:0;font-size:.7rem;color:var(--text-dim);white-space:pre-wrap;word-break:break-all">${escapeHtml(l.output.trim().slice(0,300))}</pre>` : ''}
        </div>
      `).join('');
      healthHtml = `
        <div class="card-grid cols-3" style="margin-bottom:1rem">
          <div class="field"><div class="field-label">Status</div><div class="field-value">${escapeHtml(c.state.health.status)}</div></div>
          <div class="field"><div class="field-label">Falhas</div><div class="field-value">${c.state.health.failingStreak}</div></div>
        </div>
        ${logs || '<div class="empty-field">Sem logs de health.</div>'}`;
    }

    const ports = Object.entries(c.host.portBindings || {}).filter(([,v]) => v);
    let portHtml = '<div class="empty-field">Nenhuma porta publicada.</div>';
    if (ports.length) {
      portHtml = `<div class="table-wrap"><table><thead><tr><th>Host IP</th><th>Host Port</th><th>Container Port</th></tr></thead><tbody>
        ${ports.map(([k,v]) => v.map(b => `<tr><td>${escapeHtml(b.HostIp||'0.0.0.0')}</td><td>${escapeHtml(b.HostPort)}</td><td>${escapeHtml(k)}</td></tr>`).join('')).join('')}
      </tbody></table></div>`;
    }

    const nets = Object.entries(c.net.networks || {});
    let netHtml = '<div class="empty-field">Sem redes.</div>';
    if (nets.length) {
      netHtml = `<div class="table-wrap"><table><thead><tr><th>Rede</th><th>IP</th><th>Gateway</th></tr></thead><tbody>
        ${nets.map(([n,v]) => `<tr><td>${escapeHtml(n)}</td><td>${escapeHtml(v.IPAddress||'—')}</td><td>${escapeHtml(v.Gateway||'—')}</td></tr>`).join('')}
      </tbody></table></div>`;
    }

    let volHtml = '<div class="empty-field">Nenhum volume.</div>';
    if (c.mounts.length) {
      volHtml = `<div class="table-wrap"><table><thead><tr><th>Tipo</th><th>Source</th><th>Destino</th></tr></thead><tbody>
        ${c.mounts.map(m => `<tr><td>${escapeHtml(m.Type)}</td><td>${escapeHtml(m.Source||m.Name||'')}</td><td>${escapeHtml(m.Destination||'')}</td></tr>`).join('')}
      </tbody></table></div>`;
    }

    let envHtml = '<div class="empty-field">Sem variáveis.</div>';
    if (c.config.env.length) {
      envHtml = `<div class="table-wrap"><table><thead><tr><th>Variável</th><th>Valor</th></tr></thead><tbody>
        ${c.config.env.map(e => {
          const idx = e.indexOf('=');
          const k = idx > 0 ? e.slice(0, idx) : e;
          const v = idx > 0 ? e.slice(idx + 1) : '';
          const secret = /SECRET|PASS|TOKEN|KEY/i.test(k);
          return `<tr><td><strong>${escapeHtml(k)}</strong></td><td style="${secret?'filter:blur(4px)':''}">${escapeHtml(v||'—')}</td></tr>`;
        }).join('')}
      </tbody></table></div>`;
    }

    container.innerHTML = `<div class="content">
      <div class="section">
        <div style="display:flex;gap:1rem;align-items:center;flex-wrap:wrap">
          <span class="status-pill ${escapeHtml(c.state.status)}"><span class="dot"></span>${escapeHtml(c.state.status)}</span>
          <span style="font-family:'JetBrains Mono';font-size:.8rem;color:var(--text-dim)">ID: ${escapeHtml(shortId(c.id))}</span>
        </div>
        <div class="kpis" style="margin-top:1rem">
          <div class="kpi kpi-ok"><div class="kpi-label">Uptime</div><div class="kpi-value" style="font-size:1.2rem">${fmtDuration(c.state.uptimeMs)}</div></div>
          <div class="kpi kpi-warn"><div class="kpi-label">Restarts</div><div class="kpi-value" style="font-size:1.2rem">${c.state.restartCount}</div></div>
          <div class="kpi kpi-bad"><div class="kpi-label">Exit Code</div><div class="kpi-value" style="font-size:1.2rem">${c.state.exitCode ?? '—'}</div></div>
        </div>
        <div class="action-bar">
          <button class="action-btn start" data-action="start" ${c.state.running?'disabled':''}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> Iniciar</button>
          <button class="action-btn stop" data-action="stop" ${!c.state.running?'disabled':''}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="12" height="16"/></svg> Parar</button>
          <button class="action-btn restart" data-action="restart" ${!c.state.running?'disabled':''}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 23 20"/></svg> Reiniciar</button>
          <button class="action-btn remove" data-action="remove"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg> Remover</button>
        </div>
      </div>
      <div class="section"><div class="section-head"><div class="section-num">02</div><div><h2 class="section-title">Estado</h2></div></div>
        <div class="card-grid cols-3">
          <div class="field"><div class="field-label">Started At</div><div class="field-value">${fmtDate(c.state.startedAt)}</div></div>
          <div class="field"><div class="field-label">PID</div><div class="field-value">${c.state.pid ?? '—'}</div></div>
          <div class="field"><div class="field-label">Error</div><div class="field-value">${escapeHtml(c.state.error || '—')}</div></div>
        </div>
      </div>
      <div class="section"><div class="section-head"><div class="section-num">03</div><div><h2 class="section-title">Health Check</h2></div></div>${healthHtml}</div>
      <div class="section"><div class="section-head"><div class="section-num">04</div><div><h2 class="section-title">Rede & Portas</h2></div></div>
        <h3 style="font-size:.8rem;color:var(--text-mute);margin:0 0 .5rem;text-transform:uppercase">Portas</h3>${portHtml}
        <h3 style="font-size:.8rem;color:var(--text-mute);margin:1.5rem 0 .5rem;text-transform:uppercase">Redes</h3>${netHtml}
      </div>
      <div class="section"><div class="section-head"><div class="section-num">05</div><div><h2 class="section-title">Volumes</h2></div></div>${volHtml}</div>
      <div class="section"><div class="section-head"><div class="section-num">06</div><div><h2 class="section-title">Variáveis de Ambiente</h2></div></div>${envHtml}</div>
      <div class="section"><div class="section-head"><div class="section-num">07</div><div><h2 class="section-title">JSON Bruto</h2></div></div>
        <div class="json-wrap"><pre class="json-content">${jsonHighlight(data)}</pre></div>
      </div>
    </div>`;

    // Action buttons
    container.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const action = btn.dataset.action;
        if (action === 'remove') {
          const r = await showConfirmModal({
            title: 'Remover container',
            message: `Tem certeza?`,
            confirmText: 'Remover',
            confirmClass: 'remove',
            confirmName: c.name,
            checkboxLabel: 'Remover volumes associados',
          });
          if (!r.confirmed) return;
          const qs = r.checkbox ? '?v=1' : '';
          const { error } = await apiDelete('remove', `/api/containers/${id}${qs}`);
          if (error) { showToast(error, 'error'); return; }
          showToast('Container removido', 'success');
          setState({ selectedContainer: null });
          navigate('#/overview');
        } else {
          btn.disabled = true;
          const { error } = await apiPost(action, `/api/containers/${id}/${action}`);
          if (error) { showToast(error, 'error'); btn.disabled = false; return; }
          showToast(`Container ${action}`, 'success');
          load();
        }
      });
    });
  }

  load();

  currentDispose = () => {
    ac.abort();
    cancel('inspect');
  };
}

// --- Screen: Logs ---
function renderLogs(container) {
  const id = getState().selectedContainer;
  if (!id) {
    container.innerHTML = '<div class="content"><div class="empty">Selecione um container na lista à esquerda.</div></div>';
    return;
  }

  container.innerHTML = `<div class="content">
    <div class="section">
      <div class="section-head"><div><h2 class="section-title">Logs</h2></div></div>
      <div style="display:flex;gap:.5rem;margin-bottom:1rem">
        <button class="action-btn" data-lines="100" style="background:var(--accent)">100 linhas</button>
        <button class="action-btn" data-lines="500" style="background:var(--accent)">500 linhas</button>
        <button class="action-btn" data-lines="2000" style="background:var(--accent)">2000 linhas</button>
        <button class="action-btn start" data-action="stream">▶ Stream</button>
        <button class="action-btn stop" data-action="stop-stream" disabled>■ Parar</button>
      </div>
      <pre id="logOutput" style="background:var(--bg-2);border:1px solid var(--border);border-radius:10px;padding:1rem;font-family:'JetBrains Mono',monospace;font-size:.75rem;line-height:1.6;overflow:auto;max-height:70vh;margin:0;white-space:pre-wrap;word-break:break-all"></pre>
    </div>
  </div>`;

  const logEl = document.getElementById('logOutput');
  let eventSource = null;

  function stopStream() {
    if (eventSource) { eventSource.close(); eventSource = null; }
    document.querySelector('[data-action="stream"]').disabled = false;
    document.querySelector('[data-action="stop-stream"]').disabled = true;
  }

  async function fetchLines(n) {
    const { data, error } = await apiGet('logs', `/api/containers/${id}/logs?tail=${n}`);
    if (error) { logEl.textContent = 'Erro: ' + error; return; }
    logEl.textContent = data;
  }

  container.querySelector('[data-lines="100"]').onclick = () => { stopStream(); fetchLines(100); };
  container.querySelector('[data-lines="500"]').onclick = () => { stopStream(); fetchLines(500); };
  container.querySelector('[data-lines="2000"]').onclick = () => { stopStream(); fetchLines(2000); };
  container.querySelector('[data-action="stream"]').onclick = () => {
    stopStream();
    document.querySelector('[data-action="stream"]').disabled = true;
    document.querySelector('[data-action="stop-stream"]').disabled = false;
    logEl.textContent = 'Aguardando logs...\n';
    eventSource = new EventSource(`/api/containers/${id}/logs/stream?tail=50`);
    eventSource.addEventListener('stdout', (e) => { logEl.textContent += e.data + '\n'; });
    eventSource.addEventListener('stderr', (e) => { logEl.textContent += e.data + '\n'; });
    eventSource.addEventListener('error', () => { logEl.textContent += '[stream desconectado]\n'; });
  };
  container.querySelector('[data-action="stop-stream"]').onclick = stopStream;

  fetchLines(100);

  currentDispose = () => {
    stopStream();
    cancel('logs');
  };
}

// --- Screen: Placeholder ---
function renderPlaceholder(container, title, endpoint, phase) {
  container.innerHTML = `<div class="content">
    <div class="section">
      <div class="section-head"><div><h2 class="section-title">${escapeHtml(title)}</h2></div></div>
      <div class="empty-field" style="background:var(--neutral-soft);border-color:var(--border);color:var(--text-dim)">
        Aguarda <code>${escapeHtml(endpoint)}</code>, previsto para <strong>${escapeHtml(phase)}</strong>.
      </div>
    </div>
  </div>`;
  currentDispose = () => {};
}

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
  const unhealthy = s.containers.filter(c => c.State === 'unhealthy' || (c.Status && c.Status.includes('unhealthy'))).length;
  const el = document.getElementById('globalSummary');
  if (el) el.textContent = unhealthy > 0 ? `${running}/${total} UP · ${unhealthy} unhealthy` : `${running}/${total} UP`;
});

// --- Boot ---
function boot() {
  const hash = location.hash || '#/overview';
  setState({ screen: hash });
  startPolling();

  initCommandPalette([
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
