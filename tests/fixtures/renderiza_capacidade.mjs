/* Pinta os cartoes novos da Capacidade (B1 storage, B4 score) de verdade.
 *
 * Mesmo motivo do renderiza_telas.mjs: regex sobre o fonte prova que a funcao
 * existe, nao que ela sobrevive a um payload com campo faltando. Aqui o
 * template roda, e um `d.images.size_bytes` num `images` ausente levanta neste
 * arquivo em vez de deixar o cartao no skeleton em producao.
 *
 * Tambem exercita `saudeDe` do main.js, que decide o selo unhealthy da
 * listagem — a regra "sem healthcheck nao ganha selo" e o ponto do bloco B4.
 */
import './dom_stub.mjs';

const registro = new Map();

function fazerNo(id) {
  return {
    id,
    _html: '',
    style: {},
    dataset: {},
    get innerHTML() { return this._html; },
    set innerHTML(v) {
      this._html = String(v);
      for (const m of this._html.matchAll(/id="([^"]+)"/g)) {
        if (!registro.has(m[1])) registro.set(m[1], fazerNo(m[1]));
      }
    },
    addEventListener() {},
    querySelectorAll() { return []; },
    querySelector() { return null; },
  };
}

const raizTela = fazerNo('screenContainer');
document.getElementById = (id) => registro.get(id) || null;

const GB = 1024 ** 3;

const CAPACIDADE = {
  windows: [{ label: '24h', severity: 'high', items: [] }],
  memory_by_stack: [{ name: 's1', used_mb: 100, limit_mb: 512, pct: 19.5 }],
  postura: [{ item: 'Certificados TLS em dia', valor: 'OK', status: 'ok' }],
  coletando_desde: '2026-07-01T00:00:00Z',
};

const HISTORICO = { series: [{ ts: '2026-07-28', v: 41 }], projection: null, coletando_desde: '2026-07-01T00:00:00Z' };

const STORAGE = {
  images: { count: 12, size_bytes: 6 * GB, dangling_count: 2, dangling_bytes: 4 * GB },
  containers: { count: 15, size_bytes: 300, stopped_old_count: 1, stopped_old_bytes: 200 },
  volumes: { count: 8, size_bytes: 7 * GB, orphan_count: 1, orphan_bytes: 2 * GB },
  build_cache: { count: 2, size_bytes: 600 * 1024 * 1024, reclaimable_bytes: 500 * 1024 * 1024 },
  reclaimable_bytes: 6 * GB + 200,
  orphans: [
    { type: 'image', id: 'sha256:bbb', name: '<none>:<none>', size_bytes: 3 * GB, reason: 'imagem sem tag' },
    { type: 'volume', id: 'sobra_v', name: 'sobra_v', size_bytes: 2 * GB, reason: 'ninguem referencia' },
    { type: 'container', id: 'c2', name: 'zumbi', size_bytes: 200, reason: 'parado ha 40 dias' },
  ],
  orphan_exited_days: 7,
};

const STORAGE_LIMPO = {
  images: { count: 1, size_bytes: 2 * GB, dangling_count: 0, dangling_bytes: 0 },
  containers: { count: 1, size_bytes: 0, stopped_old_count: 0, stopped_old_bytes: 0 },
  volumes: { count: 0, size_bytes: 0, orphan_count: 0, orphan_bytes: 0 },
  build_cache: { count: 0, size_bytes: 0, reclaimable_bytes: 0 },
  reclaimable_bytes: 0,
  orphans: [],
  orphan_exited_days: 7,
};

const SECURITY = {
  containers: [
    {
      id: 'ruim', name: 'com_socket', image: 'nginx:1.25', state: 'running', health: null,
      score: 55, penalty: 45,
      violations: [
        { rule: 'docker_socket_mounted', severity: 'critical', weight: 30, title: 'Socket do Docker montado no container', evidence: '/var/run/docker.sock:/var/run/docker.sock' },
        { rule: 'run_as_root', severity: 'high', weight: 15, title: 'Processo roda como root', evidence: 'Config.User=(vazio = root)' },
      ],
    },
    { id: 'medio', name: 'sem_limite', image: 'redis:7', state: 'running', health: 'unhealthy', score: 95, penalty: 5,
      violations: [{ rule: 'no_memory_limit', severity: 'medium', weight: 5, title: 'Sem limite de memoria', evidence: 'HostConfig.Memory=0' }] },
    { id: 'bom', name: 'conforme', image: 'app:1', state: 'running', health: 'healthy', score: 100, penalty: 0, violations: [] },
  ],
  summary: {
    containers_avaliados: 3, score_medio: 83.3, score_minimo: 55, conformes: 1,
    violacoes_por_severidade: { critical: 1, high: 1, medium: 1 },
    unhealthy: 1, sem_healthcheck: 1,
  },
  checks: [{ rule: 'docker_socket_mounted', severity: 'critical', title: 'Socket do Docker montado', weight: 30 }],
  pesos: { critical: 30, high: 15, medium: 5 },
};

