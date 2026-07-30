/* Régua do kernel — vitais + 1 chip por módulo (doc 09 §A, doc 10 §1).
 *
 * NÃO é módulo, é chrome. Invariante 1 do doc 10: os vitais do host não podem
 * ser ocultados, arrastados nem cobertos pela subtela. Por isso a régua vive
 * fora da área rolável e fora do registro.
 *
 * Invariante 3: módulo oculto mantém o chip vivo e clicável. O chip lê o
 * `summary` do /api/overview — 1 chamada, não 1 por chip (doc 09 §B) — e clicar
 * nele reexibe o módulo. É o que impede "ocultar" de virar "perder o dado".
 *
 * Um dado, uma origem (doc 10 §4): chip e módulo leem o MESMO payload. Nunca
 * duas consultas que possam divergir na mesma tela.
 */

import { escapeHtml } from '../fmt.js';
import { doEscopo, porId } from './registry.js';
import { tipoDeCockpit } from './escopo.js';

const ID_REGUA = 'kernelRegua';

function pct(v) {
  return typeof v === 'number' ? `${Math.round(v)}%` : '—';
}

function tomDeVital(v, atencao, critico) {
  if (typeof v !== 'number') return 'neutro';
  if (v >= critico) return 'bad';
  if (v >= atencao) return 'warn';
  return 'ok';
}

/* Vitais: sempre os quatro, sempre nesta ordem, sempre presentes. Ausência de
 * amostra é "—", não 0 — zero de CPU é uma afirmação, e uma falsa. */
function vitaisHtml(vitals) {
  const v = vitals || {};
  const disco = v.disk || {};
  const itens = [
    ['CPU', pct(v.cpu_pct), tomDeVital(v.cpu_pct, 70, 90)],
    ['RAM', pct(v.mem_pct), tomDeVital(v.mem_pct, 80, 92)],
    ['Disco', pct(disco.pct), tomDeVital(disco.pct, 80, 90)],
    ['Swap', pct(v.swap_pct), tomDeVital(v.swap_pct, 50, 80)],
  ];
  return itens.map(([rotulo, valor, tom]) =>
    `<span class="rg-vital rg-${tom}"><span class="rg-rot">${rotulo}</span><span class="rg-val">${valor}</span></span>`
  ).join('');
}

/* Chips de módulo. Um módulo só entra na régua se declarar `chip()` E o chip
 * devolver conteúdo — módulo sem chave no summary não inventa chip. */
function chipsHtml(escopo, summary, estado) {
  const ocultos = new Set(estado.ocultos || []);
  const ordem = estado.ordem || [];
  const partes = [];

  for (const id of ordem) {
    const mod = porId(id);
    if (!mod || !mod.chip) continue;
    if (!mod.escopos.includes(escopo.t)) continue;

    let dados = null;
    try {
      dados = mod.chip(escopo, summary);
    } catch {
      // Chip que levanta é chip que não aparece. Não derruba a régua inteira.
      continue;
    }
    if (!dados || !dados.valor) continue;

    const oculto = ocultos.has(id);
    const velho = dados.stale ? ' rg-velho' : '';
    partes.push(
      `<button type="button" class="rg-chip${oculto ? ' rg-oculto' : ''}${velho}"`
      + ` data-modulo="${escapeHtml(id)}" aria-pressed="${oculto ? 'false' : 'true'}"`
      + ` title="${escapeHtml(dados.titulo || mod.nome)}${oculto ? ' — oculto, clique para exibir' : ''}${dados.stale ? ' (dado velho)' : ''}">`
      + `<span class="rg-rot">${escapeHtml(dados.rotulo || mod.nome)}</span>`
      + `<span class="rg-val">${escapeHtml(String(dados.valor))}</span>`
      + `</button>`
    );
  }
  return partes.join('');
}

export function montarRegua(alvo) {
  if (!alvo) return null;
  alvo.innerHTML = `<div class="regua" id="${ID_REGUA}" role="group" aria-label="Vitais e resumo dos módulos"></div>`;
  return document.getElementById(ID_REGUA);
}

/**
 * Redesenha a régua.
 * @param {object} opts.escopo    escopo aberto
 * @param {object} opts.overview  payload de /api/overview (vitals + summary)
 * @param {object} opts.estado    layout do tipo de cockpit atual
 * @param {function} opts.onChip  callback(id) quando um chip é clicado
 */
export function pintarRegua(opts) {
  const el = document.getElementById(ID_REGUA);
  if (!el) return;
  const { escopo, overview, estado, onChip } = opts;
  const summary = (overview && overview.summary) || null;

  el.innerHTML =
    `<div class="rg-vitais">${vitaisHtml(overview && overview.vitals)}</div>`
    + `<div class="rg-chips">${chipsHtml(escopo, summary, estado)}</div>`;

  if (typeof onChip === 'function') {
    el.querySelectorAll('.rg-chip').forEach((btn) => {
      btn.addEventListener('click', () => onChip(btn.dataset.modulo));
    });
  }
}

/* Faixa crítica — invariante 2: é do HOST inteiro e aparece em qualquer escopo,
 * inclusive dentro do cockpit de um container de outra stack. Também fora do
 * registro: não é ocultável. */
export function pintarFaixaCritica(alvo, achados) {
  if (!alvo) return;
  const lista = Array.isArray(achados) ? achados : [];
  const critico = lista.find((f) => f && f.severity === 'critical');
  if (!critico) {
    alvo.innerHTML = '';
    alvo.hidden = true;
    return;
  }
  alvo.hidden = false;
  const titulo = critico.title_plain || critico.title || '';
  const corpo = critico.interpretation_plain || critico.interpretation || '';
  const desde = critico.first_seen || '';
  alvo.innerHTML =
    `<div class="faixa-critica" role="alert">`
    + `<span class="fc-sev">crítico</span>`
    + `<span class="fc-titulo">${escapeHtml(titulo)}</span>`
    + (corpo ? `<span class="fc-corpo">${escapeHtml(corpo)}</span>` : '')
    + (desde ? `<span class="fc-desde">desde ${escapeHtml(desde)}</span>` : '')
    + `</div>`;
}

/* Helper que os módulos usam para montar chip a partir do summary, já tratando
 * a degradação: chave nula + stale_since preenchido = chip velho, não chip zero.
 * Centralizado aqui para os 13 módulos não repetirem a mesma checagem. */
export function chipDoSummary(summary, chave, montar) {
  if (!summary) return null;
  const valor = summary[chave];
  const stale = !!(summary.stale_since && summary.stale_since[chave]);
  if (valor === null || valor === undefined) {
    // Sem dado: chip presente, valor "—", declarado velho. Ausência ≠ zero.
    return { valor: '—', stale: true, titulo: `${chave}: sem leitura recente` };
  }
  const saida = montar(valor);
  if (!saida || !saida.valor) return null;
  return { ...saida, stale: stale || !!saida.stale };
}
