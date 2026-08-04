/* Exercita o ROTEADOR da hash sob node (kernel/app.js).
 *
 * Fixture separado do `exercita_kernel.mjs` de propósito: rotear muda escopo e
 * reexibe módulo oculto, e fazer isso no meio daquele harness contaminaria os
 * estados que ele compara. Aqui o kernel nasce limpo e só a navegação é medida.
 *
 * O defeito que estes casos travam: o `hashchange` roteava só por `deHash`, que
 * conhece `#/stack/<id>` e `#/container/<id>` e devolve o host para todo o
 * resto. Todo `#/<modulo>` caía nesse resto — mesma tela, sem erro de console,
 * sem 404. Nenhum teste de então falhava, porque nenhum media NAVEGAÇÃO.
 */
import { instalar, documento } from './dom_min.mjs';

instalar();

function slot(id) {
  const el = documento.createElement('div');
  el.id = id;
  documento.body.appendChild(el);
  return el;
}

const els = {
  regua: slot('kernelReguaSlot'),
  faixa: slot('kernelFaixa'),
  grade: slot('screenContainer'),
  painel: slot('kernelPainel'),
  subtela: slot('kernelSubtela'),
};
slot('mainTitle');
slot('mainSubtitle');
slot('toastContainer');

// Rede muda: o roteador é síncrono e não depende de dado, mas `iniciar()` dispara
// uma busca. Devolver 503 para tudo prova, de quebra, que a navegação funciona
// com o backend fora do ar — que é justamente quando alguém navega no painel.
globalThis.fetch = async () => ({
  ok: false, status: 503, json: async () => ({ detail: 'indisponível' }), text: async () => '',
});

const reg = await import(new URL('../../app/static/js/kernel/registry.js', import.meta.url));
const kernel = await import(new URL('../../app/static/js/kernel/app.js', import.meta.url));

const saida = {};
kernel.iniciar(els);
await new Promise((r) => setTimeout(r, 0));

const estado = () => kernel._interno.estadoAtual();
const naGrade = (id) => !!documento.getElementById(`mod-${id}`);

/* --- 1. `#/<modulo>` revela o módulo ------------------------------------- */
// O alvo é escolhido do próprio estado, não escrito à mão: o núcleo não pode
// citar módulo por nome (doc 10 §4), e o teste que o vigia também não deveria.
const oculto = (estado().ocultos || [])[0] || null;
saida.oculto_id = oculto;
if (oculto) {
  saida.oculto_na_grade_antes = naGrade(oculto);
  kernel.rotear(`#/${oculto}`);
  saida.oculto_ainda_oculto_depois = (estado().ocultos || []).includes(oculto);
  saida.oculto_na_grade_depois = naGrade(oculto);
}

const visivel = (estado().ordem || []).find((id) => !(estado().ocultos || []).includes(id));
saida.visivel_id = visivel;
if (visivel) {
  kernel.rotear(`#/${visivel}`);
  saida.visivel_continua_na_grade = naGrade(visivel);
  saida.visivel_escopo = kernel._interno.escopoAtual().t;
}

/* --- 2. `#/stack/x` e `#/container/x` continuam trocando o escopo -------- */
kernel.rotear('#/container/criptotrade-app');
saida.escopo_container = kernel._interno.escopoAtual();
kernel.rotear('#/stack/web');
saida.escopo_stack = kernel._interno.escopoAtual();
kernel.rotear('#/');
saida.escopo_host = kernel._interno.escopoAtual();

/* --- 3. hash desconhecida cai no host, sem levantar --------------------- */
kernel.rotear('#/dossie');
saida.desconhecida_escopo = kernel._interno.escopoAtual();

/* --- 4. módulo que não vive no host não finge que navegou ---------------- */
const soDeEscopo = reg.todos().find((m) => !m.escopos.includes('host'));
saida.sem_host_id = soDeEscopo ? soDeEscopo.id : null;
saida.sem_host_alcancavel = soDeEscopo ? kernel.alcancavelNoHost(`#/${soDeEscopo.id}`) : null;
if (soDeEscopo) {
  kernel.rotear(`#/${soDeEscopo.id}`);
  saida.sem_host_escopo = kernel._interno.escopoAtual();
  saida.sem_host_na_grade = naGrade(soDeEscopo.id);
}

/* --- 5. `alcancavelNoHost`: o que o rail pode oferecer ------------------- */
const comHost = reg.todos().find((m) => m.escopos.includes('host'));
saida.com_host_id = comHost ? comHost.id : null;
saida.alcancavel = {
  host: kernel.alcancavelNoHost('#/'),
  vazia: kernel.alcancavelNoHost(''),
  modulo_host: comHost ? kernel.alcancavelNoHost(`#/${comHost.id}`) : null,
  inexistente: kernel.alcancavelNoHost('#/dossie'),
  container: kernel.alcancavelNoHost('#/container/abc'),
  stack: kernel.alcancavelNoHost('#/stack/web'),
};

/* --- 6. a query string não atrapalha (attention.js navega com `?host=`) -- */
if (comHost) {
  kernel.rotear('#/');
  kernel.rotear(`#/${comHost.id}?host=exemplo.com`);
  saida.com_query_na_grade = naGrade(comHost.id);
  saida.com_query_escopo = kernel._interno.escopoAtual().t;
}

kernel._interno.parar();
process.stdout.write(JSON.stringify(saida), () => process.exit(0));