const SECURITY_CONFORME = {
  containers: [{ id: 'bom', name: 'conforme', score: 100, penalty: 0, health: 'healthy', violations: [] }],
  summary: {
    containers_avaliados: 1, score_medio: 100, score_minimo: 100, conformes: 1,
    violacoes_por_severidade: { critical: 0, high: 0, medium: 0 }, unhealthy: 0, sem_healthcheck: 0,
  },
  checks: [], pesos: { critical: 30, high: 15, medium: 5 },
};

function servir(mapa) {
  globalThis.fetch = async (url) => {
    const chave = Object.keys(mapa).find(k => url.startsWith(k));
    if (chave === undefined) throw new Error(`rota nao prevista no teste: ${url}`);
    const corpo = mapa[chave];
    if (corpo === null) return { ok: false, status: 503, json: async () => ({ detail: 'socket-proxy indisponivel' }) };
    return { ok: true, status: 200, json: async () => corpo, text: async () => JSON.stringify(corpo) };
  };
}

const { renderCapacidade } = await import(new URL('../../app/static/js/screens/capacidade.js', import.meta.url));

const saida = {};

async function rodar(nome, mapa) {
  servir(mapa);
  registro.clear();
  registro.set('screenContainer', raizTela);
  const dispose = renderCapacidade(raizTela);
  for (let i = 0; i < 40; i++) await Promise.resolve();
  await new Promise(r => setTimeout(r, 0));
  await new Promise(r => setTimeout(r, 0));
  saida[nome + '_storage'] = (registro.get('capStorage') || {})._html || '';
  saida[nome + '_security'] = (registro.get('capSecurity') || {})._html || '';
  saida[nome + '_body'] = (registro.get('capBody') || {})._html || '';
  if (typeof dispose === 'function') dispose();
}

await rodar('cheio', {
  '/api/capacity': CAPACIDADE,
  '/api/metrics/history': HISTORICO,
  '/api/storage': STORAGE,
  '/api/security': SECURITY,
});

await rodar('limpo', {
  '/api/capacity': CAPACIDADE,
  '/api/metrics/history': HISTORICO,
  '/api/storage': STORAGE_LIMPO,
  '/api/security': SECURITY_CONFORME,
});

// Storage fora do ar: a Capacidade que ja carregou nao pode desaparecer.
await rodar('storage_caido', {
  '/api/capacity': CAPACIDADE,
  '/api/metrics/history': HISTORICO,
  '/api/storage': null,
  '/api/security': SECURITY,
});

// Payload truncado — secoes ausentes nao podem levantar no template.
await rodar('truncado', {
  '/api/capacity': CAPACIDADE,
  '/api/metrics/history': HISTORICO,
  '/api/storage': { orphans: [], reclaimable_bytes: 0 },
  '/api/security': { containers: [], summary: {} },
});

/* --- saudeDe: a regra do selo unhealthy --------------------------------- */
servir({ '/api': {} });
const { saudeDe } = await import(new URL('../../app/static/js/main.js', import.meta.url));

saida.saude = {
  explicito_unhealthy: saudeDe({ Health: 'unhealthy', Status: 'Up 2 hours' }),
  explicito_healthy: saudeDe({ Health: 'healthy', Status: 'Up 2 hours (unhealthy)' }),
  sem_healthcheck: saudeDe({ Health: null, Status: 'Up 2 hours' }),
  fallback_status: saudeDe({ Status: 'Up 2 hours (unhealthy)' }),
  fallback_state: saudeDe({ State: 'unhealthy' }),
  vazio: saudeDe({}),
  nulo: saudeDe(null),
  starting: saudeDe({ Health: 'starting' }),
};

process.stdout.write(JSON.stringify(saida));
