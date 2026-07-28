import { apiGet, cancel } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { showToast } from '../notifications.js';
import { navigate } from '../main.js';
import { getState } from '../store.js';

let _disposed = false;
let _lastData = null;
let _findingsDispose = null;

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

function renderContainers(containers, findingsMap) {
  if (!containers || !containers.length) return '<div class="empty">Nenhum container</div>';
  const depth = getState().depth || 'dado';
  return containers.map(c => {
    const lbl = label(c.state, c.health);
    const memStr = c.mem_limit ? fmtBytes(c.mem_limit) : 'sem limite';
    const finding = findingsMap ? findingsMap[c.name] : null;
    let secLine;
    if (depth === 'dado') {
      secLine = escapeHtml(c.image);
    } else if (depth === 'informacao') {
      secLine = finding ? `<span style="color:var(--text-dim)">${escapeHtml(finding.interpretation_plain || finding.interpretation || '')}</span>` : '<span style="color:var(--text-mute);font-style:italic">Nenhum achado</span>';
    } else if (depth === 'conhecimento') {
      secLine = finding ? `<span style="color:var(--accent);font-style:italic">${escapeHtml(finding.recommendation || '')}</span>` : '<span style="color:var(--text-mute);font-style:italic">Nenhum achado</span>';
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
      <div class="ov-age" id="ovStatsAge"></div>
      <div class="ov-grid" id="ovGrid"><div class="skeleton" style="height:400px"></div></div>
    </div>
    <div class="ov-right" id="ovRight">
      <h3 style="margin:0 0 1rem;font-size:.85rem;color:var(--text-mute);text-transform:uppercase;display:flex;justify-content:space-between;align-items:center">
        <span>Precisa da sua aten\u00e7\u00e3o</span>
        <a href="#/incidente" style="font-size:.7rem;color:var(--accent);text-decoration:none">ver todos</a>
      </h3>
      <div id="ovFindings"><div class="skeleton" style="height:200px"></div></div>
    </div>
  </div>`;

  let pollTimer = null;

  function showFallback(id) {
    const div = el(id);
    if (div && !div.querySelector('.stack-block,.container-card,.kpi,.vital')) {
      div.innerHTML = '<div class="empty-field" style="margin-bottom:.5rem">Sem conex\u00e3o — painel indispon\u00edvel</div>';
    }
  }

  function severityColor(sev) {
    if (sev === 'critical') return 'var(--bad)';
    if (sev === 'high') return 'var(--warn)';
    if (sev === 'medium') return 'var(--accent)';
    return 'var(--text-dim)';
  }

  function severityLabel(sev) {
    if (sev === 'critical') return 'Cr\u00edtico';
    if (sev === 'high') return 'Alto';
    if (sev === 'medium') return 'M\u00e9dio';
    return 'Baixo';
  }

  function renderRightFindings(data) {
    if (_disposed) return;
    const div = el('ovFindings');
    if (!div) return;
    if (!data || !data.length) {
      div.innerHTML = '<div class="empty-field" style="margin:.5rem 0">Nenhum achado ativo</div>';
      return;
    }
    const depth = getState().depth || 'dado';
    const items = data.slice(0, 8).map(f => {
      const color = severityColor(f.severity);
      const showPlain = depth === 'informacao' || depth === 'conhecimento';
      const title = showPlain && f.title_plain ? f.title_plain : (f.title || f.id);
      const age = f.first_seen ? Math.round((Date.now() - new Date(f.first_seen).getTime()) / 1000) : 0;
      const ago = age < 60 ? `h\u00e1 ${age}s` : age < 3600 ? `h\u00e1 ${Math.floor(age / 60)}min` : `h\u00e1 ${Math.floor(age / 3600)}h`;
      const duration = f.first_seen && f.last_seen ? Math.round((new Date(f.last_seen).getTime() - new Date(f.first_seen).getTime()) / 1000) : 0;
      const durStr = duration > 60 ? `${Math.floor(duration / 60)}min` : duration > 0 ? `${duration}s` : '';
      const rel = f.related_container;
      const isAgg = Array.isArray(f.targets);
      const targetLabel = isAgg ? `${f.targets.length} hosts` : escapeHtml(f.target || '');
      const targetsAttr = isAgg ? JSON.stringify(f.targets) : '';
      return `<div class="atn-mini" data-id="${escapeHtml(f.id)}" data-scope="${escapeHtml(f.scope || 'container')}" data-target="${escapeHtml(f.target || '')}" data-targets="${escapeHtml(targetsAttr)}" style="border-left:3px solid ${color}">
        <div class="atn-mini-head">
          <span class="atn-mini-sev" style="background:${color}">${severityLabel(f.severity)}</span>
          ${durStr ? `<span style="font-size:.6rem;color:var(--text-mute)">${durStr}</span>` : ''}
          <span class="atn-mini-ago">${ago}</span>
        </div>
        <div class="atn-mini-title">${escapeHtml(title)}</div>
        ${rel ? `<div style="margin-top:.15rem"><a href="#/dossie?c=${encodeURIComponent(rel)}" style="font-size:.6rem;color:var(--accent);text-decoration:none" onclick="event.stopPropagation()">→ ${escapeHtml(rel)}</a></div>` : ''}
      </div>`;
    }).join('');
    div.innerHTML = items;
    div.querySelectorAll('.atn-mini').forEach(card => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('a')) return;
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
        navigate('#/incidente');
      });
    });
  }

  async function fetchOverview() {
    const { data, error } = await apiGet('ov_data', '/api/overview');
    if (_disposed) return;
    if (error) {
      if (!_lastData) {
        showFallback('ovStacks');
        showFallback('ovHost');
        showFallback('ovGrid');
      }
      showToast(_lastData ? 'Rede inst\u00e1vel — dados podem estar desatualizados' : error, _lastData ? 'warning' : 'error');
      return;
    }
    if (!data) return;
    _lastData = data;

    const s = el('ovStacks');
    if (s) s.innerHTML = renderStacks(data.stacks);
    const h = el('ovHost');
    if (h) h.innerHTML = renderVitals(data.vitals);
    const k = el('ovKpis');
    if (k) k.innerHTML = renderKpis(data.counters);
    const findingsRes = await apiGet('ov_findings', '/api/findings?status=open');
    const findingsData = _disposed ? null : findingsRes.data;
    const findingsMap = {};
    if (findingsData) {
      findingsData.forEach(f => { findingsMap[f.target] = f; });
    }
    const g = el('ovGrid');
    if (g) g.innerHTML = renderContainers(data.containers, findingsMap);
    if (findingsData) renderRightFindings(findingsData);

    const sa = el('ovStatsAge');
    if (sa && data.stats_as_of) {
      const age = Math.round((Date.now() - new Date(data.stats_as_of).getTime()) / 1000);
      sa.textContent = `Stats: h\u00e1 ${age}s`;
    }

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
