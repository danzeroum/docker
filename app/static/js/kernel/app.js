/* Núcleo do Cockpit Vivo — monta cockpit por escopo, sem conhecer módulo algum.
 *
 * Substitui o `switch (_route(screen))` com um `case` por tela que vivia em
 * main.js. Aquele switch era o oposto exato da regra do doc 10 §4: o núcleo
 * conhecia cada tela pelo nome, e acrescentar tela significava editá-lo.
 *
 * `grep` neste arquivo não encontra o id de nenhum módulo. A única lista de
 * módulos do sistema está em `modulos/index.js`.
 *
 * Observer é o padrão do loop (doc 10 §3): um polling compartilhado busca
 * `/api/overview` (que já traz o summary numa chamada) e notifica quem estiver
 * montado. Módulo oculto não é montado, logo não busca — e o chip dele continua
 * vivo porque lê o summary, não o próprio endpoint.
 */

import { apiGet } from '../data.js';
import { registrarTodos } from '../modulos/index.js';
import { doEscopo, porId, todos } from './registry.js';
import { deHash, mesmo, paraHash, rotulo, tipoDeCockpit, host, stack, container } from './escopo.js';
import { carregar, reconciliar, alternarOculto } from './layout.js';
import { montarRegua, pintarRegua, pintarFaixaCritica } from './regua.js';
import { pintarCockpit, desmontar } from './cockpit.js';
import { abrir as abrirPz, alternar as alternarPz, aberto as pzAberto, pintarPainel } from './personalizar.js';
import { abrirSubtela, fecharSubtela } from './subtela.js';

const INTERVALO_MS = 15000;

let _escopo = host();
let _estado = null;
let _dados = { overview: null, findings: [] };
let _timer = null;
let _els = {};

/* --- estado de layout ---------------------------------------------------- */

function estadoDoEscopo(escopo) {
  const tipo = tipoDeCockpit(escopo);
  const idsDoEscopo = doEscopo(tipo).map((m) => m.id);
  return reconciliar(carregar(tipo), idsDoEscopo);
}

/* --- navegação ----------------------------------------------------------- */

function irPara(novo, { semHash } = {}) {
  if (mesmo(novo, _escopo) && _estado) return;
  _escopo = novo;
  _estado = estadoDoEscopo(novo);
  if (!semHash) {
    const alvo = paraHash(novo);
    if (location.hash !== alvo) location.hash = alvo;
  }
  pintar();
}

function abrirContainer(id) {
  irPara(container(id));
}

function abrirStack(id) {
  irPara(stack(id));
}

function voltarAoHost() {
  irPara(host());
}

/* --- pintura ------------------------------------------------------------- */

function contexto() {
  // O que todo módulo recebe. Handlers de navegação entram aqui para que módulo
  // nenhum precise conhecer o roteador — inversão de dependência: o núcleo
  // fornece, o módulo consome.
  return { ..._dados, abrirContainer, abrirStack, voltarAoHost, escopo: _escopo };
}

function pintar() {
  if (!_estado) _estado = estadoDoEscopo(_escopo);

  pintarFaixaCritica(_els.faixa, _dados.findings);
  pintarRegua({
    escopo: _escopo,
    overview: _dados.overview,
    estado: _estado,
    onChip: (id) => {
      // Invariante 3: o chip de um módulo oculto reexibe o módulo. É o que
      // impede "ocultar" de significar "perder o dado".
      const ocultos = new Set(_estado.ocultos || []);
      if (ocultos.has(id)) {
        _estado = alternarOculto(tipoDeCockpit(_escopo), _estado, id);
        pintar();
        return;
      }
      const el = document.querySelector(`.mod[data-modulo="${id}"]`);
      if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
    },
  });

  pintarPainel(_els.painel, _escopo, _estado, (novo) => {
    _estado = reconciliar(novo, doEscopo(tipoDeCockpit(_escopo)).map((m) => m.id));
    pintar();
  });

  if (_escopo.t === 'container') {
    const alvo = abrirSubtela(
      _els.subtela, _escopo.id, rotuloDaStack(_escopo.id), voltarAoHost
    );
    // A grade de fundo continua sendo a do host: o kernel e a faixa seguem
    // visíveis por construção (doc 10 §2).
    pintarCockpitEm(_els.grade, host(), estadoDoEscopo(host()));
    if (alvo) pintarCockpitEm(alvo, _escopo, _estado, { manter: true });
  } else {
    fecharSubtela(_els.subtela);
    pintarCockpitEm(_els.grade, _escopo, _estado);
  }

  atualizarTitulo();
}

