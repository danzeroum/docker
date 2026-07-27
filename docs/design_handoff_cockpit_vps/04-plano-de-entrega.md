# 04 · Plano de entrega

Seis fases. Cada uma entrega tela funcionando com dado real — nenhuma fase termina com
placeholder na interface.

---

## F0 · Fundação (sem dado novo)

**Backend:** dividir `app.py` em routers; cache com TTL; máscara de segredos em
`Config.Env`; apertar CORS; teto no `tail` de logs.

**Frontend:** `store.js`, `data.js`, roteador por hash, rail de 9 destinos, topbar com perfil
e profundidade, `themes.css` com os 3 temas, migração da chave `cockpit-theme`.

**Aceite**
- As 9 telas existem e navegam; as ainda não implementadas mostram estado vazio honesto
  ("em construção — F3").
- Trocar tema e perfil persiste entre recargas.
- `GET /api/containers/{id}/json` não devolve mais nenhum segredo em texto claro.
- Suíte atual (24 testes) continua verde.

---

## F1 · Visão geral com dado real

**Backend:** `GET /api/overview` (fan-out concorrente + cache 5 s), `GET /api/stats/all`.

**Frontend:** stacks agrupadas por `com.docker.compose.project`, grade dos 15 containers,
faixa de vitais do host, 4 KPIs. Profundidade **Dado** funcionando de verdade (é a única que
não depende do motor de achados).

**Aceite**
- A Visão geral carrega em menos de 1,5 s com 15 containers.
- Nenhum nome de container, imagem ou domínio escrito à mão no JS.
- Uma stack derrubada aparece na cor certa em até 5 s.
- Profundidades Informação e Conhecimento mostram estado vazio explícito (chega em F2).

---

## F2 · Motor de achados

**Backend:** `services/findings.py` com as 13 regras de container/host,
`GET /api/findings`, `GET /api/findings/{id}`, `first_seen` persistido em SQLite.

**Frontend:** fila "Precisa da sua atenção", tela **Atenção agora** (cadeia, evidências,
ações, caixa de aprendizado), Dossiê do container, legendas de profundidade em toda a UI.

**Aceite**
- Parar um container de teste faz aparecer um achado em até 15 s, com cadeia e ação.
- As três profundidades mostram textos diferentes, todos vindos da API.
- `grep -r "reiniciar não resolve" app/static/js/` não retorna nada.
- Perfil Gestor mostra a variante `_plain`; perfil Dev mostra a evidência crua.

---

## F3 · Ingress & TLS

**Backend:** `services/nginx.py` com crossplane, `GET /api/ingress`; `services/certs.py`,
`GET /api/certificates`; as 11 regras de ingress no motor de achados.

**Frontend:** tela Ingress & TLS completa; coluna "exposição" do Dossiê passa a vir do
cruzamento com o ingress; Topologia usa hosts reais.

**Aceite**
- Os 13 hosts aparecem sem nenhuma lista fixa no código.
- Os 4 achados conhecidos são detectados sozinhos: `http_plain` (2 hosts),
  `docs_public`, `stream_timeout`, `default_cert_borrowed`.
- Cada achado mostra arquivo, linha e trecho reais.
- Renovar um certificado no host muda `days_left` em até 1 h, sem redeploy.
- Teste de regressão: o `nginx.conf` de hoje, como fixture, produz exatamente o catálogo
  esperado de achados.

---

## F4 · Histórico e capacidade

**Backend:** coletor de 60 s, SQLite com retenção, `GET /api/metrics/history` com projeção
por mínimos quadrados, `GET /api/capacity`.

**Frontend:** tela Capacidade (3 horizontes, projeção de disco, memória por stack, evolução,
postura), sparklines reais na tela de Logs.

**Aceite**
- A projeção mostra `r²`; abaixo de 0,7 ela se rotula "tendência instável" e omite a data.
- Com menos de 7 dias de coleta, a tela diz há quanto tempo está coletando em vez de projetar.
- A linha de "evolução" é calculada de `Created` e `not_before`, não digitada.
- Reiniciar o container do cockpit não perde histórico.

---

## F5 · Ações, tarefas e auditoria

**Backend:** `POST /api/session/unlock`, `X-Cockpit-Unlock` obrigatório nas mutações,
`audit`, `GET|POST|PATCH /api/tasks`, criação automática de tarefa a partir de achado.

**Frontend:** botão de destravar no rail, botões de ação habilitados só com sessão
destravada, board de tarefas, plantão mobile.

**Aceite**
- Sem destravar, nenhuma rota de mutação aceita chamada — testado por request direta, não só
  pela UI.
- Toda mutação aparece em `/api/audit` com usuário, alvo e resultado.
- Achado resolvido move a tarefa gerada para `done`; tarefa manual nunca é movida sozinha.
- Token expira em 30 min e a UI volta a travar sem recarregar.

---

## F6 · Tempo real e acabamento

**Backend:** `EVENTS: 1` no socket-proxy, stream de eventos em SSE, middleware de telemetria,
`GET /api/api-metrics`.

**Frontend:** polling de 5 s vira reconciliação de 30 s; tela Backend & API; paleta `⌘K`
ampliada para hosts e achados; estados de erro, vazio e permissão em todos os painéis.

**Aceite**
- Parar um container reflete na UI em menos de 2 s.
- A tela Backend & API mostra p95 medido, não estimado.
- Com o socket-proxy sem `EVENTS`, o painel explica o que habilitar em vez de ficar vazio.

---

## Riscos e decisões que precisam de dono

| # | Decisão | Opções | Recomendação |
|---|---|---|---|
| 1 | Acesso aos certificados | montar `/etc/letsencrypt:ro` no cockpit **ou** job no host escrevendo `certs.json` | job no host — o container nunca vê chave privada |
| 2 | `POST`/`DELETE` no socket-proxy | manter **ou** fechar e tornar o cockpit somente leitura | manter, **com** token de destravamento e auditoria (F5) |
| 3 | `EVENTS` e `SYSTEM` no proxy | habilitar **ou** continuar com polling | habilitar; ambos são leitura |
| 4 | Seletor de cenário | remover **ou** `?demo=1` | `?demo=1`, é ótimo para treinar plantonista |
| 5 | Padrão de alerta | faixa fixa, fila fixa, ou híbrido | híbrido: fila sempre, faixa só em `critical` |
| 6 | Custo mensal no executivo | `.env` **ou** remover o cartão | `.env`; o cartão é o que torna a tela útil para o cliente |
| 7 | Nome de negócio por domínio | `servicos.yml` **ou** rótulos Docker | `servicos.yml` — o gateway conhece domínios, não produtos |
| 8 | Backup | criar stack de backup **ou** aceitar o risco explicitamente | criar; hoje o achado `no_backup` é o mais grave da VPS |

---

## Definição de pronto (global)

1. Nenhum dado de exibição escrito à mão no frontend.
2. Todo texto de interpretação e recomendação vem de `/api/findings`.
3. Cada painel trata carregando, vazio, erro e sem permissão.
4. Nenhuma rota de mutação funciona sem sessão destravada, e todas ficam na auditoria.
5. Segredos mascarados no servidor.
6. Testes: fixtures reais de `nginx.conf` e `inspect.json`; o catálogo de achados é
   verificado por teste.
7. A Visão geral cabe em 1440 × 900 sem rolagem, com 15 containers e 12 stacks.
