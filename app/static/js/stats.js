let statsWs = null;
let statsCpuHistory = [];
let statsMemHistory = [];
const STATS_MAX_POINTS = 60;

function renderSparklineSvg(points, width, height, color) {
  if (!points || points.length < 2) return '';
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const range = max - min || 1;
  const stepX = width / (points.length - 1);
  const d = points.map((p, i) => {
    const x = i * stepX;
    const y = height - ((p - min) / range) * (height - 4) - 2;
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="display:block;width:100%;height:${height}px">
    <path d="${d}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}

function renderStatsViewer(containerId) {
  statsCpuHistory = [];
  statsMemHistory = [];

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
          <div class="kpi-sub" id="statCpuSparkline"></div>
        </div>
        <div class="kpi kpi-ok">
          <div class="kpi-label">Memória</div>
          <div class="kpi-value" id="statMem" style="font-size:1.5rem">—%</div>
          <div class="kpi-sub" id="statMemSub">—</div>
          <div class="kpi-sub" id="statMemSparkline"></div>
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
      const cpu = data.cpu_percent || 0;
      const mem = data.mem_percent || 0;

      document.getElementById('statCpu').textContent = `${cpu}%`;
      document.getElementById('statMem').textContent = `${mem}%`;
      document.getElementById('statMemSub').textContent = `${fmtBytes(data.mem_usage)} / ${fmtBytes(data.mem_limit)}`;
      document.getElementById('statNetRx').textContent = fmtBytes(data.net_rx);
      document.getElementById('statNetTx').textContent = fmtBytes(data.net_tx);
      document.getElementById('statsBarCpu').style.width = `${Math.min(cpu, 100)}%`;
      document.getElementById('statsBarCpu').style.background = cpu > 80 ? 'var(--bad)' : cpu > 50 ? 'var(--warn)' : 'var(--accent)';
      document.getElementById('statsStatus').textContent = `Atualizado ${new Date().toLocaleTimeString('pt-BR')}`;

      statsCpuHistory.push(cpu);
      statsMemHistory.push(mem);
      if (statsCpuHistory.length > STATS_MAX_POINTS) statsCpuHistory.shift();
      if (statsMemHistory.length > STATS_MAX_POINTS) statsMemHistory.shift();

      document.getElementById('statCpuSparkline').innerHTML = renderSparklineSvg(statsCpuHistory, 120, 30, '#7dd3fc');
      document.getElementById('statMemSparkline').innerHTML = renderSparklineSvg(statsMemHistory, 120, 30, '#86efac');
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
