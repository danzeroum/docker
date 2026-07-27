let logsEventSource = null;
let logsPaused = false;
let logsAutoScroll = true;

function renderLogsViewer(containerId) {
  const content = document.getElementById('mainContent');
  content.innerHTML = `
    <div class="section" id="logs">
      <div class="section-head">
        <div class="section-num">08</div>
        <div><h2 class="section-title">Logs</h2></div>
      </div>
      <div style="display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1rem">
        <input type="text" id="logsFilter" class="search-input" style="flex:1;min-width:150px" placeholder="Filtrar logs...">
        <button class="action-btn" id="logsPauseBtn" style="background:var(--accent);color:#fff">Pausar</button>
        <button class="action-btn" id="logsDownloadBtn" style="background:var(--neutral);color:#fff">Download</button>
      </div>
      <div id="logsContainer" style="background:var(--bg-2);border:1px solid var(--border);border-radius:10px;padding:.75rem;height:400px;overflow-y:auto;font-family:'JetBrains Mono',monospace;font-size:.75rem;line-height:1.6">
        <div class="empty">Aguardando logs...</div>
      </div>
    </div>
  `;

  const logsContainer = document.getElementById('logsContainer');

  function appendLog(stream, text) {
    if (logsPaused) return;
    const filter = document.getElementById('logsFilter')?.value?.toLowerCase();
    if (filter && !text.toLowerCase().includes(filter)) return;

    if (logsContainer.querySelector('.empty')) {
      logsContainer.innerHTML = '';
    }

    const line = document.createElement('div');
    line.className = `log-line ${stream}`;
    line.textContent = text;
    if (stream === 'stderr') {
      line.style.color = '#fca5a5';
    }
    logsContainer.appendChild(line);

    if (logsAutoScroll) {
      logsContainer.scrollTop = logsContainer.scrollHeight;
    }
  }

  // Close previous connection
  if (logsEventSource) {
    logsEventSource.close();
  }

  logsEventSource = new EventSource(`/api/containers/${containerId}/logs/stream?tail=100`);
  logsEventSource.addEventListener('stdout', (e) => appendLog('stdout', e.data));
  logsEventSource.addEventListener('stderr', (e) => appendLog('stderr', e.data));
  logsEventSource.addEventListener('error', () => {
    if (logsContainer.querySelector('.empty')) {
      logsContainer.innerHTML = '';
    }
    const line = document.createElement('div');
    line.style.color = 'var(--text-mute)';
    line.textContent = '[conexão encerrada]';
    logsContainer.appendChild(line);
  });

  // Pause/resume
  const pauseBtn = document.getElementById('logsPauseBtn');
  pauseBtn.addEventListener('click', () => {
    logsPaused = !logsPaused;
    pauseBtn.textContent = logsPaused ? 'Continuar' : 'Pausar';
    pauseBtn.style.background = logsPaused ? 'var(--warn)' : 'var(--accent)';
    if (!logsPaused) logsAutoScroll = true;
  });

  // Auto-scroll on user scroll
  logsContainer.addEventListener('scroll', () => {
    const threshold = 30;
    logsAutoScroll = (logsContainer.scrollHeight - logsContainer.scrollTop - logsContainer.clientHeight) < threshold;
  });

  // Download
  document.getElementById('logsDownloadBtn').addEventListener('click', () => {
    const lines = logsContainer.querySelectorAll('.log-line');
    const text = Array.from(lines).map(l => l.textContent).join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${containerId.substring(0, 12)}.log`;
    a.click();
    URL.revokeObjectURL(url);
  });

  // Filter
  document.getElementById('logsFilter').addEventListener('input', () => {
    const filter = document.getElementById('logsFilter').value.toLowerCase();
    logsContainer.querySelectorAll('.log-line').forEach(line => {
      line.style.display = filter && !line.textContent.toLowerCase().includes(filter) ? 'none' : '';
    });
  });
}

function cleanupLogsStream() {
  if (logsEventSource) {
    logsEventSource.close();
    logsEventSource = null;
  }
  logsPaused = false;
  logsAutoScroll = true;
}
