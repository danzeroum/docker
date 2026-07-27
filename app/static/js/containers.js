function getStackName(c) {
  return (c.Labels && c.Labels['com.docker.compose.project']) || null;
}

function renderContainerList() {
  const listEl = document.getElementById('containerList');
  let filtered = allContainers;

  if (currentFilter === 'running') {
    filtered = filtered.filter(c => c.State === 'running');
  }
  if (currentFilter === 'exited') {
    filtered = filtered.filter(c => c.State === 'exited' || c.State === 'created' || c.State === 'dead');
  }
  if (currentFilter === 'unhealthy') {
    filtered = filtered.filter(c => c.State === 'unhealthy' ||
      (c.Status && c.Status.includes('unhealthy')));
  }

  if (searchTerm) {
    const term = searchTerm.toLowerCase();
    filtered = filtered.filter(c => {
      const name = (c.Names && c.Names[0] || '').toLowerCase();
      const image = (c.Image || '').toLowerCase();
      return name.includes(term) || image.includes(term);
    });
  }

  if (filtered.length === 0) {
    listEl.innerHTML = '<div class="empty">Nenhum container encontrado</div>';
    return;
  }

  function renderItem(c) {
    const id = c.Id;
    const name = (c.Names && c.Names[0] || '').replace(/^\//, '');
    const image = c.Image || '';
    let statusCls = c.State || 'unknown';
    if (c.Status && c.Status.includes('unhealthy')) statusCls = 'unhealthy';

    return `
      <div class="list-item ${id === selectedContainerId ? 'active' : ''}" data-id="${id}">
        <div class="item-status ${statusCls}"></div>
        <div class="item-info">
          <div class="item-name" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
          <div class="item-image" title="${escapeHtml(image)}">${escapeHtml(image)}</div>
        </div>
      </div>
    `;
  }

  // Group by stack
  const groups = {};
  filtered.forEach(c => {
    const stack = getStackName(c) || '__ungrouped__';
    if (!groups[stack]) groups[stack] = [];
    groups[stack].push(c);
  });

  const hasGroups = Object.keys(groups).length > 1 || !groups['__ungrouped__'];
  let html = '';

  Object.entries(groups).sort(([a], [b]) => {
    if (a === '__ungrouped__') return 1;
    if (b === '__ungrouped__') return -1;
    return a.localeCompare(b);
  }).forEach(([stack, containers]) => {
    if (hasGroups && stack !== '__ungrouped__') {
      const stackRunning = containers.filter(c => c.State === 'running').length;
      html += `<div class="stack-header" data-stack="${escapeHtml(stack)}">
        <span class="stack-toggle">▼</span>
        <span class="stack-name">${escapeHtml(stack)}</span>
        <span class="stack-count">${stackRunning}/${containers.length}</span>
      </div>`;
    }
    html += `<div class="stack-group" data-stack="${escapeHtml(stack)}">`;
    containers.forEach(c => { html += renderItem(c); });
    html += '</div>';
  });

  listEl.innerHTML = html;

  // Stack toggle
  listEl.querySelectorAll('.stack-header').forEach(header => {
    header.addEventListener('click', () => {
      const group = header.nextElementSibling;
      if (group && group.classList.contains('stack-group')) {
        const isHidden = group.style.display === 'none';
        group.style.display = isHidden ? '' : 'none';
        header.querySelector('.stack-toggle').textContent = isHidden ? '▼' : '▶';
      }
    });
  });

  listEl.querySelectorAll('.list-item').forEach(item => {
    item.addEventListener('click', () => {
      selectedContainerId = item.dataset.id;
      document.getElementById('tabNav').style.display = 'flex';
      renderContainerList();
      cleanupLogsStream();
      cleanupStatsWs();
      cleanupTerminal();
      fetchContainerDetail(selectedContainerId);
    });
  });
}

function renderGlobalOverview() {
  if (selectedContainerId) return;

  const total = allContainers.length;
  const running = allContainers.filter(c => c.State === 'running').length;
  const exited = allContainers.filter(c => c.State === 'exited' || c.State === 'created' || c.State === 'dead').length;
  const unhealthy = allContainers.filter(c =>
    c.State === 'unhealthy' || (c.Status && c.Status.includes('unhealthy'))
  ).length;

  document.getElementById('globalSummary').textContent = unhealthy > 0
    ? `${running}/${total} UP · ${unhealthy} unhealthy`
    : `${running}/${total} UP`;
  document.getElementById('mainTitle').textContent = 'Visão Geral do Host';
  document.getElementById('mainSubtitle').textContent = `${total} containers detectados`;
  document.getElementById('tabNav').style.display = 'none';

  document.getElementById('mainContent').innerHTML = `
    <div class="overview-hero">
      <h2 style="margin:0 0 .5rem;font-size:1.5rem">Dashboard do Host</h2>
      <p style="color:var(--text-dim);margin:0">
        Selecione um container na lista à esquerda para ver detalhes profundos,
        ou filtre por estado clicando nos cards abaixo.
      </p>
    </div>

    <div class="kpis" id="containerKpis">
      <div class="kpi kpi-accent" onclick="setFilter('all')">
        <div class="kpi-label">Total de Containers</div>
        <div class="kpi-value">${total}</div>
      </div>
      <div class="kpi kpi-ok" onclick="setFilter('running')">
        <div class="kpi-label">Rodando</div>
        <div class="kpi-value">${running}</div>
      </div>
      <div class="kpi kpi-warn" onclick="setFilter('exited')">
        <div class="kpi-label">Parados / Exited</div>
        <div class="kpi-value">${exited}</div>
      </div>
      <div class="kpi kpi-bad" onclick="setFilter('unhealthy')">
        <div class="kpi-label">Unhealthy</div>
        <div class="kpi-value">${unhealthy}</div>
      </div>
    </div>

    <div class="kpis" id="systemKpis">
      <div class="kpi kpi-accent">
        <div class="kpi-label">CPU</div>
        <div class="kpi-value" id="sysCpu">—</div>
        <div class="kpi-sub" id="sysCpuSub">carregando...</div>
      </div>
      <div class="kpi kpi-ok">
        <div class="kpi-label">Memória</div>
        <div class="kpi-value" id="sysMem">—</div>
        <div class="kpi-sub" id="sysMemSub">carregando...</div>
      </div>
      <div class="kpi kpi-warn">
        <div class="kpi-label">Swap</div>
        <div class="kpi-value" id="sysSwap">—</div>
        <div class="kpi-sub" id="sysSwapSub">carregando...</div>
      </div>
      <div class="kpi kpi-accent">
        <div class="kpi-label">Disco</div>
        <div class="kpi-value" id="sysDisk">—</div>
        <div class="kpi-sub" id="sysDiskSub">carregando...</div>
      </div>
      <div class="kpi kpi-ok">
        <div class="kpi-label">Load Avg</div>
        <div class="kpi-value" id="sysLoad">—</div>
        <div class="kpi-sub" id="sysLoadSub">carregando...</div>
      </div>
      <div class="kpi kpi-accent">
        <div class="kpi-label">Uptime</div>
        <div class="kpi-value" id="sysUptime">—</div>
        <div class="kpi-sub" id="sysUptimeSub">carregando...</div>
      </div>
    </div>

    <div id="systemWarnings" style="margin-top:1rem"></div>
  `;

  fetchSystemInfo();
}

function parseInspect(data) {
  const c = Array.isArray(data) ? data[0] : data;
  const state = c.State || {};
  const config = c.Config || {};
  const host = c.HostConfig || {};
  const net = c.NetworkSettings || {};
  const health = state.Health || null;

  let status = state.Status || 'unknown';
  if (health && health.Status === 'unhealthy' && state.running) status = 'unhealthy';

  return {
    name: c.Name ? c.Name.replace(/^\//, '') : '',
    id: c.Id || '',
    image: config.Image || '',
    state: {
      status,
      running: !!state.Running,
      exitCode: state.ExitCode ?? null,
      startedAt: state.StartedAt ? new Date(state.StartedAt) : null,
      uptimeMs: state.Status === 'running' && state.StartedAt
        ? (new Date() - new Date(state.StartedAt))
        : 0,
      restartCount: state.RestartCount ?? 0,
      pid: state.Pid ?? null,
      error: state.Error || null,
      health: health ? {
        status: health.Status || 'none',
        failingStreak: health.FailingStreak ?? 0,
        log: (health.Log || []).map(l => ({
          start: l.Start,
          exitCode: l.ExitCode,
          output: l.Output
        }))
      } : null
    },
    config: { env: config.Env || [] },
    host: { portBindings: host.PortBindings || {}, restartPolicy: host.RestartPolicy || {} },
    net: { ip: net.IPAddress || '', networks: net.Networks || {} },
    mounts: c.Mounts || []
  };
}

function renderContainerDetail(data, rawJson) {
  document.getElementById('mainTitle').textContent = data.name || shortId(data.id);
  document.getElementById('mainSubtitle').textContent = data.image || '';
  const content = document.getElementById('mainContent');

  let healthHtml = `
    <div class="section" id="health">
      <div class="section-head">
        <div class="section-num">03</div>
        <div><h2 class="section-title">Health Check</h2></div>
      </div>
      <div class="empty-field">Nenhum HEALTHCHECK definido.</div>
    </div>`;

  if (data.state.health) {
    const logs = data.state.health.log.slice().reverse().map(l => `
      <div class="section" style="margin-bottom:.75rem;padding:.75rem 1rem;border-left:3px solid ${l.exitCode === 0 ? 'var(--ok)' : 'var(--bad)'}">
        <div style="display:flex;gap:.5rem;align-items:center;margin-bottom:.25rem">
          <span style="font-family:'JetBrains Mono';font-size:.7rem;padding:.15rem .4rem;border-radius:4px;background:${l.exitCode===0?'var(--ok-soft)':'var(--bad-soft)'};color:${l.exitCode===0?'#86efac':'#fca5a5'}">
            exit ${l.exitCode}
          </span>
          <span style="font-size:.7rem;color:var(--text-mute);font-family:'JetBrains Mono'">${fmtDate(l.start)}</span>
        </div>
        ${l.output ? `<pre style="margin:0;font-size:.7rem;color:var(--text-dim);white-space:pre-wrap;word-break:break-all">${escapeHtml(l.output.trim().slice(0,300))}</pre>` : ''}
      </div>
    `).join('');

    healthHtml = `
      <div class="section" id="health">
        <div class="section-head">
          <div class="section-num">03</div>
          <div><h2 class="section-title">Health Check</h2></div>
        </div>
        <div class="card-grid cols-3" style="margin-bottom:1rem">
          <div class="field">
            <div class="field-label">Status</div>
            <div class="field-value">${escapeHtml(data.state.health.status)}</div>
          </div>
          <div class="field">
            <div class="field-label">Falhas Consecutivas</div>
            <div class="field-value">${data.state.health.failingStreak}</div>
          </div>
        </div>
        ${logs || '<div class="empty-field">Sem logs de health.</div>'}
      </div>
    `;
  }

  let portHtml = '<div class="empty-field">Nenhuma porta publicada.</div>';
  const ports = Object.entries(data.host.portBindings || {}).filter(([k,v]) => v);
  if (ports.length) {
    portHtml = `<div class="table-wrap">
      <table>
        <thead><tr><th>Host IP</th><th>Host Port</th><th>Container Port</th></tr></thead>
        <tbody>
          ${ports.map(([k,v]) =>
            v.map(b => `
              <tr>
                <td>${escapeHtml(b.HostIp || '0.0.0.0')}</td>
                <td>${escapeHtml(b.HostPort)}</td>
                <td>${escapeHtml(k)}</td>
              </tr>
            `).join('')
          ).join('')}
        </tbody>
      </table>
    </div>`;
  }

  const networks = Object.entries(data.net.networks || {});
  let netHtml = '<div class="empty-field">Sem redes.</div>';
  if (networks.length) {
    netHtml = `<div class="table-wrap">
      <table>
        <thead><tr><th>Rede</th><th>IP</th><th>Gateway</th></tr></thead>
        <tbody>
          ${networks.map(([n,v]) => `
            <tr>
              <td>${escapeHtml(n)}</td>
              <td>${escapeHtml(v.IPAddress || '—')}</td>
              <td>${escapeHtml(v.Gateway || '—')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>`;
  }

  let volHtml = '<div class="empty-field">Nenhum volume.</div>';
  if (data.mounts.length) {
    volHtml = `<div class="table-wrap">
      <table>
        <thead><tr><th>Tipo</th><th>Source</th><th>Destination</th></tr></thead>
        <tbody>
          ${data.mounts.map(m => `
            <tr>
              <td>${escapeHtml(m.Type)}</td>
              <td>${escapeHtml(m.Source || m.Name || '')}</td>
              <td>${escapeHtml(m.Destination || '')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>`;
  }

  let envHtml = '<div class="empty-field">Sem variáveis.</div>';
  if (data.config.env.length) {
    envHtml = `<div class="table-wrap">
      <table>
        <thead><tr><th>Variável</th><th>Valor</th></tr></thead>
        <tbody>
          ${data.config.env.map(e => {
            const idx = e.indexOf('=');
            const k = idx > 0 ? e.slice(0, idx) : e;
            const v = idx > 0 ? e.slice(idx+1) : '';
            const secret = /SECRET|PASS|TOKEN|KEY/i.test(k);
            return `
              <tr>
                <td><strong>${escapeHtml(k)}</strong></td>
                <td style="${secret ? 'filter:blur(4px)' : ''}">${escapeHtml(v || '—')}</td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>`;
  }

  const prettyJson = JSON.stringify(rawJson, null, 2);
  const highlighted = prettyJson
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/(\"(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\\"])*\"(\\s*:)?|\\b(true|false|null)\\b|-?\\d+(?:\\.\\d+)?)/g, m => {
      let cls = 'json-number';
      if (/^\"/.test(m)) cls = /:$/.test(m) ? 'json-key' : 'json-string';
      else if (/true|false/.test(m)) cls = 'json-bool';
      else if (/null/.test(m)) cls = 'json-null';
      return `<span class="${cls}">${m}</span>`;
    });

  content.innerHTML = `
    <div class="section" id="overview">
      <div style="display:flex;gap:1rem;align-items:center;flex-wrap:wrap">
        <span class="status-pill ${escapeHtml(data.state.status)}">
          <span class="dot"></span>${escapeHtml(data.state.status)}
        </span>
        <span style="font-family:'JetBrains Mono';font-size:.8rem;color:var(--text-dim)">
          ID: ${escapeHtml(shortId(data.id))}
        </span>
      </div>
      <div class="kpis" style="margin-top:1rem">
        <div class="kpi kpi-ok">
          <div class="kpi-label">Uptime</div>
          <div class="kpi-value" style="font-size:1.2rem">${fmtDuration(data.state.uptimeMs)}</div>
        </div>
        <div class="kpi kpi-warn">
          <div class="kpi-label">Restarts</div>
          <div class="kpi-value" style="font-size:1.2rem">${data.state.restartCount}</div>
        </div>
        <div class="kpi kpi-bad">
          <div class="kpi-label">Exit Code</div>
          <div class="kpi-value" style="font-size:1.2rem">${data.state.exitCode ?? '—'}</div>
        </div>
      </div>

      <div class="action-bar" id="actionBar">
        <button class="action-btn start" id="btnStart" title="Iniciar container">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          Iniciar
        </button>
        <button class="action-btn stop" id="btnStop" title="Parar container">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="12" height="16"/></svg>
          Parar
        </button>
        <button class="action-btn restart" id="btnRestart" title="Reiniciar container">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 23 20"/></svg>
          Reiniciar
        </button>
        <button class="action-btn remove" id="btnRemove" title="Remover container">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          Remover
        </button>
      </div>
    </div>

    <div class="section" id="estado">
      <div class="section-head">
        <div class="section-num">02</div>
        <div><h2 class="section-title">Estado</h2></div>
      </div>
      <div class="card-grid cols-3">
        <div class="field">
          <div class="field-label">Started At</div>
          <div class="field-value">${fmtDate(data.state.startedAt)}</div>
        </div>
        <div class="field">
          <div class="field-label">PID</div>
          <div class="field-value">${data.state.pid ?? '—'}</div>
        </div>
        <div class="field">
          <div class="field-label">Error</div>
          <div class="field-value">${escapeHtml(data.state.error || '—')}</div>
        </div>
      </div>
    </div>

    ${healthHtml}

    <div class="section" id="rede">
      <div class="section-head">
        <div class="section-num">04</div>
        <div><h2 class="section-title">Rede & Portas</h2></div>
      </div>
      <h3 style="font-size:.8rem;color:var(--text-mute);margin:0 0 .5rem;text-transform:uppercase">Portas</h3>
      ${portHtml}
      <h3 style="font-size:.8rem;color:var(--text-mute);margin:1.5rem 0 .5rem;text-transform:uppercase">Redes</h3>
      ${netHtml}
    </div>

    <div class="section" id="volumes">
      <div class="section-head">
        <div class="section-num">05</div>
        <div><h2 class="section-title">Volumes</h2></div>
      </div>
      ${volHtml}
    </div>

    <div class="section" id="env">
      <div class="section-head">
        <div class="section-num">06</div>
        <div><h2 class="section-title">Variáveis de Ambiente</h2></div>
      </div>
      ${envHtml}
    </div>

    <div class="section" id="json">
      <div class="section-head">
        <div class="section-num">07</div>
        <div><h2 class="section-title">JSON Bruto</h2></div>
      </div>
      <div class="json-wrap">
        <pre class="json-content">${highlighted}</pre>
      </div>
    </div>
  `;

  const running = data.state.running;
  document.getElementById('btnStart').disabled = running;
  document.getElementById('btnStop').disabled = !running;
  document.getElementById('btnRestart').disabled = !running;
  document.getElementById('btnRemove').disabled = false;
}

function setFilter(filter) {
  currentFilter = filter;
  document.querySelectorAll('.filter-pill').forEach(p =>
    p.classList.toggle('active', p.dataset.filter === filter)
  );
  renderContainerList();
}
