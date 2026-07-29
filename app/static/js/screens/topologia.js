/* Topologia — o caminho real da requisicao, montado de duas rotas que ja existem.
 *
 * Nao ha rota propria de topologia e nao deve haver: cada elo da corrente ja e
 * observavel. /api/ingress da os dominios e o proxy_pass de cada um; /api/overview da o
 * inventario do daemon. Cruzar os dois responde a unica pergunta que a tela
 * precisa responder — "onde a requisicao para de andar".
 *
 * Nenhum nome de container, dominio ou porta esta escrito aqui. O no do ingress
 * e descoberto por publicar 80/443 no host; o do socket-proxy pela propria
 * resposta de /api/overview (o inventario so chega por ele); o do daemon pelo
 * campo host. Upstream sem container correspondente vira no AUSENTE — que e um
 * achado, nao um erro de carregamento.
 */
import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';

let _disposed = false;

function el(id) { return document.getElementById(id); }

const CSS_CAIXA = 'background:var(--sf);border:1px solid var(--bd1);border-radius:var(--rc);padding:12px 13px';
const CSS_RUBRICA = 'font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:700';

function cor(estado) {
  if (estado === 'ok') return 'var(--ok)';
  if (estado === 'warn') return 'var(--warn)';
  if (estado === 'bad') return 'var(--bad)';
  return 'var(--text-dim)';
}

function pill(estado, texto) {
  const c = cor(estado);
  return `<span style="font-size:9.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:${c};border:1px solid ${c};border-radius:999px;padding:1px 7px;white-space:nowrap">${escapeHtml(texto)}</span>`;
}

/* --- Leitura do ingress ---------------------------------------------------
 * upstream chega como "http://nome:porta" ou "http://nome:porta/caminho".
 * O nome antes dos dois pontos e o que o daemon conhece como container.
 */
