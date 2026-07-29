import { escapeHtml } from './fmt.js';
import { getState, setState } from './store.js';

export function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const icons = {
    success: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    error: '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
    info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
    warning: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>'
  };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${icons[type] || icons.info}</svg>
    <div class="toast-message">${escapeHtml(message)}</div>
    <button type="button" class="toast-close" data-action="close">✕</button>
  `;
  toast.querySelector('[data-action="close"]').onclick = () => toast.remove();
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('show'));
  setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 4000);
}

// --- Foco preso no modal ---------------------------------------------------
// Modal aberto com o Tab escapando para o fundo e uma armadilha classica: o
// teclado sai da caixa, mexe no que esta atras e o usuario nao ve onde esta.
// Os tres modais compartilham o mesmo overlay, entao o controle e um so.

const FOCAVEIS = 'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

let soltarFocoAtual = null;

function prenderFoco(overlay) {
  const anterior = document.activeElement;

  const aoTeclar = (e) => {
    if (e.key !== 'Tab') return;
    const alvos = Array.from(overlay.querySelectorAll(FOCAVEIS))
      .filter(el => el.offsetParent !== null || el === document.activeElement);
    if (!alvos.length) {
      e.preventDefault();
      return;
    }
    const primeiro = alvos[0];
    const ultimo = alvos[alvos.length - 1];
    if (e.shiftKey && document.activeElement === primeiro) {
      e.preventDefault();
      ultimo.focus();
    } else if (!e.shiftKey && document.activeElement === ultimo) {
      e.preventDefault();
      primeiro.focus();
    }
  };

  overlay.addEventListener('keydown', aoTeclar);
  const primeiro = overlay.querySelector(FOCAVEIS);
  if (primeiro) primeiro.focus();

  soltarFocoAtual = () => {
    overlay.removeEventListener('keydown', aoTeclar);
    // Devolve o foco a quem abriu o modal, nao ao topo da pagina.
    if (anterior && typeof anterior.focus === 'function') anterior.focus();
  };
}

function soltarFoco() {
  if (soltarFocoAtual) {
    soltarFocoAtual();
    soltarFocoAtual = null;
  }
}

let modalResolve = null;

export function showConfirmModal(opts) {
  const overlay = document.getElementById('confirmModal');
  document.getElementById('modalTitle').textContent = opts.title || 'Confirmação';
  document.getElementById('modalText').innerHTML = opts.message || 'Tem certeza?';

  const inputWrap = document.getElementById('modalInputWrap');
  const inputEl = document.getElementById('modalInput');
  const nameEl = document.getElementById('modalConfirmName');
  const checkboxWrap = document.getElementById('modalCheckboxWrap');
  const checkboxLabel = document.getElementById('modalCheckboxLabel');
  const checkbox = document.getElementById('modalCheckbox');
  const confirmBtn = document.getElementById('modalConfirm');

  inputWrap.style.display = 'none';
  checkboxWrap.style.display = 'none';
  inputEl.value = '';
  checkbox.checked = false;

  confirmBtn.className = 'modal-btn confirm';
  if (opts.confirmClass) confirmBtn.classList.add(opts.confirmClass);
  confirmBtn.textContent = opts.confirmText || 'Confirmar';

  if (opts.confirmName) {
    inputWrap.style.display = '';
    nameEl.textContent = opts.confirmName;
  }
  if (opts.checkboxLabel) {
    checkboxWrap.style.display = '';
    checkboxLabel.textContent = opts.checkboxLabel;
    checkbox.checked = !!opts.checkboxChecked;
  }

  overlay.classList.add('open');
  prenderFoco(overlay);

  return new Promise((resolve) => {
    modalResolve = resolve;

    const cleanup = () => {
      overlay.classList.remove('open');
      soltarFoco();
      document.getElementById('modalCancel').removeEventListener('click', onCancel);
      confirmBtn.removeEventListener('click', onConfirm);
      inputEl.removeEventListener('keydown', onKeydown);
    };

    const onCancel = () => { cleanup(); resolve({ confirmed: false }); };
    const onConfirm = () => {
      if (opts.confirmName && inputEl.value !== opts.confirmName) {
        inputEl.style.borderColor = 'var(--bad)';
        inputEl.focus();
        return;
      }
      inputEl.style.borderColor = '';
      cleanup();
      resolve({ confirmed: true, name: inputEl.value, checkbox: checkbox.checked });
    };
    const onKeydown = (e) => {
      if (e.key === 'Enter') onConfirm();
      else if (e.key === 'Escape') onCancel();
    };

    document.getElementById('modalCancel').addEventListener('click', onCancel);
    confirmBtn.addEventListener('click', onConfirm);
    inputEl.addEventListener('keydown', onKeydown);
  });
}

export function showUnlockModal() {
  return new Promise((resolve) => {
    const overlay = document.getElementById('confirmModal');
    document.getElementById('modalTitle').textContent = 'Destravar';
    document.getElementById('modalConfirmName').textContent = '';
    const inputWrap = document.getElementById('modalInputWrap');
    const inputEl = document.getElementById('modalInput');
    const checkboxWrap = document.getElementById('modalCheckboxWrap');
    const confirmBtn = document.getElementById('modalConfirm');
    inputWrap.style.display = '';
    checkboxWrap.style.display = 'none';
    inputEl.style.borderColor = '';
    inputEl.placeholder = 'Motivo (opcional)';
    confirmBtn.className = 'modal-btn confirm start';
    confirmBtn.textContent = 'Destravar';
    document.getElementById('modalText').innerHTML = '<div style="margin-bottom:.5rem;color:var(--text-dim);font-size:.85rem">Confirme para destravar mutações por 30 minutos.</div>';

    overlay.classList.add('open');
  prenderFoco(overlay);

    const cleanup = () => {
      overlay.classList.remove('open');
      soltarFoco();
      document.getElementById('modalCancel').removeEventListener('click', onCancel);
      confirmBtn.removeEventListener('click', onConfirm);
      inputEl.removeEventListener('keydown', onKeydown);
    };
    const onCancel = () => { cleanup(); resolve(null); };
    const onConfirm = async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Destravando…';
      const motivo = inputEl.value.trim();
      try {
        const res = await fetch('/api/session/unlock', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ motivo }),
        });
        if (!res.ok) {
          let detail = '';
          try { const j = await res.json(); detail = j.detail || ''; } catch {}
          showToast(detail || 'Erro ao destravar', 'error');
          confirmBtn.disabled = false;
          confirmBtn.textContent = 'Destravar';
          return;
        }
        const data = await res.json();
        const unlockData = { token: data.token, expiresAt: data.expires_at };
        setState({ unlock: unlockData });
        cleanup();
        resolve(unlockData);
      } catch (err) {
        showToast('Erro de rede ao destravar', 'error');
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Destravar';
      }
    };
    const onKeydown = (e) => {
      if (e.key === 'Enter') onConfirm();
      else if (e.key === 'Escape') onCancel();
    };
    document.getElementById('modalCancel').addEventListener('click', onCancel);
    confirmBtn.addEventListener('click', onConfirm);
    inputEl.addEventListener('keydown', onKeydown);
  });
}

export function showAckModal(finding) {
  return new Promise((resolve) => {
    const overlay = document.getElementById('confirmModal');
    const textEl = document.getElementById('modalText');
    const inputWrap = document.getElementById('modalInputWrap');
    const inputEl = document.getElementById('modalInput');
    const checkboxWrap = document.getElementById('modalCheckboxWrap');
    const checkboxLabel = document.getElementById('modalCheckboxLabel');
    const checkbox = document.getElementById('modalCheckbox');
    const confirmBtn = document.getElementById('modalConfirm');

    document.getElementById('modalTitle').textContent = 'Silenciar achado';
    inputWrap.style.display = 'none';
    checkboxWrap.style.display = 'none';
    inputEl.value = '';
    inputEl.placeholder = '';

    // Build inline form
    const reasonOptions = ['falso_positivo', 'assumido', 'agendado', 'outro'];
    textEl.innerHTML = `
      <div style="margin-bottom:.75rem">
        <label style="display:block;font-size:.8rem;color:var(--text-dim);margin-bottom:.25rem">Motivo <strong style="color:var(--bad)">*</strong></label>
        <select id="ackReason" style="width:100%;padding:.5rem;border-radius:8px;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:inherit;font-size:.85rem">
          <option value="">— Selecione —</option>
          ${reasonOptions.map(r => `<option value="${r}">${r}</option>`).join('')}
        </select>
      </div>
      <div style="margin-bottom:.75rem">
        <label style="display:block;font-size:.8rem;color:var(--text-dim);margin-bottom:.25rem">Observação</label>
        <input id="ackNote" type="text" style="width:100%;padding:.5rem;border-radius:8px;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:inherit;font-size:.85rem" placeholder="opcional">
      </div>
      <div style="margin-bottom:.5rem">
        <label style="display:block;font-size:.8rem;color:var(--text-dim);margin-bottom:.25rem">Silenciar por</label>
        <div style="display:flex;gap:.35rem;flex-wrap:wrap">
          <button type="button" class="ack-dur" data-dur="4h" style="padding:.3rem .6rem;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text-dim);cursor:pointer;font-family:inherit;font-size:.8rem">4h</button>
          <button type="button" class="ack-dur active" data-dur="24h" style="padding:.3rem .6rem;border-radius:6px;border:1px solid var(--border);background:var(--accent);color:#fff;cursor:pointer;font-family:inherit;font-size:.8rem">24h</button>
          <button type="button" class="ack-dur" data-dur="7d" style="padding:.3rem .6rem;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text-dim);cursor:pointer;font-family:inherit;font-size:.8rem">7d</button>
          <button type="button" class="ack-dur" data-dur="30d" style="padding:.3rem .6rem;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text-dim);cursor:pointer;font-family:inherit;font-size:.8rem">30d</button>
        </div>
      </div>
    `;

    confirmBtn.textContent = 'Silenciar';
    confirmBtn.className = 'modal-btn confirm';
    confirmBtn.disabled = true;
    checkboxWrap.style.display = 'none';

    const reasonEl = document.getElementById('ackReason');
    const noteEl = document.getElementById('ackNote');

    reasonEl.addEventListener('change', () => {
      confirmBtn.disabled = !reasonEl.value;
    });

    textEl.addEventListener('click', (e) => {
      const durBtn = e.target.closest('.ack-dur');
      if (!durBtn) return;
      textEl.querySelectorAll('.ack-dur').forEach(b => {
        b.style.background = 'var(--surface)';
        b.style.color = 'var(--text-dim)';
      });
      durBtn.style.background = 'var(--accent)';
      durBtn.style.color = '#fff';
    });

    overlay.classList.add('open');
  prenderFoco(overlay);

    const cleanup = () => {
      overlay.classList.remove('open');
      soltarFoco();
      document.getElementById('modalCancel').removeEventListener('click', onCancel);
      confirmBtn.removeEventListener('click', onConfirm2);
    };
    const onCancel = () => { cleanup(); resolve(null); };
    const onConfirm2 = () => {
      const reason = reasonEl.value;
      if (!reason) {
        reasonEl.style.borderColor = 'var(--bad)';
        reasonEl.focus();
        return;
      }
      const activeDur = textEl.querySelector('.ack-dur.active') || textEl.querySelector('.ack-dur');
      const until = activeDur ? activeDur.dataset.dur : '24h';
      cleanup();
      resolve({ reason, note: noteEl.value, until });
    };
    // Escape fecha, como nos outros dois modais. Faltava so neste.
    const onKeydownAck = (e) => { if (e.key === 'Escape') onCancel(); };
    overlay.addEventListener('keydown', onKeydownAck);
    document.getElementById('modalCancel').addEventListener('click', onCancel);
    confirmBtn.addEventListener('click', onConfirm2);
  });
}
