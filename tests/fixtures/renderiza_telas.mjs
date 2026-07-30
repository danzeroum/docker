/* Chama renderTopologia e renderPlantao de verdade, com fetch e DOM falsos.
 *
 * Os testes de logica cobrem a decisao; este cobre o caminho inteiro — se um
 * template levanta (campo ausente, alvo nulo), aqui aparece. Imprime o HTML de
 * cada tela para o pytest conferir o que foi pintado.
 *
 * Nao substitui navegador: nao ha layout, foco nem evento real.
 */
import './dom_stub.mjs';

/* --- DOM suficiente para innerHTML + getElementById ---------------------- */
const registro = new Map();

function fazerNo(id) {
  const no = {
    id,
    _html: '',
    style: {},
    dataset: {},
    get innerHTML() { return this._html; },
    set innerHTML(v) {
      this._html = String(v);
      // registra os ids que aparecem no HTML pintado, para getElementById achar
      for (const m of this._html.matchAll(/id="([^"]+)"/g)) {
        if (!registro.has(m[1])) registro.set(m[1], fazerNo(m[1]));
      }
    },
    addEventListener() {},
    querySelectorAll(sel) {
      // usado para religar os cartoes da fila; basta a contagem estar certa
      const attr = /\[data-open\]/.test(sel) ? 'data-open' : null;
      if (!attr) return [];
      return [...this._html.matchAll(/data-open="([^"]*)"/g)].map(m => ({
        dataset: { open: m[1] },
        addEventListener() {},
      }));
    },
    querySelector() { return null; },
  };
  return no;
}

const raizTela = fazerNo('screenContainer');
document.getElementById = (id) => registro.get(id) || null;

/* --- respostas de rede falsas ------------------------------------------- */
const INGRESS = {
  hosts: {
    'a.exemplo.com': { ssl: true, hsts: true, upstreams: ['http://vivo:80'], port_80: { https_redirect: true }, port_443: { locations: 2 } },
    'b.exemplo.com': { ssl: true, auth_basic: true, upstreams: ['http://parado:8080'], port_443: { locations: 1 } },
    'c.exemplo.com': { ssl: false, port_80: { upstream: 'http://fantasma:3000', https_redirect: false } },
    'd.localhost': { internal: true, upstreams: ['http://vivo:80'] },
  },
  totals: { total: 4, public: 3, with_ssl: 2, with_hsts: 1, with_auth: 1 },
  parsed_at: '2026-07-29T10:00:00Z',
  warnings: [],
};

const OVERVIEW = {
  host: { name: 'srv-de-teste', cpus: 4, os: 'Linux 6.1', docker: '27.0' },
  vitals: {},
  containers: [
    { name: 'vivo', stack: 's1', state: 'running', health: 'none', ports: '', restart_count: 0 },
    { name: 'parado', stack: 's2', state: 'exited', health: 'unhealthy', ports: '', restart_count: 0 },
    { name: 'borda', stack: 'ing', state: 'running', health: 'none', ports: '80/tcp, 443/tcp', restart_count: 3 },
  ],
  counters: { total: 3, running: 2, exited: 1, attention: 1 },
};

/* Datas RELATIVAS ao instante do teste, nao literais.
 *
 * A versao anterior fixava '2026-07-28' e o teste cobrava o texto renderizado
 * "há 1d": as duas coisas so concordam no dia em que a fixture foi escrita. O
 * teste passou a falhar sozinho quando o calendario virou, sem ninguem mexer no
 * frontend. Idade e derivada de `Date.now()` na tela, entao a fixture tem de
 * ser derivada dele tambem. */
const AGORA = Date.now();
const atras = (ms) => new Date(AGORA - ms).toISOString().replace('.000Z', 'Z');
const MIN = 60 * 1000;
const HORA = 60 * MIN;
const DIA = 24 * HORA;

const FINDINGS = [
  { id: 'f1', rule: 'upstream_missing', severity: 'critical', target: 'fantasma', scope: 'ingress',
    score: 80, status: 'open', occurrences: 12, first_seen: atras(DIA + HORA), last_seen: atras(HORA),
    title: 'upstream fantasma nao existe', title_plain: 'O site c.exemplo.com aponta para um serviço que não existe',
    recommendation: 'corrigir proxy_pass', recommendation_plain: 'Corrigir o endereço no nginx ou recriar o serviço' },
  { id: 'f2', rule: 'oom', severity: 'high', target: 'parado', scope: 'container',
    score: 60, status: 'open', occurrences: 1, first_seen: atras(30 * MIN), last_seen: atras(30 * MIN),
    title: 'container morto por falta de memoria' },
  { id: 'f3', rule: 'http_plain', severity: 'medium', scope: 'ingress', score: 30, status: 'open',
    occurrences: 3, first_seen: atras(10 * DIA), targets: ['x.exemplo.com', 'y.exemplo.com'],
    title: 'hosts sem TLS' },
];

const RESPOSTAS = {
  '/api/ingress': INGRESS,
  '/api/overview': OVERVIEW,
  '/api/findings?status=open': FINDINGS,
};

globalThis.fetch = async (url) => {
  const corpo = RESPOSTAS[url];
  if (corpo === undefined) throw new Error(`rota nao prevista no teste: ${url}`);
  return { ok: true, status: 200, json: async () => corpo, text: async () => JSON.stringify(corpo) };
};

/* --- executa ------------------------------------------------------------ */
const { renderTopologia } = await import(new URL('../../app/static/js/screens/topologia.js', import.meta.url));
const { renderPlantao } = await import(new URL('../../app/static/js/screens/plantao.js', import.meta.url));

const saida = {};

async function rodar(nome, render, idCorpo) {
  registro.clear();
  registro.set('screenContainer', raizTela);
  const dispose = render(raizTela);
  // uma volta de microtasks basta: as telas fazem fetch e pintam
  for (let i = 0; i < 20; i++) await Promise.resolve();
  await new Promise(r => setTimeout(r, 0));
  saida[nome] = (registro.get(idCorpo) || {})._html || '';
  saida[nome + '_resumo'] = (registro.get('pltResumo') || {})._html || '';
  if (typeof dispose === 'function') dispose();
  saida[nome + '_dispose'] = typeof dispose === 'function';
}

await rodar('topologia', renderTopologia, 'topoBody');
await rodar('plantao', renderPlantao, 'pltFila');

/* --- e uma segunda passada com as duas rotas caidas --------------------- */
globalThis.fetch = async () => ({ ok: false, status: 503, json: async () => ({ detail: 'socket-proxy fora' }) });
await rodar('topologia_caida', renderTopologia, 'topoBody');
await rodar('plantao_caido', renderPlantao, 'pltFila');

/* --- e uma terceira com ingress de pe e inventario vazio ---------------- */
globalThis.fetch = async (url) => {
  const corpo = url === '/api/ingress' ? INGRESS : { host: {}, containers: [], counters: {} };
  return { ok: true, status: 200, json: async () => corpo };
};
await rodar('topologia_sem_inventario', renderTopologia, 'topoBody');

process.stdout.write(JSON.stringify(saida));
