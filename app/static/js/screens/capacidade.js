import { apiGet } from '../data.js';
import { assinar, TICK_MS } from '../kernel/relogio.js';
import { atributo, casca, classeUnica, deMolde, lista, medida, mostrar, texto } from '../kernel/patch.js';

let _disposed = false;

/* Capacidade é uma tela de TENDÊNCIA, e era a que mais sofria com a repintura:
 * 30 colunas recriadas a cada 30s nascem na altura final, então a série
 * "pulava" de estado em vez de crescer, e as três listas ao lado voltavam ao
 * topo enquanto se lia a quinta linha. Chaveado, o desenho anima da altura
 * anterior para a nova e o scroll fica onde o operador deixou (doc 13).
 *
 * De quebra, a paleta saiu do JS. Este arquivo pintava com `var(--tx2)`,
 * `var(--bd0)` e `var(--sf)` — tokens do protótipo que NUNCA existiram no
 * themes.css. Metade das bordas e dos textos secundários vinha caindo no valor
 * inicial do navegador desde o porte. As classes abaixo usam os tokens reais.
 */
const MOLDE_COLUNA = '<div class="cap-col"><div class="cap-col-fill"></div></div>';
const MOLDE_JANELA = '<div class="cap-janela">'
  + '<div class="cap-janela-topo"><span class="cap-ponto"></span><span data-rot></span></div>'
  + '<div data-itens></div>'
  + '<div class="cap-vazio" data-sem-item hidden>Nenhum item</div>'
  + '</div>';
const MOLDE_JANELA_ITEM = '<div class="cap-item">'
  + '<span class="cap-ponto"></span><span class="cap-item-txt" data-txt></span></div>';
const MOLDE_MEM = '<div class="cap-mem">'
  + '<span class="cap-mem-nome" data-nome></span>'
  + '<div class="cap-barra"><div class="cap-barra-fill" data-fill></div></div>'
  + '<span class="cap-mem-val" data-val></span></div>';
const MOLDE_POSTURA = '<div class="cap-postura">'
  + '<span class="cap-icone" data-icone></span>'
  + '<span class="cap-postura-item" data-item></span>'
  + '<span class="cap-postura-val" data-val></span></div>';
const MOLDE_ORFAO = '<div class="cap-linha">'
  + '<span class="cap-tag" data-tipo></span>'
  + '<span class="cap-nome" data-nome></span>'
  + '<span class="cap-val" data-tam></span></div>';
const MOLDE_SECAO = '<div class="cap-secao">'
  + '<span data-rot></span><span class="cap-val" data-tam></span></div>';
const MOLDE_SCORE = '<div class="cap-linha">'
  + '<span class="cap-score" data-score></span>'
  + '<span class="cap-nome" data-nome></span>'
  + '<span class="cap-sev" data-sev></span>'
  + '<span class="cap-val" data-n></span></div>';

const TONS = ['cap-ok', 'cap-warn', 'cap-bad', 'cap-accent', 'cap-mute'];

function el(id) { return document.getElementById(id); }

function tomDeSeveridade(sev) {
  if (sev === 'bad' || sev === 'critical' || sev === 'high') {
    return sev === 'medium' ? 'cap-accent' : (sev === 'high' ? 'cap-warn' : 'cap-bad');
  }
  if (sev === 'warn') return 'cap-warn';
  if (sev === 'medium') return 'cap-accent';
  if (sev === 'ok') return 'cap-ok';
  return 'cap-mute';
}

function severityLabel(sev) {
  if (sev === 'critical') return 'Crítico';
  if (sev === 'high') return 'Alto';
  if (sev === 'medium') return 'Médio';
  return 'Baixo';
}

function iconeDe(st) {
  if (st === 'ok') return '✓';
  if (st === 'warn') return '⚠';
  return '✗';
}

function fmtGB(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(0)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}

const ROTULO_ORFAO = { image: 'imagem', volume: 'volume', container: 'container' };

