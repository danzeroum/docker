import { apiGet } from '../data.js';
import { fmtDate } from '../fmt.js';
import { assinar, TICK_MS } from '../kernel/relogio.js';
import { classeUnica, deMolde, lista, mostrar, texto } from '../kernel/patch.js';

let _disposed = false;
let _pollTimer = null;

/* A auditoria é a tela que mais custa perder de vista: quem a abre está
 * conferindo se a ação que acabou de disparar foi registrada, e cada leitura
 * reconstruía a tabela inteira — 200 linhas, com o scroll de volta ao topo e a
 * linha que se estava lendo em outro lugar. Agora a linha é chaveada e só a
 * entrada nova entra, no topo, piscando (doc 13). */
const MOLDE_LINHA = '<tr>'
  + '<td class="aud-data" data-data></td>'
  + '<td><span class="pill-action" data-acao></span></td>'
  + '<td><strong data-alvo></strong></td>'
  + '<td class="aud-mono" data-resultado></td>'
  + '<td class="aud-mono aud-ip" data-ip></td>'
  + '</tr>';

const TONS = ['aud-negado', 'aud-erro'];

const CASCA = '<div class="content"><div class="section">'
  + '<div class="section-head"><div><h2 class="section-title">Auditoria</h2></div></div>'
  + '<div id="auditList">'
  + '<div class="skeleton" data-skeleton style="height:400px"></div>'
  + '<div class="empty" data-vazio hidden>Nenhuma entrada de auditoria</div>'
  + '<div class="table-wrap" data-tabela hidden><table><thead><tr>'
  + '<th>Data</th><th>Ação</th><th>Alvo</th><th>Resultado</th><th>IP</th>'
  + '</tr></thead><tbody data-corpo></tbody></table></div>'
  + '</div></div></div>';

export function renderAuditoria(container) {
  _disposed = false;
  let carregou = false;

  container.innerHTML = CASCA;
  const skeleton = container.querySelector('[data-skeleton]');
  const vazio = container.querySelector('[data-vazio]');
  const tabela = container.querySelector('[data-tabela]');
  const corpo = container.querySelector('[data-corpo]');

  async function load() {
    if (_disposed) return;
    const { data, error } = await apiGet('audit', '/api/audit?limit=200');
    if (_disposed) return;
    if (error || !data) {
      // Só a primeira falha vira tela de erro. Depois de carregada, a auditoria
      // que está na tela é a melhor verdade disponível — apagá-la porque uma
      // leitura falhou seria trocar dado bom por incerteza.
      if (!carregou) {
        mostrar(skeleton, false);
        mostrar(vazio, true);
        texto(vazio, error ? 'Erro ao carregar auditoria' : 'Nenhuma entrada de auditoria');
      }
      return;
    }
    carregou = true;
    mostrar(skeleton, false);
    mostrar(vazio, !data.length);
    mostrar(tabela, !!data.length);

    lista(corpo, data, {
      // O id da entrada é imutável por construção: auditoria não se reescreve.
      chave: (e, i) => String(e.id != null ? e.id : `${e.created_at}|${e.action}|${e.project}|${i}`),
      criar: () => deMolde(MOLDE_LINHA),
      atualizar: (el, e) => {
        const negado = !!(e.result && e.result.includes('403'));
        const erro = !!(e.result && e.result !== 'success' && !negado);
        classeUnica(el, TONS, negado ? 'aud-negado' : (erro ? 'aud-erro' : null));
        texto(el.querySelector('[data-data]'), fmtDate(e.created_at));
        texto(el.querySelector('[data-acao]'), e.action);
        texto(el.querySelector('[data-alvo]'), e.project);
        texto(el.querySelector('[data-resultado]'), e.result);
        texto(el.querySelector('[data-ip]'), e.ip);
      },
    });
  }

  load();
  // 15s vira 3 ticks do relógio compartilhado: sem `setInterval` próprio e sem
  // `visibilitychange` próprio — a pausa com aba oculta é do relógio.
  _pollTimer = assinar(load, 3 * TICK_MS);

  return () => {
    _disposed = true;
    if (typeof _pollTimer === 'function') _pollTimer();
    _pollTimer = null;
  };
}
