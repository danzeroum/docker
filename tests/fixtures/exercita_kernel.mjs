/* Exercita o kernel do Cockpit Vivo de verdade sob node (Sprint 2a).
 *
 * Os dois aceites que só um teste de execução pega:
 *  1. registrar um módulo em RUNTIME o faz aparecer na régua e no Personalizar
 *     sem tocar main.js — é o teste de aberto/fechado do doc 10 §4;
 *  2. com `actions_enabled=false` nenhum botão de ação EXISTE no DOM (ausente,
 *     não `display:none`).
 *
 * Também cobre o que regex sobre o fonte não prova: layout corrompido volta ao
 * padrão, os ↑↓ e o drag produzem o mesmo estado, e módulo oculto mantém chip.
 */
import './dom_stub.mjs';

/* --- DOM com innerHTML + getElementById + querySelector(All) ------------- */
const registro = new Map();

function fazerNo(id) {
  const no = {
    id,
    _html: '',
    _filhos: new Map(),
    hidden: false,
    style: {},
    dataset: {},
    get innerHTML() { return this._html; },
    set innerHTML(v) {
      this._html = String(v);
      this._filhos = new Map();
      for (const m of this._html.matchAll(/id="([^"]+)"/g)) {
        if (!registro.has(m[1])) registro.set(m[1], fazerNo(m[1]));
      }
    },
    get textContent() { return this._texto || ''; },
    set textContent(v) { this._texto = String(v); },
    _handlers: null,
    addEventListener(evt, fn) {
      if (evt === 'input' || evt === 'click') {
        this._handlers = this._handlers || [];
        this._handlers.push(fn);
      }
    },
    setAttribute(k, v) { this.dataset[k] = v; },
    getAttribute(k) { return this.dataset[k]; },
    scrollIntoView() {},
    appendChild() {},
    removeChild() {},
    remove() {},
    classList: { add() {}, remove() {}, contains: () => false },
    querySelectorAll(sel) {
      const m = /\[data-([a-z-]+)(?:="([^"]*)")?\]/.exec(sel)
        || /\.([a-z-]+)/.exec(sel);
      if (!m) return [];
      const attr = m[1];
      const achados = [];
      for (const mm of this._html.matchAll(new RegExp(`data-${attr}(?:="([^"]*)")?`, 'g'))) {
        const valor = mm[1] === undefined ? '' : mm[1];
        // Nó PERSISTENTE por (pai, atributo, valor): um módulo que escreve em
        // `querySelector('[data-serie]').innerHTML` precisa que esse nó
        // sobreviva à chamada, senão o teste mede um objeto descartável e
        // conclui que o render nao pintou nada.
        const chave = `${attr}=${valor}`;
        if (!this._filhos.has(chave)) {
          const filho = fazerNo(`${this.id}::${chave}`);
          filho.dataset = { [attr]: valor, modulo: valor, id: valor, acao: valor, range: valor };
          filho.disabled = false;
          this._filhos.set(chave, filho);
        }
        achados.push(this._filhos.get(chave));
      }
      if (!achados.length && sel.startsWith('.')) {
        const cls = sel.slice(1);
        const n = (this._html.match(new RegExp(`class="[^"]*\\b${cls}\\b`, 'g')) || []).length;
        for (let i = 0; i < n; i++) achados.push({ dataset: {}, addEventListener() {} });
      }
      return achados;
    },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
  };
  return no;
}

const els = {
  regua: fazerNo('kernelReguaSlot'),
  faixa: fazerNo('kernelFaixa'),
  grade: fazerNo('screenContainer'),
  painel: fazerNo('kernelPainel'),
  subtela: fazerNo('kernelSubtela'),
};
for (const [, no] of Object.entries(els)) registro.set(no.id, no);
registro.set('mainTitle', fazerNo('mainTitle'));
registro.set('mainSubtitle', fazerNo('mainSubtitle'));
// `showToast` procura este container; sem ele um módulo que só quis avisar de
// erro derruba o harness.
registro.set('toastContainer', fazerNo('toastContainer'));

document.getElementById = (id) => registro.get(id) || null;
document.querySelector = (sel) => els.grade.querySelector(sel);
document.querySelectorAll = (sel) => els.grade.querySelectorAll(sel);

/* createElement precisa devolver algo consultável: `showToast` monta o nó e
 * procura o botão de fechar dentro dele. Sem isto o harness quebra por
 * limitação própria, e um corpo de módulo que só quis avisar de erro derrubaria
 * o teste como se fosse bug de produção. */
globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);

