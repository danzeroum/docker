/* Doc 13 — a interface não reconstrói a árvore por leitura.
 *
 * Três níveis, um arquivo:
 *
 *   UNIDADE       `lista()` e `texto()` do patch.js — a linha que sobrevive,
 *                 a que sai, a que entra e a que reordena;
 *   INTEGRAÇÃO    um módulo real sob leituras repetidas, contando nós criados
 *                 e destruídos por MutationObserver;
 *   ACEITAÇÃO     o roteiro do doc 12 exercitado sem perder foco nem scroll,
 *                 e o relógio compartilhado com a aba oculta.
 *
 * A medida é IDENTIDADE DE NÓ, não igualdade de HTML. As duas divergem
 * exatamente no caso que interessa: um `innerHTML =` idempotente produz string
 * final idêntica e mesmo assim matou toda a árvore no caminho — levando junto o
 * `:hover`, o foco, a seleção e o `scrollTop` que viviam nos nós antigos.
 *
 * `MutationObserver` conta as duas coisas separadamente porque elas respondem a
 * perguntas diferentes: nó ADICIONADO que já era conhecido é movimento
 * (reordenação, que é barata e correta); nó adicionado inédito é criação.
 */
import { instalar, documento } from './dom_min.mjs';

instalar();

const saida = {};

/* --- instrumento ---------------------------------------------------------- */

/* Um nó "conhecido" nunca mais conta como criado. É assim que reordenar deixa
 * de ser confundido com recriar — a distinção que o doc 13 exige e que a
 * contagem crua de `addedNodes` não faz. */
function espiar(raiz) {
  const conhecidos = new WeakSet();
  const marcar = (no) => {
    if (no.nodeType !== 1) return;
    conhecidos.add(no);
    for (const f of no.children) marcar(f);
  };
  marcar(raiz);

  const contas = { criados: 0, removidos: 0, movidos: 0 };
  const obs = new MutationObserver((registros) => {
    for (const r of registros) {
      for (const no of r.addedNodes) {
        if (no.nodeType !== 1) continue;
        if (conhecidos.has(no)) contas.movidos += 1;
        else { contas.criados += 1; marcar(no); }
      }
      for (const no of r.removedNodes) if (no.nodeType === 1) contas.removidos += 1;
    }
  });
  obs.observe(raiz, { childList: true, subtree: true });
  return {
    contas,
    async colher() {
      await Promise.resolve();
      await Promise.resolve();
      return { ...contas };
    },
    zerar() { contas.criados = 0; contas.removidos = 0; contas.movidos = 0; },
    parar() { obs.disconnect(); },
  };
}

function caixa() {
  const el = documento.createElement('div');
  documento.body.appendChild(el);
  return el;
}

async function assentar(voltas = 40) {
  for (let i = 0; i < voltas; i++) await Promise.resolve();
  await new Promise((r) => setTimeout(r, 0));
}

/* --- UNIDADE: patch.js ---------------------------------------------------- */

const patch = await import(new URL('../../app/static/js/kernel/patch.js', import.meta.url));

const MOLDE = '<div class="linha"><span data-nome></span><span data-val></span></div>';

function pintarLista(alvo, nomes) {
  return patch.lista(alvo, nomes, {
    chave: (n) => n.id,
    criar: () => patch.deMolde(MOLDE),
    atualizar: (el, n) => {
      patch.texto(el.querySelector('[data-nome]'), n.id);
      patch.texto(el.querySelector('[data-val]'), String(n.v), { flash: true });
    },
  });
}

const alvoUnidade = caixa();
const TRES = [{ id: 'api', v: 1 }, { id: 'front', v: 2 }, { id: 'worker', v: 3 }];
pintarLista(alvoUnidade, TRES);
const nosIniciais = alvoUnidade.querySelectorAll('.linha');

// 1. payload idêntico: nenhum nó recriado, nenhum movido
const r1 = pintarLista(alvoUnidade, TRES);
saida.unidade_identico = {
  ...r1,
  mesmosNos: alvoUnidade.querySelectorAll('.linha').every((n, i) => n === nosIniciais[i]),
};

// 2. só o valor muda: o nó é o mesmo e o texto trocou
const r2 = pintarLista(alvoUnidade, [{ id: 'api', v: 9 }, { id: 'front', v: 2 }, { id: 'worker', v: 3 }]);
saida.unidade_valor = {
  ...r2,
  mesmoNo: alvoUnidade.querySelectorAll('.linha')[0] === nosIniciais[0],
  valor: nosIniciais[0].querySelector('[data-val]').textContent,
  piscou: nosIniciais[0].querySelector('[data-val]').className,
};

// 3. um item sai: SÓ a linha dele sai; as vizinhas mantêm o nó
const r3 = pintarLista(alvoUnidade, [{ id: 'api', v: 9 }, { id: 'worker', v: 3 }]);
saida.unidade_remocao = {
  ...r3,
  restantes: alvoUnidade.querySelectorAll('.linha').map((n) => n.querySelector('[data-nome]').textContent),
  vizinhasIntactas: alvoUnidade.querySelectorAll('.linha')[0] === nosIniciais[0]
    && alvoUnidade.querySelectorAll('.linha')[1] === nosIniciais[2],
};

