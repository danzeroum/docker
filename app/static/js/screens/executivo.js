import { apiGet, cancel } from '../data.js';
import { escapeHtml } from '../fmt.js';

// Nenhuma frase de diagnostico aqui: hero, riscos e impacto vem dos campos
// _plain do motor. O que existe neste arquivo e rotulo de interface.

function moeda(valor) {
  return valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

export function renderExecutivo(container) {
  let pollTimer = null;

  function kpis(d) {
    const cartoes = [];

    cartoes.push({
      label: 'Serviços no ar',
      valor: String(d.services.length + d.services_unmapped),
      nota: d.services_unmapped
        ? `${d.services_unmapped} sem nome de negócio`
        : 'todos identificados',
      tom: d.services_unmapped ? 'warn' : 'ok',
    });

    cartoes.push({
      label: 'Precisa de decisão',
      valor: String(d.risks.length),
      nota: d.risks.length ? 'aguardando você' : 'nada pendente',
      tom: d.risks.length ? 'warn' : 'ok',
    });

    // Sem COST_MONTHLY o cartao nao existe — "R$ 0" seria dado inventado.
    if (d.cost_monthly !== null && d.cost_monthly !== undefined) {
      cartoes.push({
        label: 'Custo mensal',
        valor: moeda(d.cost_monthly),
        nota: 'servidor',
        tom: 'mute',
      });
    }

    return cartoes.map(c => `<div class="kpi kpi-${c.tom}">
      <div class="kpi-label">${escapeHtml(c.label)}</div>
      <div class="kpi-value">${escapeHtml(c.valor)}</div>
      <div class="kpi-note">${escapeHtml(c.nota)}</div>
    </div>`).join('');
  }

  function hero(h) {
    if (!h) {
      return `<section class="exec-hero exec-hero-ok">
        <h2 class="exec-hero-title">Nenhum problema exige sua atenção agora</h2>
        <p class="exec-hero-text">Os serviços estão no ar e nada aguarda decisão.</p>
      </section>`;
    }
    const grave = h.severity === 'critical' || h.severity === 'high';
    return `<section class="exec-hero ${grave ? 'exec-hero-bad' : 'exec-hero-warn'}">
      <h2 class="exec-hero-title">${escapeHtml(h.title)}</h2>
      ${h.text ? `<p class="exec-hero-text">${escapeHtml(h.text)}</p>` : ''}
      ${h.impact ? `<p class="exec-hero-impact">${escapeHtml(h.impact)}</p>` : ''}
      ${h.recommendation ? `<p class="exec-hero-next"><strong>O que fazer:</strong> ${escapeHtml(h.recommendation)}</p>` : ''}
    </section>`;
  }

  function servicos(d) {
    const linhas = d.services.map(s => `<li class="exec-servico">
      <span class="exec-servico-nome">${escapeHtml(s.name)}</span>
      ${s.critical ? '<span class="exec-tag">essencial</span>' : ''}
      ${s.description ? `<span class="exec-servico-desc">${escapeHtml(s.description)}</span>` : ''}
    </li>`);

    if (d.services_unmapped) {
      linhas.push(`<li class="exec-servico exec-servico-vazio">
        <span class="exec-servico-nome">não mapeado</span>
        <span class="exec-tag warn">${d.services_unmapped}</span>
        <span class="exec-servico-desc">sem nome de negócio no arquivo de configuração</span>
      </li>`);
    }

    if (!linhas.length) {
      return `<div class="empty">Nenhum serviço publicado identificado.</div>`;
    }
    return `<ul class="exec-lista">${linhas.join('')}</ul>`;
  }

  function riscos(lista) {
    if (!lista.length) {
      return `<div class="exec-sem-risco">Nada aguardando sua aprovação.</div>`;
    }
    return `<ul class="exec-lista">${lista.map(r => `<li class="exec-risco exec-risco-${escapeHtml(r.severity || 'medium')}">
      <div class="exec-risco-topo">
        ${r.service ? `<span class="exec-servico-nome">${escapeHtml(r.service)}</span>` : ''}
        <span class="exec-prazo">${r.horizon_days ? `em ${r.horizon_days} dias` : 'sem prazo'}</span>
      </div>
      <div class="exec-risco-titulo">${escapeHtml(r.title)}</div>
      ${r.impact ? `<div class="exec-risco-impacto">${escapeHtml(r.impact)}</div>` : ''}
      ${r.decision ? `<div class="exec-risco-decisao"><strong>Decisão:</strong> ${escapeHtml(r.decision)}</div>` : ''}
    </li>`).join('')}</ul>`;
  }

  function avisoConfig(faltando) {
    if (!faltando || !faltando.length) return '';
    return `<div class="exec-config-aviso">
      Configuração faltando: ${faltando.map(f => `<code>${escapeHtml(f)}</code>`).join(', ')}.
      Sem ela os serviços aparecem como "não mapeado".
    </div>`;
  }

  function render(d) {
    container.innerHTML = `<div class="content">
      ${avisoConfig(d.config_missing)}
      ${hero(d.hero)}
      <div class="exec-kpis">${kpis(d)}</div>
      <div class="exec-colunas">
        <section class="section">
          <div class="section-head"><div><h2 class="section-title">Serviços que o cliente enxerga</h2></div></div>
          ${servicos(d)}
        </section>
        <section class="section">
          <div class="section-head"><div><h2 class="section-title">Precisa da sua decisão</h2></div></div>
          ${riscos(d.risks || [])}
        </section>
      </div>
    </div>`;
  }

  async function carregar() {
    const { data, error } = await apiGet('executive', '/api/executive');
    if (error) {
      container.innerHTML = `<div class="content"><div class="section">
        <div class="empty-field">${escapeHtml(error)}</div></div></div>`;
      return;
    }
    render(data);
  }

  carregar();
  pollTimer = setInterval(carregar, 30000);

  return () => {
    if (pollTimer) clearInterval(pollTimer);
    cancel('executive');
  };
}