document.createElement = () => {
  const filho = { onclick: null, addEventListener() {}, remove() {}, style: {}, dataset: {}, classList: { add() {}, remove() {}, contains: () => false } };
  return {
    ...filho,
    innerHTML: '', textContent: '', className: '',
    appendChild() {}, setAttribute() {}, getAttribute: () => null,
    querySelector: () => filho,
    querySelectorAll: () => [filho],
  };
};

/* --- payloads ------------------------------------------------------------ */
const GB = 1024 ** 3;

const SUMMARY = {
  findings: { open: 3, critical: 1 },
  stacks: { up: 2, total: 3, stopped_with_domain: 1 },
  ingress: { hosts: 13, https_forced: 11, certs_expiring: null, cert_window_days: null },
  capacity: { days_to_90: 24, r2: 0.86, disk_pct: 71 },
  audit: { last_at: '2026-07-30T12:00:00Z', last_actor: 'dz' },
  tasks: { total: 6, todo: 2 },
  storage: { reclaimable_gb: 9.8, orphans: 4 },
  security: { min_score: 70, critical: 1 },
  drift: { count: null },
  capabilities: { actions_enabled: true, terminal_enabled: false },
  stale_since: {},
};

const OVERVIEW = {
  host: { name: 'srv-teste', cpus: 4 },
  vitals: { cpu_pct: 22, mem_pct: 61, swap_pct: 3, disk: { pct: 71, mountpoint: '/' } },
  counters: { total: 3, running: 2, exited: 1, attention: 1 },
  stacks: [
    { id: 'web', running: 2, total: 2, worst: 'ok', containers: ['api', 'front'] },
    { id: 'batch', running: 0, total: 1, worst: 'warn', containers: ['worker'] },
  ],
  containers: [
    { id: 'c1', name: 'api', stack: 'web', state: 'running', health: 'none', cpu_pct: 3, mem_usage: 100 },
    { id: 'c2', name: 'front', stack: 'web', state: 'running', health: 'unhealthy', cpu_pct: 1, mem_usage: 50 },
    { id: 'c3', name: 'worker', stack: 'batch', state: 'exited', health: 'none', cpu_pct: 0, mem_usage: 0 },
  ],
  summary: SUMMARY,
};

const FINDINGS = [
  { id: 'f1', severity: 'critical', title: 'upstream sumiu', title_plain: 'Um site aponta para serviço que não existe',
    interpretation_plain: 'Visitantes recebem erro', first_seen: '2026-07-29T02:00:00Z' },
  { id: 'f2', severity: 'high', title: 'oom' },
];

function servir(mapa) {
  globalThis.fetch = async (url) => {
    const chave = Object.keys(mapa).find((k) => url.startsWith(k));
    const corpo = chave === undefined ? null : mapa[chave];
    if (corpo === null || corpo === undefined) {
      return { ok: false, status: 503, json: async () => ({ detail: 'indisponível' }), text: async () => '' };
    }
    return { ok: true, status: 200, json: async () => corpo, text: async () => JSON.stringify(corpo) };
  };
}

const STORAGE = {
  images: { count: 3, size_bytes: 6 * GB, dangling_count: 2 },
  containers: { count: 2, size_bytes: 200 },
  volumes: { count: 1, size_bytes: 2 * GB, orphan_count: 1 },
  build_cache: { count: 0, size_bytes: 0, reclaimable_bytes: 0 },
  reclaimable_bytes: 9.8 * GB,
  orphans: [
    { type: 'image', id: 'sha256:aaa', name: '<none>:<none>', size_bytes: 3 * GB, reason: 'dangling' },
    { type: 'volume', id: 'sobra_v', name: 'sobra_v', size_bytes: 2 * GB, reason: 'ninguem referencia' },
  ],
  orphan_exited_days: 7,
};

const DRY_RUN = {
  dry_run: true,
  candidates: [
    { type: 'image', id: 'sha256:aaa', name: '<none>:<none>', size_bytes: 3 * GB, reason: 'dangling' },
  ],
  count: 1,
  reclaimable_bytes: 3 * GB,
  removed_bytes: 0,
};

const EVENTOS = {
  events: [
    { id: 3, ts: new Date(Date.now() - 30000).toISOString(), action: 'die', actor_name: 'criptotrade-app',
      stack: 'criptotrade', exit_code: '137', severity: 'critical' },
    { id: 2, ts: new Date(Date.now() - 60000).toISOString(), action: 'start', actor_name: 'api',
      stack: 'web', exit_code: '', severity: 'info' },
  ],
  count: 2, next_before_id: null, filters: {},
};