const CASCA = '<div class="content"><div class="section">'
  + '<div class="section-head"><div><h2 class="section-title">Capacidade</h2></div></div>'
  + '<div id="capBody" class="cap-corpo">'
  + '<div class="skeleton" data-skeleton style="height:500px"></div>'
  + '<div data-conteudo hidden>'
  + '<div class="cap-janelas" data-janelas></div>'
  + '<div class="cap-colunas">'
  + '<div class="cap-esquerda">'
  + '<div id="capDiskChart" class="cap-caixa">'
  + '<div class="cap-rotulo" id="capChartTitle">Disco (30 dias)</div>'
  + '<div id="capChartBody" class="cap-grafico"></div>'
  + '<div id="capChartNote" class="cap-nota"></div>'
  + '</div>'
  + '<div class="cap-caixa">'
  + '<div class="cap-rotulo">Memória por stack</div>'
  + '<div class="cap-rolagem" data-mem></div>'
  + '<div class="cap-vazio" data-sem-mem hidden>Nenhum dado de memória</div>'
  + '<div class="cap-nota">Consumo atual dos containers em cada projeto</div>'
  + '</div></div>'
  + '<div class="cap-direita">'
  + '<div class="cap-caixa"><div class="cap-rotulo">Postura de segurança e operação</div>'
  + '<div class="cap-rolagem" data-postura></div>'
  + '<div class="cap-vazio" data-sem-postura hidden>Nenhum dado</div></div>'
  + '<div class="cap-caixa"><div class="cap-rotulo">Score de segurança por container</div>'
  + '<div id="capSecurity">'
  + '<div class="cap-erro" data-sec-erro hidden></div>'
  + '<div class="cap-destaque"><strong data-sec-medio></strong><span data-sec-sub></span></div>'
  + '<div class="cap-nota" data-sec-resumo></div>'
  + '<div class="cap-rolagem" data-sec-lista></div>'
  + '<div class="cap-vazio cap-ok" data-sec-limpo hidden>Todos os containers conformes</div>'
  + '<div class="cap-nota" data-sec-rodape></div>'
  + '</div></div>'
  + '<div class="cap-caixa"><div class="cap-rotulo">Storage e recursos órfãos</div>'
  + '<div id="capStorage">'
  + '<div class="cap-erro" data-stg-erro hidden></div>'
  + '<div class="cap-destaque"><strong data-stg-total></strong><span>recuperáveis</span></div>'
  + '<div class="cap-secoes" data-stg-secoes></div>'
  + '<div class="cap-rolagem" data-stg-lista></div>'
  + '<div class="cap-vazio cap-ok" data-stg-limpo hidden>Nenhum recurso órfão — nada a recuperar</div>'
  + '<div class="cap-nota" data-stg-resto hidden></div>'
  + '<div class="cap-nota" data-stg-rodape></div>'
  + '</div></div>'
  + '</div></div>'
  + '<div class="cap-nota" data-coletando></div>'
  + '</div></div></div></div>';

