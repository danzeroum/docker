import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';

let _disposed = false;

function el(id) { return document.getElementById(id); }

export function renderBackend(container) {
  _disposed = false;

  container.innerHTML = `<div class="content">
    <div class="section">
      <div class="section-head"><div><h2 class="section-title">Backend &amp; API</h2></div></div>
      <div id="beBody"><div class="skeleton" style="height:400px"></div></div>
    </div>
  </div>`;

  let pollTimer = null;

  async function fetchData() {
    const { data, error } = await apiGet('be_data', '/api/backend');
    if (_disposed) return;
    if (error) {
      const b = el('beBody');
      if (b) b.innerHTML = '<div class="empty">Erro ao carregar dados do backend</div>';
      return;
    }
    renderBody(data);
  }

  function renderBody(d) {
    const b = el('beBody');
    if (!b) return;

    const telemetry = d.telemetry || [];
    const findings = d.findings || {};

    let teleRows = telemetry.length ? telemetry.map(r => {
      const bar = Math.min(r.p95_ms / 200, 1) * 100;
      const errColor = r.error_rate > 10 ? 'var(--bad)' : r.error_rate > 2 ? 'var(--warn)' : 'var(--ok)';
      return `<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--bd0);font-size:11px">
        <span style="flex:1;min-width:0;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escapeHtml(r.route)}</span>
        <span style="width:50px;text-align:right;font-family:monospace">${r.total}</span>
        <div style="width:60px;height:6px;border-radius:3px;background:var(--bd0);overflow:hidden">
          <div style="width:${bar}%;height:100%;border-radius:3px;background:var(--accent)"></div>
        </div>
        <span style="width:45px;text-align:right;font-family:monospace;color:var(--txd)">${r.p95_ms}ms</span>
        <span style="width:45px;text-align:right;font-family:monospace;color:${errColor}">${r.error_rate}%</span>
        <span style="width:45px;text-align:right;font-family:monospace;color:var(--txd)">${r.dur_max_ms}ms</span>
      </div>`;
    }).join('') : '<div style="font-size:11px;color:var(--text-dim);padding:12px">Aguardando dados de telemetria (coleta a cada 1h)</div>';

    let findingsHtml = '';
    if (findings.by_rule) {
      findingsHtml = Object.entries(findings.by_rule).map(([rule, count]) =>
        `<div style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:11px">
          <span style="flex:1">${escapeHtml(rule)}</span>
          <span style="font-family:monospace;color:var(--txd)">${count}</span>
        </div>`
      ).join('');
    }

    b.innerHTML = `<div style="display:flex;flex-direction:column;gap:11px">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:11px">
        <div style="background:var(--sf);border:1px solid var(--bd1);border-radius:var(--rc);padding:12px 13px">
          <div style="font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700;margin-bottom:9px">Telemetria (${telemetry.length} rotas &mdash; &uacute;ltima hora)</div>
          <div style="display:flex;align-items:center;gap:8px;padding:4px 0 8px;font-size:9.5px;color:var(--text-dim);border-bottom:1px solid var(--bd0);margin-bottom:4px">
            <span style="flex:1">Rota</span>
            <span style="width:50px;text-align:right">Req</span>
            <span style="width:60px"></span>
            <span style="width:45px;text-align:right">p95</span>
            <span style="width:45px;text-align:right">Err</span>
            <span style="width:45px;text-align:right">Max</span>
          </div>
          <div style="max-height:300px;overflow-y:auto">${teleRows}</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:11px">
          <div style="background:var(--sf);border:1px solid var(--bd1);border-radius:var(--rc);padding:12px 13px">
            <div style="font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700;margin-bottom:8px">Achados abertos</div>
            <div style="font-size:28px;font-weight:700;color:${findings.open > 0 ? 'var(--bad)' : 'var(--ok)'}">${findings.open || 0}</div>
            <div style="margin-top:8px;border-top:1px solid var(--bd0);padding-top:6px">${findingsHtml}</div>
          </div>
          <div style="background:var(--sf);border:1px solid var(--bd1);border-radius:var(--rc);padding:12px 13px">
            <div style="font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700;margin-bottom:8px">Eventos do daemon</div>
            <div id="beEventStatus" style="font-size:12px;color:var(--ok)">Conectado via SSE</div>
            <div id="beEventLast" style="font-size:10.5px;color:var(--text-dim);margin-top:4px"></div>
          </div>
        </div>
      </div>
      <div style="flex-shrink:0;font-size:9.5px;color:#64748b;line-height:1.4">Gerado em ${new Date().toLocaleString('pt-BR')}</div>
    </div>`;
  }

  fetchData();
  pollTimer = setInterval(fetchData, 30000);

  return () => {
    _disposed = true;
    if (pollTimer) clearInterval(pollTimer);
  };
}
