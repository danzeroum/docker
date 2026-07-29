import { apiGet, cancel } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { showToast } from '../notifications.js';
import { navigate } from '../main.js';
import { getState, setState } from '../store.js';

let _disposed = false;
let _highlightedHosts = [];
let _allHosts = [];
let _allFindings = [];
let _pollTimer = null;

const POLL_MS = 300000;

function el(id) { return document.getElementById(id); }

function sevColor(s) {
  if (s === 'critical') return 'var(--bad)';
  if (s === 'high') return 'var(--warn)';
  if (s === 'medium') return 'var(--accent)';
  return 'var(--text-dim)';
}
function sevLabel(s) {
  if (s === 'critical') return 'Crítico';
  if (s === 'high') return 'Alto';
  if (s === 'medium') return 'Médio';
  return 'Baixo';
}

function yesno(v) {
  return v ? '<span style="color:var(--ok);font-weight:700">✓</span>' : '<span style="color:var(--text-mute)">—</span>';
}

function renderKpis(hosts, totals) {
  const publics = Object.entries(hosts).filter(([, h]) => !h.internal);
  const httpPlain = publics.filter(([, h]) => {
    const p80 = h.port_80;
    return p80 && !p80.https_redirect && p80.upstream;
  }).length;
  const html = `
    <div class="kpi kpi-accent"><div class="kpi-label">Públicos</div><div class="kpi-value">${totals.public}</div></div>
    <div class="kpi kpi-ok"><div class="kpi-label">Com TLS</div><div class="kpi-value">${totals.with_ssl}</div></div>
    <div class="kpi ${httpPlain > 0 ? 'kpi-bad' : 'kpi-ok'}"><div class="kpi-label">HTTP texto claro</div><div class="kpi-value">${httpPlain}</div></div>
    <div class="kpi kpi-ok"><div class="kpi-label">HSTS</div><div class="kpi-value">${totals.with_hsts}</div></div>
    <div class="kpi kpi-warn"><div class="kpi-label">Filtro bots</div><div class="kpi-value">${totals.with_bot_filter}</div></div>`;
  const k = el('igKpis');
  if (k) k.innerHTML = html;
}

function renderHostRow(name, h) {
  const p80 = h.port_80;
  const p443 = h.port_443;
  let p80html = '—';
  if (p80) {
    if (p80.https_redirect) p80html = '<span style="color:var(--ok);font-weight:500">→ 301</span>';
    else if (p80.upstream) p80html = `<span style="color:var(--bad);font-weight:600">HTTP</span>`;
    else if (p80.acme_challenge) p80html = '<span style="color:var(--text-dim)">ACME</span>';
  }
  let p443html = '—';
  if (p443) {
    const us = h.upstreams || [];
    p443html = us.length ? `<span style="font-family:JetBrains Mono;font-size:.7rem">${escapeHtml(us[0])}${us.length > 1 ? ` +${us.length - 1}` : ''}</span>` : '<span style="color:var(--text-dim)">sem proxy</span>';
  }
  const highlighted = _highlightedHosts.includes(name);
  return `<button type="button" class="ig-row${highlighted ? ' ig-highlight' : ''}" data-host="${escapeHtml(name)}">
    <div class="ig-cell ig-cell-name"><strong>${escapeHtml(name)}</strong></div>
    <div class="ig-cell ig-cell-p80">${p80html}</div>
    <div class="ig-cell ig-cell-p443">${p443html}</div>
    <div class="ig-cell ig-cell-bool">${yesno(h.hsts)}</div>
    <div class="ig-cell ig-cell-bool">${yesno(h.bot_filter)}</div>
    <div class="ig-cell ig-cell-bool">${yesno(h.auth_basic)}</div>
    <div class="ig-cell ig-cell-cert" title="${escapeHtml(h.cert_path || '')}">${h.cert_path ? `<span style="font-family:JetBrains Mono;font-size:.7rem;color:var(--text-dim)">${escapeHtml(h.cert_path.split('/').slice(-2).join('/'))}</span>` : '—'}</div>
  </button>`;
}

