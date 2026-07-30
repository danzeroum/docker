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
 *
 * A régua é desenhada UMA vez (doc 13). Cada leitura escreve no nó que já
 * existe: `:hover` sobre um chip sobrevive à leitura, o valor que mudou pisca
 * por 0,9s, e o `title` de quem não mudou não é reescrito à toa. Reconstruir a
 * régua a cada 15s era o que fazia o chip escapar do ponteiro no meio do clique.
 *
 * A pílula "ao vivo" vive aqui pelo mesmo motivo dos vitais: sem indicador o
 * olho não distingue "parado" de "atualizando", e a primeira leitura de uma tela
 * sem sinal de vida é sempre "travou".
 */

import { porId } from './registry.js';
import {
  atributo, classe, classeUnica, deMolde, lista, mostrar, texto,
} from './patch.js';

const ID_REGUA = 'kernelRegua';

const TONS = ['rg-ok', 'rg-warn', 'rg-bad', 'rg-neutro'];

/* Sempre os quatro, sempre nesta ordem, sempre presentes. Ausência de amostra é
 * "—", não 0 — zero de CPU é uma afirmação, e uma falsa. */
const VITAIS = [
  { chave: 'CPU', ler: (v) => v.cpu_pct, atencao: 70, critico: 90 },
  { chave: 'RAM', ler: (v) => v.mem_pct, atencao: 80, critico: 92 },
  { chave: 'Disco', ler: (v) => (v.disk || {}).pct, atencao: 80, critico: 90 },
  { chave: 'Swap', ler: (v) => v.swap_pct, atencao: 50, critico: 80 },
];

const MOLDE_VITAL =
  '<span class="rg-vital"><span class="rg-rot"></span><span class="rg-val"></span></span>';

/* O chip é escrito como `button` com a classe `rg-chip`, por extenso e de
 * propósito: é assim que o guarda de acessibilidade confere que ele não voltou
 * a ser uma `div` com handler de clique (test_acessibilidade). O molde nasce
 * vazio — dado entra por textContent, e por isso nenhum payload da régua tem
 * caminho para virar markup. */
const MOLDE_CHIP =
  '<button type="button" class="rg-chip" data-modulo="">'
  + '<span class="rg-rot"></span><span class="rg-val"></span></button>';

const MOLDE_REGUA =
  `<div class="regua" id="${ID_REGUA}" role="group" aria-label="Vitais e resumo dos módulos">`
  + '<span class="rg-vivo" data-vivo title="lendo do daemon a cada ciclo">'
  + '<span class="rg-vivo-ponto"><span class="rg-vivo-pulso"></span></span>'
  + '<span class="rg-vivo-rot" data-vivo-rot>ao vivo</span>'
  + '<span class="rg-vivo-trilho"><span class="rg-vivo-varredura" data-varredura></span></span>'
  + '</span>'
  + '<div class="rg-vitais" data-vitais></div>'
  + '<div class="rg-chips" data-chips></div>'
  + '</div>';

let _onChip = null;
let _delegado = false;

function pct(v) {
  return typeof v === 'number' ? `${Math.round(v)}%` : '—';
}

function tomDeVital(v, atencao, critico) {
  if (typeof v !== 'number') return 'rg-neutro';
  if (v >= critico) return 'rg-bad';
  if (v >= atencao) return 'rg-warn';
  return 'rg-ok';
}

export function montarRegua(alvo) {
  if (!alvo) return null;
  alvo.innerHTML = MOLDE_REGUA;
  const el = document.getElementById(ID_REGUA);
  const chips = el && el.querySelector ? el.querySelector('[data-chips]') : null;
  if (chips && !_delegado) {
    /* Delegação: UM listener na faixa de chips, instalado uma vez. Religar
     * handler por chip a cada leitura era metade do custo da repintura — e,
     * pior, trocava o handler debaixo de um clique já começado. */
    chips.addEventListener('click', (ev) => {
      const btn = ev.target && ev.target.closest ? ev.target.closest('.rg-chip') : null;
      if (btn && typeof _onChip === 'function') _onChip(btn.dataset.modulo);
    });
    _delegado = true;
  }
  return el;
}

/* --- pílula "ao vivo" ----------------------------------------------------- */

/* A varredura reinicia a cada leitura: é o que diferencia "atualizando" de
 * "parado com um ponto verde". Reiniciar por troca de classe, não por reflow
 * forçado — mesma razão do flash (patch.js). */
const VARREDURAS = ['varre-a', 'varre-b'];

/** Marca que uma leitura acabou de chegar: reinicia a varredura de 2,2s. */
export function marcarLeitura() {
  const trilho = document.querySelector('[data-varredura]');
  if (!trilho || !trilho.classList) return;
  const atual = trilho.classList.contains(VARREDURAS[0]) ? 0 : 1;
  classe(trilho, VARREDURAS[atual], false);
  classe(trilho, VARREDURAS[1 - atual], true);
}

/**
 * Pausa o indicador — durante o drag do Personalizar e enquanto o relógio está
 * parado (aba oculta). "ao vivo" enquanto nada é buscado seria mentira, e é
 * justamente essa mentira que faz o operador confiar no indicador errado.
 */
