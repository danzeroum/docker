/* Exercita o selo de imagem desatualizada (4-B6) sob node.
 *
 * O que só a execução prova: que `carregarUpdates` faz UMA chamada mesmo com o
 * kernel remontando os módulos a cada 15s, e que o selo some por inteiro quando
 * o job nunca rodou — o `summary=null` do contrato, que regex sobre o fonte não
 * distingue de `summary={outdated_count:0}`.
 */
import './dom_stub.mjs';

/* --- DOM suficiente para `pintarSelos` ------------------------------------ */

function fazerNo(marca) {
  return {
    className: '',
    textContent: '',
    title: '',
    dataset: {},
    filhos: [],
    appendChild(f) { this.filhos.push(f); return f; },
    querySelector(sel) {
      if (sel === '.mod-nome-cel') return this._nome || (this._nome = fazerNo(`${marca}:nome`));
      return null;
    },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
}

function fazerCorpo() {
  return {
    _html: '',
    _linhas: new Map(),
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); this._linhas = new Map(); },
    querySelectorAll(sel) {
      if (!sel.includes('data-imagem')) return [];
      const achados = [];
      for (const m of this._html.matchAll(/data-imagem="([^"]*)"/g)) {
        const imagem = m[1];
        if (!this._linhas.has(imagem)) {
          const no = fazerNo(imagem);
          no.dataset = { imagem, abrir: imagem };
          this._linhas.set(imagem, no);
        }
        achados.push(this._linhas.get(imagem));
      }
      return achados;
    },
  };
}

globalThis.document.createElement = () => fazerNo('novo');

/* --- fetch de mentira ----------------------------------------------------- */

let chamadas = 0;
let resposta = { images: [], count: 0, summary: null };
let falhar = false;

globalThis.fetch = async () => {
  chamadas += 1;
  if (falhar) throw new Error('rede');
  return { ok: true, json: async () => resposta, text: async () => '' };
};
globalThis.AbortController = class {
  constructor() { this.signal = {}; }
  abort() {}
};

const { carregarUpdates, seloDeImagem, _resetarCache } = await import('../../app/static/js/updates.js');
const containers = (await import('../../app/static/js/modulos/containers.js')).default;

const VERIFICADO = '2026-07-30T03:14:00Z';
function comDados() {
  return {
    images: [
      { image: 'nginx:1.25', status: 'desatualizada', consultado_em: VERIFICADO,
        remoto_em: '2026-07-29T10:00:00Z' },
      { image: 'redis:7', status: 'atualizada', consultado_em: VERIFICADO, remoto_em: '' },
      { image: 'docker.io/library/postgres:16', status: 'desatualizada',
        consultado_em: VERIFICADO, remoto_em: '' },
    ],
    count: 3,
    summary: { outdated_count: 2, checked: 3, consultado_em: VERIFICADO },
  };
}

const saida = {};

/* 1. selo por status ------------------------------------------------------- */
_resetarCache();
resposta = comDados();
chamadas = 0;
let estado = await carregarUpdates();
saida.desatualizada = seloDeImagem(estado, 'nginx:1.25');
saida.atualizadaNaoTemSelo = seloDeImagem(estado, 'redis:7');
saida.foraDaListagemNaoTemSelo = seloDeImagem(estado, 'meu-app:local');
// `docker.io/x` e `x` são a mesma imagem; o compose escolhe qual forma escrever.
saida.prefixoDockerIo = seloDeImagem(estado, 'library/postgres:16');

/* 2. cache: o kernel remonta os módulos, isto não vira uma chamada por vez --- */
await carregarUpdates();
await carregarUpdates();
saida.chamadasComCache = chamadas;

/* 3. concorrência: lista e subtela pedem juntas -> ainda uma chamada -------- */
_resetarCache();
chamadas = 0;
await Promise.all([carregarUpdates(), carregarUpdates(), carregarUpdates()]);
saida.chamadasConcorrentes = chamadas;

/* 4. job nunca rodou: summary null -> selo nenhum --------------------------- */
_resetarCache();
resposta = { images: [], count: 0, summary: null };
estado = await carregarUpdates();
saida.semJobSelo = seloDeImagem(estado, 'nginx:1.25');

/* 5. rota falhou: não afirma "em dia" --------------------------------------- */
_resetarCache();
falhar = true;
estado = await carregarUpdates();
saida.comFalhaSelo = seloDeImagem(estado, 'nginx:1.25');
falhar = false;

/* 6. render de verdade do módulo `containers` ------------------------------- */
_resetarCache();
resposta = comDados();
const corpo = fazerCorpo();
const dados = {
  overview: {
    containers: [
      { name: 'api', stack: 'web', state: 'running', image: 'nginx:1.25' },
      { name: 'cache', stack: 'web', state: 'running', image: 'redis:7' },
    ],
  },
};
const dispose = containers.render({ t: 'host' }, dados, corpo);
saida.listaPintaAntesDoSelo = corpo.innerHTML.includes('data-abrir="api"');
await new Promise((r) => setTimeout(r, 10));
const linhas = corpo.querySelectorAll('[data-imagem]');
saida.selosNaLista = linhas.map((l) => ({
  imagem: l.dataset.imagem,
  selos: (l._nome ? l._nome.filhos : []).map((f) => ({ classe: f.className, texto: f.textContent })),
}));

/* 7. dispose antes da resposta: nada é pintado num corpo já desmontado ------ */
_resetarCache();
const corpo2 = fazerCorpo();
const dispose2 = containers.render({ t: 'host' }, dados, corpo2);
dispose2();
await new Promise((r) => setTimeout(r, 10));
saida.aposDisposeSemSelo = corpo2.querySelectorAll('[data-imagem]')
  .every((l) => !l._nome || !l._nome.filhos.length);

if (typeof dispose === 'function') dispose();

process.stdout.write(JSON.stringify(saida, null, 2));
