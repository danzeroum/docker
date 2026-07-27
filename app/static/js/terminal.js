let terminalWs = null;
let terminalInstance = null;

function renderTerminal(containerId) {
  const content = document.getElementById('mainContent');
  content.innerHTML = `
    <div class="section" id="terminal-section">
      <div class="section-head">
        <div class="section-num">10</div>
        <div><h2 class="section-title">Terminal</h2></div>
      </div>
      <div id="terminal-container" style="background:#000;border-radius:8px;padding:0;overflow:hidden;height:400px"></div>
      <div style="margin-top:.5rem;font-size:.75rem;color:var(--text-mute)" id="terminalStatus">Conectando...</div>
    </div>
  `;

  const termContainer = document.getElementById('terminal-container');

  if (typeof Terminal === 'undefined') {
    termContainer.innerHTML = '<div class="empty" style="color:var(--text-dim);padding:2rem">Carregando xterm.js...</div>';
    loadXterm(() => initTerminal(containerId));
  } else {
    initTerminal(containerId);
  }
}

function loadXterm(callback) {
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = 'https://cdn.jsdelivr.net/npm/xterm@5/css/xterm.min.css';
  document.head.appendChild(link);

  const script = document.createElement('script');
  script.src = 'https://cdn.jsdelivr.net/npm/xterm@5/lib/xterm.min.js';
  script.onload = callback;
  document.head.appendChild(script);
}

function initTerminal(containerId) {
  const termContainer = document.getElementById('terminal-container');
  const statusEl = document.getElementById('terminalStatus');

  if (terminalInstance) {
    terminalInstance.dispose();
    terminalInstance = null;
  }

  const term = new Terminal({
    cursorBlink: true,
    cursorStyle: 'block',
    fontSize: 13,
    fontFamily: "'JetBrains Mono', 'Courier New', monospace",
    theme: {
      background: '#0a0a0a',
      foreground: '#e6edf7',
      cursor: '#2496ED',
    },
    cols: 80,
    rows: 24,
  });
  terminalInstance = term;
  term.open(termContainer);

  // Fit terminal to container
  term.element.style.height = '100%';

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/api/containers/${containerId}/terminal`;

  if (terminalWs) terminalWs.close();
  terminalWs = new WebSocket(wsUrl);

  terminalWs.onopen = () => {
    statusEl.textContent = 'Conectado';
    term.focus();
  };

  terminalWs.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === 'stdout') {
        term.write(msg.data);
      } else if (msg.type === 'error') {
        statusEl.textContent = `Erro: ${msg.message}`;
        term.writeln(`\x1b[31mErro: ${msg.message}\x1b[0m`);
      } else if (msg.type === 'exit') {
        statusEl.textContent = `Processo encerrado (código ${msg.code})`;
      } else if (msg.type === 'started') {
        statusEl.textContent = 'Exec iniciado';
      }
    } catch (err) {
      console.error('Terminal message error:', err);
    }
  };

  terminalWs.onclose = () => {
    if (statusEl) statusEl.textContent = 'Desconectado';
  };

  terminalWs.onerror = () => {
    if (statusEl) statusEl.textContent = 'Erro de conexão';
  };

  term.onData((data) => {
    if (terminalWs && terminalWs.readyState === WebSocket.OPEN) {
      terminalWs.send(JSON.stringify({ type: 'stdin', data: data }));
    }
  });
}

function cleanupTerminal() {
  if (terminalWs) {
    terminalWs.close();
    terminalWs = null;
  }
  if (terminalInstance) {
    terminalInstance.dispose();
    terminalInstance = null;
  }
}
