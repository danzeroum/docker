import { apiGet, apiPost, apiPatch, cancel } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { showToast, showUnlockModal } from '../notifications.js';

// Estrutura do board, nao dado: os rotulos das 4 colunas do contrato §9.
const COLUNAS = [
  { key: 'todo', label: 'A fazer' },
  { key: 'doing', label: 'Em andamento' },
  { key: 'blocked', label: 'Bloqueada' },
  { key: 'done', label: 'Concluída' },
];

const PROXIMA = { todo: 'doing', doing: 'done', blocked: 'doing', done: 'todo' };

export function renderTarefas(container) {
  let pollTimer = null;

  function cartao(t) {
    const auto = t.origem === 'auto';
    const etiqueta = auto
      ? `<span class="task-tag auto">do diagnóstico</span>`
      : `<span class="task-tag">manual</span>`;
    const alvo = t.target
      ? `<div class="task-target">${escapeHtml(t.target)}</div>`
      : '';
    const nota = t.note
      ? `<div class="task-note">${escapeHtml(t.note)}</div>`
      : '';
    const detalhe = t.detail
      ? `<div class="task-detail">${escapeHtml(t.detail)}</div>`
      : '';
    const destino = PROXIMA[t.col] || 'doing';
    const rotuloDestino = (COLUNAS.find(c => c.key === destino) || {}).label || destino;
    return `<article class="task-card" data-id="${escapeHtml(t.id)}">
      <div class="task-head">${etiqueta}</div>
      <h3 class="task-title">${escapeHtml(t.title)}</h3>
      ${alvo}
      ${detalhe}
      ${nota}
      <div class="task-actions">
        <button type="button" class="action-btn task-move" data-id="${escapeHtml(t.id)}" data-col="${escapeHtml(destino)}">
          Mover para ${escapeHtml(rotuloDestino)}
        </button>
      </div>
    </article>`;
  }

  function render(data) {
    const colunas = data?.columns || [];
    const porChave = {};
    for (const c of colunas) porChave[c.key] = c.tasks || [];

    let html = `<div class="content"><div class="section">
      <div class="section-head"><div><h2 class="section-title">Tarefas</h2></div>
        <button type="button" class="action-btn" id="novaTarefa">Nova tarefa</button>
      </div>
      <div class="kanban">`;
    for (const col of COLUNAS) {
      const itens = porChave[col.key] || [];
      html += `<section class="kanban-col" data-col="${col.key}" aria-label="${col.label}">
        <header class="kanban-head">
          <span class="kanban-title">${col.label}</span>
          <span class="kanban-count">${itens.length}</span>
        </header>
        <div class="kanban-body">
          ${itens.length ? itens.map(cartao).join('') : '<div class="empty">—</div>'}
        </div>
      </section>`;
    }
    html += `</div></div></div>`;
    container.innerHTML = html;
    ligarEventos();
  }

  async function comUnlock(fn) {
    let r = await fn();
    const erro = r?.error || '';
    if (erro && (erro.includes('403') || erro.includes('Unlock') ||
                 erro.includes('ausente') || erro.includes('destravamento'))) {
      if (await showUnlockModal()) r = await fn();
    }
    return r;
  }

  function ligarEventos() {
    container.querySelectorAll('.task-move').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        const col = btn.dataset.col;
        btn.disabled = true;
        const { error } = await comUnlock(() =>
          apiPatch('task-' + id, `/api/tasks/${encodeURIComponent(id)}`, { col }));
        if (error) {
          showToast(error, 'error');
          btn.disabled = false;
          return;
        }
        carregar();
      });
    });

    container.querySelector('#novaTarefa')?.addEventListener('click', async () => {
      const title = window.prompt('Título da tarefa');
      if (!title || !title.trim()) return;
      const { error } = await comUnlock(() =>
        apiPost('task-nova', '/api/tasks', {
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: title.trim() }),
        }));
      if (error) { showToast(error, 'error'); return; }
      carregar();
    });
  }

  async function carregar() {
    const { data, error } = await apiGet('tasks', '/api/tasks');
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
    cancel('tasks');
  };
}