export function pausarVivo(pausado) {
  const pilula = document.querySelector('[data-vivo]');
  if (!pilula) return;
  classe(pilula, 'rg-pausado', !!pausado);
  texto(pilula.querySelector('[data-vivo-rot]'), pausado ? 'pausado' : 'ao vivo');
  atributo(pilula, 'title', pausado
    ? 'leitura pausada — volta ao soltar, ou ao voltar para esta aba'
    : 'lendo do daemon a cada ciclo');
}

/* --- vitais e chips ------------------------------------------------------- */

function pintarVitais(recipiente, vitals) {
  const v = vitals || {};
  lista(recipiente, VITAIS, {
    chave: (item) => item.chave,
    criar: () => deMolde(MOLDE_VITAL),
    atualizar: (el, item) => {
      const bruto = item.ler(v);
      texto(el.querySelector('.rg-rot'), item.chave);
      // flash: o vital que mudou se anuncia. Sem isso, quatro números que
      // trocam em silêncio são quatro números que ninguém vê trocar.
      texto(el.querySelector('.rg-val'), pct(bruto), { flash: true });
      classeUnica(el, TONS, tomDeVital(bruto, item.atencao, item.critico));
    },
  });
}

/* Chips de módulo. Um módulo só entra na régua se declarar `chip()` E o chip
 * devolver conteúdo — módulo sem chave no summary não inventa chip. */
function chipsDoEscopo(escopo, summary, estado) {
  const ocultos = new Set(estado.ocultos || []);
  const saida = [];
  for (const id of estado.ordem || []) {
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
    saida.push({ id, mod, dados, oculto: ocultos.has(id) });
  }
  return saida;
}

function pintarChips(recipiente, escopo, summary, estado) {
  lista(recipiente, chipsDoEscopo(escopo, summary, estado), {
    chave: (c) => c.id,
    criar: () => deMolde(MOLDE_CHIP),
    atualizar: (el, c) => {
      atributo(el, 'data-modulo', c.id);
      atributo(el, 'aria-pressed', c.oculto ? 'false' : 'true');
      atributo(el, 'title',
        `${c.dados.titulo || c.mod.nome}`
        + `${c.oculto ? ' — oculto, clique para exibir' : ''}`
        + `${c.dados.stale ? ' (dado velho)' : ''}`);
      classe(el, 'rg-oculto', c.oculto);
      classe(el, 'rg-velho', !!c.dados.stale);
      texto(el.querySelector('.rg-rot'), c.dados.rotulo || c.mod.nome);
      texto(el.querySelector('.rg-val'), String(c.dados.valor), { flash: true });
    },
  });
}

/**
 * Repinta a régua por PATCH — nenhum nó é recriado enquanto a identidade dos
 * chips não muda.
 *
 * @param {object} opts.escopo    escopo aberto
 * @param {object} opts.overview  payload de /api/overview (vitals + summary)
 * @param {object} opts.estado    layout do tipo de cockpit atual
 * @param {function} opts.onChip  callback(id) quando um chip é clicado
 */
export function pintarRegua(opts) {
  const el = document.getElementById(ID_REGUA);
  if (!el) return;
  const { escopo, overview, estado, onChip } = opts;
  if (typeof onChip === 'function') _onChip = onChip;

  pintarVitais(el.querySelector('[data-vitais]'), overview && overview.vitals);
  pintarChips(
    el.querySelector('[data-chips]'), escopo, (overview && overview.summary) || null, estado
  );
}

/* Faixa crítica — invariante 2: é do HOST inteiro e aparece em qualquer escopo,
 * inclusive dentro do cockpit de um container de outra stack. Também fora do
 * registro: não é ocultável.
 *
 * Também por patch: um alerta que se redesenha a cada leitura pisca sozinho, e
 * um alerta que pisca sozinho vira um alerta que ninguém lê. */
const MOLDE_FAIXA =
  '<div class="faixa-critica" role="alert">'
  + '<span class="fc-sev">crítico</span>'
  + '<span class="fc-titulo"></span>'
  + '<span class="fc-corpo"></span>'
  + '<span class="fc-desde"></span>'
  + '</div>';

export function pintarFaixaCritica(alvo, achados) {
  if (!alvo) return;
  const achadosLista = Array.isArray(achados) ? achados : [];
  const critico = achadosLista.find((f) => f && f.severity === 'critical');
  if (!critico) {
    mostrar(alvo, false);
    return;
  }
  if (!alvo.querySelector('.faixa-critica')) alvo.innerHTML = MOLDE_FAIXA;
  mostrar(alvo, true);
  const corpo = critico.interpretation_plain || critico.interpretation || '';
  const desde = critico.first_seen || '';
  texto(alvo.querySelector('.fc-titulo'), critico.title_plain || critico.title || '');
  texto(alvo.querySelector('.fc-corpo'), corpo);
  mostrar(alvo.querySelector('.fc-corpo'), !!corpo);
  texto(alvo.querySelector('.fc-desde'), desde ? `desde ${desde}` : '');
  mostrar(alvo.querySelector('.fc-desde'), !!desde);
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
