/* Mapa `imagem -> estado de atualização`, compartilhado pela lista e pela
 * subtela (B6).
 *
 * Vive fora de `modulos/` porque dois módulos de escopos diferentes leem o
 * mesmo dado: `containers` (host/stack) e `config` (container). Sem isto, cada
 * um faria a sua chamada e a subtela pediria `/api/updates` de novo por cima da
 * lista que acabou de pedir.
 *
 * Não entra no `/api/overview`: o job roda uma vez por dia e o overview é
 * buscado a cada 15s. Carregar um dado diário em cada polling é pagar 5.760
 * vezes por dia por uma informação que muda uma.
 *
 * O cache de 5 min é o que impede que o repolling de 15s do kernel — que
 * remonta os módulos, e portanto chama isto de novo — vire uma chamada por
 * repintura.
 */

import { apiGet } from './data.js';

const TTL_MS = 5 * 60 * 1000;

let _cache = null;      // { emMs, mapa, resumo }
let _emVoo = null;

function _hhmm(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function _chaves(imagem) {
  // `docker.io/nginx:1.25` e `nginx:1.25` são a mesma imagem; qual das duas
  // formas aparece depende de como o compose escreveu a linha `image:`.
  const s = String(imagem || '');
  if (!s) return [];
  return s.startsWith('docker.io/') ? [s, s.slice('docker.io/'.length)] : [s, `docker.io/${s}`];
}

/** Busca (com cache) o estado das imagens. Nunca levanta. */
export async function carregarUpdates(forcar) {
  const agora = Date.now();
  if (!forcar && _cache && agora - _cache.emMs < TTL_MS) return _cache;
  if (_emVoo) return _emVoo;

  _emVoo = (async () => {
    const { data, error } = await apiGet('updates', '/api/updates');
    if (error || !data) {
      // Sem resposta não é "nada desatualizado": mantém o cache anterior, e se
      // não houver, devolve resumo nulo — que a UI lê como "não sei".
      return _cache || { emMs: agora, mapa: new Map(), resumo: null };
    }
    const mapa = new Map();
    for (const linha of data.images || []) {
      for (const k of _chaves(linha.image)) mapa.set(k, linha);
    }
    _cache = { emMs: Date.now(), mapa, resumo: data.summary || null };
    return _cache;
  })();

  try {
    return await _emVoo;
  } finally {
    _emVoo = null;
  }
}

/**
 * Selo para uma imagem, ou `null`.
 *
 * `null` em três casos que a UI trata igual — não desenha nada:
 * job nunca rodou (`resumo` nulo), imagem fora da listagem (registry privado ou
 * construída localmente), e imagem em dia. Só `desatualizada` vira selo: um
 * selo "em dia" em cada linha seria ruído em 20 linhas para informar zero.
 */
export function seloDeImagem(estado, imagem) {
  if (!estado || !estado.resumo) return null;
  const linha = _chaves(imagem).map((k) => estado.mapa.get(k)).find(Boolean);
  if (!linha || linha.status !== 'desatualizada') return null;
  const hora = _hhmm(linha.consultado_em);
  return {
    texto: hora ? `imagem desatualizada · verificado ${hora}` : 'imagem desatualizada',
    titulo: linha.remoto_em ? `tag remota publicada em ${linha.remoto_em}` : '',
  };
}

/** Só para os testes: zera o cache entre casos. */
export function _resetarCache() {
  _cache = null;
  _emVoo = null;
}
