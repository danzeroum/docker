import { apiGet, cancel } from '../data.js';
import { showToast } from '../notifications.js';
import { getState, setState } from '../store.js';
import { assinar, TICK_MS } from '../kernel/relogio.js';
import { atributo, casca, classe, classeUnica, deMolde, lista, mostrar, texto } from '../kernel/patch.js';

let _disposed = false;
let _highlightedHosts = [];
let _pollTimer = null;

/* 5 min = 60 ticks. Ingress é a leitura mais cara e a mais estável do cockpit
 * (nginx.conf muda por deploy, não por minuto), então continua sendo a mais
 * espaçada — mas agora em fase com as outras, e pausando com a aba oculta. */
const PERIODO_TICKS = 60;

/* A tabela de hosts é onde o operador CLICA para destacar uma linha e depois
 * procura essa linha no painel de achados ao lado. Recriá-la apagava o destaque
 * e desfazia o `scrollIntoView` que o próprio clique tinha feito — o operador
 * clicava, a tela rolava até o host, e a leitura seguinte devolvia tudo ao
 * começo. Chaveada pelo `server_name`, o destaque é uma classe que sobrevive
 * (doc 13). */
const MOLDE_ROW = '<button type="button" class="ig-row" data-host="">'
  + '<div class="ig-cell ig-cell-name"><strong data-nome></strong></div>'
  + '<div class="ig-cell ig-cell-p80" data-p80></div>'
  + '<div class="ig-cell ig-cell-p443" data-p443></div>'
  + '<div class="ig-cell ig-cell-bool" data-hsts></div>'
  + '<div class="ig-cell ig-cell-bool" data-bots></div>'
  + '<div class="ig-cell ig-cell-bool" data-auth></div>'
  + '<div class="ig-cell ig-cell-cert" data-cert></div>'
  + '</button>';

const MOLDE_KPI = '<div class="kpi"><div class="kpi-label" data-rot></div>'
  + '<div class="kpi-value" data-val></div></div>';

const MOLDE_CERT = '<div class="ig-cert-item">'
  + '<div class="ig-cert-path" data-path></div>'
  + '<div class="ig-cert-hosts" data-hosts></div></div>';

const MOLDE_ACHADO = '<div class="ig-finding">'
  + '<button type="button" class="card-open"><span class="sr-only">Abrir achado</span></button>'
  + '<div class="ig-finding-head">'
  + '<span class="ig-finding-sev" data-sev></span>'
  + '<span class="ig-finding-score" data-score></span>'
  + '<span class="ig-finding-targets" data-alvos></span>'
  + '</div>'
  + '<div class="ig-finding-title" data-titulo></div>'
  + '<div class="ig-finding-actions">'
  + '<span class="ig-finding-evidence" data-evidencia></span>'
  + '<a class="ig-finding-link" data-link hidden></a>'
  + '</div></div>';

const CASCA = '<div class="content ingress-layout">'
  + '<div class="ingress-kpis" id="igKpis">'
  + '<div class="skeleton" data-skeleton style="height:70px"></div>'
  + '<div class="kpis" data-kpis hidden></div>'
  + '<div class="empty-field" data-indisponivel hidden>Ingress indisponível</div>'
  + '</div>'
  + '<div class="ingress-body">'
  + '<div class="ingress-center" id="igCenter">'
  + '<div class="skeleton" data-skeleton-tabela style="height:400px"></div>'
  + '<div class="ig-table-wrap" data-tabela hidden>'
  + '<div class="ig-header">'
  + '<div class="ig-cell ig-cell-name ig-th">Host</div>'
  + '<div class="ig-cell ig-th">:80</div>'
  + '<div class="ig-cell ig-th">:443</div>'
  + '<div class="ig-cell ig-cell-bool ig-th" title="HSTS">HSTS</div>'
  + '<div class="ig-cell ig-cell-bool ig-th" title="Bot filter">Bots</div>'
  + '<div class="ig-cell ig-cell-bool ig-th" title="Auth basic">Auth</div>'
  + '<div class="ig-cell ig-cell-cert ig-th">Certificado</div>'
  + '</div><div data-rows></div></div></div>'
  + '<div class="ingress-right" id="igRight"><div class="ig-panel">'
  + '<div class="ig-panel-section"><h3 class="ig-panel-title">Certificados</h3>'
  + '<div class="ig-cert-list" data-certs></div>'
  + '<div class="empty-field" data-sem-cert hidden>Nenhum certificado SSL</div></div>'
  + '<div class="ig-panel-section"><h3 class="ig-panel-title">Achados de Ingress</h3>'
  + '<div class="ig-finding-list" data-achados></div>'
  + '<div class="empty-field" data-sem-achado hidden>Nenhum achado de ingress ativo</div></div>'
  + '</div></div></div>'
  + '<div class="ingress-footer" id="igFooter"><span class="ig-internos" data-internos></span></div>'
  + '</div>';

