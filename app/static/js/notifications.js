function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const icons = {
    success: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    error: '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
    info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
    warning: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>'
  };
  const svg = icons[type] || icons.info;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${svg}</svg>
    <div class="toast-message">${escapeHtml(message)}</div>
    <button class="toast-close" onclick="this.parentElement.remove()">✕</button>
  `;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('show'));
  setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 4000);
}

let modalResolve = null;

function showConfirmModal(opts) {
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

  return new Promise((resolve) => {
    modalResolve = resolve;

    const cleanup = () => {
      overlay.classList.remove('open');
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
      resolve({
        confirmed: true,
        name: inputEl.value,
        checkbox: checkbox.checked
      });
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
