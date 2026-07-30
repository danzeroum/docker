import { apiGet, apiPost, apiPatch, cancel } from '../data.js';
import { showToast, showUnlockModal } from '../notifications.js';
import { assinar, TICK_MS } from '../kernel/relogio.js';
import { atributo, casca, deMolde, lista, mostrar, texto } from '../kernel/patch.js';

// Estrutura do board, nao dado: os rotulos das 4 colunas do contrato §9.
const COLUNAS = [
  { key: 'todo', label: 'A fazer' },
  { key: 'doing', label: 'Em andamento' },
  { key: 'blocked', label: 'Bloqueada' },
  { key: 'done', label: 'Concluída' },
];

const PROXIMA = { todo: 'doing', doing: 'done', blocked: 'doing', done: 'todo' };

/* Kanban é o pior caso do rebuild por leitura (doc 13): mover um cartão é um
 * gesto de dois passos — clicar em "Mover para" e ver o cartão trocar de
 * coluna. Com a coluna inteira redesenhada a cada 30s, o botão sumia debaixo do
 * ponteiro e o `disabled` que o próprio código tinha acabado de aplicar era
 * apagado pela leitura seguinte, liberando um segundo PATCH da mesma tarefa. */
const MOLDE_CARTAO = '<article class="task-card" data-id="">'
  + '<div class="task-head"><span class="task-tag" data-tag></span></div>'
  + '<h3 class="task-title" data-titulo></h3>'
  + '<div class="task-target" data-alvo hidden></div>'
  + '<div class="task-detail" data-detalhe hidden></div>'
  + '<div class="task-note" data-nota hidden></div>'
  + '<div class="task-actions">'
  + '<button type="button" class="action-btn task-move" data-id="" data-col=""></button>'
  + '</div></article>';

const MOLDE_COLUNA = '<section class="kanban-col" data-col="">'
  + '<header class="kanban-head">'
  + '<span class="kanban-title" data-rot></span>'
  + '<span class="kanban-count" data-n></span>'
  + '</header>'
  + '<div class="kanban-body" data-corpo></div>'
  + '<div class="empty" data-vazio hidden>—</div>'
  + '</section>';

const CASCA = '<div class="content"><div class="section">'
  + '<div class="section-head"><div><h2 class="section-title">Tarefas</h2></div>'
  + '<button type="button" class="action-btn" id="novaTarefa">Nova tarefa</button>'
  + '</div>'
  + '<div class="empty-field" data-erro hidden></div>'
  + '<div class="kanban" data-kanban></div>'
  + '</div></div>';

export function renderTarefas(container) {
  let pollTimer = null;
  let carregou = false;
  // Tarefa com PATCH em voo não é reabilitada pela leitura: era assim que um
  // segundo clique disparava a mesma mutação.
  const emVoo = new Set();

  async function comUnlock(fn) {
    let r = await fn();
    const erro = r?.error || '';
    if (erro && (erro.includes('403') || erro.includes('Unlock') ||
                 erro.includes('ausente') || erro.includes('destravamento'))) {
      if (await showUnlockModal()) r = await fn();
    }
    return r;
  }

  async function mover(btn) {
    const id = btn.dataset.id;
    const col = btn.dataset.col;
    emVoo.add(id);
    btn.disabled = true;
    const { error } = await comUnlock(() =>
      apiPatch('task-' + id, `/api/tasks/${encodeURIComponent(id)}`, { col }));
    emVoo.delete(id);
    if (error) {
      showToast(error, 'error');
      btn.disabled = false;
      return;
    }
    carregar();
  }

  async function nova() {
    const title = window.prompt('Título da tarefa');
    if (!title || !title.trim()) return;
    const { error } = await comUnlock(() =>
      apiPost('task-nova', '/api/tasks', {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim() }),
      }));
    if (error) { showToast(error, 'error'); return; }
    carregar();
  }

  casca(container, 'tarefas-v1', (el) => {
    el.innerHTML = CASCA;
    // Delegação: o cartão pode nascer e morrer, o handler não.
    el.addEventListener('click', (ev) => {
      const mv = ev.target.closest ? ev.target.closest('.task-move') : null;
      if (mv && !mv.disabled) { mover(mv); return; }
      const nv = ev.target.closest ? ev.target.closest('#novaTarefa') : null;
      if (nv) nova();
    });
  });

  const kanban = container.querySelector('[data-kanban]');
  const erro = container.querySelector('[data-erro]');

  function pintarCartao(el, t) {
    const destino = PROXIMA[t.col] || 'doing';
    const rotuloDestino = (COLUNAS.find(c => c.key === destino) || {}).label || destino;
    atributo(el, 'data-id', t.id);

    const tag = el.querySelector('[data-tag]');
    const auto = t.origem === 'auto';
    texto(tag, auto ? 'do diagnóstico' : 'manual');
    tag.classList.toggle('auto', auto);

    texto(el.querySelector('[data-titulo]'), t.title);
    for (const [sel, valor] of [['[data-alvo]', t.target], ['[data-detalhe]', t.detail], ['[data-nota]', t.note]]) {
      const no = el.querySelector(sel);
      mostrar(no, !!valor);
      if (valor) texto(no, valor);
    }

    const btn = el.querySelector('.task-move');
    atributo(btn, 'data-id', t.id);
    atributo(btn, 'data-col', destino);
    texto(btn, `Mover para ${rotuloDestino}`);
    btn.disabled = emVoo.has(t.id);
  }

  function render(data) {
    const porChave = {};
    for (const c of data?.columns || []) porChave[c.key] = c.tasks || [];

    lista(kanban, COLUNAS, {
      chave: (c) => c.key,
      criar: () => deMolde(MOLDE_COLUNA),
      atualizar: (col, def) => {
        const itens = porChave[def.key] || [];
        atributo(col, 'data-col', def.key);
        atributo(col, 'aria-label', def.label);
        texto(col.querySelector('[data-rot]'), def.label);
        texto(col.querySelector('[data-n]'), String(itens.length), { flash: true });
        mostrar(col.querySelector('[data-vazio]'), !itens.length);
        lista(col.querySelector('[data-corpo]'), itens, {
          chave: (t) => String(t.id),
          criar: () => deMolde(MOLDE_CARTAO),
          atualizar: pintarCartao,
        });
      },
    });
  }

  async function carregar() {
    const { data, error } = await apiGet('tasks', '/api/tasks');
    if (error) {
      // Erro só toma a tela enquanto não houve board. Depois disso, o board na
      // tela vale mais que uma mensagem: as tarefas continuam sendo as mesmas.
      if (!carregou) {
        mostrar(erro, true);
        texto(erro, error);
        mostrar(kanban, false);
      }
      return;
    }
    carregou = true;
    mostrar(erro, false);
    mostrar(kanban, true);
    render(data);
  }

  carregar();
  // 30s = 6 ticks do relógio compartilhado.
  pollTimer = assinar(carregar, 6 * TICK_MS);

  return () => {
    if (typeof pollTimer === 'function') pollTimer();
    pollTimer = null;
    cancel('tasks');
  };
}
