import { apiGet, cancel } from '../data.js';
import { escapeHtml, fmtDate } from '../fmt.js';
import { showToast } from '../notifications.js';
import { navigate } from '../main.js';
import { getState } from '../store.js';

let _disposed = false;

function el(id) { return document.getElementById(id); }

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

export function renderAttention(container) {
  _disposed = false;

  container.innerHTML = `<div class="content">
    <div class="section">
      <div class="section-head"><div><h2 class="section-title">Aten\u00e7\u00e3o</h2></div></div>
      <div id="atnFilters" style="display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap">
        <button class="filter-pill active" data-sev="all">Todos</button>
        <button class="filter-pill" data-sev="critical" style="border-color:var(--bad)">Cr\u00edtico</button>
        <button class="filter-pill" data-sev="high" style="border-color:var(--warn)">Alto</button>
        <button class="filter-pill" data-sev="medium" style="border-color:var(--accent)">M\u00e9dio</button>
      </div>
      <div id="atnList"><div class="skeleton" style="height:400px"></div></div>
    </div>
  </div>`;

  let pollTimer = null;
  let currentSev = 'all';

  async function fetchFindings() {
    const { data, error } = await apiGet('atn_data', '/api/findings?status=open');
    if (_disposed) return;
    if (error) {
      const l = el('atnList');
      if (l) l.innerHTML = '<div class="empty">Erro ao carregar achados</div>';
      return;
    }
    if (!data) return;

    const filtered = currentSev === 'all' ? data : data.filter(f => f.severity === currentSev);
    const list = el('atnList');
    if (!list) return;

    if (!filtered.length) {
      list.innerHTML = '<div class="empty" style="padding:2rem">Nenhum achado ativo</div>';
      return;
    }

    const depth = getState().depth || 'dado';

    list.innerHTML = filtered.map(f => {
      const color = severityColor(f.severity);
      const showPlain = depth === 'informacao' || depth === 'conhecimento';
      const title = showPlain && f.title_plain ? f.title_plain : f.title;
      const interp = showPlain && f.interpretation_plain ? f.interpretation_plain : (f.interpretation || '');
      const age = f.first_seen ? Math.round((Date.now() - new Date(f.first_seen).getTime()) / 1000) : 0;
      const ago = age < 60 ? `h\u00e1 ${age}s` : age < 3600 ? `h\u00e1 ${Math.floor(age / 60)}min` : `h\u00e1 ${Math.floor(age / 3600)}h`;
      const duration = f.first_seen && f.last_seen ? Math.round((new Date(f.last_seen).getTime() - new Date(f.first_seen).getTime()) / 1000) : 0;
      const durStr = duration > 60 ? `${Math.floor(duration / 60)}min` : duration > 0 ? `${duration}s` : '';
      return `<div class="atn-card" data-id="${escapeHtml(f.id)}" style="border-left:3px solid ${color}">
        <div class="atn-head">
          <span class="atn-sev" style="background:${color};color:#fff">${severityLabel(f.severity)}</span>
          <span class="atn-score">${f.score}</span>
          <span class="atn-target">${escapeHtml(f.target)}</span>
          ${durStr ? `<span class="atn-occs">${durStr}</span>` : ''}
          <span class="atn-ago">${ago}</span>
        </div>
        <div class="atn-title">${escapeHtml(title)}</div>
        ${interp ? `<div class="atn-interp">${escapeHtml(interp)}</div>` : ''}
        ${f.recommendation ? `<div class="atn-reco">${escapeHtml(f.recommendation)}</div>` : ''}
      </div>`;
    }).join('');

    list.querySelectorAll('.atn-card').forEach(card => {
      card.addEventListener('click', () => {
        setState({ selectedFinding: card.dataset.id });
        navigate('#/incidente');
      });
    });
  }

  fetchFindings();
  pollTimer = setInterval(fetchFindings, 10000);

  el('atnFilters')?.addEventListener('click', (e) => {
    const btn = e.target.closest('.filter-pill');
    if (!btn) return;
    currentSev = btn.dataset.sev;
    el('atnFilters').querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    fetchFindings();
  });

  document.addEventListener('visibilitychange', onVis);

  function onVis() {
    if (_disposed) return;
    if (document.hidden) {
      clearInterval(pollTimer);
      pollTimer = null;
    } else {
      fetchFindings();
      pollTimer = setInterval(fetchFindings, 10000);
    }
  }

  return () => {
    _disposed = true;
    if (pollTimer) clearInterval(pollTimer);
    cancel('atn_data');
    document.removeEventListener('visibilitychange', onVis);
  };
}
