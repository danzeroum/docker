const PALETTE_COMMANDS = [
  { id: 'filter-all', label: 'Filtrar: Todos os containers', icon: '⊞', action: () => setFilter('all') },
  { id: 'filter-running', label: 'Filtrar: Rodando', icon: '▶', action: () => setFilter('running') },
  { id: 'filter-exited', label: 'Filtrar: Parados', icon: '■', action: () => setFilter('exited') },
  { id: 'filter-unhealthy', label: 'Filtrar: Unhealthy', icon: '⚠', action: () => setFilter('unhealthy') },
  { id: 'theme-toggle', label: 'Alternar tema (claro/escuro)', icon: '☀', action: () => {
    applyTheme(!document.documentElement.classList.contains('light'));
  }},
  { id: 'refresh', label: 'Recarregar containers', icon: '↻', action: () => fetchContainers() },
  { id: 'go-host', label: 'Voltar à Visão Geral do Host', icon: '⌂', action: () => {
    selectedContainerId = null;
    document.getElementById('tabNav').style.display = 'none';
    renderGlobalOverview();
    renderContainerList();
  }},
];

function initCommandPalette() {
  const palette = document.createElement('div');
  palette.id = 'commandPalette';
  palette.innerHTML = `
    <div class="palette-overlay" id="paletteOverlay">
      <div class="palette" id="paletteBox">
        <input class="palette-input" id="paletteInput" type="text" placeholder="Digite um comando..." autofocus>
        <div class="palette-list" id="paletteList"></div>
      </div>
    </div>
  `;
  document.body.appendChild(palette);

  const overlay = document.getElementById('paletteOverlay');
  const input = document.getElementById('paletteInput');
  const list = document.getElementById('paletteList');

  let selectedIndex = 0;

  function renderCommands(filter) {
    const term = filter.toLowerCase();
    const filtered = PALETTE_COMMANDS.filter(c => c.label.toLowerCase().includes(term));
    selectedIndex = 0;
    if (filtered.length === 0) {
      list.innerHTML = '<div class="palette-empty">Nenhum comando encontrado</div>';
      return;
    }
    list.innerHTML = filtered.map((c, i) => `
      <div class="palette-item ${i === 0 ? 'active' : ''}" data-id="${c.id}">
        <span class="palette-icon">${c.icon}</span>
        <span class="palette-label">${c.label}</span>
      </div>
    `).join('');
  }

  function executeSelected() {
    const term = input.value.toLowerCase();
    const filtered = PALETTE_COMMANDS.filter(c => c.label.toLowerCase().includes(term));
    if (filtered[selectedIndex]) {
      closePalette();
      filtered[selectedIndex].action();
    }
  }

  function closePalette() {
    overlay.classList.remove('open');
  }

  input.addEventListener('input', () => renderCommands(input.value));

  input.addEventListener('keydown', (e) => {
    const items = list.querySelectorAll('.palette-item');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
      items.forEach((el, i) => el.classList.toggle('active', i === selectedIndex));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      selectedIndex = Math.max(selectedIndex - 1, 0);
      items.forEach((el, i) => el.classList.toggle('active', i === selectedIndex));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      executeSelected();
    } else if (e.key === 'Escape') {
      closePalette();
    }
  });

  list.addEventListener('click', (e) => {
    const item = e.target.closest('.palette-item');
    if (item) {
      const id = item.dataset.id;
      const cmd = PALETTE_COMMANDS.find(c => c.id === id);
      if (cmd) {
        closePalette();
        cmd.action();
      }
    }
  });

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closePalette();
  });

  // Global keyboard shortcut
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K' || e.key === 'p' || e.key === 'P')) {
      e.preventDefault();
      overlay.classList.toggle('open');
      if (overlay.classList.contains('open')) {
        input.value = '';
        renderCommands('');
        input.focus();
      }
    }
  });
}
