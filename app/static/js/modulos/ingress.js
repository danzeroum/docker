/* Módulo `ingress` (registro do doc 10 §1).
 *
 * Corpo reaproveitado de `screens/ingress.js` — o doc 09 §A já previa isso como 🔧:
 * "a lógica de dados não muda". A 2a entrega a estrutura de módulos; a adaptação
 * visual de cada corpo à caixa do módulo viaja com o sprint do bloco dele.
 *
 * O 5-certs acrescenta a validade dos certificados, que era a chave `null` mais
 * antiga do contrato. Ela tem três leituras, e a diferença entre a segunda e a
 * terceira é alguém ser acordado ou não:
 *
 *   sem fonte  → "—"          (o diretório não está montado; não estou olhando)
 *   0 na janela → sem alarme  (olhei, e nenhum está perto de vencer)
 *   N na janela → "certs N"   (olhei, e N estão)
 */

import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { renderIngress } from '../screens/ingress.js';
import { chipDoSummary } from '../kernel/regua.js';

function certosNoChip(v) {
  // "certs 0" fixo no chip seria ruído permanente ao lado do HTTPS, que é o
  // dado principal daqui. O zero não some da tela — ele vive no `title` e na
  // linha do módulo, onde diz "olhei e está tudo bem" sem gritar.
  if (v.certs_expiring == null) return { sufixo: '', nota: 'validade de certificado sem fonte' };
  if (!v.certs_expiring) {
    return { sufixo: '', nota: `nenhum cert vence nos próximos ${v.cert_window_days} dias` };
  }
  return {
    sufixo: ` · certs ${v.certs_expiring}`,
    nota: `${v.certs_expiring} cert(s) vencendo em até ${v.cert_window_days} dias`,
  };
}

function linhaDeCerts(data) {
  if (!data || data.expiring == null) {
    return `<div class="cert-linha cert-sem-fonte">Certificados: —
      <span class="mod-meta">${escapeHtml((data && data.motivo) || 'sem fonte')}</span></div>`;
  }
  const dentro = (data.certs || []).filter((c) => c.expiring);
  const avisos = (data.avisos || []).length;
  const rodape = avisos
    // Symlink quebrado em live/ é rotina do certbot, não incidente — por isso
    // ele conta separado e não entra no número que dispara notificação.
    ? ` <span class="mod-meta">${avisos} lineage(s) ilegível(is)</span>`
    : '';
  if (!dentro.length) {
    return `<div class="cert-linha">Certificados: ${(data.certs || []).length} lido(s),
      nenhum vence em ${data.window_days} dias${rodape}</div>`;
  }
  return `<div class="cert-linha cert-alerta">Certificados vencendo${rodape}</div>`
    + dentro.map((c) => `<div class="mod-item">
        <span class="mod-tag">cert</span>
        <span class="mod-nome-cel">${escapeHtml(c.name)}</span>
        <span class="mod-meta">${c.days} dia(s)</span>
      </div>`).join('');
}

export default {
  id: 'ingress',
  nome: 'Ingress & TLS',
  escopos: ['host', 'stack', 'container'],
  span: 6,

  chip: (escopo, summary) => chipDoSummary(summary, 'ingress', (v) => {
    if (v.hosts == null) return null;
    const c = certosNoChip(v);
    return {
      rotulo: 'HTTPS',
      valor: `${v.https_forced}/${v.hosts}${c.sufixo}`,
      titulo: `hosts públicos com redirecionamento forçado · ${c.nota}`,
    };
  }),

  render: (escopo, dados, corpo) => {
    const dispose = renderIngress(corpo, escopo, dados);
    let vivo = true;

    // Depois do corpo do ingress: a validade dos certificados vem de outra rota
    // e de um cache de 1h, e segurar a tela por ela seria atrasar o dado de
    // agora pelo dado do mês.
    (async () => {
      const { data, error } = await apiGet('mod_certs', '/api/certs');
      if (!vivo || error) return;
      const caixa = document.createElement('div');
      caixa.className = 'cert-bloco';
      caixa.innerHTML = linhaDeCerts(data);
      corpo.appendChild(caixa);
    })();

    return () => {
      vivo = false;
      if (typeof dispose === 'function') dispose();
    };
  },
};