/* Dois cockpits podem estar na tela ao mesmo tempo (fundo + subtela), então o
 * desmonte é explícito e por alvo em vez de global. */
function pintarCockpitEm(alvo, escopo, estado, opts) {
  if (!alvo) return;
  if (!opts || !opts.manter) desmontar();
  pintarCockpit(alvo, escopo, estado, contexto());
}

function rotuloDaStack(idContainer) {
  const lista = (_dados.overview && _dados.overview.containers) || [];
  const c = lista.find((x) => x.name === idContainer || x.id === idContainer);
  return c && c.stack ? `stack: ${c.stack}` : '';
}

function atualizarTitulo() {
  const t = document.getElementById('mainTitle');
  const s = document.getElementById('mainSubtitle');
  if (t) t.textContent = _escopo.t === 'host' ? 'Cockpit Docker' : rotulo(_escopo);
  if (s) {
    const n = (_estado.ordem || []).length - (_estado.ocultos || []).length;
    s.textContent = `${n} módulo(s) visível(is)${_estado.preset ? ` · preset ${_estado.preset}` : ' · personalizado'}`;
  }
}

/* --- dados --------------------------------------------------------------- */

async function buscar() {
  const [ov, fd] = await Promise.all([
    apiGet('kernel_overview', '/api/overview'),
    apiGet('kernel_findings', '/api/findings?status=open'),
  ]);
  if (!ov.error && ov.data) _dados.overview = ov.data;
  if (!fd.error && Array.isArray(fd.data)) _dados.findings = fd.data;
  pintar();
}

function iniciarPolling() {
  pararPolling();
  _timer = setInterval(() => {
    // Pausa com aba oculta — mantido do comportamento anterior (doc 00).
    if (!document.hidden) buscar();
  }, INTERVALO_MS);
}

function pararPolling() {
  if (_timer) clearInterval(_timer);
  _timer = null;
}

/* --- boot ---------------------------------------------------------------- */

export function iniciar(els) {
  _els = els || {};
  registrarTodos();
  montarRegua(_els.regua);

  _escopo = deHash(location.hash);
  _estado = estadoDoEscopo(_escopo);

  window.addEventListener('hashchange', () => {
    irPara(deHash(location.hash), { semHash: true });
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) buscar();
  });

  const btn = document.getElementById('personalizarBtn');
  if (btn) {
    btn.addEventListener('click', () => {
      alternarPz();
      btn.setAttribute('aria-pressed', pzAberto() ? 'true' : 'false');
      pintar();
    });
  }

  pintar();
  buscar();
  iniciarPolling();
}

/* Ponte para os corpos de tela que ainda chamam `navigate('#/algo')`.
 *
 * A derivação é GENÉRICA de propósito: `#/x` procura um módulo de id `x` no
 * registro e o revela. Não há tabela de apelidos — uma tabela aqui devolveria ao
 * núcleo o conhecimento de módulos que a 2a acabou de tirar dele. Hash que não
 * casa com módulo nenhum cai no escopo host, que é o destino seguro.
 */
export function navegarPorHash(hash) {
  const id = String(hash || '').replace(/^#\/?/, '').split('?')[0];
  if (id && porId(id)) {
    const tipo = tipoDeCockpit(_escopo);
    const ocultos = new Set(_estado.ocultos || []);
    if (ocultos.has(id)) _estado = alternarOculto(tipo, _estado, id);
    pintar();
    const el = document.querySelector(`.mod[data-modulo="${id}"]`);
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
    return;
  }
  irPara(host());
}

/* Exposto para teste: registrar um módulo em runtime e conferir que ele aparece
 * na régua e no Personalizar sem tocar este arquivo (aceite do doc 10 §testes). */
export const _interno = {
  repintar: pintar,
  escopoAtual: () => _escopo,
  estadoAtual: () => _estado,
  definirDados: (d) => { _dados = { ..._dados, ...d }; },
  irPara,
  modulosRegistrados: () => todos().map((m) => m.id),
};
