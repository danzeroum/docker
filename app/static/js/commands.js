export function initCommandPalette(extraCommands = []) {
  const commands = [
    { id: 'go-overview', label: 'Visão Geral', icon: '⌂', action: () => { location.hash = '#/overview'; } },
    { id: 'go-dossie', label: 'Dossiê do Container', icon: '⊞', action: () => { location.hash = '#/dossie'; } },
    { id: 'go-logs', label: 'Logs', icon: '☰', action: () => { location.hash = '#/logs'; } },
    ...extraCommands,
  ];

  const palette = document.createElement('div');
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
    const filtered = commands.filter(c => c.label.toLowerCase().includes(term));
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
    const filtered = commands.filter(c => c.label.toLowerCase().includes(term));
    if (filtered[selectedIndex]) {
      closePalette();
      filtered[selectedIndex].action();
    }
  }

  function closePalette() { overlay.classList.remove('open'); }

  input.addEventListener('input', () => renderCommands(input.value));
  input.addEventListener('keydown', (e) => {
    const items = list.querySelectorAll('.palette-item');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectedIndex = Math.min(selectedIndex + 1, Math.max(items.length - 1, 0));
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
      const cmd = commands.find(c => c.id === item.dataset.id);
      if (cmd) { closePalette(); cmd.action(); }
    }
  });
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closePalette();
  });
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
