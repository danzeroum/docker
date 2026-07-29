import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';

let _disposed = false;

function el(id) { return document.getElementById(id); }

function severityColor(sev) {
  if (sev === 'bad' || sev === 'critical') return 'var(--bad)';
  if (sev === 'warn' || sev === 'high') return 'var(--warn)';
  if (sev === 'medium') return 'var(--accent)';
  return 'var(--text-dim)';
}

function severityBg(sev) {
  const s = sev || 'low';
  if (s === 'critical' || s === 'high') return 'background:linear-gradient(135deg,#fce4ec,#ffebee);border-color:#ef9a9a';
  if (s === 'medium') return 'background:linear-gradient(135deg,#fff3e0,#fff8e1);border-color:#ffe082';
  return 'background:linear-gradient(135deg,#e8f5e9,#f1f8e9);border-color:#c8e6c9';
}

function severityLabel(sev) {
  if (sev === 'critical') return 'Cr\u00edtico';
  if (sev === 'high') return 'Alto';
  if (sev === 'medium') return 'M\u00e9dio';
  return 'Baixo';
}

function statusIcon(st) {
  if (st === 'ok') return '<span style="color:var(--ok);font-size:14px">&#x2713;</span>';
  if (st === 'warn') return '<span style="color:var(--warn);font-size:14px">&#x26A0;</span>';
  return '<span style="color:var(--bad);font-size:14px">&#x2717;</span>';
}

