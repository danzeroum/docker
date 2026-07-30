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
    hidden: false,
    style: {},
    dataset: {},
    get innerHTML() { return this._html; },
    set innerHTML(v) {
      this._html = String(v);
      for (const m of this._html.matchAll(/id="([^"]+)"/g)) {
        if (!registro.has(m[1])) registro.set(m[1], fazerNo(m[1]));
      }
    },
    get textContent() { return this._texto || ''; },
    set textContent(v) { this._texto = String(v); },
    addEventListener() {},
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
      for (const mm of this._html.matchAll(new RegExp(`data-${attr}="([^"]*)"`, 'g'))) {
        achados.push({ dataset: { [attr]: mm[1], modulo: mm[1], id: mm[1] }, addEventListener() {} });
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

servir({ '/api/overview': OVERVIEW, '/api/findings': FINDINGS, '/api': {} });

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
process.stdout.write(JSON.stringify(saida), () => process.exit(0));