const SEVERIDADES = ['sev-critical', 'sev-high', 'sev-medium', 'sev-low'];

function sevClass(s) {
  return SEVERIDADES.includes(`sev-${s}`) ? `sev-${s}` : 'sev-low';
}

function sevLabel(s) {
  if (s === 'critical') return 'Crítico';
  if (s === 'high') return 'Alto';
  if (s === 'medium') return 'Médio';
  return 'Baixo';
}

function p80De(h) {
  const p = h.port_80;
  if (!p) return { txt: '—', tom: null };
  if (p.https_redirect) return { txt: '→ 301', tom: 'ig-ok' };
  if (p.upstream) return { txt: 'HTTP', tom: 'ig-bad' };
  if (p.acme_challenge) return { txt: 'ACME', tom: 'ig-mute' };
  return { txt: '—', tom: null };
}

function p443De(h) {
  if (!h.port_443) return { txt: '—', tom: null };
  const us = h.upstreams || [];
  if (!us.length) return { txt: 'sem proxy', tom: 'ig-mute' };
  return { txt: `${us[0]}${us.length > 1 ? ` +${us.length - 1}` : ''}`, tom: 'ig-mono' };
}

const TONS_CELULA = ['ig-ok', 'ig-bad', 'ig-mute', 'ig-mono'];

function destacar(hosts) {
  _highlightedHosts = hosts;
  document.querySelectorAll('.ig-row').forEach((rw) => {
    classe(rw, 'ig-highlight', hosts.includes(rw.dataset.host));
  });
  hosts.forEach((h) => {
    try {
      const alvo = document.querySelector(`.ig-row[data-host="${h.replace(/"/g, '\\"')}"]`);
      if (alvo && alvo.scrollIntoView) alvo.scrollIntoView({ block: 'nearest' });
    } catch { /* seletor com aspas exóticas: destaque perdido, tela intacta */ }
  });
}

function renderKpis(container, hosts, totals) {
  const publics = Object.entries(hosts).filter(([, h]) => !h.internal);
  const httpPlain = publics.filter(([, h]) => {
    const p80 = h.port_80;
    return p80 && !p80.https_redirect && p80.upstream;
  }).length;
  const itens = [
    { chave: 'publicos', rot: 'Públicos', val: totals.public, tom: 'kpi-accent' },
    { chave: 'tls', rot: 'Com TLS', val: totals.with_ssl, tom: 'kpi-ok' },
    { chave: 'claro', rot: 'HTTP texto claro', val: httpPlain, tom: httpPlain > 0 ? 'kpi-bad' : 'kpi-ok' },
    { chave: 'hsts', rot: 'HSTS', val: totals.with_hsts, tom: 'kpi-ok' },
    { chave: 'bots', rot: 'Filtro bots', val: totals.with_bot_filter, tom: 'kpi-warn' },
  ];
  lista(container, itens, {
    chave: (k) => k.chave,
    criar: () => deMolde(MOLDE_KPI),
    atualizar: (elKpi, k) => {
      classeUnica(elKpi, ['kpi-accent', 'kpi-ok', 'kpi-bad', 'kpi-warn'], k.tom);
      texto(elKpi.querySelector('[data-rot]'), k.rot);
      texto(elKpi.querySelector('[data-val]'), String(k.val), { flash: true });
    },
  });
}

