/* Módulo `stacks` — agregado por projeto compose (escopo host).
 *
 * Clicar numa stack abre o mini cockpit dela: mesmo registro de módulos, escopo
 * `{t:'stack', id}`. É de graça — não existe tela de stack, existe escopo.
 *
 * Lista chaveada pelo id da stack (doc 13): subir ou descer um container muda o
 * contador `running/total` no nó que já existe, e nada mais é tocado.
 */

import { chipDoSummary } from '../kernel/regua.js';
import { atributo, classeUnica, deMolde, lista, mostrar, texto } from '../kernel/patch.js';

const TONS = ['ok', 'warn', 'bad', 'exited'];

const MOLDE_LINHA = '<button type="button" class="mod-linha" data-stack="">'
  + '<span class="item-status"></span>'
  + '<span class="mod-nome-cel"></span>'
  + '<span class="mod-meta"></span>'
  + '</button>';

const CASCA = '<div class="mod-lista" data-lista></div>'
  + '<div class="empty" data-vazio hidden>Nenhuma stack encontrada</div>';

export default {
  id: 'stacks',
  nome: 'Stacks',
  escopos: ['host'],
  span: 6,

  chip: (escopo, summary) => chipDoSummary(summary, 'stacks', (v) => ({
    rotulo: 'Stacks',
    valor: `${v.up}/${v.total}`,
    // stopped_with_domain null = ingress indisponível, não "nenhuma exposta".
    titulo: v.stopped_with_domain == null
      ? 'stacks inteiras no ar / total (exposição não avaliada)'
      : `${v.stopped_with_domain} parada(s) com domínio publicado`,
  })),

  render: (escopo, dados, corpo) => {
    let vivo = true;
    corpo.innerHTML = CASCA;
    const recipiente = corpo.querySelector('[data-lista]');
    const vazio = corpo.querySelector('[data-vazio]');

    recipiente.addEventListener('click', (ev) => {
      const linha = ev.target.closest ? ev.target.closest('[data-stack]') : null;
      if (!linha) return;
      const abrir = dados && dados.abrirStack;
      if (typeof abrir === 'function') abrir(linha.dataset.stack);
    });

    function atualizar(novos) {
      if (!vivo) return;
      const stacks = ((novos && novos.overview) || {}).stacks || [];
      mostrar(vazio, !stacks.length);
      lista(recipiente, stacks, {
        chave: (s) => s.id,
        criar: () => deMolde(MOLDE_LINHA),
        atualizar: (el, s) => {
          atributo(el, 'data-stack', s.id);
          classeUnica(el.querySelector('.item-status'), TONS,
            TONS.includes(s.worst) ? s.worst : 'exited');
          texto(el.querySelector('.mod-nome-cel'), s.id);
          texto(el.querySelector('.mod-meta'), `${s.running}/${s.total}`, { flash: true });
        },
      });
    }

    atualizar(dados);
    return { atualizar, dispose: () => { vivo = false; } };
  },
};