// 4. reordenar é insertBefore, não redesenhar
const r4 = pintarLista(alvoUnidade, [{ id: 'worker', v: 3 }, { id: 'api', v: 9 }]);
saida.unidade_reordem = {
  ...r4,
  ordem: alvoUnidade.querySelectorAll('.linha').map((n) => n.querySelector('[data-nome]').textContent),
  reaproveitou: alvoUnidade.querySelectorAll('.linha')[0] === nosIniciais[2],
};

// 5. um item entra: só ele nasce
const r5 = pintarLista(alvoUnidade, [{ id: 'worker', v: 3 }, { id: 'api', v: 9 }, { id: 'novo', v: 0 }]);
saida.unidade_insercao = r5;

// 6. `texto` não escreve o que já está escrito
const alvoTexto = documento.createElement('span');
saida.unidade_texto = {
  primeira: patch.texto(alvoTexto, 'oi'),
  repetida: patch.texto(alvoTexto, 'oi'),
  diferente: patch.texto(alvoTexto, 'tchau'),
};

// 7. o flash não dispara na PRIMEIRA escrita: chegada de dado não é mudança
const alvoFlash = documento.createElement('span');
patch.texto(alvoFlash, '10', { flash: true });
saida.flash_primeira = alvoFlash.className;
patch.texto(alvoFlash, '11', { flash: true });
saida.flash_mudanca = alvoFlash.className;
patch.texto(alvoFlash, '12', { flash: true });
saida.flash_realterna = alvoFlash.className;

/* --- INTEGRAÇÃO: um módulo real sob leituras repetidas -------------------- */

globalThis.fetch = async () => ({
  ok: true, status: 200, json: async () => ({}), text: async () => '',
});

const containers = (await import(new URL('../../app/static/js/modulos/containers.js', import.meta.url))).default;

function payload(nomes) {
  return {
    overview: {
      containers: nomes.map((n, i) => ({
        id: `id-${n}`, name: n, stack: 'web', state: 'running',
        health: 'none', image: 'nginx:1.25', cpu_pct: 2 + i, mem_usage: 100,
      })),
    },
  };
}

const QUINZE = Array.from({ length: 15 }, (_, i) => `svc-${String(i).padStart(2, '0')}`);

const alvoMod = caixa();
const montado = containers.render({ t: 'host' }, payload(QUINZE), alvoMod);
await assentar();

const espiao = espiar(alvoMod);

// 20 leituras seguidas com o mesmo payload
for (let i = 0; i < 20; i++) montado.atualizar(payload(QUINZE));
saida.integracao_20_polls = await espiao.colher();
saida.integracao_nos_apos_20 = alvoMod.querySelectorAll('[data-abrir]').length;

// scroll interno e foco sobrevivem a 3 leituras seguidas
const lista_ = alvoMod.querySelector('[data-lista]');
lista_.scrollTop = 120;
const linhaFocada = alvoMod.querySelectorAll('[data-abrir]')[4];
linhaFocada.focus();
for (let i = 0; i < 3; i++) montado.atualizar(payload(QUINZE));
saida.integracao_scroll = lista_.scrollTop;
saida.integracao_foco = documento.activeElement === linhaFocada;

// a barra de CPU anda no MESMO nó: é isso que permite a transição rodar
const barraAntes = linhaFocada.querySelector('.mod-barra-fill');
const larguraAntes = barraAntes.style.getPropertyValue('--barra');
const outro = payload(QUINZE);
outro.overview.containers[4].cpu_pct = 12;
montado.atualizar(outro);
saida.integracao_barra = {
  mesmoNo: linhaFocada.querySelector('.mod-barra-fill') === barraAntes,
  antes: larguraAntes,
  depois: barraAntes.style.getPropertyValue('--barra'),
};

// item removido do payload: só a linha dele sai
espiao.zerar();
const vizinhaAntes = alvoMod.querySelectorAll('[data-abrir]')[0];
const semUm = QUINZE.filter((n) => n !== 'svc-07');
montado.atualizar(payload(semUm));
saida.integracao_remocao = await espiao.colher();
saida.integracao_remocao_vizinha = alvoMod.querySelectorAll('[data-abrir]')[0] === vizinhaAntes;
saida.integracao_remocao_restantes = alvoMod.querySelectorAll('[data-abrir]').length;

espiao.parar();
montado.dispose();

/* --- ACEITAÇÃO: o campo de busca dos logs não é interrompido -------------- */

const modLogs = (await import(new URL('../../app/static/js/modulos/logs.js', import.meta.url))).default;

globalThis.fetch = async (url) => {
  if (String(url).includes('/logs?tail=')) {
    return { ok: true, status: 200, text: async () => 'linha 1\nlinha 2\n', json: async () => ({}) };
  }
  return { ok: true, status: 200, json: async () => ({}), text: async () => '' };
};

const alvoLogs = caixa();
const logs = modLogs.render({ t: 'container', id: 'api' }, { overview: {} }, alvoLogs);
await assentar();

