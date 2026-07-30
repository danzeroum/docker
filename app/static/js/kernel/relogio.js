/* Relógio compartilhado — UM `setInterval` no cockpit inteiro (doc 13 §4).
 *
 * Antes havia seis: `main.js` (30s), `attention.js` (10s), `auditoria.js`
 * (15s), `ingress.js` (POLL_MS), `projects.js` (10s) e `commands.js` (60s),
 * cada um com o próprio `visibilitychange`. Dois efeitos, os dois ruins:
 *
 * - os piscas ficam desalinhados. Seis relógios com fases independentes
 *   produzem atualização em momentos arbitrários, e o olho lê movimento sem
 *   causa — que é exatamente a sensação que este ciclo veio tirar;
 * - a pausa com aba oculta era responsabilidade de cada um. Um que esquecesse
 *   ficava buscando para uma aba que ninguém olha, e o `setInterval` do
 *   navegador ainda entrega a rajada acumulada ao voltar.
 *
 * Aqui a pausa é do relógio, não do assinante: com a aba oculta nenhum tick
 * acontece. Ao voltar, cada assinante cujo período já venceu roda UMA vez —
 * não uma vez por período perdido. Rajada acumulada é o que faz uma aba
 * retomada gastar 12 requisições de uma vez e parecer travada de novo.
 *
 * Módulo declara período como MÚLTIPLO do tick, nunca em milissegundos soltos:
 * é isso que mantém os piscas em fase. `assinar(fn, 2 * TICK_MS)` lê a cada dois
 * ticks, no mesmo instante em que quem lê a cada um também lê.
 */

/** Base de tempo do cockpit. Todo período é múltiplo disto. */
export const TICK_MS = 5000;

let _timer = null;
let _tick = 0;
let _ligado = false;

/* Set e não Array: assinante que se desassina durante o próprio disparo é
 * rotina (dispose de módulo). Splice em array sob iteração pula o vizinho. */
const _assinantes = new Set();

function periodoEmTicks(periodoMs) {
  const bruto = Number(periodoMs) || TICK_MS;
  const ticks = Math.max(1, Math.round(bruto / TICK_MS));
  if (Math.abs(ticks * TICK_MS - bruto) > 1) {
    // Aviso, não erro: um período fora da grade continua funcionando, só deixa
    // de estar em fase com os outros. Derrubar a tela por isso seria pior.
    // eslint-disable-next-line no-console
    console.warn(`relógio: ${bruto}ms não é múltiplo de ${TICK_MS}ms; usando ${ticks * TICK_MS}ms`);
  }
  return ticks;
}

function disparar(assinante) {
  assinante.ultimo = _tick;
  try {
    assinante.fn();
  } catch (e) {
    // Assinante que levanta não pode parar o relógio dos outros.
    // eslint-disable-next-line no-console
    console.error('relógio: assinante levantou', e);
  }
}

function bater() {
  if (document.hidden) return;
  _tick += 1;
  for (const a of [..._assinantes]) {
    if (_tick - a.ultimo >= a.ticks) disparar(a);
  }
}

function iniciar() {
  if (_timer) return;
  _timer = setInterval(bater, TICK_MS);
}

function parar() {
  if (_timer) clearInterval(_timer);
  _timer = null;
}

/* Ao voltar de aba oculta: UMA atualização, e uma só.
 *
 * Todo assinante roda exatamente uma vez, independentemente de quantos períodos
 * teriam vencido na ausência. As duas alternativas são piores: repor os ticks
 * perdidos entrega a rajada acumulada (12 requisições no instante em que a aba
 * volta, que é quando o operador está olhando), e não fazer nada deixa a tela
 * mostrando o estado de dez minutos atrás sem dizer que é velho. */
function aoVoltar() {
  if (document.hidden) {
    parar();
    return;
  }
  iniciar();
  _tick += 1;
  for (const a of [..._assinantes]) disparar(a);
}

/**
 * Assina o relógio.
 *
 * @param {function} fn        chamado a cada `periodoMs`
 * @param {number} periodoMs   múltiplo de TICK_MS
 * @param {object} [opcoes]    `{ agora: true }` dispara já na assinatura
 * @returns {function} cancela a assinatura
 */
export function assinar(fn, periodoMs, opcoes) {
  if (typeof fn !== 'function') throw new TypeError('assinar precisa de função');
  const assinante = { fn, ticks: periodoEmTicks(periodoMs), ultimo: _tick };
  _assinantes.add(assinante);
  ligar();
  if (opcoes && opcoes.agora) disparar(assinante);
  return () => {
    _assinantes.delete(assinante);
    // Sem assinante, sem timer. Um relógio batendo para ninguém acorda a aba de
    // graça — e, num harness de teste, é o que impede o processo de terminar.
    if (!_assinantes.size) parar();
  };
}

/** Liga o relógio (idempotente). Chamado pela primeira assinatura. */
export function ligar() {
  if (_ligado) return;
  _ligado = true;
  document.addEventListener('visibilitychange', aoVoltar);
  if (!document.hidden) iniciar();
}

/** Desliga tudo — usado no `beforeunload` e entre casos de teste. */
export function desligar() {
  parar();
  if (_ligado) document.removeEventListener('visibilitychange', aoVoltar);
  _ligado = false;
  _assinantes.clear();
  _tick = 0;
}

/* Só para teste: avança o relógio sem esperar tempo real. `bater` respeita
 * `document.hidden`, então o caso "aba oculta não tica" é exercitável. */
export const _interno = {
  bater,
  aoVoltar,
  tickAtual: () => _tick,
  quantos: () => _assinantes.size,
};
