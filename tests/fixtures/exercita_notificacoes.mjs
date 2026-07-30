/* Exercita o selo "notificado hh:mm · canal" (4-B7) sob node.
 *
 * O caso que só a execução separa: uma tentativa REGISTRADA mas não entregue
 * (canal fora do ar) não pode virar selo. Ela existe na resposta da rota — é
 * justamente o registro de que o alerta não chegou — e um mapa ingênuo que só
 * olhasse `regra`+`alvo` diria "notificado" para quem não recebeu nada.
 */
import './dom_stub.mjs';

const { carregarNotificacoes, seloDeNotificacao, _resetarCache } =
  await import('../../app/static/js/notificacoes.js');

let chamadas = 0;
let resposta = { notifications: [], summary: null };
let falhar = false;

globalThis.fetch = async () => {
  chamadas += 1;
  if (falhar) throw new Error('rede');
  return { ok: true, json: async () => resposta, text: async () => '' };
};
globalThis.AbortController = class {
  constructor() { this.signal = {}; }
  abort() {}
};

const ENTREGA = '2026-07-30T03:14:00Z';
const ANTES = '2026-07-30T01:00:00Z';

function comDados() {
  return {
    notifications: [
      // mais recente primeiro, como a rota devolve
      { regra: 'unhealthy', alvo: 'api', ts: ENTREGA, enviado_em: ENTREGA,
        canais: ['telegram', 'discord'], falhas: '' },
      { regra: 'unhealthy', alvo: 'api', ts: ANTES, enviado_em: ANTES,
        canais: ['telegram'], falhas: '' },
      // tentativa registrada e NAO entregue: nenhum canal aceitou
      { regra: 'disk_high', alvo: '/', ts: ENTREGA, enviado_em: null,
        canais: [], falhas: 'slack: HTTP 500' },
      { regra: 'container_die', alvo: 'worker', ts: ENTREGA, enviado_em: ENTREGA,
        canais: ['telegram'], falhas: 'discord: HTTP 404' },
    ],
    summary: { total: 4, sem_entrega: 1, ultima_entrega: ENTREGA },
  };
}

const saida = {};

_resetarCache();
resposta = comDados();
chamadas = 0;
let estado = await carregarNotificacoes();

saida.entregue = seloDeNotificacao(estado, 'unhealthy', 'api');
saida.semEntregaNaoTemSelo = seloDeNotificacao(estado, 'disk_high', '/');
saida.regraNaoNotificadaNaoTemSelo = seloDeNotificacao(estado, 'restart_loop', 'api');
saida.alvoDiferenteNaoHerdaSelo = seloDeNotificacao(estado, 'unhealthy', 'worker');
saida.entregaParcial = seloDeNotificacao(estado, 'container_die', 'worker');

/* cache: a fila de achados repinta a cada poll ------------------------------ */
await carregarNotificacoes();
await carregarNotificacoes();
saida.chamadasComCache = chamadas;

/* rota muda -> forcar recarrega --------------------------------------------- */
resposta = { notifications: [], summary: null };
estado = await carregarNotificacoes(true);
saida.chamadasAposForcar = chamadas;
saida.aposLimparSelo = seloDeNotificacao(estado, 'unhealthy', 'api');

/* motor nunca rodou ---------------------------------------------------------- */
_resetarCache();
resposta = { notifications: [], summary: null };
estado = await carregarNotificacoes();
saida.semMotorSelo = seloDeNotificacao(estado, 'unhealthy', 'api');

/* rota falhou ---------------------------------------------------------------- */
_resetarCache();
falhar = true;
estado = await carregarNotificacoes();
saida.comFalhaSelo = seloDeNotificacao(estado, 'unhealthy', 'api');
falhar = false;

process.stdout.write(JSON.stringify(saida, null, 2));