const campo = alvoLogs.querySelector('[data-busca]');
campo.value = 'oo';
campo.focus();
const preLogs = alvoLogs.querySelector('[data-pre]');
preLogs.scrollHeight = 500;
preLogs.clientHeight = 100;
preLogs.scrollTop = 40;   // o operador subiu para ler

const espiaoLogs = espiar(alvoLogs);
for (let i = 0; i < 3; i++) logs.atualizar();
await assentar();
saida.aceite_logs = {
  mesmoCampo: alvoLogs.querySelector('[data-busca]') === campo,
  textoDigitado: campo.value,
  focoMantido: documento.activeElement === campo,
  scrollMantido: preLogs.scrollTop,
  ...(await espiaoLogs.colher()),
};
espiaoLogs.parar();
logs.dispose();

/* --- ACEITAÇÃO: relógio compartilhado ------------------------------------ */

const relogio = await import(new URL('../../app/static/js/kernel/relogio.js', import.meta.url));

relogio.desligar();
let batidas = 0;
const cancelar = relogio.assinar(() => { batidas += 1; }, relogio.TICK_MS);
const cancelarLento = (() => {
  let lentas = 0;
  const c = relogio.assinar(() => { lentas += 1; }, 3 * relogio.TICK_MS);
  return { c, ler: () => lentas };
})();

relogio._interno.bater();
relogio._interno.bater();
relogio._interno.bater();
saida.relogio_periodos = { rapido: batidas, lento: cancelarLento.ler() };

// aba oculta: nenhum tick
documento.hidden = true;
const antesDeOcultar = batidas;
for (let i = 0; i < 10; i++) relogio._interno.bater();
saida.relogio_oculto = batidas - antesDeOcultar;

// ao voltar: UMA atualização por assinante, não a rajada represada
documento.hidden = false;
const antesDeVoltar = { rapido: batidas, lento: cancelarLento.ler() };
relogio._interno.aoVoltar();
saida.relogio_retorno = {
  rapido: batidas - antesDeVoltar.rapido,
  lento: cancelarLento.ler() - antesDeVoltar.lento,
};

cancelar();
cancelarLento.c();
saida.relogio_sem_assinantes = relogio._interno.quantos();
relogio.desligar();

/* --- ACEITAÇÃO: a régua faz patch, e a pílula diz a verdade --------------- */

const regua = await import(new URL('../../app/static/js/kernel/regua.js', import.meta.url));
const registry = await import(new URL('../../app/static/js/kernel/registry.js', import.meta.url));

const slotRegua = caixa();
slotRegua.id = 'kernelReguaSlot';
regua.montarRegua(slotRegua);

registry.limpar();
registry.registrar({
  id: 'sonda', nome: 'Sonda', escopos: ['host'], span: 6,
  chip: (_e, s) => (s ? { rotulo: 'Sonda', valor: String(s.n) } : null),
  render: () => null,
});

const estado = { ordem: ['sonda'], ocultos: [], cheios: [] };
const opts = (cpu, n) => ({
  escopo: { t: 'host' },
  overview: { vitals: { cpu_pct: cpu, mem_pct: 50, swap_pct: 1, disk: { pct: 40 } }, summary: { n } },
  estado,
});

regua.pintarRegua(opts(20, 1));
const vitaisAntes = slotRegua.querySelectorAll('.rg-vital');
const chipAntes = slotRegua.querySelector('.rg-chip');
const espiaoRegua = espiar(slotRegua);

regua.pintarRegua(opts(20, 1));   // leitura idêntica
const reguaIdentica = await espiaoRegua.colher();
regua.pintarRegua(opts(81, 2));   // valores mudaram
const reguaMudou = await espiaoRegua.colher();

saida.regua = {
  identica: reguaIdentica,
  aposMudanca: { criados: reguaMudou.criados - reguaIdentica.criados },
  mesmosVitais: slotRegua.querySelectorAll('.rg-vital').every((n, i) => n === vitaisAntes[i]),
  mesmoChip: slotRegua.querySelector('.rg-chip') === chipAntes,
  cpuTexto: vitaisAntes[0].querySelector('.rg-val').textContent,
  cpuTom: vitaisAntes[0].className,
  chipValor: chipAntes.querySelector('.rg-val').textContent,
  chipPiscou: /flash-[ab]/.test(chipAntes.querySelector('.rg-val').className),
};
espiaoRegua.parar();

// a pílula ao vivo: varredura reinicia a cada leitura, e o drag a pausa
const varredura = slotRegua.querySelector('[data-varredura]');
regua.marcarLeitura();
const varre1 = varredura.className;
regua.marcarLeitura();
const varre2 = varredura.className;
regua.pausarVivo(true);
const pausada = {
  classe: slotRegua.querySelector('[data-vivo]').className,
  rotulo: slotRegua.querySelector('[data-vivo-rot]').textContent,
};
regua.pausarVivo(false);
saida.vivo = {
  varreduraAlterna: varre1 !== varre2 && !!varre1 && !!varre2,
  pausada,
  retomada: slotRegua.querySelector('[data-vivo-rot]').textContent,
};

process.stdout.write(JSON.stringify(saida, null, 2), () => process.exit(0));
