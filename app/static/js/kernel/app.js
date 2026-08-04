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
import {
  montarRegua, pintarRegua, pintarFaixaCritica, marcarLeitura, pausarVivo,
  informarIdadeDaAmostra,
} from './regua.js';
import { pintarCockpit, desmontar } from './cockpit.js';
import { abrir as abrirPz, alternar as alternarPz, aberto as pzAberto, pintarPainel } from './personalizar.js';
import { abrirSubtela, fecharSubtela, corpoSubtela } from './subtela.js';
import { assinar, desligar as pararRelogio, TICK_MS } from './relogio.js';

/* 15s continua sendo o período — agora declarado como MÚLTIPLO do tick do
 * relógio compartilhado, e não como um `setInterval` próprio. É o que mantém a
 * leitura do kernel em fase com a dos módulos: um pisca só, não seis. */
const PERIODO_TICKS = 3;

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

/* Estado de leitura da régua. Sem rede vence aba oculta na hora de rotular: é a
 * parada que o operador precisa notar, porque não volta sozinha. `navigator.onLine`
 * pode não existir em ambiente de teste sem navegador — ausente conta como online,
 * que é o comportamento de antes deste bloco. */
function dizerSeEstaLendo() {
  const semRede = typeof navigator === 'object' && navigator && navigator.onLine === false;
  const oculto = typeof document === 'object' && document && document.hidden;
  pausarVivo(semRede || !!oculto, semRede ? 'rede' : 'oculto');
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
    pintarCockpit(_els.grade, host(), estadoDoEscopo(host()), contexto());
    if (alvo) pintarCockpit(alvo, _escopo, _estado, contexto());
  } else {
    // Sair do escopo de container é a única hora em que os módulos da subtela
    // morrem. O desmonte é por ALVO: a grade de fundo continua montada, e é
    // justamente por isso que voltar para a Visão geral não recarrega nada.
    // O `if` não é defensivo à toa: `desmontar()` sem alvo desmonta TUDO, e sem
    // ele fechar uma subtela já fechada derrubaria a grade de fundo.
    const corpoAnterior = corpoSubtela(_els.subtela);
    if (corpoAnterior) desmontar(corpoAnterior);
    fecharSubtela(_els.subtela);
    pintarCockpit(_els.grade, _escopo, _estado, contexto());
  }

  atualizarTitulo();
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
  /* A idade da amostra vem no mesmo pacote e é entregue à régua aqui, junto do
   * dado. Fora deste ponto ela seria um palpite: `stats_as_of` só vale contra o
   * instante em que a resposta chegou. */
  informarIdadeDaAmostra(_dados.overview);
  // A varredura da pílula reinicia AQUI, com o dado na mão: é o único instante
  // em que ela é verdade. Reiniciar no disparo do relógio anunciaria leitura
  // antes de haver leitura.
  marcarLeitura();
  pintar();
}

function iniciarPolling() {
  pararPolling();
  // Nenhum `setInterval` novo: o kernel é mais um assinante do relógio.
  _timer = assinar(buscar, PERIODO_TICKS * TICK_MS);
}

function pararPolling() {
  if (typeof _timer === 'function') _timer();
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
    rotear(location.hash);
  });
  /* A busca de retorno é do relógio, não daqui: ele dispara UMA atualização por
   * assinante ao voltar. O que sobra para o kernel é dizer a verdade na régua —
   * nada sendo lido, a pílula não pode continuar dizendo "ao vivo".
   *
   * São DUAS razões para a leitura parar, e a pílula precisa das duas num lugar
   * só: se cada evento chamasse `pausarVivo` sozinho, voltar para a aba enquanto
   * ainda sem rede apagaria o aviso de rede e a pílula voltaria a mentir. */
  document.addEventListener('visibilitychange', dizerSeEstaLendo);
  window.addEventListener('offline', dizerSeEstaLendo);
  window.addEventListener('online', dizerSeEstaLendo);
  dizerSeEstaLendo();

  const btn = document.getElementById('personalizarBtn');
  if (btn) {
    btn.addEventListener('click', () => {
      alternarPz();
      btn.setAttribute('aria-pressed', pzAberto() ? 'true' : 'false');
      pintar();
    });
  }

  pintar();
  // A hash de entrada passa pelo MESMO roteador que o `hashchange`. Sem isto,
  // abrir `#/auditoria` direto (link colado, favorito, recarregar a página)
  // pintaria o host e pararia aí — a mesma falha, só que na primeira carga.
  rotear(location.hash);
  buscar();
  iniciarPolling();
}

/* --- roteador da hash ------------------------------------------------------
 *
 * UM roteador, dono único da hash. Antes o `hashchange` chamava só `deHash`, que
 * conhece `#/stack/<id>` e `#/container/<id>` e devolve o host para todo o resto
 * — e os 11 itens do rail caíam nesse "resto". Clicar não fazia NADA: sem erro
 * de console, sem 404, a mesma tela. Falha silenciosa, que é o modo de errar
 * mais caro deste produto (a mesma razão do aviso de nginx ausente em app.py).
 *
 * A hash tem duas gramáticas, nesta ordem:
 *
 *   `#/stack/<id>`, `#/container/<id>`  →  troca o ESCOPO (outro cockpit)
 *   `#/<idDeModulo>`                    →  revela e rola até o MÓDULO
 *
 * O que não casa com nenhuma das duas cai no host — destino seguro e, para
 * `#/`, o destino correto.
 *
 * A segunda derivação é GENÉRICA de propósito: o id vem do registro, não de uma
 * tabela de apelidos aqui. Tabela devolveria ao núcleo o conhecimento de módulos
 * que a Sprint 2a tirou dele, e `grep` de id de módulo neste arquivo tem de
 * continuar vazio (doc 10 §4).
 */
