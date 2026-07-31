/* Subtela central — o cockpit de um container sobre a Visão geral.
 *
 * Central e não página cheia por uma razão de requisito, não de estética
 * (doc 10 §2): o overlay abre ABAIXO do header e da régua, então os vitais e a
 * faixa crítica continuam visíveis **por construção**. Página cheia esconderia
 * a régua sob scroll e quebraria o invariante 1.
 *
 * Fecha por Esc, ✕ e clique no fundo — os três, porque cada um é o reflexo de
 * um usuário diferente e nenhum deles deve ficar preso.
 */

import { escapeHtml } from '../fmt.js';

const ID_OVERLAY = 'subtelaOverlay';
const ID_CORPO = 'subtelaCorpo';

let _onFechar = null;
let _teclaLigada = false;
let _aberta = null;

function aoTeclar(ev) {
  if (ev.key === 'Escape' && _onFechar) _onFechar();
}

/** O corpo da subtela aberta, ou `null`. Quem monta módulos aqui precisa dele
 *  para desmontá-los antes de fechar. */
export function corpoSubtela(alvo) {
  if (!alvo || alvo.hidden) return null;
  return document.getElementById(ID_CORPO);
}

/**
 * Abre — ou reaproveita — a subtela de um container.
 *
 * Idempotente por título: reabrir a MESMA subtela devolve o corpo que já está
 * na tela em vez de recriá-lo. Sem isso, cada leitura do kernel trocava o nó do
 * corpo, e com ele iam embora o scroll da lista de logs, o texto digitado na
 * busca e os módulos montados dentro (doc 13 §1).
 */
export function abrirSubtela(alvo, titulo, subtitulo, onFechar) {
  if (!alvo) return null;
  _onFechar = onFechar;
  if (_aberta === titulo && !alvo.hidden) {
    const sub = alvo.querySelector('.sub-chip');
    if (sub && sub.textContent !== (subtitulo || '')) sub.textContent = subtitulo || '';
    return document.getElementById(ID_CORPO);
  }
  _aberta = titulo;
  alvo.hidden = false;
  alvo.innerHTML = `<div class="sub-fundo" data-acao="fechar"></div>
    <div class="sub-painel" role="dialog" aria-modal="false" aria-label="${escapeHtml(titulo)}">
      <header class="sub-topo">
        <button type="button" class="sub-voltar" data-acao="fechar">&larr; Visão geral</button>
        <div class="sub-ident">
          <strong class="sub-titulo">${escapeHtml(titulo)}</strong>
          ${subtitulo ? `<span class="sub-chip">${escapeHtml(subtitulo)}</span>` : ''}
        </div>
        <button type="button" class="sub-fechar" data-acao="fechar" title="Fechar (Esc)">✕</button>
      </header>
      <div class="sub-corpo" id="${ID_CORPO}"></div>
    </div>`;

  alvo.querySelectorAll('[data-acao="fechar"]').forEach((el) => {
    el.addEventListener('click', () => { if (_onFechar) _onFechar(); });
  });

  if (!_teclaLigada) {
    document.addEventListener('keydown', aoTeclar);
    _teclaLigada = true;
  }
  return document.getElementById(ID_CORPO);
}

export function fecharSubtela(alvo) {
  _onFechar = null;
  if (!alvo) return;
  if (_aberta === null && alvo.hidden) return;
  _aberta = null;
  alvo.hidden = true;
  alvo.innerHTML = '';
}

export function subtelaAberta(alvo) {
  return !!(alvo && !alvo.hidden && alvo.innerHTML);
}

export { ID_OVERLAY };
