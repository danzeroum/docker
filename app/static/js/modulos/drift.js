/* Módulo `drift` — compose declarado × runtime (B8).
 *
 * O chip percorre os três estados que a régua construiu sem nomear:
 * `null` = sem fonte (e o chip se cala), `0` = a fonte rodou e diz que está
 * limpo, `N` = a fonte acusa. Desde a 2a ele vivia no primeiro por falta de
 * backend; agora `0` é uma afirmação, e por isso o chip **não some** quando não
 * há divergência.
 *
 * "Não avaliada" tem lugar próprio e não é somada ao drift: `${TAG}` sem o
 * `.env` do projeto não é divergência, é o limite da comparação. Misturar as
 * duas contagens transformaria uma limitação conhecida em alarme.
 */

import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { chipDoSummary } from '../kernel/regua.js';

function linhaDrift(d) {
  return `<div class="mod-item drift-linha">
    <span class="mod-tag">${escapeHtml(d.campo || '')}</span>
    <span class="mod-nome-cel">${escapeHtml(d.servico || '')} · ${escapeHtml(d.chave || '')}</span>
    <span class="drift-par">
      <span class="drift-esperado">${escapeHtml(String(d.esperado == null ? '—' : d.esperado))}</span>
      <span class="drift-seta">→</span>
      <span class="drift-atual">${escapeHtml(String(d.atual == null ? '—' : d.atual))}</span>
    </span>
  </div>`;
}

function blocoProjeto(p) {
  const cabeca = `<div class="drift-projeto">${escapeHtml(p.name || '')}
    <span class="mod-meta">${p.servicos} serviço(s)</span></div>`;
  if (p.aviso) {
    // Aviso não é drift: não dá para afirmar divergência num arquivo que não se
    // conseguiu ler, e mostrar "Sem divergências" aqui seria a pior das leituras.
    return cabeca + `<div class="empty drift-aviso">${escapeHtml(p.aviso)}</div>`;
  }
  const itens = (p.drift || []).map(linhaDrift).join('');
  const pendentes = (p.nao_avaliadas || []).length;
  const rodape = pendentes
    ? `<div class="drift-pendente">${pendentes} chave(s) não avaliada(s) — interpolação
       sem o .env do projeto, faixa de portas ou serviço construído localmente</div>`
    : '';
  return cabeca + (itens || '<div class="empty">Sem divergências</div>') + rodape;
}

export default {
  id: 'drift',
  nome: 'Drift',
  escopos: ['host', 'stack'],
  span: 6,

  chip: (escopo, summary) => chipDoSummary(summary, 'drift', (v) => (
    v.count == null
      ? null
      : {
        rotulo: 'Drift',
        valor: String(v.count),
        titulo: v.count
          ? 'divergências compose × runtime'
          : 'compose e runtime batem — verificado, não presumido',
      }
  )),

  render: (escopo, dados, corpo) => {
    let vivo = true;
    corpo.innerHTML = '<div class="skeleton" style="height:120px"></div>';

    (async () => {
      const { data, error } = await apiGet('mod_drift', '/api/drift');
      if (!vivo) return;
      if (error || !data) {
        corpo.innerHTML = `<div class="empty">${escapeHtml(error || 'Sem dado de drift')}</div>`;
        return;
      }
      let projetos = data.projects || [];
      if (escopo.t === 'stack') projetos = projetos.filter((p) => p.name === escopo.id);

      let html = projetos.map(blocoProjeto).join('');

      // Só no host: no escopo de uma stack, um container de fora dela não é
      // achado dessa stack — apareceria como ruído em toda stack aberta.
      const orfaos = escopo.t === 'host' ? (data.fora_de_projeto || []) : [];
      if (orfaos.length) {
        html += `<div class="drift-projeto">Fora de projeto
          <span class="mod-meta">${orfaos.length}</span></div>`
          + orfaos.map((c) => `<div class="mod-item drift-linha">
              <span class="mod-tag">órfão</span>
              <span class="mod-nome-cel">${escapeHtml(c.name || '')}</span>
              <span class="drift-par"><span class="drift-atual">${escapeHtml(c.image || '')}</span></span>
            </div>`).join('');
      }

      corpo.innerHTML = html || '<div class="empty">Nenhum projeto com compose localizável</div>';
    })();

    return () => { vivo = false; };
  },
};
