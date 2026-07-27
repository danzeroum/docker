import { apiGet, cancel } from '../data.js';
import { fmtBytes, fmtDate, shortId, escapeHtml } from '../fmt.js';
import { showToast } from '../notifications.js';
import { navigate } from '../main.js';
import { getState } from '../store.js';

let _disposed = false;

function el(id) { return document.getElementById(id); }

function label(state, health) {
  if (state === 'running' && health === 'unhealthy') return 'sick';
  if (state === 'running') return 'up';
  if (state === 'restarting') return 'loop';
  return 'off';
}

function stateColor(s) {
  if (s === 'running') return 'var(--ok)';
  if (s === 'restarting') return 'var(--bad)';
  return 'var(--text-dim)';
}

function worstColor(w) {
  if (w === 'bad') return 'var(--bad)';
  if (w === 'warn') return 'var(--warn)';
  return 'var(--ok)';
}

function renderVitals(v) {
  if (!v) return '';
  const d = v.disk || {};
  return `<div class="vitals">
    <div class="vital"><span class="vital-label">CPU</span><span class="vital-value">${v.cpu_pct.toFixed(1)}%</span></div>
    <div class="vital"><span class="vital-label">RAM</span><span class="vital-value">${v.mem_pct.toFixed(1)}%</span></div>
    <div class="vital"><span class="vital-label">Disk</span><span class="vital-value">${d.pct != null ? d.pct.toFixed(1) + '%' : '—'}</span></div>
    <div class="vital"><span class="vital-label">Swap</span><span class="vital-value">${v.swap_pct.toFixed(1)}%</span></div>
  </div>`;
}

function renderKpis(counters) {
  if (!counters) return '';
  return `<div class="kpis">
    <div class="kpi"><div class="kpi-label">Containers</div><div class="kpi-value">${counters.total}</div></div>
    <div class="kpi kpi-ok"><div class="kpi-label">Rodando</div><div class="kpi-value">${counters.running}</div></div>
    <div class="kpi ${counters.attention > 0 ? 'kpi-bad' : 'kpi-ok'}"><div class="kpi-label">Precisam de você</div><div class="kpi-value">${counters.attention}</div></div>
    <div class="kpi"><div class="kpi-label">Disco do host</div><div class="kpi-value" id="ovDiskKpi">—</div></div>
  </div>`;
}

function renderStacks(stacks) {
  if (!stacks || !stacks.length) return '<div class="empty">Nenhuma stack</div>';
  return stacks.map(s => {
    const c = worstColor(s.worst);
    const dotsHtml = s.containers.map(cn => `<span class="stack-contr" data-name="${escapeHtml(cn)}">${escapeHtml(cn)}</span>`).join('');
    return `<div class="stack-block" data-stack="${escapeHtml(s.id)}">
      <div class="stack-head" style="--stack-color:${c}">
        <span class="stack-dot"></span>
        <span class="stack-name">${escapeHtml(s.id)}</span>
        <span class="stack-count">${s.running}/${s.total}</span>
      </div>
      <div class="stack-body">${dotsHtml}</div>
    </div>`;
  }).join('');
}

function renderContainers(containers) {
  if (!containers || !containers.length) return '<div class="empty">Nenhum container</div>';
  const depth = getState().depth || 'dado';
  return containers.map(c => {
    const lbl = label(c.state, c.health);
    const memStr = c.mem_limit ? fmtBytes(c.mem_limit) : 'sem limite';
    let secLine = escapeHtml(c.image);
    if (depth === 'informacao' || depth === 'conhecimento') {
      secLine = '<span style="color:var(--text-mute);font-style:italic">Aguarda achados — F2</span>';
    }
    return `<div class="container-card" data-id="${escapeHtml(c.id)}" data-state="${escapeHtml(c.state)}">
      <div class="card-header">
        <span class="card-badge ${lbl}">${lbl}</span>
        <span class="card-name" title="${escapeHtml(c.name)}">${escapeHtml(c.name)}</span>
      </div>
      <div class="card-image" title="${escapeHtml(c.image)}">${secLine}</div>
      <div class="card-bars">
        <div class="bar-row"><span class="bar-label">CPU</span><div class="bar"><div class="bar-fill" style="width:${Math.min(c.cpu_pct, 100)}%"></div></div><span class="bar-value">${c.cpu_pct.toFixed(1)}%</span></div>
        <div class="bar-row"><span class="bar-label">MEM</span>${c.mem_pct != null ? `<div class="bar"><div class="bar-fill" style="width:${Math.min(c.mem_pct, 100)}%"></div></div><span class="bar-value">${c.mem_pct.toFixed(1)}% · ${memStr}</span>` : `<div class="bar" style="opacity:.3"><div class="bar-fill" style="width:0%"></div></div><span class="bar-value" style="font-style:italic;color:var(--text-mute)">sem limite</span>`}</div>
      </div>
      <div class="card-footer">
        <span>${c.ports || 'sem portas'}</span>
        <span class="card-exposure ${c.exposure === 'internet' ? 'exp-internet' : 'exp-pendente'}">${c.exposure === 'internet' ? 'Internet' : c.exposure === 'pendente' ? 'pendente' : 'interna'}</span>
      </div>
    </div>`;
  }).join('');
}

