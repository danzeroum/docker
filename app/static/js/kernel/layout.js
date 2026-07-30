/* Layout persistido POR TIPO de cockpit (doc 10 §1, invariante 4).
 *
 *   localStorage["cockpit.layout.{host|stack|container}"]
 *     = { v:1, ordem: [id], ocultos: [id], cheios: [id], preset: id|null }
 *
 * Chaveado pelo tipo, nunca pela instância: um arranjo para todos os projetos.
 *
 * Estado corrompido volta ao padrão com console limpo — é teste explícito do
 * doc 10 §testes. localStorage é editável pelo usuário e sobrevive a deploy;
 * tratar o que sai dele como confiável é o mesmo erro de tratar env como
 * confiável, que já custou dado neste projeto.
 */

import { doTipo, padraoDoTipo } from './presets.js';

const VERSAO = 1;
const PREFIXO = 'cockpit.layout.';

function chave(tipo) {
  return `${PREFIXO}${tipo}`;
}

function listaDeIds(valor) {
  if (!Array.isArray(valor)) return null;
  const limpos = valor.filter((v) => typeof v === 'string' && v);
  return limpos.length === valor.length ? limpos : limpos;
}

export function padrao(tipo) {
  const preset = padraoDoTipo(tipo);
  return {
    v: VERSAO,
    ordem: preset ? [...preset.ordem] : [],
    ocultos: preset ? [...(preset.ocultos || [])] : [],
    cheios: [],
    preset: preset ? preset.id : null,
  };
}

export function carregar(tipo) {
  let cru = null;
  try {
    cru = localStorage.getItem(chave(tipo));
  } catch {
    return padrao(tipo);
  }
  if (!cru) return padrao(tipo);

  let obj;
  try {
    obj = JSON.parse(cru);
  } catch {
    // JSON inválido: volta ao padrão sem gritar. Não é erro do usuário nem
    // condição que o operador possa consertar lendo o console.
    return padrao(tipo);
  }
  if (!obj || typeof obj !== 'object' || obj.v !== VERSAO) return padrao(tipo);

  const ordem = listaDeIds(obj.ordem);
  const ocultos = listaDeIds(obj.ocultos);
  const cheios = listaDeIds(obj.cheios);
  if (ordem === null) return padrao(tipo);

  return {
    v: VERSAO,
    ordem,
    ocultos: ocultos || [],
    cheios: cheios || [],
    preset: typeof obj.preset === 'string' ? obj.preset : null,
  };
}

export function salvar(tipo, estado) {
  try {
    localStorage.setItem(chave(tipo), JSON.stringify({
      v: VERSAO,
      ordem: estado.ordem || [],
      ocultos: estado.ocultos || [],
      cheios: estado.cheios || [],
      preset: estado.preset || null,
    }));
  } catch {
    // Cota cheia ou modo privado: o layout deixa de persistir, a tela segue.
  }
  return estado;
}

export function restaurar(tipo) {
  try {
    localStorage.removeItem(chave(tipo));
  } catch { /* idem */ }
  return padrao(tipo);
}

export function aplicarPreset(tipo, presetId) {
  const p = doTipo(tipo).find((x) => x.id === presetId);
  if (!p) return carregar(tipo);
  return salvar(tipo, {
    v: VERSAO,
    ordem: [...p.ordem],
    ocultos: [...(p.ocultos || [])],
    cheios: [],
    preset: p.id,
  });
}

/* Qualquer ajuste manual desliga o rótulo do preset — mas o preset de origem
 * não é esquecido, só deixa de ser afirmado (doc 10 §2). */
function personalizado(estado) {
  return { ...estado, preset: null };
}

export function alternarOculto(tipo, estado, id) {
  const ocultos = new Set(estado.ocultos || []);
  if (ocultos.has(id)) ocultos.delete(id);
  else ocultos.add(id);
  return salvar(tipo, personalizado({ ...estado, ocultos: [...ocultos] }));
}

export function alternarCheio(tipo, estado, id) {
  const cheios = new Set(estado.cheios || []);
  if (cheios.has(id)) cheios.delete(id);
  else cheios.add(id);
  return salvar(tipo, personalizado({ ...estado, cheios: [...cheios] }));
}

/** Move um módulo `delta` posições. Reorder é swap O(1) (doc 10 §3). */
export function mover(tipo, estado, id, delta) {
  const ordem = [...(estado.ordem || [])];
  const i = ordem.indexOf(id);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= ordem.length) return estado;
  [ordem[i], ordem[j]] = [ordem[j], ordem[i]];
  return salvar(tipo, personalizado({ ...estado, ordem }));
}

/** Troca por swap ao pairar — mesma semântica dos ↑↓, para os dois gestos
 *  produzirem estado idêntico (aceite do doc 10 §testes). */
export function trocar(tipo, estado, idA, idB) {
  const ordem = [...(estado.ordem || [])];
  const i = ordem.indexOf(idA);
  const j = ordem.indexOf(idB);
  if (i < 0 || j < 0 || i === j) return estado;
  [ordem[i], ordem[j]] = [ordem[j], ordem[i]];
  return salvar(tipo, personalizado({ ...estado, ordem }));
}

/* Reconcilia o layout salvo com o registro ATUAL: módulo novo entra no fim,
 * módulo que saiu do registro é descartado. Sem isto, registrar um módulo novo
 * exigiria que todo usuário limpasse o localStorage para vê-lo.
 *
 * Módulo desconhecido entra OCULTO, de propósito. Duas razões:
 * - grade é escolha do operador; módulo que ele nunca escolheu não deve brotar
 *   no meio do arranjo dele depois de um deploy;
 * - é o que mantém Plantão, Executivo, Backend e Topologia fora dos presets
 *   padrão (decisão de escopo do doc 14) sem precisar de lista negra: eles são
 *   registrados, aparecem no Personalizar, e só entram na grade se pedidos.
 */
export function reconciliar(estado, idsDisponiveis) {
  const disponiveis = new Set(idsDisponiveis);
  const ordem = (estado.ordem || []).filter((id) => disponiveis.has(id));
  const ocultos = new Set((estado.ocultos || []).filter((id) => disponiveis.has(id)));
  for (const id of idsDisponiveis) {
    if (!ordem.includes(id)) {
      ordem.push(id);
      ocultos.add(id);
    }
  }
  return {
    ...estado,
    ordem,
    ocultos: [...ocultos],
    cheios: (estado.cheios || []).filter((id) => disponiveis.has(id)),
  };
}

export function visiveis(estado) {
  const ocultos = new Set(estado.ocultos || []);
  return (estado.ordem || []).filter((id) => !ocultos.has(id));
}