export function renderCapacidade(container) {
  _disposed = false;

  container.innerHTML = `<div class="content">
    <div class="section">
      <div class="section-head"><div><h2 class="section-title">Capacidade</h2></div></div>
      <div id="capBody"><div class="skeleton" style="height:500px"></div></div>
    </div>
  </div>`;

  let pollTimer = null;

  async function fetchData() {
    const { data, error } = await apiGet('cap_data', '/api/capacity');
    if (_disposed) return;
    if (error) {
      const b = el('capBody');
      if (b) b.innerHTML = '<div class="empty">Erro ao carregar dados de capacidade</div>';
      return;
    }
    renderCapBody(data);
    const { data: hist, error: histErr } = await apiGet('cap_history', '/api/metrics/history?series=disk_pct&range=30');
    if (!_disposed && !histErr && hist) {
      renderDiskChart(hist);
    }
  }

  function renderCapBody(d) {
    const b = el('capBody');
    if (!b) return;

    let coletando = '';
    if (d.coletando_desde) {
      const dt = new Date(d.coletando_desde.replace('Z', ''));
      coletando = `Coletando desde ${dt.toLocaleDateString('pt-BR')}`;
    }

    let windowsHtml = (d.windows || []).map(w => {
      const items = (w.items || []).map(i =>
        `<div style="display:flex;align-items:flex-start;gap:8px">
          <span style="width:6px;height:6px;border-radius:50%;background:${severityColor(w.severity)};flex-shrink:0;margin-top:5px"></span>
          <span style="font-size:11px;color:var(--tx2);line-height:1.45">${escapeHtml(i.text)}</span>
        </div>`
      ).join('');
      const itemCount = (w.items || []).length;
      return `<div style="${severityBg(w.severity)};border:1px solid;border-radius:var(--rc);padding:12px 13px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:${itemCount ? '9px' : '0'}">
          <span style="width:8px;height:8px;border-radius:50%;background:${severityColor(w.severity)};flex-shrink:0"></span>
          <span style="font-size:10px;letter-spacing:.14em;text-transform:uppercase;font-weight:700;color:#64748b">${w.label}</span>
        </div>
        ${items || '<div style="font-size:11px;color:var(--text-dim)">Nenhum item</div>'}
      </div>`;
    }).join('');

    let memHtml = (d.memory_by_stack || []).map(c => {
      const pct = c.pct != null ? c.pct : 0;
      const barColor = pct > 80 ? 'var(--bad)' : pct > 60 ? 'var(--warn)' : 'var(--accent)';
      const valor = c.limit_mb ? `${c.used_mb} / ${c.limit_mb} MB` : `${c.used_mb} MB`;
      return `<div style="display:flex;align-items:center;gap:9px">
        <span style="width:112px;flex-shrink:0;font-size:11px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escapeHtml(c.name)}</span>
        <div style="flex:1;height:7px;border-radius:3px;background:var(--bd0);overflow:hidden">
          <div style="width:${Math.min(pct, 100)}%;height:100%;border-radius:3px;background:${barColor}"></div>
        </div>
        <span style="width:80px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--txd)">${valor}</span>
      </div>`;
    }).join('') || '<span style="font-size:11px;color:var(--text-dim)">Nenhum dado de memoria</span>';

    let posturaHtml = (d.postura || []).map(p =>
      `<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--bd0)">
        ${statusIcon(p.status)}
        <span style="flex:1;min-width:0;font-size:11px">${escapeHtml(p.item)}</span>
        <span style="font-size:10.5px;font-weight:500;color:${severityColor(p.status)}">${escapeHtml(p.valor)}</span>
      </div>`
    ).join('') || '<span style="font-size:11px;color:var(--text-dim)">Nenhum dado</span>';

    b.innerHTML = `<div style="display:flex;flex-direction:column;gap:11px">
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:11px;flex-shrink:0">${windowsHtml}</div>
      <div style="flex:1;min-height:0;display:grid;grid-template-columns:1fr 372px;gap:11px">
        <div style="display:flex;flex-direction:column;gap:11px;min-height:0">
          <div id="capDiskChart" style="flex:1;min-height:100px;background:var(--sf);border:1px solid var(--bd1);border-radius:var(--rc);padding:12px 13px;display:flex;flex-direction:column">
            <div style="font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700" id="capChartTitle">Disco (30 dias)</div>
            <div id="capChartBody" style="flex:1;min-height:0;display:flex;align-items:flex-end;gap:3px;margin:12px 0 8px"></div>
            <div id="capChartNote" style="font-size:11px;color:var(--tx2);line-height:1.5;border-top:1px solid var(--bd0);padding-top:8px">${coletando}</div>
          </div>
          <div style="flex:1;min-height:0;background:var(--sf);border:1px solid var(--bd1);border-radius:var(--rc);padding:12px 13px;display:flex;flex-direction:column">
            <div style="font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700;margin-bottom:9px">Mem\u00f3ria por stack</div>
            <div style="flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:6px">${memHtml}</div>
            <div style="font-size:10.5px;color:#64748b;line-height:1.45;margin-top:8px;border-top:1px solid var(--bd0);padding-top:8px">Consumo atual dos containers em cada projeto</div>
          </div>
        </div>
        <div style="display:flex;flex-direction:column;gap:11px;min-height:0">
          <div style="background:var(--sf);border:1px solid var(--bd1);border-radius:var(--rc);padding:12px 13px">
            <div style="font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700;margin-bottom:10px">Postura de seguran\u00e7a e opera\u00e7\u00e3o</div>
            <div style="max-height:300px;overflow-y:auto">${posturaHtml}</div>
          </div>
        </div>
      </div>
      <div style="flex-shrink:0;font-size:9.5px;color:#64748b;line-height:1.4">${coletando ? coletando + ' &mdash; ' : ''}Gerado em ${new Date().toLocaleString('pt-BR')}</div>
    </div>`;
  }

  function renderDiskChart(hist) {
    const body = el('capChartBody');
    const note = el('capChartNote');
    if (!body) return;

    const proj = hist.projection;
    const pts = hist.series || [];

    let noteText = '';
    if (proj && proj.stable) {
      const d80 = proj.days_to_80, d90 = proj.days_to_90;
      const parts = [];
      if (d80 != null) parts.push(`80% em ~${d80}d`);
      if (d90 != null) parts.push(`90% em ~${d90}d`);
      parts.push(`r\u00B2=${proj.r2}`);
      noteText = `Proje\u00E7\u00E3o: ${parts.join(', ')} (${proj.slope_per_day > 0 ? 'subindo' : 'descendo'} ${Math.abs(proj.slope_per_day).toFixed(2)}%/dia)`;
    } else if (proj && !proj.stable) {
      noteText = `Tend\u00EAncia inst\u00E1vel (r\u00B2=${proj.r2.toFixed(2)} < 0,7) \u2014 dados insuficientes para projetar`;
    } else if (hist.coletando_desde) {
      const dt = new Date(hist.coletando_desde.replace('Z', ''));
      noteText = `Coletando desde ${dt.toLocaleDateString('pt-BR')} \u2014 s\u00E9rie curta para proje\u00E7\u00E3o (< 7 dias)`;
    }

    if (note) note.innerHTML = noteText;

    const vals = pts.map(p => p.v);
    const maxV = Math.max(...vals, 10);
    const limit = 90;

    const days = pts.slice(-30);
    const showProj = proj && proj.stable;
    const projBars = showProj ? 10 : 0;
    const totalBars = days.length + projBars;

    if (!days.length) {
      body.innerHTML = '<div style="font-size:11px;color:var(--text-dim);align-self:center;margin:auto">Aguardando coleta de dados</div>';
      return;
    }

    body.style.gap = projBars > 0 ? '3px' : '2px';
    body.innerHTML = days.map((p, i) => {
      const pct = (p.v / limit) * 100;
      const h = Math.max(4, (pct / 100) * 120);
      const color = p.v > 80 ? 'var(--bad)' : p.v > 60 ? 'var(--warn)' : 'var(--accent)';
      return `<div style="flex:1;height:130px;display:flex;align-items:flex-end;position:relative" title="${p.ts}: ${p.v.toFixed(1)}%">
        <div style="width:100%;height:${h.toFixed(0)}px;border-radius:2px 2px 0 0;background:${color};min-height:2px;transition:height .3s"></div>
      </div>`;
    }).join('') + (showProj ? projBarsLayout(proj, days) : '');
  }

  function projBarsLayout(proj, days) {
    const lastV = days.length ? days[days.length - 1].v : 50;
    const s = proj.slope_per_day;
    const i = proj.intercept;
    let html = '';
    for (let x = 1; x <= 10; x++) {
      const v = i + s * (days.length - 1 + x);
      const h = Math.max(4, (Math.min(v, 100) / 90) * 120);
      const reached90 = v >= 90;
      const color = reached90 ? 'var(--bad)' : 'var(--text-dim)';
      const label = reached90 ? '!' : '';
      html += `<div style="flex:1;height:130px;display:flex;align-items:flex-end;position:relative" title="Proj ${x}d: ${v.toFixed(1)}%">
        <div style="width:100%;height:${h.toFixed(0)}px;border-radius:2px 2px 0 0;background:${color};min-height:2px;opacity:0.5">${label}</div>
      </div>`;
    }
    return html;
  }

  fetchData();
  pollTimer = setInterval(fetchData, 30000);

  return () => {
    _disposed = true;
    if (pollTimer) clearInterval(pollTimer);
  };
}