const HISTORY = {
  container_id: 'front', resolution: 'raw', range_hours: 24,
  points: Array.from({ length: 12 }, (_, i) => ({ ts: `2026-07-30T${String(i).padStart(2, '0')}:00:00Z`, cpu_pct: i * 2, mem_bytes: 1000 + i })),
  point_count: 12, downsampled_from: null, retention: { raw_hours: 24, rollup_days: 30 },
};

const ROTAS_2B = {
  '/api/overview': OVERVIEW,
  '/api/findings': FINDINGS,
  '/api/storage': STORAGE,
  '/api/events': EVENTOS,
  '/api/containers/front/history': HISTORY,
  '/api/containers': { Id: 'front', Name: '/front', State: { Status: 'running' }, Config: {}, HostConfig: {}, Mounts: [] },
  '/api/security': { containers: [], summary: {} },
  '/api': {},
};

servir(ROTAS_2B);

/* --- executa ------------------------------------------------------------- */
const reg = await import(new URL('../../app/static/js/kernel/registry.js', import.meta.url));
const lay = await import(new URL('../../app/static/js/kernel/layout.js', import.meta.url));
const esc = await import(new URL('../../app/static/js/kernel/escopo.js', import.meta.url));
const mods = await import(new URL('../../app/static/js/modulos/index.js', import.meta.url));
const kernel = await import(new URL('../../app/static/js/kernel/app.js', import.meta.url));

const saida = {};

/* `montarRegua` cria um filho `#kernelRegua` e é NELE que os chips entram; cada
 * módulo escreve no próprio `#mod-<id>`. Ler o nó pai devolveria só o esqueleto,
 * e o teste passaria a medir o harness em vez do kernel. */
const lerRegua = () => (registro.get('kernelRegua') || {}).innerHTML || '';
const lerCorpo = (id) => (registro.get(`mod-${id}`) || {}).innerHTML || '';

kernel.iniciar(els);
kernel._interno.definirDados({ overview: OVERVIEW, findings: FINDINGS });
kernel._interno.repintar();
await new Promise((r) => setTimeout(r, 0));

saida.registrados = reg.todos().map((m) => m.id).sort();
saida.doPrototipo = mods.DO_PROTOTIPO.map((m) => m.id).sort();
saida.extras = mods.EXTRAS.map((m) => m.id).sort();
saida.regua = lerRegua();
saida.faixa = els.faixa.innerHTML;
saida.grade_host = els.grade.innerHTML;
saida.estado_host = kernel._interno.estadoAtual();

/* --- aceite 1: módulo registrado em runtime aparece sem tocar main.js ---- */
reg.registrar({
  id: 'sonda_de_teste',
  nome: 'Sonda de teste',
  escopos: ['host', 'stack', 'container'],
  span: 6,
  chip: () => ({ rotulo: 'Sonda', valor: '42' }),
  render: (escopo, dados, corpo) => { corpo.innerHTML = '<b>sonda viva</b>'; },
});
// Reconciliar acrescenta módulo desconhecido como OCULTO — então ele aparece no
// Personalizar e como chip na régua, sem invadir a grade de ninguém.
kernel._interno.irPara(esc.stack('web'));
kernel._interno.irPara(esc.host());
kernel._interno.repintar();
saida.regua_com_sonda = lerRegua();
saida.estado_com_sonda = kernel._interno.estadoAtual();
saida.grade_com_sonda_oculta = els.grade.innerHTML;
saida.corpo_sonda_oculta = lerCorpo('sonda_de_teste');

// Exibindo a sonda, ela entra na grade e renderiza.
const st = lay.alternarOculto('host', kernel._interno.estadoAtual(), 'sonda_de_teste');
saida.sonda_visivel_no_estado = !(st.ocultos || []).includes('sonda_de_teste');
kernel._interno.irPara(esc.stack('web'));
kernel._interno.irPara(esc.host());
kernel._interno.repintar();
saida.grade_com_sonda_visivel = els.grade.innerHTML;
saida.corpo_sonda_visivel = lerCorpo('sonda_de_teste');

/* --- escopos: stack e container ------------------------------------------ */
kernel._interno.irPara(esc.stack('web'));
kernel._interno.repintar();
saida.grade_stack = els.grade.innerHTML;
saida.faixa_no_stack = els.faixa.innerHTML;

