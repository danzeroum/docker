/* Exercita a logica pura de topologia.js e plantao.js e imprime JSON.
 *
 * Chamado por tests/test_telas_topologia_plantao.py. Nao usa framework: node
 * importa os modulos ES do frontend como o navegador importaria, e as
 * afirmacoes ficam do lado do pytest.
 */
import './dom_stub.mjs';

const raiz = new URL('../../app/static/js/', import.meta.url);
const topo = await import(new URL('screens/topologia.js', raiz));
const plt = await import(new URL('screens/plantao.js', raiz));

const saida = {};

// --- topologia: leitura de upstream -----------------------------------------
saida.alvos = [
  'http://criptotrade-frontend:80',
  'http://btv-squad-dashboard:7878/painel',
  'https://app:8000',
  'http://semporta',
  '',
  null,
].map(u => topo.alvoDoUpstream(u));

// --- topologia: cruzamento com o inventario ---------------------------------
const ingress = {
  hosts: {
    'no-ar.exemplo.com': { ssl: true, upstreams: ['http://app-vivo:80'] },
    'parado.exemplo.com': { ssl: true, upstreams: ['http://app-parado:80'] },
    'sumiu.exemplo.com': { ssl: true, upstreams: ['http://app-que-nao-existe:80'] },
    'doente.exemplo.com': { ssl: true, upstreams: ['http://app-doente:80'] },
    'so-redirect.exemplo.com': { ssl: false, port_80: { https_redirect: true } },
    'interno.localhost': { internal: true, upstreams: ['http://app-vivo:80'] },
  },
  totals: { total: 6, public: 5, with_ssl: 4, with_auth: 0 },
  parsed_at: '2026-07-29T10:00:00Z',
};
const containers = [
  { name: 'app-vivo', stack: 'x', state: 'running', health: 'none', ports: '' },
  { name: 'app-parado', stack: 'x', state: 'exited', health: 'unhealthy', ports: '' },
  { name: 'app-doente', stack: 'x', state: 'running', health: 'unhealthy', ports: '' },
  { name: 'borda', stack: 'ingress', state: 'running', health: 'none', ports: '80/tcp, 443/tcp', restart_count: 2 },
];

const cruzados = topo.confrontarUpstreams(topo.elosDoIngress(ingress), containers);
saida.situacoes = cruzados
  .map(c => ({ dominio: c.dominio, alvo: c.alvo ? c.alvo.nome : null, situacao: c.situacao }))
  .sort((a, b) => a.dominio.localeCompare(b.dominio));

// Inventario vazio: sem leitura do daemon nao da para afirmar que sumiu.
saida.sem_inventario = topo.confrontarUpstreams(topo.elosDoIngress(ingress), [])
  .filter(c => c.alvo)
  .map(c => c.situacao);

// --- topologia: descoberta do no de ingress ---------------------------------
saida.ingress_achado = (topo.acharIngress(containers) || {}).name || null;
saida.ingress_sem_candidato = topo.acharIngress([
  { name: 'nada', state: 'running', ports: '5432/tcp' },
]);
saida.ingress_lista_vazia = topo.acharIngress([]);

// --- plantao: ordem de atendimento ------------------------------------------
const T = (h) => new Date(Date.UTC(2026, 6, 29, 12 - h, 0, 0)).toISOString();
const fila = [
  { id: 'medio-antigo', severity: 'medium', first_seen: T(50), score: 10 },
  { id: 'critico-novo', severity: 'critical', first_seen: T(1), score: 10 },
  { id: 'critico-antigo', severity: 'critical', first_seen: T(30), score: 10 },
  { id: 'alto', severity: 'high', first_seen: T(2), score: 10 },
  { id: 'baixo', severity: 'low', first_seen: T(99), score: 10 },
  { id: 'critico-mais-pontos', severity: 'critical', first_seen: T(1), score: 90 },
];
saida.ordem = plt.ordenarFila(fila).map(f => f.id);
saida.ordem_nao_mutou_entrada = fila[0].id;
saida.ordem_lista_vazia = plt.ordenarFila([]).length;
saida.ordem_sem_lista = plt.ordenarFila(null).length;
saida.ordem_severidade_desconhecida = plt.ordenarFila([
  { id: 'lixo', severity: 'inventada', first_seen: T(1) },
  { id: 'baixo', severity: 'low', first_seen: T(1) },
]).map(f => f.id);

// --- plantao: tempo aberto --------------------------------------------------
const agora = Date.UTC(2026, 6, 29, 12, 0, 0);
saida.tempos = [
  plt.tempoAberto(T(0), agora),
  plt.tempoAberto(T(1), agora),
  plt.tempoAberto(T(26), agora),
  plt.tempoAberto(null, agora),
  plt.tempoAberto(new Date(agora + 60000).toISOString(), agora),
];

process.stdout.write(JSON.stringify(saida, null, 1));
