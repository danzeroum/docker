/* Cockpit = grade de módulos para um escopo (doc 10 §1).
 *
 * O núcleo NÃO conhece módulo nenhum pelo nome. Ele itera o registro, filtra
 * por escopo, ordena pelo layout e chama `render(escopo, dados)`. É o teste de
 * aberto/fechado do doc 10 §4: acrescentar módulo é registrar um arquivo.
 *
 * Strategy é o padrão aqui (doc 10 §3): o render por escopo é a estratégia, e o
 * cockpit é quem a aplica sem saber qual é.
 *
 * ---------------------------------------------------------------------------
 * Montar UMA vez, atualizar sempre (doc 13 §1)
 * ---------------------------------------------------------------------------
 * Até aqui `pintarCockpit` desmontava e remontava a grade INTEIRA a cada
 * leitura do kernel. O custo não era só a repintura: remontar significava
 * refazer as buscas próprias de cada módulo, reabrir os `EventSource` da
 * timeline e do follow de logs, e devolver ao começo qualquer estado que o
 * módulo tivesse — janela de métricas escolhida, termo digitado, scroll.
 *
 * Agora a grade tem uma ASSINATURA (escopo + ids visíveis + larguras). Enquanto
 * ela não muda, `pintarCockpit` não toca no DOM da grade: chama `atualizar` em
 * cada módulo montado e cada um escreve nos próprios nós. A grade só é
 * reconstruída quando o operador muda alguma coisa — ocultar, mover, trocar de
 * preset, mudar de escopo. Nunca por leitura.
 *
 * Contrato de retorno do `render`, retrocompatível:
 *   - `function`                → dispose (o que os módulos já devolviam);
 *   - `{ atualizar?, dispose? }` → `atualizar(dados)` a cada leitura;
 *   - nada                      → módulo estático, nunca reprocessado.
 */

import { escapeHtml } from '../fmt.js';
import { porId } from './registry.js';

/* Um registro por ALVO: dois cockpits podem estar na tela ao mesmo tempo (a
 * grade de fundo e a subtela do container), e o desmonte de um não pode levar
 * os módulos do outro. Vazar dispose é vazar poller — foi assim que o
 * `let pollTimer` duplicado matou o main.js antes. */
const _montagens = new WeakMap();
/* Os alvos vivos, para o desmonte global do `beforeunload` e dos testes.
 * WeakMap não é iterável, e um Set de nós seria vazamento — daí WeakRef. */
let _alvos = new Set();

function esquecer(alvo) {
  for (const ref of [..._alvos]) {
    if (ref.deref() === alvo || ref.deref() === undefined) _alvos.delete(ref);
  }
}

function disporModulo(montado) {
  try {
    if (typeof montado.dispose === 'function') montado.dispose();
  } catch { /* dispose que levanta não impede os outros */ }
}

/** Desmonta os módulos de um alvo (ou de todos, sem argumento). */
export function desmontar(alvo) {
  if (alvo) {
    const m = _montagens.get(alvo);
    if (!m) return;
    for (const [, montado] of m.mods) disporModulo(montado);
    _montagens.delete(alvo);
    esquecer(alvo);
    return;
  }
  for (const ref of _alvos) {
    const el = ref.deref();
    if (el) desmontar(el);
  }
  _alvos = new Set();
}

function caixaHtml(mod, span) {
  return `<section class="mod" data-modulo="${escapeHtml(mod.id)}" style="grid-column:span ${span}">`
    + `<header class="mod-head"><h2 class="mod-nome">${escapeHtml(mod.nome)}</h2>`
    + `<span class="mod-sub" data-sub="${escapeHtml(mod.id)}"></span></header>`
    + `<div class="mod-corpo" id="mod-${escapeHtml(mod.id)}"></div>`
    + `</section>`;
}

/* A assinatura descreve a GRADE, não o dado: mesmo escopo, mesmos módulos
 * visíveis, mesmas larguras ⇒ nenhum nó precisa nascer ou morrer. */
function assinaturaDe(escopo, visiveis, cheios) {
  return `${escopo.t}/${escopo.id || ''}|`
    + visiveis.map((m) => `${m.id}:${cheios.has(m.id) ? 12 : m.span}`).join(',');
}

function normalizar(retorno) {
  if (typeof retorno === 'function') return { dispose: retorno, atualizar: null };
  if (retorno && typeof retorno === 'object') {
    return {
      dispose: typeof retorno.dispose === 'function' ? retorno.dispose : null,
      atualizar: typeof retorno.atualizar === 'function' ? retorno.atualizar : null,
    };
  }
  return { dispose: null, atualizar: null };
}

/**
 * Pinta (ou atualiza) a grade de um escopo.
 *
 * @param {HTMLElement} alvo
 * @param {object} escopo
 * @param {object} estado  layout reconciliado
 * @param {object} dados   payload compartilhado (overview, findings, ...)
 */
export function pintarCockpit(alvo, escopo, estado, dados) {
  if (!alvo) return;

  const ocultos = new Set(estado.ocultos || []);
  const cheios = new Set(estado.cheios || []);
  const visiveis = (estado.ordem || [])
    .map((id) => porId(id))
    .filter((m) => m && !ocultos.has(m.id) && m.escopos.includes(escopo.t));

  const assinatura = assinaturaDe(escopo, visiveis, cheios);
  const montagem = _montagens.get(alvo);

  /* Caminho da LEITURA: a grade já é esta. Nenhum nó nasce, nenhum morre. */
  if (montagem && montagem.assinatura === assinatura) {
    for (const [id, montado] of montagem.mods) {
      if (!montado.atualizar) continue;
      try {
        montado.atualizar(dados);
      } catch (e) {
        // Falha de atualização degrada o módulo, não a grade — e o card
        // continua com o último dado bom em vez de virar caixa de erro.
        // eslint-disable-next-line no-console
        console.error(`módulo ${id} ao atualizar:`, e);
      }
    }
    return;
  }

  /* Caminho da MUDANÇA: só chega aqui por ação do operador ou troca de escopo. */
  desmontar(alvo);

  if (!visiveis.length) {
    alvo.innerHTML = '<div class="empty">Nenhum módulo visível neste cockpit. '
      + 'Abra Personalizar para exibir módulos.</div>';
    return;
  }

  alvo.innerHTML = `<div class="grade">${
    visiveis.map((m) => caixaHtml(m, cheios.has(m.id) ? 12 : m.span)).join('')
  }</div>`;

  const mods = new Map();
  // Render por módulo, isolado: módulo que levanta mostra erro no próprio card
  // e não derruba os outros (degradação por módulo, doc 12 §testes).
  for (const mod of visiveis) {
    const corpo = document.getElementById(`mod-${mod.id}`);
    if (!corpo) continue;
    try {
      mods.set(mod.id, normalizar(mod.render(escopo, dados, corpo)));
    } catch (e) {
      corpo.innerHTML = `<div class="empty">Falha ao desenhar este módulo</div>`;
      // eslint-disable-next-line no-console
      console.error(`módulo ${mod.id}:`, e);
    }
  }
  _montagens.set(alvo, { assinatura, mods });
  _alvos.add(new WeakRef(alvo));
}

/** Subtítulo de um módulo (ex.: "raw 24h · agregado 30d" nas Métricas). */
export function definirSub(id, texto) {
  const el = document.querySelector(`[data-sub="${id}"]`);
  if (el && el.textContent !== (texto || '')) el.textContent = texto || '';
}

/** Só para teste: quantos módulos estão montados num alvo. */
export function _montados(alvo) {
  const m = _montagens.get(alvo);
  return m ? [...m.mods.keys()] : [];
}
