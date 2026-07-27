const PERSIST_KEYS = ['perfil', 'depth', 'tema'];
const listeners = [];

function loadPersisted() {
  const raw = localStorage.getItem('cockpit-store');
  if (raw) {
    try { return JSON.parse(raw); } catch {}
  }
  return {};
}

function loadUnlock() {
  const raw = sessionStorage.getItem('cockpit-unlock');
  if (raw) {
    try { return JSON.parse(raw); } catch {}
  }
  return { token: null, expiresAt: null };
}

const persisted = loadPersisted();
const unlock = loadUnlock();

let state = {
  screen: '/overview',
  perfil: persisted.perfil || 'sre',
  depth: persisted.depth ?? null,
  tema: (() => {
    if (persisted.tema) return persisted.tema;
    const old = localStorage.getItem('cockpit-theme');
    if (old === 'light') return 'claro';
    if (old === 'dark') return 'cockpit';
    return 'cockpit';
  })(),
  selectedContainer: null,
  selectedFinding: null,
  search: '',
  filter: 'all',
  containers: [],
  system: null,
  unlock,
};

function persist() {
  const toSave = {};
  for (const k of PERSIST_KEYS) toSave[k] = state[k];
  localStorage.setItem('cockpit-store', JSON.stringify(toSave));
  for (const k of ['cockpit-perfil', 'cockpit-depth', 'cockpit-tema']) localStorage.removeItem(k);
}

function persistUnlock() {
  if (state.unlock.token) {
    sessionStorage.setItem('cockpit-unlock', JSON.stringify(state.unlock));
  } else {
    sessionStorage.removeItem('cockpit-unlock');
  }
}

export function getState() { return state; }

export function setState(partial) {
  const changed = [];
  for (const k of Object.keys(partial)) {
    if (state[k] !== partial[k]) {
      state[k] = partial[k];
      changed.push(k);
    }
  }
  if (changed.length) {
    if (changed.some(k => PERSIST_KEYS.includes(k))) persist();
    if (changed.includes('unlock')) persistUnlock();
    for (const fn of listeners) fn(state, changed);
  }
}

export function subscribe(fn) {
  listeners.push(fn);
  return () => { const i = listeners.indexOf(fn); if (i >= 0) listeners.splice(i, 1); };
}
