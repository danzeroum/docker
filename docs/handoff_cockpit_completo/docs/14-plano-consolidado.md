# 14 · Plano consolidado — backend B1–B11 × face de interface

> Atualizado após a Sprint 2a. O registro da execução está na seção 15, no fim.

Funde três coisas que até aqui viviam separadas: os prompts de backend B1–B11
(`blocos-b1-b11-prompts-completos.md`), a face de interface dos docs 10/11/12, e o que a
Sprint 1 efetivamente entregou (`13-blocos-agregados.md`). Nada dos três se perde.

Obedece às 4 regras do `LEIA-ME.md`: zero mock, kernel invariante, chip vivo, ações
fail-closed auditadas antes de executar.

---

## 1 · Dois pré-requisitos que a Sprint 2 assume e que não existem

Este é o achado principal da revisão do protótipo. As duas coisas abaixo são **fundação**,
não detalhe, e a Sprint 2 proposta ("portar módulo Armazenamento e Eventos, registrados no
registro de módulos; summary da régua ganha 3 chaves") pressupõe as duas prontas.

### 1.1 O registro de módulos não existe

O doc 10 §1 define `Modulo = {id, nome, escopos, span, chip(escopo), render(escopo, dados)}`
e o doc 10 §4 é explícito: *"módulo novo = 1 arquivo novo, zero `if` no núcleo"*.

O que existe hoje em `app/static/js/main.js:71-85` é o oposto exato:

```js
switch (_route(screen)) {
  case '#/overview':   dispose = renderOverview(container); break;
  case '#/capacidade': dispose = renderCapacidade(container); break;
  // ... 13 cases
}
```

São **13 telas de página cheia num switch**, não 13 módulos × 3 escopos. Um `case` por tela
no núcleo é literalmente o que o doc 10 proíbe. Além disso não há escopo (`{t:'stack', id}`),
não há régua de chips, não há modo Personalizar, não há subtela central — o prompt do doc 10
§5 ("Implementar o Cockpit Vivo") nunca foi executado.

Consequência prática: **não é possível "registrar um módulo no registro de módulos" antes de
o registro existir.** O trabalho de UI da Sprint 2 tem um pré-requisito maior do que os dois
módulos que ele quer acrescentar.

Alguns nomes coincidem entre as telas atuais e os módulos do protótipo (`capacidade`,
`ingress`, `tarefas`, `auditoria`, `atencao`), mas são conceitos diferentes: tela = rota de
página cheia; módulo = read model parametrizado por escopo. A migração reaproveita o **corpo**
de cada tela (o doc 09 §A já mapeia isso como 🔧), não a estrutura.

### 1.2 `/api/overview` não tem bloco `summary`

O doc 09 §B item 1 especifica o `summary` com 6 chaves (`findings`, `stacks`, `ingress`,
`capacity`, `audit`, `tasks`) e o justifica: *"alimenta a régua inteira em 1 chamada, sem 6
fetches por poll"*. Está marcado 🆕 e **nunca foi implementado** — `grep summary
app/routers/overview.py` não devolve nada.

Isso sustenta o invariante 3 (módulo oculto mantém chip vivo) e a conta de complexidade do
doc 10 §3 ("a régua custa 1 chamada, não 10"). Sem ele, chip vivo com módulo oculto é
impossível sem N fetches.

Portanto: acrescentar `storage.reclaimable`, `security.min_score` e `updates.outdated` ao
`summary` — pedido da Sprint 2 — exige **primeiro criar o `summary`** com as 6 chaves
originais. É o "1 PR pequeno" do doc 09 §B, ainda em aberto.

### 1.3 Terceira lacuna, menor: a UI não sabe se `ENABLE_ACTIONS` está ligado

O aceite do doc 11 é mais rígido do que "renderizar cinza": *"Sem ENABLE_ACTIONS: nenhum
botão de ação existe no DOM (não é `display:none`)"*. Para cumprir isso o frontend precisa
**saber** o valor da flag, e hoje nenhuma rota o expõe.

Menor esforço coerente com o resto: a flag entra no próprio `summary`
(`summary.capabilities.actions_enabled`), junto com `unlock.active`. Um endpoint
`/api/capabilities` separado custaria mais um fetch por poll, contra a economia que motiva o
`summary`.

---

## 2 · Decisão pendente: linguagem ubíqua nas chaves novas

O doc 10 §1 fixa: *"o nome na UI = nome no código = chave da API. Sem sinônimos em nenhuma
camada."* Há um conflito real entre o que a Sprint 1 entregou e o que os docs 09/12 esperam:

| Docs 09 §B / 12 esperam | Sprint 1 entregou |
|---|---|
| `summary.storage.reclaimable` | `/api/storage` → `reclaimable_bytes` |
| `summary.security.min_score` | `/api/security` → `summary.score_minimo` |
| — | `/api/security` → `violacoes_por_severidade`, `conformes` |

O repo já é bilíngue por decisão anterior: ids de módulo e de tela são em português
(`atencao`, `capacidade`, `metricas`), mas as chaves do `summary` no doc 09 §B são em inglês
(`open`, `critical`, `days_to_90`).

**Recomendação:** as chaves do `summary` seguem os docs 09/12 **verbatim** — é o contrato que
o protótipo e os docs referenciam, e é o payload que a régua lê. Os payloads dos endpoints
`/api/storage` e `/api/security` ficam como estão; o construtor do `summary` mapeia de um para
o outro. Assim nenhum contrato já entregue quebra e a régua fica exatamente como
especificada. Reversível: é um mapeamento num único lugar.

Se a preferência for unificar tudo em português, a hora de decidir é **antes** da Sprint 2 —
depois de a régua existir, renomear chave é mudança em três camadas.

---

## 3 · Onde a Sprint 1 deixou os docs desatualizados

Dois pontos a corrigir nos docs, para não gerar trabalho duplicado:

- **Doc 10 §3** diz que sparkline por container *"exige gravar `target` no sampler 🆕
  pequeno"* e aponta para `/api/metrics/history?series=…&target=…`. Isso foi resolvido, mas
  por outro caminho: `GET /api/containers/{id}/history?range=` (rota própria, resolução
  `raw`/`hourly` no payload, teto de 500 pontos). A linha do doc 10 §3 deve apontar para a
  rota nova.
- **Doc 12** lista `/api/storage`, `/api/containers/{id}/history` e `/api/security` como
  *"novos endpoints exigidos"*. Os três **existem** desde a Sprint 1. Restam exigidos:
  `/api/events` (histórico paginado), `/api/logs/search` e `/api/updates`.
- **Anexo B1–B11** e o `LEIA-ME` dizem que os prompts XML completos "estão com o
  desenvolvedor". Eles estão no repo, em
  `docs/handoff_cockpit_completo/docs/blocos-b1-b11-prompts-completos.md`.

---

## 4 · Roadmap consolidado

Ordem de backend do autor (B3/B5 → B6/B7/B9 → B8/B11 → B10) cruzada com a ordem de valor
para a interface do doc 11 (B2 → B4 → B3 → B1+B10 → B5 → B6 → B8).

| Sprint | Backend | Design/UI |
|---|---|---|
| ~~1~~ ✅ | ~~B2 histórico/rollup · B1 storage · B4 security~~ | ~~Cards na Capacidade · badge Health na lista~~ |
| **2a — fundação** | `summary` no `/api/overview` (6 chaves do doc 09 §B + `capabilities` + as 3 novas) | **Registro de módulos** + escopos + régua de chips + Personalizar + subtela central (doc 10 §5). Migra as 13 telas para módulos reaproveitando os corpos |
| **2b** | B3-residual (ring SQLite v11 + filtros server-side + `GET /api/events`) · B10-residual (prune dry-run, `ENABLE_ACTIONS`, audit-antes, v12) | Módulo **Armazenamento** (GB recuperáveis + prune atrás da trava) · Módulo **Eventos** (3 escopos) · Subtela: sparklines de `/history` + score B4 com violações |
| **3** | B5 logs FTS5 + follow SSE | Upgrade do módulo **Logs**: busca com highlight + selo ● follow |
| **4** | B6 updates Hub · B7 notificações · B9 `/metrics` | Badge "desatualizada" com `consultado_em` · selo "notificado hh:mm · canal" no achado |
| **5** | B8 drift · B11 hardening | Módulo **Drift** + chip na régua · dívida `sw.js` (telas fora do `STATIC_ASSETS`, com teste de invalidação) |

A Sprint 2 foi partida em **2a/2b** por causa do §1: juntar a fundação do Cockpit Vivo com
dois módulos novos numa sprint só é o tipo de escopo que estoura no meio e deixa as duas
metades pela metade. 2a não entrega feature nova — entrega a estrutura que torna 2b, 3, 4 e 5
trabalho de "1 arquivo novo por módulo", que é a promessa do doc 10.

**Critério de aceitação do conjunto** (inalterado): o roteiro de 2 min do doc 12 executado
contra dados reais — cenário API caindo → subtela do container → buscar `oom` nos logs →
destravar → reiniciar → auditoria → chip Drift → Personalizar — com `grep` no JS não
encontrando nome de container, domínio nem métrica escrita à mão (doc 01).

---

## 5 · Blocos residuais da Sprint 2

### B3-residual — persistência e filtros de eventos
Prompt do revisor mantido. Duas notas de implementação:

- Migration **v11**. Vale a regra dura do doc 00: *toda migração de esquema tem teste com
  banco populado antes do deploy* — a v3 perdeu `first_seen` em produção por não ter isso.
- "Mesmo consumer" é a regra certa: `app/events.py` já mantém um único stream com backoff e
  já faz `_broadcast` + `_invalidate_caches`. Persistir é acrescentar um consumidor à
  função de broadcast, **não** abrir um segundo stream `/events`.
- Ring por contagem reaproveita `purge_samples`, que já roda a cada ciclo de 60 s do
  `sampler`. Não precisa de trigger nem de tarefa nova.

### B10-residual — prune, flag e auditoria-antes
Prompt do revisor mantido. A alegação central confere no código: `_mutate_container`
(`app/routers/containers.py:257-268`) chama `add_audit_entry` **depois** de `proxy_fn`
retornar, ou no `except`. Ação que trava o daemon não gera linha nenhuma.

Notas:
- O refactor é uma **migração** (`audit_log` ganha o par `started`→resultado). Migration
  **v12**, com teste de banco populado, mesma regra acima.
- `ENABLE_ACTIONS=0` cobrindo também as 4 rotas da F5 (`start/stop/restart`, `DELETE`) e as
  2 de stack é o ponto mais importante do bloco: uma flag que cobrisse só o `prune` daria
  falsa sensação de read-only, com a superfície de mutação da F5 aberta ao lado.
- `dry_run` fora do build cache mantém coerência com o `reclaimable_bytes` do B1, que já
  exclui build cache de propósito.

### S2-UI — módulos + régua
Prompt do revisor mantido, com o pré-requisito do §1.1 explicitado no `<context>`: o registro
de módulos é entregável da 2a, não premissa. E o `<rules>` ganha a linha do §1.3 — o botão só
não existe no DOM se a UI souber a flag, o que exige `summary.capabilities`.

### S2-UI-subtela — sparklines + score
Prompt do revisor mantido. O backend está pronto e os dois aceites amarram bem:
- score 55 para `privileged`+`root` é a aritmética já congelada no backend e coberta por
  teste (`tests/test_security.py::test_privileged_mais_root_da_55_com_duas_violacoes`);
- `history` vazio → "coletando…" é a borda do primeiro dia de uso, e o payload já entrega o
  que a UI precisa para distinguir: `points: []` com `point_count: 0`, mais `retention` para
  a tela declarar a janela (exigência do doc 10 §4, análise descritiva).

---

## 6 · Registro de validação

Revisão do protótipo `Cockpit Vivo Completo.dc.html` feita contra os docs 09–12, não linha a
linha: o arquivo é saída compilada (`<x-dc>` + `support.js`, identificadores de uma letra), o
que torna leitura de código improdutiva. O que foi conferido: os 13 ids de módulo
(`armazenamento, atencao, auditoria, capacidade, config, containers, drift, eventos, ingress,
logs, metricas, stacks, tarefas`), os 7 presets nos 3 escopos, e os dados de demo que precisam
morrer na implementação (`criptotrade-app`, `familia-web`, `giva-api`, `prompte`,
`redis-teste`, `juridico`, `docker-cockpit-proxy`) — que é exatamente o teste de `grep` do
doc 01.

---

# 15 · Sprint 2a — executada

Registro do que a 2a entregou, e das decisões tomadas durante a execução.

## Backend: bloco `summary`

`app/summary.py`. O doc 09 §B especificava desde a primeira iteração e nunca foi
implementado. O desenho tem duas metades, porque há dois compromissos simultâneos:

- `montar()` só lê cache em memória e SQLite — zero chamada ao daemon no request;
- `aquecer_loop()` mantém esses caches quentes em background, a cada 60 s.

A segunda metade não estava no prompt e é o que faz o invariante 3 valer de
verdade. Se o summary buscasse sob demanda, o chip de um módulo oculto nunca
seria preenchido (ninguém dispara a busca) e a régua viraria decoração. Se
buscasse no request, cada poll dispararia `/system/df`.

`cache.peek()` é a peça que separa as duas: lê sem disparar o factory. A
fronteira do "velho demais" é o TTL da própria entrada, não uma constante global
— a projeção de disco é cacheada por 5 min e o storage por 30 s.

**Duas chaves saem `null` por falta de fonte real**, com `stale_since` datado:

- `drift.count` — B8 pendente. A chave já sai no contrato para a régua não mudar
  de forma quando o drift chegar.
- `ingress.certs_expiring` e `cert_window_days` — **não há fonte**. Não existe
  regra de expiração entre as 17 do motor, e o diretório do certbot não está
  montado no container (o compose monta só `nginx` e `/opt/btv`). O doc 09 §C
  lista o chip "certs_expiring 3" como se fosse derivável; não é. Inventar dias
  aqui é exatamente o que o doc 01 proíbe.

`summary.stacks` deriva dos containers que o `/api/overview` já montou, **não**
de `/api/projects`: aquela rota roda `docker compose ps` por projeto via
subprocess, e chamá-la por poll colocaria ~12 subprocessos no caminho de cada
request da régua.

## Frontend: registro de módulos

O `switch` com um `case` por tela saiu de `main.js`. No lugar: `kernel/` com
`registry`, `escopo`, `layout`, `presets`, `regua`, `cockpit`, `personalizar`,
`subtela` e `app`. `grep` nos arquivos do núcleo não encontra o id de nenhum
módulo — coberto por teste (`test_nucleo_nao_cita_nenhum_modulo_por_nome`).

**18 módulos**, não 17. Ao portar, apareceu um órfão que a contagem inicial não
previa: `projetos`, a tela de start/stop de stack compose atrás de
`require_unlock` — foi ela que obrigou a F5 a existir. Sem registrar, sumiria no
porte. Registrada como os outros extras, fora dos presets.

`screens/overview.js` foi **removida**, não portada: seus quatro painéis são
exatamente os módulos `atencao`, `containers`, `stacks` e `ingress`. O Dossiê e
a tela de Logs (~275 linhas em `main.js`) também saíram, substituídos pela
subtela + os módulos `config`, `metricas` e `logs`.

`reconciliar()` acrescenta módulo desconhecido como **oculto**. É o que mantém
os 5 extras fora da grade sem precisar de lista negra, e evita que um deploy
faça brotar módulo no arranjo de quem nunca o escolheu.

## Decisões de escopo confirmadas

1. **Os extras** (`backend`, `executivo`, `plantao`, `projetos`, `topologia`)
   são registrados e aparecem no Personalizar; nenhum preset padrão os
   referencia. Nenhum tem chave no `summary`, logo nenhum aparece na régua —
   chip sem fonte seria dado inventado.
2. **`ENABLE_ACTIONS` nasce em `1`** na 2a, porque as 4 rotas de mutação da F5
   existem e funcionam atrás do unlock; nascer `0` faria a UI esconder botão de
   rota que responde. **Na 2b a inversão do padrão e o pin explícito
   `ENABLE_ACTIONS=1` no compose de produção entram no MESMO commit da
   barreira** — separá-los derruba `unlock→reiniciar` em produção.

## Dívidas pagas no caminho

- `sw.js` passou a listar `kernel/`, `modulos/` e `screens/` em
  `STATIC_ASSETS`, com bump de `cockpit-v2` para `v3`. Era dívida registrada no
  §"Dívida conhecida" acima: sem isso o service worker servia um `main.js` que
  importa arquivos que ele não tem, e offline a interface ficava em branco.
- `mod-linha` é sempre `<button>`; linha sem ação usa `mod-item` (`<div>`).
  `test_acessibilidade` pegou a classe única servindo duas semânticas — botão
  que não faz nada é pior para o teclado que um div honesto.
- O follow de logs por SSE quase ficou de fora do porte. Um teste existente
  (`test_logs_texto`) foi quem pegou.

## Testes migrados, não apagados

Oito testes codificavam a arquitetura antiga (`case '#/rota':` no switch,
`fetchLines` no `main.js`, classes de `screens/overview.js`). Cada um foi
**retargetado preservando a intenção** — "a tela está ligada ao render real, não
a um placeholder" virou "o módulo está registrado e chama o render real". A
justificativa está no corpo de cada teste, para o próximo leitor não achar que
alguém afrouxou a asserção.

## O que a 2a NÃO entregou

A adaptação visual de cada corpo de módulo à caixa do módulo. Os 9 módulos que
delegam a telas existentes renderizam o markup de página cheia dentro de um
card — funciona e os dados são reais, mas o acabamento de cada um viaja com o
sprint do seu bloco (Armazenamento e Eventos na 2b, Logs na 3, Drift na 5).

O roteiro de 2 min do doc 12 navega host → stack → subtela sem reload, mas
`buscar oom nos logs` (B5) e `reiniciar` (B10-residual) só fecham na 2b/3.

## Backlog de fonte: validade de certificado

`summary.ingress.certs_expiring` e `cert_window_days` saem `null` porque **não há
fonte**, não porque a leitura falhou. Duas coisas faltam ao mesmo tempo:

- nenhuma das 17 regras do motor calcula dias até a expiração;
- o diretório do certbot não está montado no container — o compose monta
  `/opt/btv/ingress/nginx` e `/opt/btv`, ambos `:ro`, e nenhum contém os
  `fullchain.pem`.

O parser já extrai `cert_path` de cada host, então o caminho existe; o que falta
é poder ler o arquivo e uma regra que faça a conta.

**Decisão: fica em backlog e se resolve na Sprint 5, junto do B11.** Duas saídas,
e a escolha é consciente:

1. montar o diretório do certbot `:ro` no compose e criar a regra de expiração —
   os chips passam a ter fonte real;
2. tirar as duas chaves do contrato do `summary` e do doc 09 §C.

O que **não** é opção é deixar como está indefinidamente: chave permanentemente
`null` no contrato é convite a alguém "consertar" preenchendo com estimativa, que
é exatamente o dado inventado que o doc 01 proíbe.

---

# 16 · Sprint 2b — executada

## B3 — timeline persistida (v11)

`docker_events` com `id` AUTOINCREMENT, não PK temporal: o daemon emite
die+stop+start de um restart no mesmo segundo, e uma chave por timestamp
descartaria justamente a sequência que a timeline existe para mostrar.

Persistência no consumer **único**, antes do broadcast. Persistir antes de
transmitir porque o pior caso vira "evento no banco que ninguém viu ao vivo" —
o inverso perderia o evento para sempre.

Filtros no servidor: `_clients` guarda `(fila, filtro)` e o broadcast corta na
origem. `invalidate` e `error` passam por qualquer filtro — são plano de
controle, e sem eles a tela do cliente filtrado congela sem motivo aparente.

Ruído do daemon (`exec_create`, `exec_start`, `attach`) fica fora do ring:
chega às dezenas por minuto e expulsaria os `die` que o operador procura.

**Um bug pego pelo próprio teste:** `die` com exit 0 é `docker stop` — parada
limpa, pedida por alguém. O primeiro rascunho marcava como `warn`, o que
encheria a timeline de alarme falso toda vez que o operador desliga um serviço.
Alarme que sempre toca deixa de ser lido.

## B10 — prune, barreira e auditoria-antes (v12)

A barreira devolve **404, não 403**. Um 403 confirmaria que a rota está lá e que
só falta credencial. Cobre as 7 rotas que tocam o daemon; **não** cobre `ack` de
achado nem tarefas, que mutam o banco do próprio cockpit — barrá-las deixaria o
quadro de achados somente-leitura sem ganho de segurança.

A inversão do padrão para `0` e o pin `ENABLE_ACTIONS: "1"` no compose entraram
no mesmo commit, como registrado no §15. Um teste lê o compose e falha se o pin
sumir: é a bissecção do git em forma de asserção.

`projects.py` entrou na auditoria-antes junto com `containers.py`. Não estava
explícito no bloco, mas é ele que roda `docker compose up` com timeout de 60s —
o candidato mais provável a travar, e portanto o que mais precisa da linha
`running` órfã.

Prune só remove imagens dangling. Volume órfão guarda DADO e container parado há
8 dias pode ser religado na segunda; remover qualquer um dos dois precisa de um
pedido próprio que este bloco não oferece. O filtro `dangling=true` vai também
ao daemon — sem ele `/images/prune` remove toda imagem sem container usando,
inclusive as taggeadas que uma stack parada vai precisar ao subir.

## UI

Prune: dry-run → **lista** → confirmar. A lista da confirmação é a mesma do
dry-run; sem isso o padrão `dry_run=true` viraria só um clique a mais.

Timeline: histórico primeiro (para não nascer vazia), stream depois, com o
**mesmo filtro** nos dois. Coberto por teste que inspeciona as URLs pedidas em
cada escopo.

Métricas na subtela: toggle 24h/7d com cache da janela anterior — uma requisição
por troca. Render numa passada só; escrever por ponto provocaria 500 reflows num
container com histórico cheio.

## Estado do roteiro do doc 12

| Passo | Estado |
|---|---|
| Cenário API caindo → faixa crítica + achado | ✅ |
| Subtela do container: métricas em serra | ✅ (sparklines de `/history`) |
| Subtela: eventos die→start | ✅ (timeline filtrada por container) |
| Subtela: buscar `oom` nos logs | ⏳ **B5, Sprint 3** |
| Destravar → reiniciar → auditoria | ✅ |
| Chip Drift na régua | ⏳ B8, Sprint 5 (chip se cala sem fonte) |
| Personalizar | ✅ |

Falta o `buscar oom` para o roteiro executar inteiro. É o marco da Sprint 3.

---

# 17 · Sprint 4 — executada

Ordem entregue: **B9 → B6 → B7**, como pedido — B9 é independente e pequeno, e
o B7 consome o que o B6 produz.

## B9 — `/metrics` no formato exposition

Rota nova, `app/routers/metrics_prom.py`. Lê **só** o snapshot em memória
(`get_container_stats`, `get_container_inspects`, `get_last_sample`): um teste
afirma que o módulo não cita `proxy_get` nem `httpx`, porque com
`scrape_interval` de 15s cada scrape viraria 4 chamadas ao daemon por minuto,
por métrica.

Séries: `cockpit_container_cpu_pct`, `_mem_bytes`, `_mem_limit_bytes`,
`_estado`, `_unhealthy`, `cockpit_unhealthy_total`, `cockpit_containers_total`,
`cockpit_host_cpu_pct`, `cockpit_host_mem_pct`.

Três decisões com teste próprio, registradas no doc 00 (b, c): `estado=0` em vez
de a série sumir; sem healthcheck, sem série de saúde; labels só `name` e
`image`.

Auth no app e não herdada do ingress — decisão (a) do doc 00. Sem env: 503. Sem
credencial: 401 com `WWW-Authenticate` (é o 401 que faz o scraper mandar a
credencial; um 403 deixaria a integração muda).

Snapshot vazio no boot devolve 200 com `HELP`/`TYPE` válidos: o Prometheus faz o
primeiro scrape antes de o coletor rodar, e um 500 ali marcaria o alvo como
down.

## B6 — imagem desatualizada (v14)

`image_updates` (PK = `repo:tag` como aparece no `RepoTag`), job diário em
`app/updates.py`, rota `GET /api/updates` que lê **só do banco** — uma consulta
ao Hub por request estouraria o rate limit no primeiro polling da tela.

Quatro estados, nenhum deles erro: `atualizada`, `desatualizada`,
`desconhecido`, `pendente`. Decisões (d), (e) e (f) do doc 00.

`consultado_em` é coluna e não derivado: quando a fonte é uma API externa com
rate limit, a idade do dado **é** o dado. Um `desatualizada` de três dias atrás
não é a mesma afirmação que um de agora — e é por isso que o selo na tela leva a
hora.

Cache de 24h por imagem, mais curto que o intervalo do job de propósito: um
restart do cockpit não deve refazer as 20 consultas.

**UI:** selo `imagem desatualizada · verificado hh:mm` na lista de containers e
na subtela (linha da imagem). Só `desatualizada` ganha selo — um "em dia" em 20
linhas é ruído que informa zero e empurra o único selo que importa para fora do
campo de visão. O mapa vive em `app/static/js/updates.js`, compartilhado pelos
dois módulos e fora do `/api/overview`: o job roda uma vez por dia e o overview
é buscado a cada 15s.

## B7 — motor de notificações (v15)

Duas metades separadas por uma fila — decisão (l) do doc 00:

    detecção ──put_nowait──> fila ──> despachante ──> Telegram/Discord/Slack

Regras vivas: `container_die` (exit ≠ 0), `unhealthy`, `disk_high`,
`imagem_desatualizada`. `brute_force` reservada para o B11 — decisão (m).

Dedup persistido por `(regra, alvo)`, 30 min — decisão (i). Falha total não abre
a janela — decisão (j). Segredo nunca em log nem no banco — decisão (k).

**UI:** selo `notificado hh:mm · canal` no cartão do achado, juntando por
`(rule, target)` — a mesma chave do dedup no servidor, de modo que
`unhealthy` casa sozinho sem tabela de tradução no meio. Tentativa **registrada
e não entregue** não vira selo: ela existe no banco justamente para registrar
que o alerta não chegou.

## Testes

| Arquivo | Casos | O que cobre |
|---|---|---|
| `tests/test_metrics_prom.py` | 17 | auth, exposição, cardinalidade, degradação no boot |
| `tests/test_updates_v14.py` | 27 | digest, 429, cache 24h, migração v13→v14 populada |
| `tests/test_updates_ui.py` | 12 | selo da imagem, sob node, módulos ES reais |
| `tests/test_notify_v15.py` | 32 | regras, dedup, segredo, fila, migração v14→v15 populada |
| `tests/test_notificacoes_ui.py` | 9 | selo do achado, entrega parcial, sem entrega |

Suíte: **799 passando**.

## O que a Sprint 4 NÃO entregou

- **B8 (drift)** — `summary.drift.count` continua `null`, e o chip continua se
  calando. Sprint 5.
- **B11 (hardening)** — a regra de brute-force está reservada no motor, sem
  disparo. Sprint 5.
- **`certs_expiring`** — a decisão de fonte segue aberta para a Sprint 5.
- **Item (d) da 2b** — rodar o roteiro do doc 12 na VPS é trabalho de quem opera
  a VPS (bloco `4-runbook`), não deste pacote.

---

# 18 · Sprint 5 — executada. O plano B1–B11 fecha.

Ordem entregue: **B8 → certs → B11**.

## B8 — drift compose × runtime

`app/drift.py` + `GET /api/drift`. Sem migração: drift é derivado, não
histórico. Cache de 60s, lido pelo `summary` via `peek` e aquecido no
`aquecer_loop` — senão o chip só teria dado depois de alguém abrir o módulo, que
é o invariante 3 do doc 10 ao contrário.

Compara imagem/tag, portas publicadas e env declaradas, mais os containers fora
de qualquer projeto — que são drift por definição: estão rodando e não estão
escritos em lugar nenhum.

Decisões (a) a (d) do doc 00. O chip Drift, calado desde a 2a, percorre agora os
três estados do contrato.

## certs — a decisão da 2a, fechada

`app/certs.py` + `GET /api/certs`. Lê `notAfter` do X.509 dos lineages do
certbot, montados read-only. Cache de 1h: certificado tem validade em meses.

`certs_expiring` e `cert_window_days` saem do `null` **quando há mount** e
continuam `null` — com `stale_since["certs"]` — quando não há. Decisões (e) a
(h) do doc 00.

A regra `cert_expirando` entra no motor do B7 com dedup diário. O mount está
comentado no `docker-compose.yml` com as **duas** linhas necessárias (`live/` e
`archive/`) e o porquê: `live/` é feito de symlinks, e montar só ele entrega um
diretório de links quebrados.

## B11 — hardening

`app/hardening.py` (rate-limit), `app/backup.py` (backup diário),
`app/compressao.py` (gzip só em JSON/text-plain).

Rate-limit em `POST /api/session/unlock` e no 401 do `/metrics`: 5 falhas/min
por IP → 429 + `brute_force`. Decisões (i) a (n) do doc 00 — e a (i) é o bloco
inteiro: o IP contado é a origem real, não o do ingress.

Backup pela API de backup do SQLite, 7 cópias rotativas dentro do volume
`cockpit-data`. Decisões (o) e (p).

Gzip por content-type, camada mais externa. Decisão (q).

**O teste-sentinela do `brute_force` saiu no mesmo commit que liga a regra**, e
o que ficou no lugar afirma o oposto: que a regra tem disparo.

## Testes

| Arquivo | Casos |
|---|---|
| `tests/test_drift_b8.py` | 40 |
| `tests/test_certs_sprint5.py` | 23 |
| `tests/test_hardening_b11.py` | 32 |

Suíte: **894 passando** (era 799 ao fim da Sprint 4).

`PyYAML` e `cryptography` entram em `app/requirements.txt` **e** em
`tests/requirements-test.txt` — sem o segundo, os testes novos passariam na
máquina do dev e sumiriam como erro de import no CI.

## O plano, fechado

| Bloco | Sprint |
|---|---|
| B1 storage · B2 retenção · B4 segurança | 1 |
| B3 eventos · B10 prune | 2b |
| B5 busca em logs | 3 |
| B6 updates · B7 notificações · B9 métricas | 4 |
| B8 drift · B11 hardening · certs | 5 |

## O que fica fora do código

- **Item (d) da 2b** — rodar o roteiro do doc 12 na VPS, com os 15 containers
  reais. Continua honesto e aberto no doc 00, e vale dobrado agora que exercita
  drift e certificados recém-nascidos. É do operador (bloco `4-runbook`).
- **Acabamento visual dos 9 módulos delegados** — dívida deliberada registrada
  na 2a. É decisão de prioridade do dono do produto, não requisito técnico.
