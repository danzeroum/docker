import { getState, setState } from './store.js';
import { assinar, TICK_MS } from './kernel/relogio.js';

export function initCommandPalette(extraCommands = []) {
  const commands = [
    { id: 'go-overview', label: 'Visão Geral', icon: '⌂', action: () => { location.hash = '#/overview'; } },
    { id: 'go-dossie', label: 'Dossiê do Container', icon: '⊞', action: () => { location.hash = '#/dossie'; } },
    { id: 'go-logs', label: 'Logs', icon: '≡', action: () => { location.hash = '#/logs'; } },
    { id: 'go-incidente', label: 'Incidente / Atenção', icon: '⚠', action: () => { location.hash = '#/incidente'; } },
    { id: 'go-ingress', label: 'Ingress & TLS', icon: '↑', action: () => { location.hash = '#/ingress'; } },
    { id: 'go-capacidade', label: 'Capacidade', icon: '△', action: () => { location.hash = '#/capacidade'; } },
    { id: 'go-projetos', label: 'Projetos', icon: '▶', action: () => { location.hash = '#/projetos'; } },
    { id: 'go-auditoria', label: 'Auditoria', icon: '⚑', action: () => { location.hash = '#/auditoria'; } },
    { id: 'go-backend', label: 'Backend & API', icon: '⚙', action: () => { location.hash = '#/backend'; } },
    ...extraCommands,
  ];

  let searchData = { hosts: [], findings: [], projects: [] };
  let loaded = false;

  async function fetchSearchData() {
    try {
      const [iRes, fRes, pRes] = await Promise.all([
        fetch('/api/ingress/hosts'),
        fetch('/api/findings?status=open'),
        fetch('/api/projects'),
      ]);
      const hosts = iRes.ok ? (await iRes.json()).hosts || [] : [];
      const findings = fRes.ok ? (await fRes.json()).slice(0, 20) : [];
      const projects = pRes.ok ? (await pRes.json()).projects || [] : [];
      searchData = { hosts, findings, projects };
      loaded = true;
    } catch (_) {}
  }

  fetchSearchData();
  // 60s = 12 ticks. Era o sexto `setInterval` do cockpit, e o unico que nunca
  // pausava com a aba oculta: a paleta recarregava tres fontes a cada minuto
  // para uma aba que ninguem estava olhando.
  assinar(fetchSearchData, 12 * TICK_MS);

  function containerName(c) {
    return (c.Names && c.Names[0] || c.name || '').replace(/^\//, '');
  }

  function allSearchableItems(filter) {
    const t = filter.toLowerCase();
    const items = [];

    const containers = getState().containers || [];
    for (const c of containers) {
      const name = containerName(c);
      if (!name || !name.toLowerCase().includes(t)) continue;
      const safeName = encodeURIComponent(name);
      items.push({ id: 'c-' + (c.Id || c.id || name), icon: '▣', label: name, action: () => { location.hash = '#/dossie?c=' + safeName; } });
    }

    for (const h of searchData.hosts) {
      const name = h.server_name || h.name || '';
      if (!name.toLowerCase().includes(t)) continue;
      items.push({ id: 'h-' + name, icon: '↑', label: '[ingress] ' + name, action: () => { location.hash = '#/ingress?host=' + encodeURIComponent(name); } });
    }

    for (const f of searchData.findings) {
      const label = (f.rule || '') + ' - ' + (f.target || '');
      if (!label.toLowerCase().includes(t)) continue;
      const action = () => {
        if (f.scope === 'ingress' && f.targets && f.targets.length) {
          setState({ highlightedTargets: f.targets });
          location.hash = '#/ingress';
        } else {
          location.hash = '#/incidente?f=' + encodeURIComponent(f.id);
        }
      };
      items.push({ id: 'f-' + f.id, icon: '⚠', label: '[achado] ' + label, action });
    }

    for (const p of searchData.projects) {
      const name = p.name || '';
      if (!name.toLowerCase().includes(t)) continue;
      items.push({ id: 'p-' + name, icon: '▶', label: '[projeto] ' + name, action: () => { location.hash = '#/projetos'; } });
    }

    return items;
  }

  const palette = document.createElement('div');
  palette.innerHTML = `
    <div class="palette-overlay" id="paletteOverlay">
      <div class="palette" id="paletteBox">
        <input class="palette-input" id="paletteInput" type="text" placeholder="Digite um comando ou busque..." autofocus>
        <div class="palette-list" id="paletteList" role="listbox" aria-label="Resultados"></div>
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
    const navCommands = commands.filter(c => c.label.toLowerCase().includes(term));
    const searchItems = term.length >= 2 ? allSearchableItems(term) : [];
    const all = [...navCommands, ...searchItems];
    selectedIndex = 0;

    if (all.length === 0) {
      if (term.length >= 2 && !loaded) {
        list.innerHTML = '<div class="palette-empty">carregando fontes…</div>';
      } else {
        list.innerHTML = '<div class="palette-empty">Nenhum resultado</div>';
      }
      return;
    }

    list.innerHTML = all.map((c, i) => {
      const isSearch = !!c.id && (c.id.startsWith('c-') || c.id.startsWith('h-') || c.id.startsWith('f-') || c.id.startsWith('p-'));
      const icon = c.icon || '○';
      // tabindex="-1" de proposito: numa paleta quem navega e a seta, com o
      // foco parado no campo de busca. Tab passeando por 50 resultados seria
      // pior que a div de antes. Continua <button type="button">, entao Enter e clique
      // acionam o mesmo caminho.
      return `<button type="button" role="option" tabindex="-1" aria-selected="${i === 0}" class="palette-item ${i === 0 ? 'active' : ''}" data-idx="${i}">
        <span class="palette-icon">${icon}</span>
        <span class="palette-label${isSearch ? ' palette-search' : ''}">${c.label}</span>
      </button>`;
    }).join('');
  }

  function executeSelected() {
    const term = input.value.toLowerCase();
    const navCommands = commands.filter(c => c.label.toLowerCase().includes(term));
    const searchItems = term.length >= 2 ? allSearchableItems(term) : [];
    const all = [...navCommands, ...searchItems];
    if (all[selectedIndex]) {
      closePalette();
      all[selectedIndex].action();
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
      const idx = parseInt(item.dataset.idx, 10);
      const term = input.value.toLowerCase();
      const navCommands = commands.filter(c => c.label.toLowerCase().includes(term));
      const searchItems = term.length >= 2 ? allSearchableItems(term) : [];
      const all = [...navCommands, ...searchItems];
      if (all[idx]) { closePalette(); all[idx].action(); }
    }
  });
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closePalette();
  });
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
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
