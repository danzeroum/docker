import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';

let _disposed = false;

function el(id) { return document.getElementById(id); }

function severityColor(sev) {
  if (sev === 'bad' || sev === 'critical') return 'var(--bad)';
  if (sev === 'warn' || sev === 'high') return 'var(--warn)';
  if (sev === 'medium') return 'var(--accent)';
  return 'var(--text-dim)';
}

function severityBg(sev) {
  const s = sev || 'low';
  if (s === 'critical' || s === 'high') return 'background:linear-gradient(135deg,#fce4ec,#ffebee);border-color:#ef9a9a';
  if (s === 'medium') return 'background:linear-gradient(135deg,#fff3e0,#fff8e1);border-color:#ffe082';
  return 'background:linear-gradient(135deg,#e8f5e9,#f1f8e9);border-color:#c8e6c9';
}

function severityLabel(sev) {
  if (sev === 'critical') return 'Cr\u00edtico';
  if (sev === 'high') return 'Alto';
  if (sev === 'medium') return 'M\u00e9dio';
  return 'Baixo';
}

function statusIcon(st) {
  if (st === 'ok') return '<span style="color:var(--ok);font-size:14px">&#x2713;</span>';
  if (st === 'warn') return '<span style="color:var(--warn);font-size:14px">&#x26A0;</span>';
  return '<span style="color:var(--bad);font-size:14px">&#x2717;</span>';
}

