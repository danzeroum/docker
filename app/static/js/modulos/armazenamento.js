/* Módulo `armazenamento` — B1 na tela, B10 no botão.
 *
 * Fecha o ciclo: o cartão diz "X GB recuperáveis" e é daqui que se recupera.
 *
 * O fluxo é dry-run → lista → confirmar, e a lista mostrada na confirmação é a
 * MESMA que o dry-run devolveu. Sem isso o `dry_run=true` padrão do backend
 * viraria só um clique a mais: o operador confirmaria às cegas do mesmo jeito e
 * a proteção existiria só no papel.
 *
 * O botão só entra no DOM com `capabilities.actions_enabled` E sessão
 * destravada. Ausente, não `display:none` — esconder por CSS deixa a ação
 * alcançável por quem inspeciona o DOM, e o contrato do doc 11 é que ela não
 * exista.
 */

import { apiGet, apiPost } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { showToast } from '../notifications.js';
import { chipDoSummary } from '../kernel/regua.js';

const ROTULO = { image: 'imagem', volume: 'volume', container: 'container' };

function gb(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(0)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}

function temUnlock() {
  try {
    const raw = sessionStorage.getItem('cockpit-unlock');
    if (!raw) return false;
    const p = JSON.parse(raw);
    return !!(p.token && p.expiresAt && Date.now() < new Date(p.expiresAt).getTime());
  } catch {
    return false;
  }
}

function itemHtml(o) {
  return `<div class="mod-item">
    <span class="mod-tag">${escapeHtml(ROTULO[o.type] || o.type || '')}</span>
    <span class="mod-nome-cel" title="${escapeHtml(o.reason || '')}">${escapeHtml(o.name || '')}</span>
    <span class="mod-meta">${gb(o.size_bytes)}</span>
  </div>`;
}

export default {
  id: 'armazenamento',
  nome: 'Armazenamento',
  escopos: ['host'],
  span: 6,

  chip: (escopo, summary) => chipDoSummary(summary, 'storage', (v) => ({
    rotulo: 'Recuperável',
    valor: v.reclaimable_gb != null ? `${v.reclaimable_gb} GB` : '—',
    titulo: `${v.orphans} recurso(s) órfão(s)`,
  })),

  render: (escopo, dados, corpo) => {
    let vivo = true;
    // `carregou` guarda a diferença entre "ainda não sei" e "sei e vou reler".
    // O skeleton pertence ao primeiro estado e só a ele: apagar um cartão já
    // preenchido a cada leitura é o que fazia o cockpit parecer reiniciar
    // sozinho (doc 13 §3).
    let carregou = false;
    const cap = ((dados && dados.overview && dados.overview.summary) || {}).capabilities || {};
    const podeAgir = !!(cap.actions_enabled && temUnlock());

    corpo.innerHTML = '<div class="skeleton" style="height:110px"></div>';

    function pintarLista(data) {
      const orfaos = data.orphans || [];
      const acao = podeAgir
        ? '<div class="stg-acoes"><button type="button" class="stg-btn" data-acao="dry_run">'
          + 'Limpar imagens sem uso…</button></div>'
        : '';
      corpo.innerHTML =
        `<div class="stg-total">${gb(data.reclaimable_bytes)}<span> recuperáveis</span></div>`
        + (orfaos.length
          ? `<div class="mod-lista">${orfaos.slice(0, 6).map(itemHtml).join('')}</div>`
            + (orfaos.length > 6 ? `<div class="stg-nota">e mais ${orfaos.length - 6} item(ns)</div>` : '')
          : '<div class="empty ok">Nenhum recurso órfão</div>')
        + acao
        + `<div class="stg-nota">Container conta como sobra após ${data.orphan_exited_days || 7} dias parado.
             Build cache fica fora do total: é outro comando, com outro risco.</div>`;
      const btn = corpo.querySelector('[data-acao="dry_run"]');
      if (btn) btn.addEventListener('click', () => pedirDryRun(data));
    }

    async function pedirDryRun(dataAtual) {
      const btn = corpo.querySelector('[data-acao="dry_run"]');
      if (btn) { btn.disabled = true; btn.textContent = 'consultando…'; }
      const { data, error } = await apiPost('prune_dry', '/api/prune?dry_run=true');
      if (!vivo) return;
      if (error) {
        showToast(error, 'error');
        pintarLista(dataAtual);
        return;
      }
      pintarConfirmacao(data, dataAtual);
    }

    function pintarConfirmacao(previa, dataAtual) {
      const candidatos = previa.candidates || [];
      if (!candidatos.length) {
        corpo.innerHTML = '<div class="empty ok">Nada a limpar: nenhuma imagem sem uso.</div>';
        setTimeout(() => { if (vivo) pintarLista(dataAtual); }, 2500);
        return;
      }
      corpo.innerHTML = `<div class="stg-confirma">
          <div class="stg-confirma-topo">Remover ${candidatos.length} imagem(ns) sem uso,
            liberando ${gb(previa.reclaimable_bytes)}?</div>
          <div class="mod-lista">${candidatos.map(itemHtml).join('')}</div>
          <div class="stg-nota">Só imagens sem tag. Volumes e containers parados não são tocados.</div>
          <div class="stg-acoes">
            <button type="button" class="stg-btn stg-perigo" data-acao="confirmar">Remover</button>
            <button type="button" class="stg-btn" data-acao="cancelar">Cancelar</button>
          </div>
        </div>`;
      const cancelar = corpo.querySelector('[data-acao="cancelar"]');
      if (cancelar) cancelar.addEventListener('click', () => pintarLista(dataAtual));
      const confirmar = corpo.querySelector('[data-acao="confirmar"]');
      if (confirmar) confirmar.addEventListener('click', () => executar());
    }

    async function executar() {
      const btn = corpo.querySelector('[data-acao="confirmar"]');
      if (btn) { btn.disabled = true; btn.textContent = 'removendo…'; }
      const { data, error } = await apiPost('prune_real', '/api/prune?dry_run=false');
      if (!vivo) return;
      if (error) {
        showToast(error, 'error');
        carregar();
        return;
      }
      showToast(
        `${(data.removed || []).length} imagem(ns) removida(s), ${gb(data.removed_bytes)} liberados`,
        'success'
      );
      // A ação está na Auditoria — o operador precisa saber onde conferir.
      corpo.innerHTML = `<div class="stg-total">${gb(data.removed_bytes)}<span> liberados</span></div>
        <div class="stg-nota">Registrado na Auditoria.</div>`;
      setTimeout(() => { if (vivo) carregar(); }, 2500);
    }

    async function carregar() {
      const { data, error } = await apiGet('mod_storage', '/api/storage');
      if (!vivo) return;
      if (error || !data) {
        // Degrada o cartão, não a tela; e diz o que houve, não zero. Mas só na
        // primeira: com um total já na tela, uma leitura que falhou não apaga
        // o número que ainda é o melhor que se sabe.
        if (!carregou) {
          corpo.innerHTML = `<div class="empty">${escapeHtml(error || 'Sem leitura de storage')}</div>`;
        }
        return;
      }
      carregou = true;
      pintarLista(data);
    }

    carregar();
    return {
      /* Só relê quando o cartão está na lista. Durante o dry-run e a
       * confirmação o corpo é OUTRA coisa — a lista do prune que o operador
       * está lendo para decidir. Repintar por cima disso seria apagar a
       * pergunta debaixo da resposta. */
      atualizar: () => {
        if (carregou && !corpo.querySelector('.stg-confirma')) carregar();
      },
      dispose: () => { vivo = false; },
    };
  },
};
