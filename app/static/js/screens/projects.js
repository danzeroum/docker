import { apiGet, apiPost } from '../data.js';
import { escapeHtml, fmtDuration } from '../fmt.js';
import { showToast, showConfirmModal, showUnlockModal } from '../notifications.js';
import { getState, setState } from '../store.js';

export function renderProjects(container) {
  let pollTimer = null;
  const ac = new AbortController();

  function render(data) {
    const projects = data?.projects || [];
    if (!projects.length) {
      container.innerHTML = `<div class="content"><div class="section"><div class="empty">Nenhum projeto docker-compose encontrado em /opt/btv.</div></div></div>`;
      return;
    }
    let html = `<div class="content"><div class="section"><div class="section-head"><div><h2 class="section-title">Projetos</h2></div></div>
      <div class="project-grid">`;
    for (const p of projects) {
      const st = p.status || 'unknown';
      const stCls = st === 'running' ? 'ok' : st === 'partial' ? 'warn' : st === 'stopped' ? 'mute' : 'bad';
      const stLabel = st === 'running' ? 'Rodando' : st === 'partial' ? `Parcial (${p.running}/${p.total})` : st === 'stopped' ? 'Parado' : 'Erro';
      const canStart = st !== 'running' && st !== 'error';
      const canStop = st !== 'stopped' && st !== 'unknown';

      let svcHtml = '';
      if (p.services && p.services.length) {
        svcHtml = `<div class="table-wrap" style="margin-top:.75rem"><table><thead><tr><th>Serviço</th><th>Estado</th><th>Portas</th></tr></thead><tbody>`;
        for (const s of p.services) {
          const sName = s.Name || s.Service || '?';
          const sState = s.State || '?';
          const sPorts = s.Publishers || [];
          const portsStr = sPorts.length ? sPorts.map(pp => `${pp.PublishedPort||'?'}->${pp.TargetPort||'?'}`).join(', ') : '';
          svcHtml += `<tr>
            <td><strong>${escapeHtml(sName)}</strong></td>
            <td><span class="status-pill ${sState === 'running' ? 'running' : 'exited'}"><span class="dot"></span>${sState}</span></td>
            <td style="font-family:'JetBrains Mono',monospace;font-size:.75rem">${escapeHtml(portsStr) || '—'}</td>
          </tr>`;
        }
        svcHtml += `</tbody></table></div>`;
      }

      html += `<div class="project-card" data-name="${escapeHtml(p.name)}">
        <div class="project-head">
          <div>
            <div class="project-name">${escapeHtml(p.name)}</div>
            <div class="project-path" style="font-size:.7rem;color:var(--text-mute);font-family:'JetBrains Mono',monospace">${escapeHtml(p.path)}</div>
          </div>
          <div class="status-pill ${stCls}" style="margin-left:auto"><span class="dot"></span>${stLabel}</div>
        </div>
        ${svcHtml}
        <div class="action-bar" style="margin-top:.75rem;gap:.5rem">
          <button class="action-btn start" data-action="start" ${!canStart?'disabled':''}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> Iniciar</button>
          <button class="action-btn stop" data-action="stop" ${!canStop?'disabled':''}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="12" height="16"/></svg> Parar</button>
        </div>
      </div>`;
    }
    html += `</div></div></div>`;
    container.innerHTML = html;

    container.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const card = btn.closest('.project-card');
        const name = card.dataset.name;
        const action = btn.dataset.action;
        const ep = action === 'start' ? 'start' : 'stop';
        const label = action === 'start' ? 'Iniciar' : 'Parar';
        if (action === 'stop') {
          const r = await showConfirmModal({
            title: `${label} projeto`,
            message: `Tem certeza?`,
            confirmText: label,
            confirmClass: action === 'stop' ? 'remove' : '',
          });
          if (!r.confirmed) return;
        }
        btn.disabled = true;
        let { error, data } = await apiPost(`project-${ep}`, `/api/projects/${name}/${ep}`);
        if (error && (error.includes('403') || error.includes('Unlock') || error.includes('ausente') || error.includes('invalido'))) {
          if (!getState().unlock?.token) {
            const token = await showUnlockModal();
            if (!token) { btn.disabled = false; return; }
          }
          btn.disabled = false;
          const retryRes = await apiPost(`project-${ep}-retry`, `/api/projects/${name}/${ep}`);
          if (retryRes.error) { showToast(retryRes.error, 'error'); return; }
          showToast(`${label}do projeto ${name}`, 'success');
          load();
          return;
        }
        if (error) {
          showToast(error, 'error');
          btn.disabled = false;
          return;
        }
        showToast(`${label}do projeto ${name}`, 'success');
        load();
      });
    });
  }

  async function load() {
    const { data, error } = await apiGet('projects', '/api/projects');
    if (error) {
      if (error !== 'abortado') showToast(error, 'error');
      return;
    }
    render(data);
  }

  load();
  pollTimer = setInterval(load, 10000);

  return () => {
    ac.abort();
    if (pollTimer) clearInterval(pollTimer);
  };
}
