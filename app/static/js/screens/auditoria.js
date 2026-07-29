import { apiGet } from '../data.js';
import { escapeHtml, fmtDate } from '../fmt.js';

let _disposed = false;
let _pollTimer = null;

export function renderAuditoria(container) {
  _disposed = false;

  container.innerHTML = `<div class="content">
    <div class="section">
      <div class="section-head"><div><h2 class="section-title">Auditoria</h2></div></div>
      <div id="auditList"><div class="skeleton" style="height:400px"></div></div>
    </div>
  </div>`;

  async function load() {
    if (_disposed) return;
    const { data, error } = await apiGet('audit', '/api/audit?limit=200');
    if (_disposed) return;
    if (error) {
      const el = document.getElementById('auditList');
      if (el) el.innerHTML = '<div class="empty">Erro ao carregar auditoria</div>';
      return;
    }
    const el = document.getElementById('auditList');
    if (!el || !data) return;

    if (!data.length) {
      el.innerHTML = '<div class="empty">Nenhuma entrada de auditoria</div>';
      return;
    }

    el.innerHTML = `<div class="table-wrap"><table><thead><tr>
      <th>Data</th><th>Ação</th><th>Alvo</th><th>Resultado</th><th>IP</th>
    </tr></thead><tbody>
      ${data.map(e => {
        const is403 = e.result && e.result.includes('403');
        const isError = e.result && e.result !== 'success' && !is403;
        return `<tr${is403 ? ' style="background:var(--bad-soft)"' : isError ? ' style="background:var(--warn-soft)"' : ''}>
          <td style="white-space:nowrap;font-family:JetBrains Mono;font-size:.7rem">${escapeHtml(fmtDate(e.created_at))}</td>
          <td><span class="pill-action">${escapeHtml(e.action)}</span></td>
          <td><strong>${escapeHtml(e.project)}</strong></td>
          <td style="font-family:JetBrains Mono;font-size:.75rem">${escapeHtml(e.result)}</td>
          <td style="font-family:JetBrains Mono;font-size:.75rem;color:var(--text-dim)">${escapeHtml(e.ip)}</td>
        </tr>`;
      }).join('')}
    </tbody></table></div>`;
  }

  load();
  _pollTimer = setInterval(load, 15000);

  document.addEventListener('visibilitychange', onVis);

  function onVis() {
    if (_disposed) return;
    if (document.hidden) {
      if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    } else {
      load();
      _pollTimer = setInterval(load, 15000);
    }
  }

  return () => {
    _disposed = true;
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    document.removeEventListener('visibilitychange', onVis);
  };
}