export function renderOverview(container) {
  _disposed = false;

  container.innerHTML = `<div class="content overview-layout">
    <div class="ov-left" id="ovLeft">
      <div class="ov-stacks" id="ovStacks"><div class="skeleton" style="height:300px"></div></div>
    </div>
    <div class="ov-center" id="ovCenter">
      <div class="ov-host" id="ovHost"><div class="skeleton" style="height:60px"></div></div>
      <div class="ov-kpis" id="ovKpis"><div class="skeleton" style="height:80px"></div></div>
      <div class="ov-grid" id="ovGrid"><div class="skeleton" style="height:400px"></div></div>
    </div>
    <div class="ov-right" id="ovRight">
      <h3 style="margin:0 0 1rem;font-size:.85rem;color:var(--text-mute);text-transform:uppercase">Precisa da sua atenção</h3>
      <div class="empty-field" style="background:var(--neutral-soft);border-color:var(--border);color:var(--text-dim)">Aguarda <code>/api/findings</code> — previsto para F2.</div>
    </div>
  </div>`;

  let pollTimer = null;

  async function fetchOverview() {
    const { data, error } = await apiGet('ov_data', '/api/overview');
    if (error) { showToast(error, 'error'); return; }
    if (_disposed) return;
    if (!data) return;

    const s = el('ovStacks');
    if (s) s.innerHTML = renderStacks(data.stacks);
    const h = el('ovHost');
    if (h) h.innerHTML = renderVitals(data.vitals);
    const k = el('ovKpis');
    if (k) k.innerHTML = renderKpis(data.counters);
    const g = el('ovGrid');
    if (g) g.innerHTML = renderContainers(data.containers);

    const diskKpi = el('ovDiskKpi');
    if (diskKpi && data.vitals && data.vitals.disk) {
      diskKpi.textContent = data.vitals.disk.pct.toFixed(1) + '%';
    }

    if (data.host && data.host.name) {
      const hostEl = el('ovHostTitle');
      if (!hostEl) {
        const hostDiv = el('ovHost');
        if (hostDiv) {
          const h2 = document.createElement('h2');
          h2.id = 'ovHostTitle';
          h2.style.cssText = 'margin:0 0 .5rem;font-size:1.1rem';
          h2.textContent = `${data.host.name} · ${data.host.cpus} vCPU · ${data.host.mem_total_gb} GB`;
          hostDiv.prepend(h2);
        }
      } else {
        hostEl.textContent = `${data.host.name} · ${data.host.cpus} vCPU · ${data.host.mem_total_gb} GB`;
      }
    }
  }

  fetchOverview();
  pollTimer = setInterval(fetchOverview, 5000);

  document.addEventListener('visibilitychange', onVis);

  function onVis() {
    if (_disposed) return;
    if (document.hidden) {
      clearInterval(pollTimer);
      pollTimer = null;
    } else {
      fetchOverview();
      pollTimer = setInterval(fetchOverview, 5000);
    }
  }

  el('ovGrid')?.addEventListener('click', (e) => {
    const card = e.target.closest('.container-card');
    if (!card) return;
    import('../store.js').then(({ setState }) => {
      setState({ selectedContainer: card.dataset.id });
      navigate('#/dossie');
    });
  });

  el('ovStacks')?.addEventListener('click', (e) => {
    const ctr = e.target.closest('.stack-contr');
    if (!ctr) return;
    import('../store.js').then(({ getState, setState }) => {
      const containers = getState().containers;
      const found = containers.find(c => {
        const n = (c.Names && c.Names[0] || '').replace(/^\//, '');
        return n === ctr.dataset.name;
      });
      if (found) {
        setState({ selectedContainer: found.Id || found.id });
        navigate('#/dossie');
      }
    });
  });

  return () => {
    _disposed = true;
    if (pollTimer) clearInterval(pollTimer);
    cancel('ov_data');
    document.removeEventListener('visibilitychange', onVis);
  };
}
