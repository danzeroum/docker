/* Painel Personalizar — ocultar / mover / largura / presets / restaurar.
 *
 * Reconhecimento em vez de memorização (doc 10 §2): o painel lista TODOS os
 * módulos com olho, largura e ordem, e explica o contrato — "oculto continua na
 * régua". Sem isso, ocultar parece perder.
 *
 * Drag só existe com o painel aberto, para não conflitar com os cliques de
 * navegação das linhas (doc 10 §2). Os ↑↓ ficam sempre, e produzem o MESMO
 * estado persistido que o drag — HTML5 drag não funciona em touch, e a régua
 * não pode ficar inacessível num tablet por causa disso (risco assumido no
 * doc 10 §2, mitigado aqui).
 */

import { escapeHtml } from '../fmt.js';
import { doEscopo, porId } from './registry.js';
import { doTipo } from './presets.js';
import {
  alternarCheio, alternarOculto, aplicarPreset, mover, restaurar, trocar,
} from './layout.js';

const ID = 'painelPersonalizar';

let _aberto = false;
let _arrastando = null;

export function aberto() {
  return _aberto;
}

function linhaHtml(mod, estado) {
  const oculto = (estado.ocultos || []).includes(mod.id);
  const cheio = (estado.cheios || []).includes(mod.id);
  return `<li class="pz-linha" draggable="true" data-modulo="${escapeHtml(mod.id)}">
    <span class="pz-alca" aria-hidden="true">⋮⋮</span>
    <button type="button" class="pz-olho" data-acao="olho" data-id="${escapeHtml(mod.id)}"
      aria-pressed="${oculto ? 'false' : 'true'}"
      title="${oculto ? 'Exibir na grade' : 'Ocultar da grade (o chip continua na régua)'}">
      ${oculto ? '◌' : '◉'}
    </button>
    <span class="pz-nome">${escapeHtml(mod.nome)}</span>
    <button type="button" class="pz-larg" data-acao="largura" data-id="${escapeHtml(mod.id)}"
      aria-pressed="${cheio ? 'true' : 'false'}" title="Largura inteira">
      ${cheio ? 'inteira' : 'meia'}
    </button>
    <button type="button" class="pz-mv" data-acao="subir" data-id="${escapeHtml(mod.id)}" title="Subir">↑</button>
    <button type="button" class="pz-mv" data-acao="descer" data-id="${escapeHtml(mod.id)}" title="Descer">↓</button>
  </li>`;
}

function presetsHtml(tipo, estado) {
  const opcoes = doTipo(tipo).map((p) =>
    `<button type="button" class="pz-preset${estado.preset === p.id ? ' pz-ativo' : ''}"
      data-acao="preset" data-id="${escapeHtml(p.id)}">${escapeHtml(p.label)}</button>`
  ).join('');
  // Ajuste manual não apaga o preset de origem, só deixa de afirmá-lo.
  const rotulo = estado.preset ? '' : '<span class="pz-perso">personalizado</span>';
  return `<div class="pz-presets">${opcoes}${rotulo}</div>`;
}

/**
 * @param {HTMLElement} alvo    onde o painel vive
 * @param {object} escopo
 * @param {object} estado
 * @param {function} onMudanca  recebe o novo estado
 */
export function pintarPainel(alvo, escopo, estado, onMudanca) {
  if (!alvo) return;
  if (!_aberto) {
    alvo.innerHTML = '';
    alvo.hidden = true;
    return;
  }
  alvo.hidden = false;
  const tipo = escopo.t;
  // Lista TODOS os módulos do escopo, na ordem do layout — incluindo os que não
  // estão em nenhum preset (Plantão, Executivo, Backend, Topologia). É aqui que
  // eles existem para o operador.
  const doEsc = new Set(doEscopo(tipo).map((m) => m.id));
  const ordenados = (estado.ordem || [])
    .filter((id) => doEsc.has(id))
    .map((id) => porId(id))
    .filter(Boolean);

  alvo.innerHTML = `<div class="pz" id="${ID}" role="dialog" aria-label="Personalizar cockpit">
    <div class="pz-topo">
      <strong class="pz-titulo">Personalizar</strong>
      <button type="button" class="pz-fechar" data-acao="fechar" title="Fechar">✕</button>
    </div>
    ${presetsHtml(tipo, estado)}
    <ul class="pz-lista">${ordenados.map((m) => linhaHtml(m, estado)).join('')}</ul>
    <p class="pz-nota">Módulo oculto continua na régua: o chip fica vivo e clicável.
      O arranjo vale para todos os cockpits deste tipo, não só para este.</p>
    <button type="button" class="pz-restaurar" data-acao="restaurar">Restaurar padrão</button>
  </div>`;

  const painel = document.getElementById(ID);
  if (!painel) return;

  painel.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-acao]');
    if (!btn) return;
    const acao = btn.dataset.acao;
    const id = btn.dataset.id;
    let novo = estado;
    if (acao === 'olho') novo = alternarOculto(tipo, estado, id);
    else if (acao === 'largura') novo = alternarCheio(tipo, estado, id);
    else if (acao === 'subir') novo = mover(tipo, estado, id, -1);
    else if (acao === 'descer') novo = mover(tipo, estado, id, +1);
    else if (acao === 'preset') novo = aplicarPreset(tipo, id);
    else if (acao === 'restaurar') novo = restaurar(tipo);
    else if (acao === 'fechar') { fechar(); onMudanca(estado); return; }
    else return;
    onMudanca(novo);
  });

  // Drag: swap ao soltar, mesma operação dos ↑↓ (estado idêntico).
  painel.querySelectorAll('.pz-linha').forEach((li) => {
    li.addEventListener('dragstart', () => { _arrastando = li.dataset.modulo; });
    li.addEventListener('dragend', () => { _arrastando = null; });
    li.addEventListener('dragover', (ev) => ev.preventDefault());
    li.addEventListener('drop', (ev) => {
      ev.preventDefault();
      const destino = li.dataset.modulo;
      if (!_arrastando || _arrastando === destino) return;
      onMudanca(trocar(tipo, estado, _arrastando, destino));
      _arrastando = null;
    });
  });
}

export function abrir() { _aberto = true; }
export function fechar() { _aberto = false; }
export function alternar() { _aberto = !_aberto; return _aberto; }