function renderTable(recipiente, hosts) {
  const publics = Object.entries(hosts).filter(([, h]) => !h.internal);
  lista(recipiente, publics, {
    chave: ([name]) => name,
    criar: () => deMolde(MOLDE_ROW),
    atualizar: (row, [name, h]) => {
      atributo(row, 'data-host', name);
      classe(row, 'ig-highlight', _highlightedHosts.includes(name));
      texto(row.querySelector('[data-nome]'), name);

      const p80 = p80De(h);
      const c80 = row.querySelector('[data-p80]');
      texto(c80, p80.txt);
      classeUnica(c80, TONS_CELULA, p80.tom);

      const p443 = p443De(h);
      const c443 = row.querySelector('[data-p443]');
      texto(c443, p443.txt);
      classeUnica(c443, TONS_CELULA, p443.tom);

      // Booleano é ✓ ou —, nunca ✗: "não tem HSTS" é ausência de configuração,
      // e um X vermelho leria como falha onde pode ser escolha.
      texto(row.querySelector('[data-hsts]'), h.hsts ? '✓' : '—');
      classeUnica(row.querySelector('[data-hsts]'), TONS_CELULA, h.hsts ? 'ig-ok' : 'ig-mute');
      texto(row.querySelector('[data-bots]'), h.bot_filter ? '✓' : '—');
      classeUnica(row.querySelector('[data-bots]'), TONS_CELULA, h.bot_filter ? 'ig-ok' : 'ig-mute');
      texto(row.querySelector('[data-auth]'), h.auth_basic ? '✓' : '—');
      classeUnica(row.querySelector('[data-auth]'), TONS_CELULA, h.auth_basic ? 'ig-ok' : 'ig-mute');

      const cert = row.querySelector('[data-cert]');
      texto(cert, h.cert_path ? h.cert_path.split('/').slice(-2).join('/') : '—');
      atributo(cert, 'title', h.cert_path || null);
      classeUnica(cert, TONS_CELULA, h.cert_path ? 'ig-mono' : null);
    },
  });
}

function renderCerts(recipiente, vazio, hosts) {
  const certMap = new Map();
  Object.entries(hosts).filter(([, h]) => !h.internal).forEach(([name, h]) => {
    if (!h.cert_path) return;
    if (!certMap.has(h.cert_path)) certMap.set(h.cert_path, []);
    certMap.get(h.cert_path).push(name);
  });
  const entries = [...certMap.entries()].sort((a, b) => b[1].length - a[1].length);
  mostrar(vazio, !entries.length);
  lista(recipiente, entries, {
    chave: ([path]) => path,
    criar: () => deMolde(MOLDE_CERT),
    atualizar: (item, [path, hostsList]) => {
      const alvo = item.querySelector('[data-path]');
      texto(alvo, path.split('/').slice(-2).join('/'));
      atributo(alvo, 'title', path);
      lista(item.querySelector('[data-hosts]'), hostsList, {
        chave: (n) => n,
        criar: () => {
          const s = document.createElement('span');
          s.className = 'ig-cert-host';
          return s;
        },
        atualizar: (s, n) => texto(s, n),
      });
    },
  });
}

function renderFindings(recipiente, vazio, findings) {
  const sorted = [...(findings || [])].sort((a, b) => (b.score || 0) - (a.score || 0));
  mostrar(vazio, !sorted.length);
  lista(recipiente, sorted, {
    chave: (f) => String(f.id),
    criar: () => deMolde(MOLDE_ACHADO),
    atualizar: (card, f) => {
      const isAgg = Array.isArray(f.targets);
      atributo(card, 'data-finding-id', f.id);
      atributo(card, 'data-host', isAgg ? '' : (f.target || ''));
      atributo(card, 'data-targets', isAgg ? JSON.stringify(f.targets) : '');
      classeUnica(card, SEVERIDADES, sevClass(f.severity));
      texto(card.querySelector('[data-sev]'), sevLabel(f.severity));
      texto(card.querySelector('[data-score]'), String(f.score), { flash: true });
      texto(card.querySelector('[data-alvos]'),
        isAgg ? `${f.targets.length} hosts` : (f.target || ''));
      texto(card.querySelector('[data-titulo]'), f.title_plain || f.title || f.id);
      texto(card.querySelector('[data-evidencia]'), f.evidencia || f.evidence || '');
      const link = card.querySelector('[data-link]');
      mostrar(link, !!f.related_container);
      if (f.related_container) {
        atributo(link, 'href', `#/dossie?c=${encodeURIComponent(f.related_container)}`);
        atributo(link, 'title', 'Ver dossiê do container');
        texto(link, `→ ${f.related_container}`);
      }
    },
  });
}

