function handleContainerAction(action) {
  const id = selectedContainerId;
  if (!id) return;

  const labels = {
    start: 'Iniciar', stop: 'Parar', restart: 'Reiniciar', remove: 'Remover'
  };
  const label = labels[action] || action;

  if (action === 'remove') {
    const container = allContainers.find(c => c.Id === id);
    const name = container ? (container.Names?.[0] || '').replace(/^\//, '') : shortId(id);
    showConfirmModal({
      title: 'Remover Container',
      message: `Tem certeza que deseja remover <strong>${escapeHtml(name)}</strong>?`,
      confirmText: 'Remover',
      confirmClass: '',
      confirmName: name,
      checkboxLabel: 'Remover volumes associados (-v)',
      checkboxChecked: false
    }).then(async (result) => {
      if (!result.confirmed) return;
      const params = new URLSearchParams();
      if (result.checkbox) params.set('v', 'true');
      params.set('force', 'true');
      await executeAction(id, 'remove', `?${params.toString()}`, 'DELETE');
    });
    return;
  }

  const needConfirm = ['stop', 'restart'];
  if (needConfirm.includes(action)) {
    const container = allContainers.find(c => c.Id === id);
    const name = container ? (container.Names?.[0] || '').replace(/^\//, '') : shortId(id);
    showConfirmModal({
      title: `${label} Container`,
      message: `Deseja ${label.toLowerCase()} o container <strong>${escapeHtml(name)}</strong>?`,
      confirmText: label,
      confirmClass: action === 'stop' ? '' : (action === 'start' ? 'start' : 'restart')
    }).then(async (result) => {
      if (!result.confirmed) return;
      await executeAction(id, action, '', 'POST');
    });
    return;
  }

  executeAction(id, 'start', '', 'POST');
}

function syncUrl() {
  const params = new URLSearchParams();
  if (currentFilter !== 'all') params.set('filter', currentFilter);
  const hash = window.location.hash;
  const newUrl = `${window.location.pathname}${params.toString() ? '?' + params.toString() : ''}${hash}`;
  history.replaceState(null, '', newUrl);
}

document.getElementById('searchInput').addEventListener('input', e => {
  searchTerm = e.target.value;
  renderContainerList();
});

document.querySelectorAll('.filter-pill').forEach(pill => {
  pill.addEventListener('click', () => {
    setFilter(pill.dataset.filter);
    syncUrl();
  });
});

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (btn.tagName === 'A') return;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    window.location.hash = btn.dataset.target;
    document.getElementById(btn.dataset.target)?.scrollIntoView({behavior:'smooth', block:'start'});
  });
});

document.getElementById('mainContent').addEventListener('click', (e) => {
  const btn = e.target.closest('.action-btn');
  if (!btn) return;
  const id = btn.id;
  if (id === 'btnStart') handleContainerAction('start');
  else if (id === 'btnStop') handleContainerAction('stop');
  else if (id === 'btnRestart') handleContainerAction('restart');
  else if (id === 'btnRemove') handleContainerAction('remove');
});

window.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  const filterParam = params.get('filter');
  if (filterParam && ['all','running','exited','unhealthy'].includes(filterParam)) {
    currentFilter = filterParam;
    document.querySelectorAll('.filter-pill').forEach(p =>
      p.classList.toggle('active', p.dataset.filter === filterParam)
    );
  }
  const hash = window.location.hash.replace('#', '');
  if (hash) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    const targetBtn = document.querySelector(`.tab-btn[data-target="${hash}"]`);
    if (targetBtn) targetBtn.classList.add('active');
  }
  fetchContainers();
  setInterval(fetchContainers, 5000);
});