export function rotear(hash, { semHash = true } = {}) {
  const bruto = String(hash || '').replace(/^#\/?/, '').split('?')[0];
  const [primeiro, segundo] = bruto.split('/');

  if ((primeiro === 'stack' || primeiro === 'container') && segundo) {
    irPara(deHash(hash), { semHash });
    return;
  }

  const mod = bruto && !segundo ? porId(bruto) : null;
  if (mod && revelar(mod)) {
    // A hash só é sincronizada DEPOIS de a revelação dar certo: barra de endereço
    // que anuncia um destino a que não se chegou é a mesma mentira que este
    // roteador existe para acabar, só que escrita na URL.
    if (!semHash) {
      const alvo = `#/${mod.id}`;
      if (location.hash !== alvo) location.hash = alvo;
    }
    return;
  }

  irPara(host(), { semHash });
}

/** Revela e rola até o módulo. `false` = não havia onde revelá-lo. */
function revelar(mod) {
  /* Nem todo módulo existe em todo cockpit: `escopos` é declaração de cada um.
   * Endereçado de um escopo onde não vive, o destino é o host — lá ele TEM caixa.
   * Mas módulo que não vive nem no host (só de stack, só de container) não tem
   * onde ser revelado em lugar nenhum, e aí o roteador devolve `false` em vez de
   * repintar a mesma tela. Repintar a mesma tela é exatamente o defeito de
   * origem; reintroduzi-lo num caso de canto seria trocar um silêncio por outro. */
  if (!mod.escopos.includes(tipoDeCockpit(_escopo))) {
    if (!mod.escopos.includes('host')) return false;
    irPara(host(), { semHash: true });
  }

  // Invariante 3 do doc 10, o mesmo do chip da régua: endereçar um módulo oculto
  // o reexibe. Ocultar não pode significar tornar inalcançável.
  const ocultos = new Set((_estado && _estado.ocultos) || []);
  if (ocultos.has(mod.id)) {
    _estado = alternarOculto(tipoDeCockpit(_escopo), _estado, mod.id);
  }
  pintar();
  const el = document.querySelector(`.mod[data-modulo="${mod.id}"]`);
  // `block: 'start'` e não `'nearest'`: `'nearest'` é o certo para o chip da
  // régua ("garanta que dá para ver"), e o errado para navegação explícita. Um
  // módulo que já estava no rodapé da janela continuaria no rodapé, e clicar no
  // menu pareceria não ter feito nada — a percepção que originou este conserto.
  //
  // Sem `behavior: 'smooth'`: a opção do JS ignora `prefers-reduced-motion`, que
  // o resto do painel respeita (components.css §6). Rolagem instantânea honra a
  // preferência por construção, sem precisar consultá-la.
  if (el && el.scrollIntoView) el.scrollIntoView({ block: 'start' });
  return true;
}

/* Um item de navegação só deve existir se levar a algum lugar. Em vez de confiar
 * que o HTML do rail e o registro de módulos nunca divirjam — divergiram, e o
 * resultado foram links mortos —, o chrome PERGUNTA ao kernel. Sem tabela: a
 * resposta sai do registro. */
export function alcancavelNoHost(hash) {
  const bruto = String(hash || '').replace(/^#\/?/, '').split('?')[0];
  const [primeiro, segundo] = bruto.split('/');
  if ((primeiro === 'stack' || primeiro === 'container') && segundo) return true;
  if (!bruto) return true;  // `#/` é o próprio cockpit do host
  const mod = segundo ? null : porId(bruto);
  return !!(mod && mod.escopos.includes('host'));
}

/* Ponte para os corpos de tela que chamam `navigate('#/algo')`. Passa pelo mesmo
 * roteador, com `semHash: false`: navegação programática TEM de aparecer na
 * barra de endereço, senão a URL mente sobre onde o visitante está. */
export function navegarPorHash(hash) {
  rotear(hash, { semHash: false });
}

/* Exposto para teste: registrar um módulo em runtime e conferir que ele aparece
 * na régua e no Personalizar sem tocar este arquivo (aceite do doc 10 §testes). */
export const _interno = {
  repintar: pintar,
  escopoAtual: () => _escopo,
  estadoAtual: () => _estado,
  definirDados: (d) => { _dados = { ..._dados, ...d }; },
  irPara,
  buscar,
  modulosRegistrados: () => todos().map((m) => m.id),
  // Encerra o kernel inteiro: assinatura do relógio, relógio e módulos montados.
  // Usado no `beforeunload` e entre casos de teste, onde um relógio sobrevivente
  // ticaria sobre o DOM do caso seguinte.
  parar: () => { pararPolling(); pararRelogio(); desmontar(); },
};