kernel._interno.irPara(esc.container('front'));
kernel._interno.repintar();
await new Promise((r) => setTimeout(r, 0));
saida.subtela = els.subtela.innerHTML;
saida.faixa_no_container = els.faixa.innerHTML;
saida.regua_no_container = lerRegua();
// A grade de fundo continua sendo a do host: kernel visível por construção.
saida.grade_atras_da_subtela = els.grade.innerHTML;

/* --- aceite 2: sem actions_enabled, nenhum botão de ação no DOM ---------- */
const SEM_ACOES = { ...OVERVIEW, summary: { ...SUMMARY, capabilities: { actions_enabled: false, terminal_enabled: false } } };
kernel._interno.irPara(esc.host());
kernel._interno.definirDados({ overview: SEM_ACOES, findings: FINDINGS });
kernel._interno.repintar();
await new Promise((r) => setTimeout(r, 0));
saida.dom_sem_acoes = els.grade.innerHTML + lerRegua() + els.subtela.innerHTML
  + [...registro.keys()].filter((k) => k.startsWith('mod-')).map((k) => registro.get(k).innerHTML).join('');

/* --- layout: corrompido, ↑↓ vs drag, preset -> personalizado ------------- */
localStorage.setItem('cockpit.layout.host', '{isso nao e json');
saida.layout_corrompido = lay.carregar('host');

const base = lay.aplicarPreset('host', 'operacao');
saida.preset_aplicado = { preset: base.preset, ocultos: base.ocultos.slice().sort() };

const ids = base.ordem;
const porSetas = lay.mover('host', base, ids[0], +1);
const porDrag = lay.trocar('host', base, ids[0], ids[1]);
saida.setas_igual_drag = JSON.stringify(porSetas.ordem) === JSON.stringify(porDrag.ordem);
saida.ajuste_vira_personalizado = porSetas.preset === null;

const restaurado = lay.restaurar('host');
saida.restaurar_volta_ao_preset = restaurado.preset;

/* Invariante 3 com um preset que esconde módulo COM chip.
 *
 * O preset padrão (`operacao`) esconde `drift` e `logs` — justamente os dois que
 * não têm chip: `logs` não tem chave no summary, e o de `drift` se cala enquanto
 * o B8 não existe. Com ele o invariante não ficaria demonstrado. O preset
 * `executivo` esconde 4, entre eles `containers` e `auditoria`, que têm chip —
 * é o cenário do doc 12 §5: "Executivo esconde 4 módulos, chips continuam vivos".
 */
lay.aplicarPreset('host', 'executivo');
kernel._interno.irPara(esc.stack('web'));
kernel._interno.irPara(esc.host());
kernel._interno.definirDados({ overview: OVERVIEW, findings: FINDINGS });
kernel._interno.repintar();
saida.estado_executivo = kernel._interno.estadoAtual();
saida.regua_executivo = lerRegua();
saida.grade_executivo = els.grade.innerHTML;

/* --- presets do protótipo montam exatamente os 13 dele ------------------- */
const presets = await import(new URL('../../app/static/js/kernel/presets.js', import.meta.url));
const idsEmPresets = new Set();
for (const tipo of ['host', 'stack', 'container']) {
  for (const p of presets.doTipo(tipo)) p.ordem.forEach((id) => idsEmPresets.add(id));
}
saida.ids_em_presets = [...idsEmPresets].sort();

/* O kernel deixa um setInterval de polling e um EventSource vivos por desenho —
 * é o loop compartilhado do doc 10 §3. Num harness isso significa que o node
 * nunca sai, então o encerramento é explícito depois de a saída ser escrita. */
/* --- 2b-UI: corpos reais dos módulos ------------------------------------ */
lay.restaurar('host');
const mods2b = {
  armazenamento: await import(new URL('../../app/static/js/modulos/armazenamento.js', import.meta.url)),
  eventos: await import(new URL('../../app/static/js/modulos/eventos.js', import.meta.url)),
  metricas: await import(new URL('../../app/static/js/modulos/metricas.js', import.meta.url)),
};

async function corpoDe(mod, escopo, dadosExtra) {
  const alvo = fazerNo('corpo-teste');
  registro.set('corpo-teste', alvo);
  const dispose = mod.default.render(escopo, { overview: OVERVIEW, findings: FINDINGS, ...dadosExtra }, alvo);
  for (let i = 0; i < 40; i++) await Promise.resolve();
  await new Promise((r) => setTimeout(r, 0));
  // O HTML "visivel" inclui o que os filhos pintaram: modulos escrevem em
  // sub-nos (`[data-serie]`, `[data-pre]`) depois do primeiro render.
  let html = alvo.innerHTML;
  for (const [, filho] of alvo._filhos) html += filho.innerHTML;
  if (typeof dispose === 'function') dispose();
  return html;
}

