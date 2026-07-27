const controllers = new Map();

function getSignal(key) {
  if (controllers.has(key)) controllers.get(key).abort();
  const ac = new AbortController();
  controllers.set(key, ac);
  return ac.signal;
}

export function cancelAll() {
  for (const ac of controllers.values()) ac.abort();
  controllers.clear();
}

export function cancel(key) {
  if (controllers.has(key)) {
    controllers.get(key).abort();
    controllers.delete(key);
  }
}

export async function apiGet(key, url, timeout = 10000) {
  const signal = getSignal(key);
  try {
    const res = await fetch(url, {
      signal,
      headers: { 'Accept': 'application/json' },
    });
    if (!res.ok) {
      let detail = '';
      try { const j = await res.json(); detail = j.detail || ''; } catch {}
      return { error: detail || `HTTP ${res.status}` };
    }
    const data = await res.json();
    return { data };
  } catch (err) {
    if (err.name === 'AbortError') return { error: 'abortado' };
    return { error: err.message || 'Erro de rede' };
  }
}

export async function apiPost(key, url, options = {}) {
  const signal = getSignal(key);
  try {
    const res = await fetch(url, {
      method: 'POST',
      signal,
      headers: { 'Accept': 'application/json' },
      ...options,
    });
    if (!res.ok) {
      let detail = '';
      try { const j = await res.json(); detail = j.detail || ''; } catch {}
      return { error: detail || `HTTP ${res.status}` };
    }
    const data = res.status === 204 ? { ok: true } : await res.json();
    return { data };
  } catch (err) {
    if (err.name === 'AbortError') return { error: 'abortado' };
    return { error: err.message || 'Erro de rede' };
  }
}

export async function apiDelete(key, url) {
  const signal = getSignal(key);
  try {
    const res = await fetch(url, { method: 'DELETE', signal });
    if (!res.ok) {
      let detail = '';
      try { const j = await res.json(); detail = j.detail || ''; } catch {}
      return { error: detail || `HTTP ${res.status}` };
    }
    return { data: { ok: true } };
  } catch (err) {
    if (err.name === 'AbortError') return { error: 'abortado' };
    return { error: err.message || 'Erro de rede' };
  }
}