export function renderCapacidade(container) {
  _disposed = false;
  let carregou = false;
  let storageCarregou = false;
  let securityCarregou = false;
  let pollTimer = null;

  casca(container, 'capacidade-v1', (elCont) => { elCont.innerHTML = CASCA; });

  const skeleton = container.querySelector('[data-skeleton]');
  const conteudo = container.querySelector('[data-conteudo]');

  async function fetchData() {
    const { data, error } = await apiGet('cap_data', '/api/capacity');
    if (_disposed) return;
    if (error || !data) {
      // Depois da primeira carga, um erro não apaga a projeção que está na
      // tela: capacidade é a tela de decidir compra de disco, e decidir com o
      // dado de ontem é melhor que decidir sem dado nenhum.
      if (!carregou) {
        mostrar(skeleton, false);
        mostrar(conteudo, false);
        const corpo = el('capBody');
        if (corpo) corpo.innerHTML = '<div class="empty">Erro ao carregar dados de capacidade</div>';
      }
      return;
    }
    carregou = true;
    mostrar(skeleton, false);
    mostrar(conteudo, true);
    renderCapBody(data);

    const { data: hist, error: histErr } = await apiGet('cap_history', '/api/metrics/history?series=disk_pct&range=30');
    if (!_disposed && !histErr && hist) renderDiskChart(hist);

    // Storage e postura entram depois e cada um trata o proprio erro: uma
    // varredura de disco indisponivel nao pode apagar a tela de capacidade
    // que ja carregou.
    const { data: st, error: stErr } = await apiGet('cap_storage', '/api/storage');
    if (!_disposed) renderStorage(st, stErr);
    const { data: sec, error: secErr } = await apiGet('cap_security', '/api/security');
    if (!_disposed) renderSecurity(sec, secErr);
  }

  function renderStorage(d, erro) {
    const box = el('capStorage');
    if (!box) return;
    /* Fonte fora do ar é um CARTÃO com aviso, não a Capacidade inteira em erro:
     * uma varredura de disco indisponível não invalida a projeção nem a
     * postura. E o aviso só substitui o conteúdo enquanto não houve conteúdo —
     * com um total já lido, o número velho vale mais que um vazio novo. */
    if (erro || !d) {
      if (storageCarregou) return;
      mostrar(box.querySelector('[data-stg-erro]'), true);
      texto(box.querySelector('[data-stg-erro]'), erro || 'Sem dados de storage — fonte indisponível');
      mostrar(box.querySelector('.cap-destaque'), false);
      return;
    }
    storageCarregou = true;
    mostrar(box.querySelector('[data-stg-erro]'), false);
    mostrar(box.querySelector('.cap-destaque'), true);

    const orfaos = d.orphans || [];
    const total = box.querySelector('[data-stg-total]');
    texto(total, fmtGB(d.reclaimable_bytes || 0), { flash: true });
    classeUnica(total, TONS, (d.reclaimable_bytes || 0) > 5 * 1024 ** 3 ? 'cap-warn' : null);

    const secoes = [
      ['Imagens', d.images, 'dangling_count'],
      ['Volumes', d.volumes, 'orphan_count'],
      ['Containers', d.containers, 'stopped_old_count'],
      ['Build cache', d.build_cache, null],
    ].filter(([, s]) => !!s).map(([rotulo, s, chaveSobra]) => ({
      rotulo, sobra: chaveSobra ? (s[chaveSobra] || 0) : 0, bytes: s.size_bytes,
    }));

    lista(box.querySelector('[data-stg-secoes]'), secoes, {
      chave: (s) => s.rotulo,
      criar: () => deMolde(MOLDE_SECAO),
      atualizar: (linha, s) => {
        texto(linha.querySelector('[data-rot]'), s.sobra ? `${s.rotulo} (${s.sobra} sobra)` : s.rotulo);
        classeUnica(linha, TONS, s.sobra ? 'cap-warn' : null);
        texto(linha.querySelector('[data-tam]'), fmtGB(s.bytes), { flash: true });
      },
    });

    mostrar(box.querySelector('[data-stg-limpo]'), !orfaos.length);
    lista(box.querySelector('[data-stg-lista]'), orfaos.slice(0, 8), {
      chave: (o) => `${o.type || ''}:${o.name || ''}`,
      criar: () => deMolde(MOLDE_ORFAO),
      atualizar: (linha, o) => {
        texto(linha.querySelector('[data-tipo]'), ROTULO_ORFAO[o.type] || o.type || '');
        texto(linha.querySelector('[data-nome]'), o.name || '');
        atributo(linha.querySelector('[data-nome]'), 'title', o.reason || null);
        texto(linha.querySelector('[data-tam]'), fmtGB(o.size_bytes));
      },
    });

    const resto = box.querySelector('[data-stg-resto]');
    mostrar(resto, orfaos.length > 8);
    if (orfaos.length > 8) texto(resto, `e mais ${orfaos.length - 8} item(ns)`);
    texto(box.querySelector('[data-stg-rodape]'),
      `Container conta como sobra após ${d.orphan_exited_days || 7} dias parado. `
      + 'Build cache fica fora do total: é outro comando, com outro risco.');
  }

  function renderSecurity(d, erro) {
    const box = el('capSecurity');
    if (!box) return;
    if (erro || !d) {
      if (securityCarregou) return;
      mostrar(box.querySelector('[data-sec-erro]'), true);
      texto(box.querySelector('[data-sec-erro]'), erro || 'Sem dados de postura — fonte indisponível');
      mostrar(box.querySelector('.cap-destaque'), false);
      return;
    }
    securityCarregou = true;
    mostrar(box.querySelector('[data-sec-erro]'), false);
    mostrar(box.querySelector('.cap-destaque'), true);

    const s = d.summary || {};
    const medio = s.score_medio != null ? s.score_medio : 100;
    const alvo = box.querySelector('[data-sec-medio]');
    texto(alvo, String(medio), { flash: true });
    classeUnica(alvo, TONS, medio >= 85 ? 'cap-ok' : medio >= 60 ? 'cap-warn' : 'cap-bad');
    texto(box.querySelector('[data-sec-sub]'),
      `score médio · pior ${s.score_minimo != null ? s.score_minimo : '-'}`);

    const sev = s.violacoes_por_severidade || {};
    texto(box.querySelector('[data-sec-resumo]'),
      `${s.conformes || 0}/${s.containers_avaliados || 0} conformes · `
      + `${sev.critical || 0} crít · ${sev.high || 0} alta · ${sev.medium || 0} méd`);

    const piores = (d.containers || []).filter(c => (c.violations || []).length).slice(0, 6);
    mostrar(box.querySelector('[data-sec-limpo]'), !piores.length);
    lista(box.querySelector('[data-sec-lista]'), piores, {
      chave: (c) => c.name || c.id || '',
      criar: () => deMolde(MOLDE_SCORE),
      atualizar: (linha, c) => {
        const pior = (c.violations || [])[0] || {};
        const score = linha.querySelector('[data-score]');
        texto(score, String(c.score), { flash: true });
        classeUnica(score, TONS, c.score >= 85 ? 'cap-ok' : c.score >= 60 ? 'cap-warn' : 'cap-bad');
        texto(linha.querySelector('[data-nome]'), c.name || '');
        atributo(linha.querySelector('[data-nome]'), 'title',
          (c.violations || []).map(v => v.title).join(' · ') || null);
        const sevEl = linha.querySelector('[data-sev]');
        texto(sevEl, severityLabel(pior.severity));
        classeUnica(sevEl, TONS, tomDeSeveridade(pior.severity));
        texto(linha.querySelector('[data-n]'), String((c.violations || []).length));
      },
    });

    texto(box.querySelector('[data-sec-rodape]'),
      '100 menos o peso das violações (crítica 30, alta 15, média 5). '
      + `${s.sem_healthcheck || 0} sem healthcheck definido.`);
  }

  function renderCapBody(d) {
    let coletando = '';
    if (d.coletando_desde) {
      const dt = new Date(d.coletando_desde.replace('Z', ''));
      coletando = `Coletando desde ${dt.toLocaleDateString('pt-BR')}`;
    }
    texto(container.querySelector('[data-coletando]'), coletando);

    lista(container.querySelector('[data-janelas]'), d.windows || [], {
      chave: (w) => w.label,
      criar: () => deMolde(MOLDE_JANELA),
      atualizar: (caixa, w) => {
        classeUnica(caixa, TONS, tomDeSeveridade(w.severity));
        texto(caixa.querySelector('[data-rot]'), w.label);
        const itens = w.items || [];
        mostrar(caixa.querySelector('[data-sem-item]'), !itens.length);
        lista(caixa.querySelector('[data-itens]'), itens, {
          chave: (i, n) => `${n}:${i.text}`,
          criar: () => deMolde(MOLDE_JANELA_ITEM),
          atualizar: (linha, i) => texto(linha.querySelector('[data-txt]'), i.text),
        });
      },
    });

    const mem = d.memory_by_stack || [];
    mostrar(container.querySelector('[data-sem-mem]'), !mem.length);
    lista(container.querySelector('[data-mem]'), mem, {
      chave: (c) => c.name,
      criar: () => deMolde(MOLDE_MEM),
      atualizar: (linha, c) => {
        const pct = c.pct != null ? c.pct : 0;
        texto(linha.querySelector('[data-nome]'), c.name);
        const fill = linha.querySelector('[data-fill]');
        medida(fill, '--barra', `${Math.min(pct, 100)}%`);
        classeUnica(fill, TONS, pct > 80 ? 'cap-bad' : pct > 60 ? 'cap-warn' : 'cap-accent');
        texto(linha.querySelector('[data-val]'),
          c.limit_mb ? `${c.used_mb} / ${c.limit_mb} MB` : `${c.used_mb} MB`, { flash: true });
      },
    });

    const postura = d.postura || [];
    mostrar(container.querySelector('[data-sem-postura]'), !postura.length);
    lista(container.querySelector('[data-postura]'), postura, {
      chave: (p) => p.item,
      criar: () => deMolde(MOLDE_POSTURA),
      atualizar: (linha, p) => {
        const icone = linha.querySelector('[data-icone]');
        texto(icone, iconeDe(p.status));
        classeUnica(icone, TONS, tomDeSeveridade(p.status));
        texto(linha.querySelector('[data-item]'), p.item);
        const val = linha.querySelector('[data-val]');
        texto(val, p.valor, { flash: true });
        classeUnica(val, TONS, tomDeSeveridade(p.status));
      },
    });
  }

  function renderDiskChart(hist) {
    const body = el('capChartBody');
    const note = el('capChartNote');
    if (!body) return;

    const proj = hist.projection;
    const pts = hist.series || [];

    let noteText = '';
    if (proj && proj.stable) {
      const d80 = proj.days_to_80, d90 = proj.days_to_90;
      const parts = [];
      if (d80 != null) parts.push(`80% em ~${d80}d`);
      if (d90 != null) parts.push(`90% em ~${d90}d`);
      parts.push(`r²=${proj.r2}`);
      noteText = `Projeção: ${parts.join(', ')} (${proj.slope_per_day > 0 ? 'subindo' : 'descendo'} ${Math.abs(proj.slope_per_day).toFixed(2)}%/dia)`;
    } else if (proj && !proj.stable) {
      noteText = `Tendência instável (r²=${proj.r2.toFixed(2)} < 0,7) — dados insuficientes para projetar`;
    } else if (hist.coletando_desde) {
      const dt = new Date(hist.coletando_desde.replace('Z', ''));
      noteText = `Coletando desde ${dt.toLocaleDateString('pt-BR')} — série curta para projeção (< 7 dias)`;
    }
    if (note) texto(note, noteText);

    const limit = 90;
    const days = pts.slice(-30);
    const showProj = proj && proj.stable;

    if (!days.length) {
      lista(body, [], { chave: () => '', criar: () => null });
      return;
    }

    /* Medido e projetado no MESMO desenho, com tons diferentes: o operador
     * precisa ver onde a série acaba e onde a reta começa, e nunca confundir a
     * segunda com leitura. */
    const colunas = days.map((p, i) => ({
      chave: `d${i}`,
      altura: Math.max(4, (p.v / limit) * 120),
      tom: p.v > 80 ? 'cap-bad' : p.v > 60 ? 'cap-warn' : 'cap-accent',
      dica: `${p.ts}: ${p.v.toFixed(1)}%`,
      projetado: false,
    }));
    if (showProj) {
      for (let x = 1; x <= 10; x++) {
        const v = proj.intercept + proj.slope_per_day * (days.length - 1 + x);
        colunas.push({
          chave: `p${x}`,
          altura: Math.max(4, (Math.min(v, 100) / limit) * 120),
          tom: v >= 90 ? 'cap-bad' : 'cap-mute',
          dica: `Proj ${x}d: ${v.toFixed(1)}%`,
          projetado: true,
        });
      }
    }

    classeUnica(body, ['cap-com-proj'], showProj ? 'cap-com-proj' : null);
    lista(body, colunas, {
      chave: (c) => c.chave,
      criar: () => deMolde(MOLDE_COLUNA),
      atualizar: (elCol, c) => {
        atributo(elCol, 'title', c.dica);
        classeUnica(elCol, ['cap-proj'], c.projetado ? 'cap-proj' : null);
        const fill = elCol.querySelector('.cap-col-fill');
        // Altura por propriedade customizada: a transição de .7s mora no CSS,
        // e é o que faz a coluna crescer em vez de aparecer no valor final.
        medida(fill, '--altura', `${c.altura.toFixed(0)}px`);
        classeUnica(fill, TONS, c.tom);
      },
    });
  }

  fetchData();
  // 30s = 6 ticks do relógio compartilhado.
  pollTimer = assinar(fetchData, 6 * TICK_MS);

  return () => {
    _disposed = true;
    if (typeof pollTimer === 'function') pollTimer();
    pollTimer = null;
  };
}