export function renderCapacidade(container) {
  _disposed = false;

  container.innerHTML = `<div class="content">
    <div class="section">
      <div class="section-head"><div><h2 class="section-title">Capacidade</h2></div></div>
      <div id="capBody"><div class="skeleton" style="height:500px"></div></div>
    </div>
  </div>`;

  let pollTimer = null;

  async function fetchData() {
    const { data, error } = await apiGet('cap_data', '/api/capacity');
    if (_disposed) return;
    if (error) {
      const b = el('capBody');
      if (b) b.innerHTML = '<div class="empty">Erro ao carregar dados de capacidade</div>';
      return;
    }
    renderCapBody(data);
    const { data: hist, error: histErr } = await apiGet('cap_history', '/api/metrics/history?series=disk_pct&range=30');
    if (!_disposed && !histErr && hist) {
      renderDiskChart(hist);
    }
    // Storage e postura entram depois e cada um trata o proprio erro: uma
    // varredura de disco indisponivel nao pode apagar a tela de capacidade
    // que ja carregou.
    const { data: st, error: stErr } = await apiGet('cap_storage', '/api/storage');
    if (!_disposed) renderStorage(st, stErr);
    const { data: sec, error: secErr } = await apiGet('cap_security', '/api/security');
    if (!_disposed) renderSecurity(sec, secErr);
  }

  function fmtGB(bytes) {
    const n = Number(bytes) || 0;
    if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
    if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(0)} MB`;
    if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
    return `${n} B`;
  }

  const ROTULO_ORFAO = { image: 'imagem', volume: 'volume', container: 'container' };

  function renderStorage(d, erro) {
    const box = el('capStorage');
    if (!box) return;
    if (erro || !d) {
      box.innerHTML = `<div style="font-size:11px;color:var(--tx2);line-height:1.5">${
        escapeHtml(erro || 'Sem dados de storage')
      }</div>`;
      return;
    }

    const recuperavel = d.reclaimable_bytes || 0;
    const orfaos = d.orphans || [];
    const cor = recuperavel > 5 * 1024 ** 3 ? 'var(--warn)' : 'var(--tx1)';

    const linhas = orfaos.slice(0, 8).map(o =>
      `<div style="display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid var(--bd0)">
        <span style="font-size:9.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--txd);width:62px;flex-shrink:0">${
          escapeHtml(ROTULO_ORFAO[o.type] || o.type)
        }</span>
        <span style="flex:1;min-width:0;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${
          escapeHtml(o.reason || '')
        }">${escapeHtml(o.name || '')}</span>
        <span style="font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--txd)">${fmtGB(o.size_bytes)}</span>
      </div>`
    ).join('');

    const resto = orfaos.length > 8
      ? `<div style="font-size:10px;color:var(--txd);padding-top:6px">e mais ${orfaos.length - 8} item(ns)</div>`
      : '';

    const secoes = [
      ['Imagens', d.images, 'dangling_count'],
      ['Volumes', d.volumes, 'orphan_count'],
      ['Containers', d.containers, 'stopped_old_count'],
      ['Build cache', d.build_cache, null],
    ].map(([rotulo, s, chaveSobra]) => {
      if (!s) return '';
      const sobra = chaveSobra ? (s[chaveSobra] || 0) : 0;
      return `<div style="display:flex;justify-content:space-between;font-size:10.5px;padding:2px 0">
        <span style="color:var(--tx2)">${rotulo}${sobra ? ` <span style="color:var(--warn)">(${sobra} sobra)</span>` : ''}</span>
        <span style="font-family:'JetBrains Mono',monospace;color:var(--txd)">${fmtGB(s.size_bytes)}</span>
      </div>`;
    }).join('');

    box.innerHTML = `
      <div style="display:flex;align-items:baseline;gap:6px;margin-bottom:8px">
        <span style="font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:600;color:${cor}">${fmtGB(recuperavel)}</span>
        <span style="font-size:11px;color:var(--tx2)">recuper&aacute;veis</span>
      </div>
      <div style="border-top:1px solid var(--bd0);padding-top:7px;margin-bottom:8px">${secoes}</div>
      ${orfaos.length
        ? `<div style="max-height:170px;overflow-y:auto">${linhas}${resto}</div>`
        : '<div style="font-size:11px;color:var(--ok)">Nenhum recurso &oacute;rf&atilde;o &mdash; nada a recuperar</div>'}
      <div style="font-size:9.5px;color:var(--txd);line-height:1.4;margin-top:8px;border-top:1px solid var(--bd0);padding-top:7px">
        Container conta como sobra ap&oacute;s ${d.orphan_exited_days || 7} dias parado.
        Build cache fica fora do total: &eacute; outro comando, com outro risco.
      </div>`;
  }

  function renderSecurity(d, erro) {
    const box = el('capSecurity');
    if (!box) return;
    if (erro || !d) {
      box.innerHTML = `<div style="font-size:11px;color:var(--tx2);line-height:1.5">${
        escapeHtml(erro || 'Sem dados de postura')
      }</div>`;
      return;
    }

    const s = d.summary || {};
    const medio = s.score_medio != null ? s.score_medio : 100;
    const cor = medio >= 85 ? 'var(--ok)' : medio >= 60 ? 'var(--warn)' : 'var(--bad)';
    const piores = (d.containers || []).filter(c => (c.violations || []).length).slice(0, 6);

    const linhas = piores.map(c => {
      const pior = (c.violations || [])[0] || {};
      return `<div style="display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid var(--bd0)">
        <span style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:600;width:26px;flex-shrink:0;color:${
          c.score >= 85 ? 'var(--ok)' : c.score >= 60 ? 'var(--warn)' : 'var(--bad)'
        }">${c.score}</span>
        <span style="flex:1;min-width:0;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${
          escapeHtml((c.violations || []).map(v => v.title).join(' · '))
        }">${escapeHtml(c.name || '')}</span>
        <span style="font-size:9.5px;color:${severityColor(pior.severity)};text-transform:uppercase;letter-spacing:.05em">${
          escapeHtml(severityLabel(pior.severity))
        }</span>
        <span style="font-size:10px;color:var(--txd)">${(c.violations || []).length}</span>
      </div>`;
    }).join('');

    const sev = s.violacoes_por_severidade || {};
    box.innerHTML = `
      <div style="display:flex;align-items:baseline;gap:6px;margin-bottom:3px">
        <span style="font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:600;color:${cor}">${medio}</span>
        <span style="font-size:11px;color:var(--tx2)">score m&eacute;dio &middot; pior ${s.score_minimo != null ? s.score_minimo : '-'}</span>
      </div>
      <div style="font-size:10.5px;color:var(--tx2);margin-bottom:8px">
        ${s.conformes || 0}/${s.containers_avaliados || 0} conformes &middot;
        <span style="color:var(--bad)">${sev.critical || 0} cr&iacute;t</span> &middot;
        <span style="color:var(--warn)">${sev.high || 0} alta</span> &middot;
        <span style="color:var(--txd)">${sev.medium || 0} m&eacute;d</span>
      </div>
      ${piores.length
        ? `<div style="max-height:170px;overflow-y:auto">${linhas}</div>`
        : '<div style="font-size:11px;color:var(--ok)">Todos os containers conformes</div>'}
      <div style="font-size:9.5px;color:var(--txd);line-height:1.4;margin-top:8px;border-top:1px solid var(--bd0);padding-top:7px">
        100 menos o peso das viola&ccedil;&otilde;es (cr&iacute;tica 30, alta 15, m&eacute;dia 5).
        ${s.sem_healthcheck || 0} sem healthcheck definido.
      </div>`;
  }

  function renderCapBody(d) {
    const b = el('capBody');
    if (!b) return;

    let coletando = '';
    if (d.coletando_desde) {
      const dt = new Date(d.coletando_desde.replace('Z', ''));
      coletando = `Coletando desde ${dt.toLocaleDateString('pt-BR')}`;
    }

    let windowsHtml = (d.windows || []).map(w => {
      const items = (w.items || []).map(i =>
        `<div style="display:flex;align-items:flex-start;gap:8px">
          <span style="width:6px;height:6px;border-radius:50%;background:${severityColor(w.severity)};flex-shrink:0;margin-top:5px"></span>
          <span style="font-size:11px;color:var(--tx2);line-height:1.45">${escapeHtml(i.text)}</span>
        </div>`
      ).join('');
      const itemCount = (w.items || []).length;
      return `<div style="${severityBg(w.severity)};border:1px solid;border-radius:var(--rc);padding:12px 13px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:${itemCount ? '9px' : '0'}">
          <span style="width:8px;height:8px;border-radius:50%;background:${severityColor(w.severity)};flex-shrink:0"></span>
          <span style="font-size:10px;letter-spacing:.14em;text-transform:uppercase;font-weight:700;color:#64748b">${w.label}</span>
        </div>
        ${items || '<div style="font-size:11px;color:var(--text-dim)">Nenhum item</div>'}
      </div>`;
    }).join('');

    let memHtml = (d.memory_by_stack || []).map(c => {
      const pct = c.pct != null ? c.pct : 0;
      const barColor = pct > 80 ? 'var(--bad)' : pct > 60 ? 'var(--warn)' : 'var(--accent)';
      const valor = c.limit_mb ? `${c.used_mb} / ${c.limit_mb} MB` : `${c.used_mb} MB`;
      return `<div style="display:flex;align-items:center;gap:9px">
        <span style="width:112px;flex-shrink:0;font-size:11px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escapeHtml(c.name)}</span>
        <div style="flex:1;height:7px;border-radius:3px;background:var(--bd0);overflow:hidden">
          <div style="width:${Math.min(pct, 100)}%;height:100%;border-radius:3px;background:${barColor}"></div>
        </div>
        <span style="width:80px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--txd)">${valor}</span>
      </div>`;
    }).join('') || '<span style="font-size:11px;color:var(--text-dim)">Nenhum dado de memoria</span>';

    let posturaHtml = (d.postura || []).map(p =>
      `<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--bd0)">
        ${statusIcon(p.status)}
        <span style="flex:1;min-width:0;font-size:11px">${escapeHtml(p.item)}</span>
        <span style="font-size:10.5px;font-weight:500;color:${severityColor(p.status)}">${escapeHtml(p.valor)}</span>
      </div>`
    ).join('') || '<span style="font-size:11px;color:var(--text-dim)">Nenhum dado</span>';

    b.innerHTML = `<div style="display:flex;flex-direction:column;gap:11px">
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:11px;flex-shrink:0">${windowsHtml}</div>
      <div style="flex:1;min-height:0;display:grid;grid-template-columns:1fr 372px;gap:11px">
        <div style="display:flex;flex-direction:column;gap:11px;min-height:0">
          <div id="capDiskChart" style="flex:1;min-height:100px;background:var(--sf);border:1px solid var(--bd1);border-radius:var(--rc);padding:12px 13px;display:flex;flex-direction:column">
            <div style="font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700" id="capChartTitle">Disco (30 dias)</div>
            <div id="capChartBody" style="flex:1;min-height:0;display:flex;align-items:flex-end;gap:3px;margin:12px 0 8px"></div>
            <div id="capChartNote" style="font-size:11px;color:var(--tx2);line-height:1.5;border-top:1px solid var(--bd0);padding-top:8px">${coletando}</div>
          </div>
          <div style="flex:1;min-height:0;background:var(--sf);border:1px solid var(--bd1);border-radius:var(--rc);padding:12px 13px;display:flex;flex-direction:column">
            <div style="font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700;margin-bottom:9px">Mem\u00f3ria por stack</div>
            <div style="flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:6px">${memHtml}</div>
            <div style="font-size:10.5px;color:#64748b;line-height:1.45;margin-top:8px;border-top:1px solid var(--bd0);padding-top:8px">Consumo atual dos containers em cada projeto</div>
          </div>
        </div>
        <div style="display:flex;flex-direction:column;gap:11px;min-height:0;overflow-y:auto">
          <div style="background:var(--sf);border:1px solid var(--bd1);border-radius:var(--rc);padding:12px 13px">
            <div style="font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700;margin-bottom:10px">Postura de seguran\u00e7a e opera\u00e7\u00e3o</div>
            <div style="max-height:300px;overflow-y:auto">${posturaHtml}</div>
          </div>
          <div style="background:var(--sf);border:1px solid var(--bd1);border-radius:var(--rc);padding:12px 13px">
            <div style="font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700;margin-bottom:10px">Score de seguran\u00e7a por container</div>
            <div id="capSecurity"><div class="skeleton" style="height:120px"></div></div>
          </div>
          <div style="background:var(--sf);border:1px solid var(--bd1);border-radius:var(--rc);padding:12px 13px">
            <div style="font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700;margin-bottom:10px">Storage e recursos \u00f3rf\u00e3os</div>
            <div id="capStorage"><div class="skeleton" style="height:120px"></div></div>
          </div>
        </div>
      </div>
      <div style="flex-shrink:0;font-size:9.5px;color:#64748b;line-height:1.4">${coletando ? coletando + ' &mdash; ' : ''}Gerado em ${new Date().toLocaleString('pt-BR')}</div>
    </div>`;
  }

  function renderDiskChart(hist) {
    const body = el('capChartBody');
    const note = el('capChartNote');
    if (!body) return;

    const proj = hist.projection;
    const pts = hist.series || [];

    let noteText = '';
    if (proj && proj.stable) {
      const d80 = proj.days_to_80, d90 = proj.days_to_90;
      const parts = [];
      if (d80 != null) parts.push(`80% em ~${d80}d`);
      if (d90 != null) parts.push(`90% em ~${d90}d`);
      parts.push(`r\u00B2=${proj.r2}`);
      noteText = `Proje\u00E7\u00E3o: ${parts.join(', ')} (${proj.slope_per_day > 0 ? 'subindo' : 'descendo'} ${Math.abs(proj.slope_per_day).toFixed(2)}%/dia)`;
    } else if (proj && !proj.stable) {
      noteText = `Tend\u00EAncia inst\u00E1vel (r\u00B2=${proj.r2.toFixed(2)} < 0,7) \u2014 dados insuficientes para projetar`;
    } else if (hist.coletando_desde) {
      const dt = new Date(hist.coletando_desde.replace('Z', ''));
      noteText = `Coletando desde ${dt.toLocaleDateString('pt-BR')} \u2014 s\u00E9rie curta para proje\u00E7\u00E3o (< 7 dias)`;
    }

    if (note) note.innerHTML = noteText;

    const vals = pts.map(p => p.v);
    const maxV = Math.max(...vals, 10);
    const limit = 90;

    const days = pts.slice(-30);
    const showProj = proj && proj.stable;
    const projBars = showProj ? 10 : 0;
    const totalBars = days.length + projBars;

    if (!days.length) {
      body.innerHTML = '<div style="font-size:11px;color:var(--text-dim);align-self:center;margin:auto">Aguardando coleta de dados</div>';
      return;
    }

    body.style.gap = projBars > 0 ? '3px' : '2px';
    body.innerHTML = days.map((p, i) => {
      const pct = (p.v / limit) * 100;
      const h = Math.max(4, (pct / 100) * 120);
      const color = p.v > 80 ? 'var(--bad)' : p.v > 60 ? 'var(--warn)' : 'var(--accent)';
      return `<div style="flex:1;height:130px;display:flex;align-items:flex-end;position:relative" title="${p.ts}: ${p.v.toFixed(1)}%">
        <div style="width:100%;height:${h.toFixed(0)}px;border-radius:2px 2px 0 0;background:${color};min-height:2px;transition:height .3s"></div>
      </div>`;
    }).join('') + (showProj ? projBarsLayout(proj, days) : '');
  }

  function projBarsLayout(proj, days) {
    const lastV = days.length ? days[days.length - 1].v : 50;
    const s = proj.slope_per_day;
    const i = proj.intercept;
    let html = '';
    for (let x = 1; x <= 10; x++) {
      const v = i + s * (days.length - 1 + x);
      const h = Math.max(4, (Math.min(v, 100) / 90) * 120);
      const reached90 = v >= 90;
      const color = reached90 ? 'var(--bad)' : 'var(--text-dim)';
      const label = reached90 ? '!' : '';
      html += `<div style="flex:1;height:130px;display:flex;align-items:flex-end;position:relative" title="Proj ${x}d: ${v.toFixed(1)}%">
        <div style="width:100%;height:${h.toFixed(0)}px;border-radius:2px 2px 0 0;background:${color};min-height:2px;opacity:0.5">${label}</div>
      </div>`;
    }
    return html;
  }

  fetchData();
  pollTimer = setInterval(fetchData, 30000);

  return () => {
    _disposed = true;
    if (pollTimer) clearInterval(pollTimer);
  };
}
