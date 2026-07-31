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
 *
 * Skeleton só na primeira carga (doc 13 §3). Drift é lido com o compose aberto
 * ao lado, comparando linha a linha — apagar a tabela a cada leitura obriga a
 * recomeçar a comparação, e é o pior lugar do cockpit para isso acontecer.
 */

import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { chipDoSummary } from '../kernel/regua.js';
import { deMolde, lista, mostrar, texto } from '../kernel/patch.js';

const MOLDE_BLOCO = '<div class="drift-bloco">'
  + '<div class="drift-projeto"><span data-nome></span><span class="mod-meta" data-servicos></span></div>'
  + '<div class="empty drift-aviso" data-aviso hidden></div>'
  + '<div data-itens></div>'
  + '<div class="empty" data-limpo hidden>Sem divergências</div>'
  + '<div class="drift-pendente" data-pendente hidden></div>'
  + '</div>';

const MOLDE_LINHA = '<div class="mod-item drift-linha">'
  + '<span class="mod-tag" data-campo></span>'
  + '<span class="mod-nome-cel" data-alvo></span>'
  + '<span class="drift-par">'
  + '<span class="drift-esperado" data-esperado></span>'
  + '<span class="drift-seta" data-seta>→</span>'
  + '<span class="drift-atual" data-atual></span>'
  + '</span></div>';

const CASCA = '<div data-blocos></div>'
  + '<div class="empty" data-vazio hidden>Nenhum projeto com compose localizável</div>';

function valor(v) {
  return v == null ? '—' : String(v);
}

/* Container fora de projeto entra como um "projeto" sintético para o desenho
 * ser um só. A alternativa era um segundo caminho de render com as mesmas
 * regras — e dois caminhos divergem, sempre. */
function blocosDe(data, escopo) {
  let projetos = data.projects || [];
  if (escopo.t === 'stack') projetos = projetos.filter((p) => p.name === escopo.id);

  const blocos = projetos.map((p) => ({
    chave: `p:${p.name || ''}`,
    nome: p.name || '',
    servicos: p.aviso ? '' : `${p.servicos} serviço(s)`,
    // Aviso não é drift: não dá para afirmar divergência num arquivo que não se
    // conseguiu ler, e mostrar "Sem divergências" aqui seria a pior das leituras.
    aviso: p.aviso || '',
    itens: p.aviso ? [] : (p.drift || []).map((d) => ({
      chave: `${d.servico || ''}|${d.chave || ''}|${d.campo || ''}`,
      campo: d.campo || '',
      alvo: `${d.servico || ''} · ${d.chave || ''}`,
      esperado: valor(d.esperado),
      atual: valor(d.atual),
    })),
    pendente: (p.nao_avaliadas || []).length,
    limpo: !p.aviso && !(p.drift || []).length,
  }));

  // Só no host: no escopo de uma stack, um container de fora dela não é achado
  // dessa stack — apareceria como ruído em toda stack aberta.
  const orfaos = escopo.t === 'host' ? (data.fora_de_projeto || []) : [];
  if (orfaos.length) {
    blocos.push({
      chave: 'fora-de-projeto',
      nome: 'Fora de projeto',
      servicos: String(orfaos.length),
      aviso: '',
      itens: orfaos.map((c) => ({
        chave: `orfao:${c.name || ''}`,
        campo: 'órfão',
        alvo: c.name || '',
        esperado: '',
        atual: c.image || '',
      })),
      pendente: 0,
      limpo: false,
    });
  }
  return blocos;
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
    let carregou = false;
    corpo.innerHTML = '<div class="skeleton" style="height:120px"></div>';

    const buscar = async () => {
      const { data, error } = await apiGet('mod_drift', '/api/drift');
      if (!vivo) return;
      if (error || !data) {
        if (!carregou) {
          corpo.innerHTML = `<div class="empty">${escapeHtml(error || 'Sem dado de drift')}</div>`;
        }
        return;
      }
      if (!carregou) corpo.innerHTML = CASCA;
      carregou = true;

      const blocos = blocosDe(data, escopo);
      mostrar(corpo.querySelector('[data-vazio]'), !blocos.length);
      lista(corpo.querySelector('[data-blocos]'), blocos, {
        chave: (b) => b.chave,
        criar: () => deMolde(MOLDE_BLOCO),
        atualizar: (el, b) => {
          texto(el.querySelector('[data-nome]'), b.nome);
          texto(el.querySelector('[data-servicos]'), b.servicos);
          const aviso = el.querySelector('[data-aviso]');
          mostrar(aviso, !!b.aviso);
          if (b.aviso) texto(aviso, b.aviso);
          mostrar(el.querySelector('[data-limpo]'), b.limpo);
          const pendente = el.querySelector('[data-pendente]');
          mostrar(pendente, b.pendente > 0);
          if (b.pendente) {
            texto(pendente, `${b.pendente} chave(s) não avaliada(s) — interpolação `
              + 'sem o .env do projeto, faixa de portas ou serviço construído localmente');
          }
          lista(el.querySelector('[data-itens]'), b.itens, {
            chave: (d) => d.chave,
            criar: () => deMolde(MOLDE_LINHA),
            atualizar: (item, d) => {
              texto(item.querySelector('[data-campo]'), d.campo);
              texto(item.querySelector('[data-alvo]'), d.alvo);
              const esperado = item.querySelector('[data-esperado]');
              texto(esperado, d.esperado);
              mostrar(esperado, d.esperado !== '');
              mostrar(item.querySelector('[data-seta]'), d.esperado !== '');
              texto(item.querySelector('[data-atual]'), d.atual, { flash: true });
            },
          });
        },
      });
    };

    buscar();
    return {
      atualizar: () => { if (carregou) buscar(); },
      dispose: () => { vivo = false; },
    };
  },
};
