/* Módulo `config` — compose efetivo do container (escopo container).
 *
 * Imagem, portas, limites, healthcheck e política de restart do inspect, que já
 * passa pela máscara de segredo no servidor (`mask_inspect`). Ganha a linha
 * "Score de segurança" com as violações nomeadas — B4 na interface (doc 11).
 */

import { apiGet } from '../data.js';
import { escapeHtml } from '../fmt.js';
import { carregarUpdates, seloDeImagem } from '../updates.js';
import { atributo, classe, classeUnica, deMolde, lista, texto } from '../kernel/patch.js';

const TONS = ['cfg-ok', 'cfg-warn', 'cfg-bad'];
const SEVERIDADES = ['cfg-critical', 'cfg-high', 'cfg-medium', 'cfg-low'];

const MOLDE_LINHA = '<div class="cfg-linha"><span data-rot></span><strong data-val></strong></div>';
const MOLDE_VIOL = '<li><strong data-regra></strong><span data-titulo></span></li>';

const CASCA = '<div data-linhas></div><ul class="cfg-viol" data-viol></ul>';

/* `linha` virou descrição de dado, não string de HTML: quem consome é o
 * `lista` chaveado pelo rótulo. A linha "Limite de memória" continua sendo a
 * MESMA linha entre uma leitura e outra, então o valor troca com transição em
 * vez de aparecer num nó recém-nascido (doc 13). */
function linha(rotulo, valor, tom) {
  return { rotulo, valor: String(valor), tom };
}

function pintarLinhas(recipiente, linhas) {
  lista(recipiente, linhas, {
    chave: (l) => l.rotulo,
    criar: () => deMolde(MOLDE_LINHA),
    atualizar: (el, l) => {
      classeUnica(el, TONS, l.tom ? `cfg-${l.tom}` : null);
      texto(el.querySelector('[data-rot]'), l.semRotulo ? '' : l.rotulo);
      const val = el.querySelector('[data-val]');
      classe(val, 'selo-update', !!l.marca);
      atributo(val, 'title', l.titulo || null);
      texto(val, l.valor, { flash: true });
    },
  });
}

function pintarViolacoes(recipiente, violacoes) {
  lista(recipiente, violacoes, {
    chave: (v) => v.rule || v.title || '',
    criar: () => deMolde(MOLDE_VIOL),
    atualizar: (el, v) => {
      classeUnica(el, SEVERIDADES, `cfg-${v.severity || 'low'}`);
      texto(el.querySelector('[data-regra]'), v.rule || '');
      texto(el.querySelector('[data-titulo]'), v.title || '');
    },
  });
}

export default {
  id: 'config',
  nome: 'Configuração',
  escopos: ['container'],
  span: 6,

  render: (escopo, dados, corpo) => {
    let vivo = true;
    let carregou = false;
    corpo.innerHTML = '<div class="skeleton" style="height:120px"></div>';

    const buscar = async () => {
      const [insp, seg, upd] = await Promise.all([
        apiGet(`mod_cfg_${escopo.id}`, `/api/containers/${encodeURIComponent(escopo.id)}/json`),
        apiGet('mod_cfg_sec', '/api/security'),
        carregarUpdates(),
      ]);
      if (!vivo) return;
      if (insp.error || !insp.data) {
        if (!carregou) {
          corpo.innerHTML = `<div class="empty">${escapeHtml(insp.error || 'Sem inspect')}</div>`;
        }
        return;
      }
      const d = insp.data;
      const hc = d.HostConfig || {};
      const cfg = d.Config || {};
      const st = d.State || {};
      const saude = (st.Health && st.Health.Status) || null;
      const mem = Number(hc.Memory) || 0;

      // O selo fica na linha da imagem, e não numa linha própria: é um atributo
      // da imagem, não outro fato. Ausente quando o job nunca rodou.
      const selo = seloDeImagem(upd, cfg.Image);
      const linhas = [
        linha('Imagem', cfg.Image || '—'),
      ];
      if (selo) {
        linhas.push({
          rotulo: 'imagem-selo', valor: selo.texto, tom: 'warn',
          titulo: selo.titulo, semRotulo: true, marca: true,
        });
      }
      linhas.push(
        linha('Usuário', cfg.User || '(vazio = root)', cfg.User ? '' : 'warn'),
        linha('Limite de memória',
          mem > 0 ? `${Math.round(mem / (1024 * 1024))} MB` : 'sem limite', mem > 0 ? '' : 'warn'),
        linha('Restart policy', (hc.RestartPolicy && hc.RestartPolicy.Name) || '—'),
        // Sem healthcheck é ausência de medida, não saúde confirmada.
        linha('Healthcheck', saude || 'não definido', saude === 'unhealthy' ? 'bad' : ''),
      );

      const meu = !seg.error && seg.data
        ? (seg.data.containers || []).find((c) => c.id === escopo.id || c.name === escopo.id)
        : null;
      if (meu) {
        linhas.push(linha('Score de segurança', `${meu.score}/100`,
          meu.score >= 85 ? 'ok' : (meu.score >= 60 ? 'warn' : 'bad')));
      }

      if (!carregou) corpo.innerHTML = CASCA;
      carregou = true;
      pintarLinhas(corpo.querySelector('[data-linhas]'), linhas);
      pintarViolacoes(corpo.querySelector('[data-viol]'), (meu && meu.violations) || []);
    };

    buscar();
    return {
      // O inspect muda quando alguém reinicia o container ou troca a imagem —
      // e é exatamente aí que o operador está olhando esta caixa.
      atualizar: () => { if (carregou) buscar(); },
      dispose: () => { vivo = false; },
    };
  },
};