async function fetchIngress(container) {
  if (_disposed) return;
  const [ingRes, findRes] = await Promise.all([
    apiGet('ig_data', '/api/ingress'),
    apiGet('ig_findings', '/api/findings?scope=ingress&status=open'),
  ]);
  if (_disposed) return;
  const hosts = ingRes.data && ingRes.data.hosts;
  const totals = ingRes.data && ingRes.data.totals;
  const findings = findRes.data || [];

  const kpis = container.querySelector('[data-kpis]');
  const indisponivel = container.querySelector('[data-indisponivel]');
  mostrar(container.querySelector('[data-skeleton]'), false);
  mostrar(container.querySelector('[data-skeleton-tabela]'), false);

  if (!hosts || ingRes.error) {
    // Sem hosts a tela declara indisponibilidade em vez de zerar os KPIs: "0
    // públicos" e "não consegui ler o nginx.conf" são fatos diferentes, e o
    // primeiro seria uma afirmação falsa sobre a infraestrutura.
    mostrar(indisponivel, true);
    mostrar(kpis, false);
    if (ingRes.error && ingRes.error !== 'abortado') showToast(ingRes.error, 'error');
    return;
  }
  mostrar(indisponivel, false);
  mostrar(kpis, true);
  mostrar(container.querySelector('[data-tabela]'), true);

  renderKpis(kpis, hosts, totals || {});
  renderTable(container.querySelector('[data-rows]'), hosts);
  renderCerts(
    container.querySelector('[data-certs]'), container.querySelector('[data-sem-cert]'), hosts
  );
  renderFindings(
    container.querySelector('[data-achados]'), container.querySelector('[data-sem-achado]'), findings
  );

  const internos = Object.entries(hosts).filter(([, h]) => h.internal).length;
  const rodape = container.querySelector('[data-internos]');
  mostrar(rodape, internos > 0);
  if (internos) texto(rodape, `${internos} bloco interno (healthcheck do gateway)`);
}

export function renderIngress(container) {
  _disposed = false;
  _highlightedHosts = [];
  const p = new URLSearchParams(location.hash.split('?')[1] || '');
  const hostParam = p.get('host');
  const st = getState();
  if (hostParam) _highlightedHosts = [hostParam];
  if (st.highlightedTargets) {
    _highlightedHosts = st.highlightedTargets;
    setState({ highlightedTargets: null });
  }
  if (p.get('c')) setState({ selectedContainer: p.get('c') });

  casca(container, 'ingress-v1', (elCont) => {
    elCont.innerHTML = CASCA;
    // Dois listeners para a tela inteira, instalados uma vez: a linha e o
    // cartão podem ser recriados, o handler não.
    elCont.addEventListener('click', (ev) => {
      const row = ev.target.closest ? ev.target.closest('.ig-row') : null;
      if (row) { destacar([row.dataset.host]); return; }
      const aberto = ev.target.closest ? ev.target.closest('.ig-finding .card-open') : null;
      if (!aberto || (ev.target.closest && ev.target.closest('.ig-finding-link'))) return;
      const card = aberto.closest('.ig-finding');
      const raw = card.dataset.targets;
      let alvos = [];
      if (raw) { try { alvos = JSON.parse(raw); } catch { alvos = []; } }
      else if (card.dataset.host) alvos = [card.dataset.host];
      destacar(alvos);
    });
  });

  fetchIngress(container);
  _pollTimer = assinar(() => fetchIngress(container), PERIODO_TICKS * TICK_MS);

  return () => {
    _disposed = true;
    if (typeof _pollTimer === 'function') _pollTimer();
    _pollTimer = null;
    cancel('ig_data');
    cancel('ig_findings');
  };
}