function renderTable(hosts) {
  const publics = Object.entries(hosts).filter(([, h]) => !h.internal);
  const rows = publics.map(([name, h]) => renderHostRow(name, h)).join('');
  const c = el('igCenter');
  if (!c) return;
  c.innerHTML = `<div class="ig-table-wrap">
    <div class="ig-header">
      <div class="ig-cell ig-cell-name" style="color:var(--text-mute);font-weight:600;font-size:.7rem;text-transform:uppercase">Host</div>
      <div class="ig-cell" style="color:var(--text-mute);font-weight:600;font-size:.7rem;text-transform:uppercase">:80</div>
      <div class="ig-cell" style="color:var(--text-mute);font-weight:600;font-size:.7rem;text-transform:uppercase">:443</div>
      <div class="ig-cell ig-cell-bool" style="color:var(--text-mute);font-weight:600;font-size:.7rem;text-transform:uppercase" title="HSTS">HSTS</div>
      <div class="ig-cell ig-cell-bool" style="color:var(--text-mute);font-weight:600;font-size:.7rem;text-transform:uppercase" title="Bot filter">Bots</div>
      <div class="ig-cell ig-cell-bool" style="color:var(--text-mute);font-weight:600;font-size:.7rem;text-transform:uppercase" title="Auth basic">Auth</div>
      <div class="ig-cell ig-cell-cert" style="color:var(--text-mute);font-weight:600;font-size:.7rem;text-transform:uppercase">Certificado</div>
    </div>
    ${rows}
  </div>`;
  c.querySelectorAll('.ig-row').forEach(row => {
    row.addEventListener('click', () => {
      _highlightedHosts = [row.dataset.host];
      c.querySelectorAll('.ig-row').forEach(r => r.classList.toggle('ig-highlight', _highlightedHosts.includes(r.dataset.host)));
    });
  });
  if (_highlightedHosts.length) {
    _highlightedHosts.forEach(h => {
      try {
        const sel = `.ig-row[data-host="${h.replace(/"/g, '\\"')}"]`;
        const hl = c.querySelector(sel);
        if (hl) hl.scrollIntoView({ block: 'nearest' });
      } catch {}
    });
  }
}

function renderCerts(hosts) {
  const publics = Object.entries(hosts).filter(([, h]) => !h.internal);
  const certMap = {};
  publics.forEach(([name, h]) => {
    const cp = h.cert_path;
    if (!cp) return;
    if (!certMap[cp]) certMap[cp] = [];
    certMap[cp].push(name);
  });
  const entries = Object.entries(certMap).sort((a, b) => b[1].length - a[1].length);
  if (!entries.length) return '<div class="empty-field" style="margin:0">Nenhum certificado SSL</div>';
  return entries.map(([path, hostsList]) => `<div class="ig-cert-item">
    <div class="ig-cert-path" title="${escapeHtml(path)}">${escapeHtml(path.split('/').slice(-2).join('/'))}</div>
    <div class="ig-cert-hosts">${hostsList.map(n => `<span class="ig-cert-host">${escapeHtml(n)}</span>`).join('')}</div>
  </div>`).join('');
}

function renderFindingsPanel(findings) {
  if (!findings || !findings.length) return '<div class="empty-field" style="margin:0">Nenhum achado de ingress ativo</div>';
  const sorted = [...findings].sort((a, b) => (b.score || 0) - (a.score || 0));
  return sorted.map(f => {
    const color = sevColor(f.severity);
    const rel = f.related_container;
    const isAgg = Array.isArray(f.targets);
    const targetsAttr = isAgg ? JSON.stringify(f.targets) : '';
    const hostAttr = isAgg ? '' : escapeHtml(f.target || '');
    const targetLabel = isAgg ? `${f.targets.length} hosts` : escapeHtml(f.target || '');
    return `<div class="ig-finding" data-finding-id="${escapeHtml(f.id)}" data-host="${hostAttr}" data-targets="${escapeHtml(targetsAttr)}" style="border-left:3px solid ${color}">
      <button type="button" class="card-open" data-open="${escapeHtml(f.id)}"><span class="sr-only">Abrir achado</span></button>
      <div class="ig-finding-head">
        <span class="ig-finding-sev" style="background:${color}">${sevLabel(f.severity)}</span>
        <span class="ig-finding-score">${f.score}</span>
        <span class="ig-finding-targets" style="margin-left:auto;font-size:.65rem;color:var(--text-mute)">${escapeHtml(targetLabel)}</span>
      </div>
      <div class="ig-finding-title">${escapeHtml(f.title_plain || f.title || f.id)}</div>
      <div class="ig-finding-actions">
        <span class="ig-finding-evidence">${escapeHtml(f.evidence || '')}</span>
        ${rel ? `<a href="#/dossie?c=${encodeURIComponent(rel)}" class="ig-finding-link" title="Ver dossiê do container">→ ${escapeHtml(rel)}</a>` : ''}
      </div>
    </div>`;
  }).join('');
}

