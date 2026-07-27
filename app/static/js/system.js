function renderSystemInfo(sys) {
  const cpuPct = sys.cpu?.percent != null ? sys.cpu.percent.toFixed(1) : '—';
  document.getElementById('sysCpu').textContent = cpuPct + (cpuPct !== '—' ? '%' : '');
  document.getElementById('sysCpuSub').textContent = `${sys.cpu?.count || '?'} cores`;

  if (sys.memory) {
    const memPct = sys.memory.percent.toFixed(1);
    document.getElementById('sysMem').textContent = memPct + '%';
    document.getElementById('sysMemSub').textContent = `${fmtBytes(sys.memory.used)} / ${fmtBytes(sys.memory.total)}`;
  }

  if (sys.swap) {
    const swapPct = sys.swap.percent.toFixed(1);
    document.getElementById('sysSwap').textContent = swapPct + '%';
    document.getElementById('sysSwapSub').textContent = `${fmtBytes(sys.swap.used)} / ${fmtBytes(sys.swap.total)}`;
  }

  if (sys.disks && sys.disks.length > 0) {
    const root = sys.disks.find(d => d.mountpoint === '/') || sys.disks[0];
    const diskPct = root.percent.toFixed(1);
    document.getElementById('sysDisk').textContent = diskPct + '%';
    document.getElementById('sysDiskSub').textContent = `${fmtBytes(root.used)} / ${fmtBytes(root.total)} (${root.mountpoint})`;
  }

  if (sys.cpu?.load_1m != null) {
    const load = [sys.cpu.load_1m, sys.cpu.load_5m, sys.cpu.load_15m];
    document.getElementById('sysLoad').textContent = load.map(n => n.toFixed(2)).join(', ');
    document.getElementById('sysLoadSub').textContent = `${sys.cpu?.count || '?'} cores`;
  }

  if (sys.uptime_seconds != null) {
    document.getElementById('sysUptime').textContent = fmtDuration(sys.uptime_seconds * 1000);
    document.getElementById('sysUptimeSub').textContent = 'host';
  }

  const warns = [];
  if (sys.cpu?.percent != null && sys.cpu.percent > 85) warns.push(`<strong>CPU alta:</strong> ${sys.cpu.percent.toFixed(1)}%`);
  if (sys.memory && sys.memory.percent > 85) warns.push(`<strong>Memória alta:</strong> ${sys.memory.percent.toFixed(1)}%`);
  if (sys.swap && sys.swap.percent > 80) warns.push(`<strong>Swap alta:</strong> ${sys.swap.percent.toFixed(1)}%`);
  if (sys.disks) {
    sys.disks.forEach(d => { if (d.percent > 85) warns.push(`<strong>Disco cheio (${d.mountpoint}):</strong> ${d.percent.toFixed(1)}%`); });
  }
  if (sys.cpu?.load_1m && sys.cpu?.count && sys.cpu.load_1m > sys.cpu.count * 2) warns.push(`<strong>Load alto:</strong> ${sys.cpu.load_1m.toFixed(2)} (${sys.cpu.count} cores)`);

  const warnEl = document.getElementById('systemWarnings');
  if (warns.length) {
    warnEl.innerHTML = `
      <div class="empty-field" style="background:var(--bad-soft);border-color:var(--bad);color:var(--bad)">
        ${warns.map(w => `<div>${w}</div>`).join('')}
      </div>`;
  } else {
    warnEl.innerHTML = `<div class="empty-field" style="background:var(--ok-soft);border-color:var(--ok);color:var(--ok)">Sistema saudável — sem alertas</div>`;
  }
}
