/* Escopo = qual cockpit está aberto (doc 10 §1).
 *
 *   Escopo = { t: 'host' } | { t:'stack', id } | { t:'container', id }
 *
 * O mesmo módulo renderiza nos três. É isto que dá "um mini cockpit para cada
 * projeto" sem criar 3 telas: existe 1 registro × 3 escopos.
 *
 * O tipo — não a instância — é a chave do layout. Decisão do doc 10 §1
 * invariante 4: um arranjo para TODOS os projetos, não um por projeto. 15
 * layouts distintos por stack seriam caos de manutenção mental.
 */

export const HOST = { t: 'host' };

export function host() {
  return HOST;
}

export function stack(id) {
  return { t: 'stack', id: String(id) };
}

export function container(id) {
  return { t: 'container', id: String(id) };
}

export function valido(escopo) {
  if (!escopo || typeof escopo !== 'object') return false;
  if (escopo.t === 'host') return true;
  return (escopo.t === 'stack' || escopo.t === 'container') && !!escopo.id;
}

/** Chave de persistência de layout: o TIPO, nunca a instância. */
export function tipoDeCockpit(escopo) {
  return valido(escopo) ? escopo.t : 'host';
}

/** Igualdade estrutural — usada para evitar re-render à toa. */
export function mesmo(a, b) {
  if (!a || !b) return a === b;
  return a.t === b.t && (a.id || null) === (b.id || null);
}

export function rotulo(escopo) {
  if (!valido(escopo)) return '';
  if (escopo.t === 'host') return 'Visão geral';
  if (escopo.t === 'stack') return `stack: ${escopo.id}`;
  return escopo.id;
}

/* Serialização para a hash da URL, para que um cockpit seja linkável e o
 * botão voltar do navegador funcione — sem reload (aceite do doc 12). */
export function paraHash(escopo) {
  if (!valido(escopo) || escopo.t === 'host') return '#/';
  return `#/${escopo.t}/${encodeURIComponent(escopo.id)}`;
}

export function deHash(hash) {
  const limpo = String(hash || '').replace(/^#\/?/, '');
  if (!limpo) return host();
  const [tipo, cru] = limpo.split('/');
  if ((tipo === 'stack' || tipo === 'container') && cru) {
    try {
      return { t: tipo, id: decodeURIComponent(cru) };
    } catch {
      return host();
    }
  }
  return host();
}