export function alvoDoUpstream(upstream) {
  if (typeof upstream !== 'string' || !upstream) return null;
  const semEsquema = upstream.replace(/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//, '');
  const autoridade = semEsquema.split('/')[0];
  if (!autoridade) return null;
  const partes = autoridade.split(':');
  const nome = partes[0];
  if (!nome) return null;
  return { nome, porta: partes[1] || null, bruto: upstream };
}

/* Cada dominio e cada upstream que ele aponta, em uma lista plana. */
export function elosDoIngress(ingress) {
  const hosts = (ingress && ingress.hosts) || {};
  const elos = [];
  for (const [dominio, h] of Object.entries(hosts)) {
    const conf = h || {};
    const brutos = [];
    if (Array.isArray(conf.upstreams)) brutos.push(...conf.upstreams);
    const p80 = conf.port_80 || {};
    if (p80.upstream) brutos.push(p80.upstream);
    const vistos = new Set();
    for (const b of brutos) {
      const alvo = alvoDoUpstream(b);
      if (!alvo || vistos.has(alvo.nome + ':' + (alvo.porta || ''))) continue;
      vistos.add(alvo.nome + ':' + (alvo.porta || ''));
      elos.push({ dominio, interno: !!conf.internal, ssl: !!conf.ssl, alvo });
    }
    if (!brutos.length) {
      elos.push({ dominio, interno: !!conf.internal, ssl: !!conf.ssl, alvo: null });
    }
  }
  return elos;
}

/* Confronta cada upstream com o inventario do daemon.
 * Tres desfechos, tres consertos diferentes — a mesma licao da regra
 * upstream_missing: "parado" se sobe, "ausente" se corrige o proxy_pass.
 */
export function confrontarUpstreams(elos, containers) {
  const porNome = new Map();
  for (const c of containers || []) {
    if (c && c.name) porNome.set(c.name, c);
  }
  // Sem leitura do daemon nao da para afirmar que o upstream sumiu — a mesma
  // restricao que a regra upstream_missing recebeu depois de acusar container
  // parado como inexistente. Inventario vazio nao e prova de ausencia.
  const semInventario = porNome.size === 0;
  const saida = [];
  for (const elo of elos) {
    if (!elo.alvo) {
      saida.push({ ...elo, situacao: 'sem_upstream' });
      continue;
    }
    if (semInventario) {
      saida.push({ ...elo, situacao: 'sem_inventario', container: null });
      continue;
    }
    const c = porNome.get(elo.alvo.nome);
    if (!c) {
      saida.push({ ...elo, situacao: 'ausente', container: null });
    } else if (c.state !== 'running') {
      saida.push({ ...elo, situacao: 'parado', container: c });
    } else if (c.health === 'unhealthy') {
      saida.push({ ...elo, situacao: 'doente', container: c });
    } else {
      saida.push({ ...elo, situacao: 'no_ar', container: c });
    }
  }
  return saida;
}

/* O container que publica 80 ou 443 no host e o ingress — descoberto, nao
 * escrito. Se nenhum publica, o no vira ausente e a tela diz isso. */
export function acharIngress(containers) {
  const candidatos = (containers || []).filter(c => {
    const portas = (c && c.ports) || '';
    return /(^|[^0-9])(80|443)\/tcp/.test(portas);
  });
  if (!candidatos.length) return null;
  return candidatos.find(c => c.state === 'running') || candidatos[0];
}

function contarSituacoes(cruzados) {
  const n = { no_ar: 0, parado: 0, ausente: 0, doente: 0, sem_upstream: 0, sem_inventario: 0 };
  for (const c of cruzados) n[c.situacao] = (n[c.situacao] || 0) + 1;
  return n;
}

function montarNos(ingress, overview, cruzados) {
  const hosts = (ingress && ingress.hosts) || {};
  const totais = (ingress && ingress.totals) || {};
  const containers = (overview && overview.containers) || [];
  const host = (overview && overview.host) || {};
  const contadores = (overview && overview.counters) || {};
  const n = contarSituacoes(cruzados);
  const nomesDominio = Object.keys(hosts);
  const publicos = nomesDominio.filter(d => !(hosts[d] || {}).internal);
  const nos = [];

  // 1 · dominios publicados
  const semTls = publicos.filter(d => !(hosts[d] || {}).ssl).length;
  nos.push({
    nome: 'Domínios publicados',
    estado: nomesDominio.length ? (semTls ? 'warn' : 'ok') : 'dim',
    pillTexto: nomesDominio.length ? `${nomesDominio.length} hosts` : 'sem leitura',
    rede: ingress && ingress.error ? '' : '0.0.0.0:80 · 0.0.0.0:443',
    papel: nomesDominio.length
      ? `${publicos.length} públicos, ${totais.with_ssl || 0} com TLS, ${totais.with_auth || 0} atrás de basic auth`
      // papel ja passa por escapeHtml em htmlNo; escapar aqui viraria &amp; na tela
      : (ingress && ingress.error
          ? `nginx.conf não lido — ${ingress.error}`
          : 'nenhum server_name no nginx.conf'),
    metrica: String(nomesDominio.length),
    metricaLabel: 'server_name',
    transporte: 'TCP · TLS na borda',
  });

  // 2 · o container que publica as portas do host
  const ing = acharIngress(containers);
  const semInventario = containers.length === 0;
  nos.push({
    nome: ing ? ing.name : 'Ingress',
    estado: !ing ? 'dim' : ing.state === 'running' ? 'ok' : 'bad',
    pillTexto: ing ? ing.state : semInventario ? 'sem leitura' : 'não encontrado',
    rede: ing ? (ing.ports || '') : '',
    papel: ing
      ? `Termina TLS e reparte por server_name. Stack ${ing.stack}.`
      // sem inventario nao se afirma que ninguem publica as portas: nao se olhou
      : semInventario
        ? 'Inventário do daemon não chegou nesta leitura — não se sabe qual container publica as portas do host.'
        : 'Nenhum container publica 80 ou 443 no host — sem esse elo, os domínios acima não chegam a lugar nenhum.',
    metrica: ing ? String(ing.restart_count || 0) : '—',
    metricaLabel: ing ? 'restarts' : semInventario ? 'sem leitura' : 'ausente',
    transporte: 'HTTP · proxy_pass na rede docker',
  });

  // 3 · os upstreams de proxy_pass
  const alcancaveis = n.no_ar + n.doente;
  const totalElos = cruzados.filter(c => c.situacao !== 'sem_upstream').length;
  const quebrados = n.ausente + n.parado;
  const cego = n.sem_inventario > 0;
  nos.push({
    nome: 'Upstreams de proxy_pass',
    estado: cego ? 'dim' : !totalElos ? 'dim' : quebrados ? 'bad' : n.doente ? 'warn' : 'ok',
    pillTexto: cego
      ? `${totalElos} sem confronto`
      : totalElos ? `${alcancaveis}/${totalElos} no ar` : 'nenhum',
    rede: 'rede interna do docker',
    papel: cego
      ? `${totalElos} destinos declarados no nginx.conf, nenhum confrontado: o inventário do daemon não chegou, e sem ele não se afirma que um upstream sumiu.`
      : totalElos
        ? [
            n.parado ? `${n.parado} ${n.parado === 1 ? 'aponta' : 'apontam'} para container parado (subir a stack)` : '',
            n.ausente ? `${n.ausente} ${n.ausente === 1 ? 'aponta' : 'apontam'} para container inexistente (corrigir o proxy_pass)` : '',
            n.doente ? `${n.doente} ${n.doente === 1 ? 'responde' : 'respondem'} com sonda vermelha` : '',
            quebrados || n.doente ? '' : 'todos os destinos existem e estão rodando',
          ].filter(Boolean).join(' · ')
        : 'nenhum proxy_pass declarado nos server_name lidos',
    metrica: cego ? '—' : totalElos ? String(quebrados) : '—',
    metricaLabel: cego ? 'sem inventário' : 'quebrados',
    transporte: 'unix:///var/run/docker.sock (somente leitura)',
  });

  // 4 · o socket-proxy. Nao precisa de nome: o inventario desta tela veio por
  // ele. Se nao veio, o no cai sozinho.
  const inventariou = containers.length;
  nos.push({
    nome: 'Socket-proxy',
    estado: inventariou ? 'ok' : 'bad',
    pillTexto: inventariou ? 'respondendo' : 'sem resposta',
    rede: '',
    papel: inventariou
      ? `Único caminho do cockpit até o daemon. O inventário desta tela (${inventariou} containers) chegou por ele.`
      : 'O cockpit não obteve inventário algum — os nós acima estão sem confronto com a realidade.',
    metrica: String(inventariou),
    metricaLabel: 'containers',
    transporte: 'API do Docker Engine',
  });

  // 5 · daemon
  const rodando = contadores.running != null ? contadores.running : null;
  const total = contadores.total != null ? contadores.total : containers.length;
  nos.push({
    nome: host.name || 'Daemon Docker',
    estado: !total ? 'dim' : rodando === total ? 'ok' : 'warn',
    pillTexto: total ? `${rodando != null ? rodando : '?'}/${total} rodando` : 'coletando',
    rede: host.cpus ? `${host.cpus} vCPU` : '',
    papel: host.os
      ? `${host.os}. ${total - (rodando || 0)} ${total - (rodando || 0) === 1 ? 'container fora do ar' : 'containers fora do ar'} neste momento.`
      : 'Amostra do host ainda não coletada nesta sessão.',
    metrica: total ? String(total - (rodando || 0)) : '—',
    metricaLabel: 'fora do ar',
    transporte: '',
  });

  return nos;
}

function htmlNo(no, ultimo) {
  const c = cor(no.estado);
  return `<div>
    <div style="display:flex;align-items:stretch;gap:11px;${CSS_CAIXA};border-left:0;padding-left:0;overflow:hidden">
      <div style="width:4px;flex-shrink:0;background:${c}"></div>
      <div style="flex:1;min-width:0;padding:1px 0">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="font-size:13px;font-weight:700;letter-spacing:-.01em">${escapeHtml(no.nome)}</span>
          ${pill(no.estado, no.pillTexto)}
          <span style="font-size:10px;color:#64748b;font-family:'JetBrains Mono',monospace;margin-left:auto">${escapeHtml(no.rede || '')}</span>
        </div>
        <div style="font-size:11px;color:var(--txd);line-height:1.5;margin-top:3px">${escapeHtml(no.papel)}</div>
      </div>
      <div style="text-align:right;flex-shrink:0;width:92px;padding-right:13px">
        <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;color:var(--tx)">${escapeHtml(no.metrica)}</div>
        <div style="font-size:9px;color:#64748b;letter-spacing:.1em;text-transform:uppercase;font-weight:700;margin-top:1px">${escapeHtml(no.metricaLabel)}</div>
      </div>
    </div>
    ${ultimo ? '' : `<div style="padding:5px 0 5px 20px;display:flex;align-items:center;gap:7px">
      <span style="color:var(--bd1)">&#x2193;</span>
      <span style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#64748b">${escapeHtml(no.transporte || '')}</span>
    </div>`}
  </div>`;
}

function htmlQuebrados(cruzados) {
  const ruins = cruzados.filter(c => c.situacao === 'ausente' || c.situacao === 'parado' || c.situacao === 'doente');
  if (!ruins.length) {
    const cego = cruzados.some(c => c.situacao === 'sem_inventario');
    const comUpstream = cruzados.filter(c => c.situacao !== 'sem_upstream').length;
    return `<div style="font-size:11px;color:var(--text-dim);line-height:1.5">${
      cego
        ? 'Sem inventário do daemon nesta leitura — nenhum upstream foi confrontado. Lista em branco aqui não significa que está tudo certo.'
        : comUpstream
          ? 'Todo proxy_pass lido aponta para um container em execução.'
          : 'Nenhum proxy_pass lido — nada a confrontar.'
    }</div>`;
  }
  const rotulo = { ausente: 'ausente', parado: 'parado', doente: 'sonda vermelha' };
  const estado = { ausente: 'bad', parado: 'bad', doente: 'warn' };
  const conserto = {
    ausente: 'container não existe no daemon — corrigir o proxy_pass ou recriar a stack',
    parado: 'container existe e está parado — subir a stack',
    doente: 'container no ar com healthcheck falhando',
  };
  return ruins.map(r => `<div style="margin-bottom:11px">
    <div style="display:flex;align-items:center;gap:7px;margin-bottom:2px">
      <span style="font-size:11.5px;font-weight:650;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(r.alvo.nome)}</span>
      ${pill(estado[r.situacao], rotulo[r.situacao])}
    </div>
    <div style="font-size:10px;color:#64748b;font-family:'JetBrains Mono',monospace;margin-bottom:2px">${escapeHtml(r.dominio)} &rarr; ${escapeHtml(r.alvo.bruto)}</div>
    <div style="font-size:11px;color:var(--txd);line-height:1.5">${escapeHtml(conserto[r.situacao])}</div>
  </div>`).join('');
}

function htmlExposicao(ingress) {
  const hosts = (ingress && ingress.hosts) || {};
  const nomes = Object.keys(hosts);
  if (!nomes.length) {
    return `<div style="font-size:11px;color:var(--text-dim)">${
      ingress && ingress.error
        ? 'nginx.conf não lido — superfície exposta desconhecida'
        : 'Nenhum server_name lido'
    }</div>`;
  }
  return nomes.map(d => {
    const h = hosts[d] || {};
    const tags = [];
    if (h.internal) tags.push(['dim', 'interno']);
    else if (!h.ssl) tags.push(['bad', 'sem TLS']);
    else tags.push(['ok', 'TLS']);
    if (h.auth_basic) tags.push(['dim', 'basic auth']);
    if (h.hsts) tags.push(['dim', 'hsts']);
    const p80 = h.port_80 || {};
    const detalhe = [
      p80.https_redirect ? '80 &rarr; 301' : (p80.upstream ? '80 direto ao upstream' : ''),
      h.port_443 ? `443 · ${h.port_443.locations} location(s)` : '',
    ].filter(Boolean).join(' · ');
    return `<div style="display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid var(--bd0)">
      <span style="width:6px;height:6px;border-radius:50%;flex-shrink:0;background:${cor(h.internal ? 'dim' : h.ssl ? 'ok' : 'bad')}"></span>
      <div style="flex:1;min-width:0">
        <div style="font-size:11.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(d)}</div>
        <div style="font-size:10px;color:#64748b;font-family:'JetBrains Mono',monospace">${detalhe}</div>
      </div>
      <div style="display:flex;gap:4px;flex-shrink:0">${tags.map(([e, t]) => pill(e, t)).join('')}</div>
    </div>`;
  }).join('');
}

export function renderTopologia(container) {
  _disposed = false;

  container.innerHTML = `<div class="content">
    <div class="section">
      <div class="section-head"><div><h2 class="section-title">Topologia</h2></div></div>
      <div id="topoBody"><div class="skeleton" style="height:500px"></div></div>
    </div>
  </div>`;

  let pollTimer = null;

  async function carregar() {
    const [ing, ovw] = await Promise.all([
      apiGet('topo_ingress', '/api/ingress'),
      apiGet('topo_overview', '/api/overview'),
    ]);
    if (_disposed) return;
    const corpo = el('topoBody');
    if (!corpo) return;

    // As duas rotas caem juntas so se o cockpit caiu; uma delas de pe ainda
    // desenha a corrente, com o elo que falta marcado.
    if (ing.error && ovw.error) {
      corpo.innerHTML = `<div class="empty">Sem leitura de ingress nem de inventário: ${escapeHtml(ing.error)}</div>`;
      return;
    }

    const ingress = ing.data || { hosts: {}, totals: {} };
    const overview = ovw.data || { containers: [], host: {}, counters: {} };
    const cruzados = confrontarUpstreams(elosDoIngress(ingress), overview.containers);
    const nos = montarNos(ingress, overview, cruzados);
    const lido = ingress.parsed_at ? new Date(ingress.parsed_at).toLocaleString('pt-BR') : null;

    corpo.innerHTML = `<div style="display:grid;grid-template-columns:1fr 320px;gap:12px;align-items:start">
      <div style="${CSS_CAIXA};display:flex;flex-direction:column;min-width:0">
        <div style="${CSS_RUBRICA};margin-bottom:4px">Caminho da requisição — domínio até o daemon</div>
        <div style="font-size:11.5px;color:var(--txd);line-height:1.5;margin-bottom:14px;max-width:640px">
          Cada elo abaixo vem de duas leituras: o nginx.conf (domínios e proxy_pass) e o
          inventário do daemon. Onde os dois discordam, o nó fica marcado — é exatamente
          onde a requisição para de andar.
        </div>
        <div>${nos.map((n, i) => htmlNo(n, i === nos.length - 1)).join('')}</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:12px;min-width:0">
        <div style="${CSS_CAIXA}">
          <div style="${CSS_RUBRICA};margin-bottom:9px">Superfície exposta</div>
          <div style="max-height:300px;overflow-y:auto">${htmlExposicao(ingress)}</div>
        </div>
        <div style="${CSS_CAIXA}">
          <div style="${CSS_RUBRICA};margin-bottom:9px">Elos rompidos</div>
          <div style="max-height:320px;overflow-y:auto">${htmlQuebrados(cruzados)}</div>
        </div>
      </div>
    </div>
    <div style="font-size:9.5px;color:#64748b;line-height:1.4;margin-top:11px">
      ${lido ? `nginx.conf lido em ${escapeHtml(lido)} — ` : ''}inventário de ${new Date().toLocaleString('pt-BR')}
    </div>`;
  }

  carregar();
  pollTimer = setInterval(carregar, 30000);

  return () => {
    _disposed = true;
    if (pollTimer) clearInterval(pollTimer);
  };
}
