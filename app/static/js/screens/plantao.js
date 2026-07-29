/* Plantao — a fila de achados e a acao, nada mais.
 *
 * O handoff e explicito: "o mobile de plantao nao e uma versao reduzida do
 * desktop — e a fila de achados e a acao. So isso." Mesma fonte da tela de
 * Atencao (/api/findings?status=open), leitura diferente: aqui nao ha filtro,
 * nem profundidade, nem grade. Ha ordem de atendimento e o que fazer.
 *
 * A ordenacao e a unica decisao da tela: severidade primeiro, e dentro da
 * mesma severidade o mais antigo primeiro — quem esta aberto ha mais tempo ja
 * esperou demais. Isso e o oposto de "mais recente primeiro", que e o que uma
 * fila cronologica daria e que faz o plantonista atender sempre o ultimo grito.
 *
 * Sem escrita: silenciar e da tela de Atencao, que audita. Daqui se abre o
 * achado.
 */
import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { navigate } from '../main.js';
import { setState } from '../store.js';

let _disposed = false;

function el(id) { return document.getElementById(id); }

const PESO = { critical: 0, high: 1, medium: 2, low: 3 };

function corSeveridade(sev) {
  if (sev === 'critical') return 'var(--bad)';
  if (sev === 'high') return 'var(--warn)';
  if (sev === 'medium') return 'var(--accent)';
  return 'var(--text-dim)';
}

function rotuloSeveridade(sev) {
  if (sev === 'critical') return 'Crítico';
  if (sev === 'high') return 'Alto';
  if (sev === 'medium') return 'Médio';
  return 'Baixo';
}

export function ordenarFila(achados) {
  return (achados || []).slice().sort((a, b) => {
    const pa = PESO[a.severity] != null ? PESO[a.severity] : 9;
    const pb = PESO[b.severity] != null ? PESO[b.severity] : 9;
    if (pa !== pb) return pa - pb;
    const sa = (b.score || 0) - (a.score || 0);
    if (sa !== 0) return sa;
    const ta = a.first_seen ? new Date(a.first_seen).getTime() : Infinity;
    const tb = b.first_seen ? new Date(b.first_seen).getTime() : Infinity;
    return ta - tb;
  });
}

export function tempoAberto(desde, agora) {
  if (!desde) return '';
  const ms = (agora != null ? agora : Date.now()) - new Date(desde).getTime();
  if (!isFinite(ms) || ms < 0) return '';
  const min = Math.floor(ms / 60000);
  if (min < 1) return 'agora';
  if (min < 60) return `há ${min}min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `há ${h}h`;
  const d = Math.floor(h / 24);
  return `há ${d}d`;
}

function alvoLegivel(f) {
  if (Array.isArray(f.targets) && f.targets.length) {
    return f.targets.length === 1 ? String(f.targets[0]) : `${f.targets.length} alvos`;
  }
  return f.target || '';
}

function htmlCartao(f, agora) {
  const c = corSeveridade(f.severity);
  // O plantonista quer a frase direta; o tecnico e a segunda linha.
  const titulo = f.title_plain || f.title || f.rule;
  const acao = f.recommendation_plain || f.recommendation || '';
  const aberto = tempoAberto(f.first_seen, agora);
  const rep = f.occurrences > 1 ? `${f.occurrences}×` : '';
  return `<div class="plt-card" data-id="${escapeHtml(f.id)}" style="position:relative;background:var(--sf);border:1px solid var(--bd1);border-left:3px solid ${c};border-radius:var(--rc);padding:12px 13px">
    <button type="button" class="card-open" data-open="${escapeHtml(f.id)}"><span class="sr-only">Abrir achado ${escapeHtml(titulo)}</span></button>
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:5px">
      <span style="font-size:9.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:${c}">${rotuloSeveridade(f.severity)}</span>
      <span style="font-size:10px;color:#64748b;font-family:'JetBrains Mono',monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0">${escapeHtml(alvoLegivel(f))}</span>
      <span style="font-size:10px;color:#64748b;margin-left:auto;white-space:nowrap">${escapeHtml([aberto, rep].filter(Boolean).join(' · '))}</span>
    </div>
    <div style="font-size:13px;font-weight:650;line-height:1.4;letter-spacing:-.01em">${escapeHtml(titulo)}</div>
    ${acao ? `<div style="font-size:11.5px;color:var(--txd);line-height:1.5;margin-top:5px;border-top:1px solid var(--bd0);padding-top:6px">${escapeHtml(acao)}</div>` : ''}
  </div>`;
}

export function renderPlantao(container) {
  _disposed = false;

  container.innerHTML = `<div class="content">
    <div class="section">
      <div class="section-head"><div><h2 class="section-title">Plantão</h2></div></div>
      <div id="pltResumo" style="margin-bottom:11px"></div>
      <div id="pltFila"><div class="skeleton" style="height:400px"></div></div>
    </div>
  </div>`;

  let pollTimer = null;

  async function carregar() {
    const { data, error } = await apiGet('plt_findings', '/api/findings?status=open');
    if (_disposed) return;
    const fila = el('pltFila');
    const resumo = el('pltResumo');
    if (!fila) return;

    if (error) {
      fila.innerHTML = `<div class="empty">Não foi possível ler a fila de achados: ${escapeHtml(error)}</div>`;
      if (resumo) resumo.innerHTML = '';
      return;
    }

    const achados = ordenarFila(Array.isArray(data) ? data : []);
    const agora = Date.now();

    if (resumo) {
      const contagem = { critical: 0, high: 0, medium: 0, low: 0 };
      for (const f of achados) {
        if (contagem[f.severity] != null) contagem[f.severity] += 1;
      }
      resumo.innerHTML = `<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        ${['critical', 'high', 'medium', 'low'].filter(s => contagem[s]).map(s => `
          <span style="display:inline-flex;align-items:center;gap:6px;font-size:11px;background:var(--sf);border:1px solid var(--bd1);border-radius:999px;padding:3px 10px">
            <span style="width:7px;height:7px;border-radius:50%;background:${corSeveridade(s)}"></span>
            ${contagem[s]} ${escapeHtml(rotuloSeveridade(s).toLowerCase())}
          </span>`).join('')}
        <span style="font-size:11px;color:#64748b;margin-left:auto">${achados.length} aberto(s) · mais grave e mais antigo primeiro</span>
      </div>`;
    }

    if (!achados.length) {
      fila.innerHTML = '<div class="empty" style="padding:2rem">Nenhum achado aberto. Nada para atender neste plantão.</div>';
      return;
    }

    fila.innerHTML = `<div style="display:flex;flex-direction:column;gap:9px">
      ${achados.map(f => htmlCartao(f, agora)).join('')}
    </div>`;

    // Mesma convencao das outras telas: o dossie do achado le selectedFinding.
    fila.querySelectorAll('[data-open]').forEach(botao => {
      botao.addEventListener('click', () => {
        setState({ selectedFinding: botao.dataset.open });
        navigate('#/incidente');
      });
    });
  }

  carregar();
  pollTimer = setInterval(carregar, 30000);

  return () => {
    _disposed = true;
    if (pollTimer) clearInterval(pollTimer);
  };
}
