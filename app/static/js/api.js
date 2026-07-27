async function fetchContainers() {
  try {
    const res = await fetch('/api/containers');
    if (!res.ok) throw new Error('API Error');
    allContainers = await res.json();
    renderContainerList();
    renderGlobalOverview();
  } catch (err) {
    document.getElementById('containerList').innerHTML =
      '<div class="empty">Erro ao conectar</div>';
    document.getElementById('mainContent').innerHTML =
      '<div class="empty">Erro ao carregar containers</div>';
  }
}

async function fetchSystemInfo() {
  try {
    const res = await fetch('/api/system');
    if (!res.ok) throw new Error('API Error');
    const sys = await res.json();
    renderSystemInfo(sys);
  } catch (err) {
    console.error('Erro ao buscar info do sistema:', err);
    ['sysCpu','sysMem','sysSwap','sysDisk','sysLoad','sysUptime'].forEach(id => {
      document.getElementById(id).textContent = '—';
    });
    ['sysCpuSub','sysMemSub','sysSwapSub','sysDiskSub','sysLoadSub','sysUptimeSub'].forEach(id => {
      document.getElementById(id).textContent = 'indisponível';
    });
  }
}

async function fetchContainerDetail(id) {
  try {
    const res = await fetch(`/api/containers/${id}/json`);
    if (!res.ok) throw new Error('API Error');
    const data = await res.json();
    renderContainerDetail(parseInspect(data), data);
    const labBtn = document.getElementById('openLabBtn');
    if (labBtn) {
      labBtn.href = `/static/inspect-educativo.html?id=${encodeURIComponent(id)}`;
    }
  } catch (err) {
    console.error(err);
    document.getElementById('mainContent').innerHTML =
      '<div class="empty">Erro ao carregar detalhe do container.</div>';
  }
}

async function executeAction(id, action, queryString, method) {
  const btnId = `btn${action.charAt(0).toUpperCase() + action.slice(1)}`;
  const btn = document.getElementById(btnId);
  if (btn) btn.disabled = true;
  const path = action === 'remove'
    ? `/api/containers/${id}${queryString}`
    : `/api/containers/${id}/${action}${queryString}`;
  try {
    const res = await fetch(path, { method });
    if (!res.ok) {
      let detail = '';
      try { const j = await res.json(); detail = j.detail || ''; } catch {}
      throw new Error(detail || `HTTP ${res.status}`);
    }
    showToast(`Container ${action} com sucesso!`, 'success');
    fetchContainers();
    if (selectedContainerId === id) fetchContainerDetail(id);
  } catch (err) {
    showToast(`Erro ao ${action}: ${err.message}`, 'error');
    if (btn) btn.disabled = false;
  }
}
