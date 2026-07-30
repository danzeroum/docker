import { apiGet, apiPost } from '../data.js';
import { showToast, showConfirmModal, showUnlockModal } from '../notifications.js';
import { assinar, TICK_MS } from '../kernel/relogio.js';
import { atributo, casca, classeUnica, deMolde, lista, mostrar, texto } from '../kernel/patch.js';

/* Projetos é a tela com os botões mais perigosos do cockpit — start e stop de
 * stack inteira, atrás do unlock. Ela reconstruía o grid a cada 10s, o que
 * significava trocar o botão "Parar" debaixo do ponteiro entre o `mousedown` e
 * o `mouseup`, e reabilitar um botão que o próprio código tinha desabilitado
 * enquanto a ação estava em voo. Agora o cartão é chaveado pelo nome do
 * projeto: leitura nova só troca rótulo, tom e `disabled` (doc 13). */
const MOLDE_CARD = '<div class="project-card" data-name="">'
  + '<div class="project-head">'
  + '<div><div class="project-name" data-nome></div>'
  + '<div class="project-path" data-caminho></div></div>'
  + '<div class="status-pill project-estado"><span class="dot"></span><span data-estado></span></div>'
  + '</div>'
  + '<div class="table-wrap project-svcs" data-svcs hidden><table><thead><tr>'
  + '<th>Serviço</th><th>Estado</th><th>Portas</th></tr></thead>'
  + '<tbody data-svc-corpo></tbody></table></div>'
  + '<div class="action-bar">'
  + '<button type="button" class="action-btn start" data-action="start">'
  + '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
  + '<polygon points="5 3 19 12 5 21 5 3"/></svg> Iniciar</button>'
  + '<button type="button" class="action-btn stop" data-action="stop">'
  + '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
  + '<rect x="6" y="4" width="12" height="16"/></svg> Parar</button>'
  + '</div></div>';

const MOLDE_SVC = '<tr>'
  + '<td><strong data-svc-nome></strong></td>'
  + '<td><span class="status-pill"><span class="dot"></span><span data-svc-estado></span></span></td>'
  + '<td class="project-portas" data-svc-portas></td>'
  + '</tr>';

const CASCA = '<div class="content"><div class="section">'
  + '<div class="section-head"><div><h2 class="section-title">Projetos</h2></div></div>'
  + '<div class="empty" data-vazio hidden>Nenhum projeto docker-compose encontrado em /opt/btv.</div>'
  + '<div class="project-grid" data-grid></div>'
  + '</div></div>';

const TONS_ESTADO = ['ok', 'warn', 'mute', 'bad'];
const TONS_SVC = ['running', 'exited'];

function rotuloDe(p) {
  const st = p.status || 'unknown';
  if (st === 'running') return 'Rodando';
  if (st === 'partial') return `Parcial (${p.running}/${p.total})`;
  if (st === 'stopped') return 'Parado';
  return 'Erro';
}

function tomDe(p) {
  const st = p.status || 'unknown';
  if (st === 'running') return 'ok';
  if (st === 'partial') return 'warn';
  if (st === 'stopped') return 'mute';
  return 'bad';
}

function portasDe(s) {
  const pub = s.Publishers || [];
  if (!pub.length) return '—';
  return pub.map(pp => `${pp.PublishedPort || '?'}->${pp.TargetPort || '?'}`).join(', ');
}