// sem unlock: a flag está ligada mas a sessão não
globalThis.sessionStorage.removeItem('cockpit-unlock');
saida.armazenamento_sem_unlock = await corpoDe(mods2b.armazenamento, esc.host());

// com unlock e flag ligada: o botão existe
globalThis.sessionStorage.setItem('cockpit-unlock', JSON.stringify({
  token: 'tok', expiresAt: new Date(Date.now() + 600000).toISOString(),
}));
saida.armazenamento_com_unlock = await corpoDe(mods2b.armazenamento, esc.host());

// flag desligada, mesmo com unlock: o botão NÃO existe no DOM
const SEM_FLAG = { ...OVERVIEW, summary: { ...SUMMARY, capabilities: { actions_enabled: false, terminal_enabled: false } } };
saida.armazenamento_sem_flag = await corpoDe(mods2b.armazenamento, esc.host(), { overview: SEM_FLAG });

// timeline nos 3 escopos, e a URL que cada um pede
const pedidos = [];
const fetchOriginal = globalThis.fetch;
globalThis.fetch = async (url) => { pedidos.push(url); return fetchOriginal(url); };
saida.eventos_host = await corpoDe(mods2b.eventos, esc.host());
saida.eventos_stack = await corpoDe(mods2b.eventos, esc.stack('web'));
saida.eventos_container = await corpoDe(mods2b.eventos, esc.container('criptotrade-app'));
saida.urls_eventos = pedidos.filter((u) => String(u).includes('/api/events'));
globalThis.fetch = fetchOriginal;

saida.metricas_container = await corpoDe(mods2b.metricas, esc.container('front'));

// storage fora do ar degrada o cartão, não a tela
servir({ ...ROTAS_2B, '/api/storage': null });
saida.armazenamento_caido = await corpoDe(mods2b.armazenamento, esc.host());
servir({ ...ROTAS_2B, '/api/events': null });
saida.eventos_caido = await corpoDe(mods2b.eventos, esc.host());
servir(ROTAS_2B);

/* --- 3-B5: busca em logs ------------------------------------------------- */
const MARCAS = { start: '\u2062<', end: '>\u2062' };
const BUSCA = {
  results: [
    { container: 'criptotrade-app', ts: '2026-07-30T12:00:00Z', stream: 'stderr',
      trecho: `MemoryError: ${MARCAS.start}oom${MARCAS.end} killed at 512MB`,
      linha: 'MemoryError: oom killed at 512MB' },
    // linha hostil: o unico lugar do cockpit que renderiza texto de dentro do container
    { container: 'api', ts: '2026-07-30T12:01:00Z', stream: 'stdout',
      trecho: `<script>alert(1)</script> ${MARCAS.start}oom${MARCAS.end}`,
      linha: '<script>alert(1)</script> oom' },
  ],
  count: 2, query: 'oom', expression: '\"oom\"', marks: MARCAS, next_offset: null,
};

const modLogs = await import(new URL('../../app/static/js/modulos/logs.js', import.meta.url));

// A rota mais especifica PRIMEIRO: `servir` casa por prefixo na ordem das
// chaves, e o catch-all '/api' do ROTAS_2B engoliria a busca.
servir({ '/api/logs/search': BUSCA, '/api/containers': 'linha de tail\n', ...ROTAS_2B });

const alvoLogs = fazerNo('corpo-logs');
registro.set('corpo-logs', alvoLogs);
const disposeLogs = modLogs.default.render(esc.container('criptotrade-app'),
  { overview: OVERVIEW, abrirContainer: () => {} }, alvoLogs);
for (let i = 0; i < 40; i++) await Promise.resolve();

saida.logs_topo = alvoLogs.innerHTML;

// digita e dispara a busca (o modulo usa debounce de 300ms)
const campo = alvoLogs.querySelectorAll('[data-busca]')[0];
if (campo) {
  campo.value = 'oom';
  (campo._handlers || []).forEach((h) => h());
}
await new Promise((r) => setTimeout(r, 400));
for (let i = 0; i < 40; i++) await Promise.resolve();
const painelLogs = alvoLogs._filhos.get('resultados=');
saida.logs_busca = painelLogs ? painelLogs.innerHTML : '';
saida.logs_nota = (alvoLogs._filhos.get('nota=') || {}).textContent || '';
if (typeof disposeLogs === 'function') disposeLogs();

process.stdout.write(JSON.stringify(saida), () => process.exit(0));
