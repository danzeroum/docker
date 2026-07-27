let statsWs = null;
let statsInterval = null;

function renderStatsViewer(containerId) {
  const content = document.getElementById('mainContent');
  content.innerHTML = `
    <div class="section" id="stats">
      <div class="section-head">
        <div class="section-num">09</div>
        <div><h2 class="section-title">Estatísticas em Tempo Real</h2></div>
      </div>
      <div class="kpis" id="statsKpis">
        <div class="kpi kpi-accent">
          <div class="kpi-label">CPU</div>
          <div class="kpi-value" id="statCpu" style="font-size:1.5rem">—%</div>
        </div>
        <div class="kpi kpi-ok">
          <div class="kpi-label">Memória</div>
          <div class="kpi-value" id="statMem" style="font-size:1.5rem">—%</div>
          <div class="kpi-sub" id="statMemSub">—</div>
        </div>
        <div class="kpi kpi-accent">
          <div class="kpi-label">Rede (RX)</div>
          <div class="kpi-value" id="statNetRx" style="font-size:1.5rem">—</div>
        </div>
        <div class="kpi kpi-accent">
          <div class="kpi-label">Rede (TX)</div>
          <div class="kpi-value" id="statNetTx" style="font-size:1.5rem">—</div>
        </div>
      </div>
      <div style="margin-top:.5rem">
        <div style="display:flex;gap:1rem;align-items:center">
          <span id="statsStatus" style="font-size:.75rem;color:var(--text-mute)">Conectando...</span>
          <div style="flex:1;height:2px;background:var(--border);border-radius:1px;overflow:hidden">
            <div id="statsBarCpu" style="height:100%;width:0%;background:var(--accent);transition:width .5s"></div>
          </div>
        </div>
      </div>
    </div>
  `;

  // Connect WebSocket
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/api/containers/${containerId}/stats/ws`;

  if (statsWs) statsWs.close();
  statsWs = new WebSocket(wsUrl);

  statsWs.onopen = () => {
    document.getElementById('statsStatus').textContent = 'Conectado';
  };

  statsWs.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.error) {
        document.getElementById('statsStatus').textContent = `Erro: ${data.error}`;
        return;
      }
      document.getElementById('statCpu').textContent = `${data.cpu_percent}%`;
      document.getElementById('statMem').textContent = `${data.mem_percent}%`;
      document.getElementById('statMemSub').textContent = `${fmtBytes(data.mem_usage)} / ${fmtBytes(data.mem_limit)}`;
      document.getElementById('statNetRx').textContent = fmtBytes(data.net_rx);
      document.getElementById('statNetTx').textContent = fmtBytes(data.net_tx);
      document.getElementById('statsBarCpu').style.width = `${Math.min(data.cpu_percent, 100)}%`;
      document.getElementById('statsBarCpu').style.background = data.cpu_percent > 80 ? 'var(--bad)' : data.cpu_percent > 50 ? 'var(--warn)' : 'var(--accent)';
      document.getElementById('statsStatus').textContent = `Atualizado ${new Date().toLocaleTimeString('pt-BR')}`;
    } catch (err) {
      console.error('Stats parse error:', err);
    }
  };

  statsWs.onclose = () => {
    document.getElementById('statsStatus').textContent = 'Desconectado';
  };

  statsWs.onerror = () => {
    document.getElementById('statsStatus').textContent = 'Erro de conexão';
  };
}

function cleanupStatsWs() {
  if (statsWs) {
    statsWs.close();
    statsWs = null;
  }
}