export function renderProjects(container) {
  let pollTimer = null;
  let emVoo = new Set();
  const ac = new AbortController();

  casca(container, 'projetos-v1', (el) => {
    el.innerHTML = CASCA;
    // Um listener para o grid inteiro: o botão pode ser recriado, o handler não.
    el.querySelector('[data-grid]').addEventListener('click', (ev) => {
      const btn = ev.target.closest ? ev.target.closest('[data-action]') : null;
      if (btn && !btn.disabled) acionar(btn);
    });
  });

  const grid = container.querySelector('[data-grid]');
  const vazio = container.querySelector('[data-vazio]');

  function render(data) {
    const projects = (data && data.projects) || [];
    mostrar(vazio, !projects.length);
    lista(grid, projects, {
      chave: (p) => p.name,
      criar: () => deMolde(MOLDE_CARD),
      atualizar: (card, p) => {
        const st = p.status || 'unknown';
        atributo(card, 'data-name', p.name);
        texto(card.querySelector('[data-nome]'), p.name);
        texto(card.querySelector('[data-caminho]'), p.path);
        classeUnica(card.querySelector('.project-estado'), TONS_ESTADO, tomDe(p));
        texto(card.querySelector('[data-estado]'), rotuloDe(p), { flash: true });

        const svcs = p.services || [];
        mostrar(card.querySelector('[data-svcs]'), !!svcs.length);
        lista(card.querySelector('[data-svc-corpo]'), svcs, {
          chave: (s) => s.Name || s.Service || '?',
          criar: () => deMolde(MOLDE_SVC),
          atualizar: (linha, s) => {
            const estado = s.State || '?';
            texto(linha.querySelector('[data-svc-nome]'), s.Name || s.Service || '?');
            classeUnica(linha.querySelector('.status-pill'), TONS_SVC,
              estado === 'running' ? 'running' : 'exited');
            texto(linha.querySelector('[data-svc-estado]'), estado);
            texto(linha.querySelector('[data-svc-portas]'), portasDe(s));
          },
        });

        /* Botão em voo NÃO é reabilitado pela leitura. Era o pior efeito da
         * repintura aqui: o operador clicava em "Parar", o cartão era refeito
         * dois segundos depois com o botão habilitado de novo, e um segundo
         * clique disparava a mesma mutação. */
        const emAcao = emVoo.has(p.name);
        const start = card.querySelector('[data-action="start"]');
        const stop = card.querySelector('[data-action="stop"]');
        start.disabled = emAcao || st === 'running' || st === 'error';
        stop.disabled = emAcao || st === 'stopped' || st === 'unknown';
      },
    });
  }

  async function acionar(btn) {
    const card = btn.closest('.project-card');
    const name = card.dataset.name;
    const action = btn.dataset.action;
    const ep = action === 'start' ? 'start' : 'stop';
    const label = action === 'start' ? 'Iniciar' : 'Parar';
    if (action === 'stop') {
      const r = await showConfirmModal({
        title: `${label} projeto`,
        message: `Tem certeza?`,
        confirmText: label,
        confirmClass: 'remove',
      });
      if (!r.confirmed) return;
    }
    emVoo.add(name);
    btn.disabled = true;
    const soltar = () => { emVoo.delete(name); };

    let { error } = await apiPost(`project-${ep}`, `/api/projects/${name}/${ep}`);
    if (error && (error.includes('403') || error.includes('Unlock') || error.includes('ausente') || error.includes('invalido'))) {
      const result = await showUnlockModal();
      if (!result) { soltar(); btn.disabled = false; return; }
      const retryRes = await apiPost(`project-${ep}-retry`, `/api/projects/${name}/${ep}`);
      soltar();
      if (retryRes.error) { showToast(retryRes.error, 'error'); load(); return; }
      showToast(`${label}do projeto ${name}`, 'success');
      load();
      return;
    }
    soltar();
    if (error) {
      showToast(error, 'error');
      load();
      return;
    }
    showToast(`${label}do projeto ${name}`, 'success');
    load();
  }

  async function load() {
    const { data, error } = await apiGet('projects', '/api/projects');
    if (error) {
      if (error !== 'abortado') showToast(error, 'error');
      return;
    }
    render(data);
  }

  load();
  // 10s = 2 ticks do relógio compartilhado.
  pollTimer = assinar(load, 2 * TICK_MS);

  return () => {
    ac.abort();
    if (typeof pollTimer === 'function') pollTimer();
    pollTimer = null;
    emVoo = new Set();
  };
}