function renderRight(hosts, findings) {
  const r = el('igRight');
  if (!r) return;
  r.innerHTML = `<div class="ig-panel">
    <div class="ig-panel-section">
      <h3 class="ig-panel-title">Certificados</h3>
      <div class="ig-cert-list">${renderCerts(hosts)}</div>
    </div>
    <div class="ig-panel-section">
      <h3 class="ig-panel-title">Achados de Ingress</h3>
      <div class="ig-finding-list">${renderFindingsPanel(findings)}</div>
    </div>
  </div>`;
  r.querySelectorAll('.ig-finding .card-open').forEach(botao => {
    const card = botao.closest('.ig-finding');
    botao.addEventListener('click', (e) => {
      if (e.target.closest('.ig-finding-link')) return;
      const targetsRaw = card.dataset.targets;
      let hosts = [];
      if (targetsRaw) {
        try { hosts = JSON.parse(targetsRaw); } catch { hosts = []; }
      } else if (card.dataset.host) {
        hosts = [card.dataset.host];
      }
      _highlightedHosts = hosts;
      const rows = document.querySelectorAll('.ig-row');
      rows.forEach(rw => rw.classList.toggle('ig-highlight', hosts.includes(rw.dataset.host)));
      hosts.forEach(h => {
        try {
          const sel = `.ig-row[data-host="${h.replace(/"/g, '\\"')}"]`;
          const hl = document.querySelector(sel);
          if (hl) hl.scrollIntoView({ block: 'nearest' });
        } catch {}
      });
    });
  });
}

function renderFooter(hosts) {
  const internal = Object.entries(hosts).filter(([, h]) => h.internal);
  const f = el('igFooter');
  if (!f) return;
  if (internal.length) {
    f.innerHTML = `<span style="color:var(--text-mute);font-size:.7rem">${internal.length} bloco interno (healthcheck do gateway)</span>`;
  }
}

async function fetchIngress() {
  if (_disposed) return;
  const [ingRes, findRes] = await Promise.all([
    apiGet('ig_data', '/api/ingress'),
    apiGet('ig_findings', '/api/findings?scope=ingress&status=open'),
  ]);
  if (_disposed) return;
  const hosts = ingRes.data && ingRes.data.hosts;
  const totals = ingRes.data && ingRes.data.totals;
  const findings = findRes.data || [];
  _allHosts = hosts ? Object.entries(hosts) : [];
  _allFindings = findings;
  if (!hosts || ingRes.error) {
    const msg = ingRes.error || 'Erro ao carregar ingress';
    el('igKpis').innerHTML = '<div class="empty-field" style="margin:.5rem 0">Ingress indisponível</div>';
    el('igCenter').innerHTML = '';
    el('igRight').innerHTML = '';
    if (ingRes.error !== 'abortado') showToast(msg, 'error');
    return;
  }
  renderKpis(hosts, totals);
  renderTable(hosts);
  renderRight(hosts, findings);
  renderFooter(hosts);
}

export function renderIngress(container) {
  _disposed = false;
  _highlightedHosts = [];
  const p = new URLSearchParams(location.hash.split('?')[1] || '');
  const hostParam = p.get('host');
  const st = getState();
  if (hostParam) {
    _highlightedHosts = [hostParam];
  }
  if (st.highlightedTargets) {
    _highlightedHosts = st.highlightedTargets;
    setState({ highlightedTargets: null });
  }
  if (p.get('c')) {
    setState({ selectedContainer: p.get('c') });
  }

  container.innerHTML = `<div class="content ingress-layout">
    <div class="ingress-kpis" id="igKpis"><div class="skeleton" style="height:70px"></div></div>
    <div class="ingress-body">
      <div class="ingress-center" id="igCenter"><div class="skeleton" style="height:400px"></div></div>
      <div class="ingress-right" id="igRight"><div class="skeleton" style="height:400px"></div></div>
    </div>
    <div class="ingress-footer" id="igFooter"></div>
  </div>`;

  fetchIngress();
  _pollTimer = setInterval(fetchIngress, POLL_MS);

  function onVis() {
    if (_disposed) return;
    if (!document.hidden) fetchIngress();
  }
  document.addEventListener('visibilitychange', onVis);

  return () => {
    _disposed = true;
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    cancel('ig_data');
    cancel('ig_findings');
    document.removeEventListener('visibilitychange', onVis);
  };
}
