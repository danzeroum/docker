# 11 · B1–B11 × interface — o que agrega na UI e o que é só backend

Análise da compilação "O que fica para agregar" contra o modelo do Cockpit Vivo (doc 10:
módulo = read model por escopo). Veredito curto: **8 dos 11 blocos aparecem na tela**; o
sistema de módulos absorve todos sem mudar o núcleo — cada um vira módulo novo ou enriquece
um existente. B9 e B11 são invisíveis; B7 quase.

## Mapa bloco → UI

| Bloco | Agrega na UI? | Onde entra no Cockpit Vivo |
|---|---|---|
| B1 Storage/órfãos | **Sim — módulo novo** | Módulo "Armazenamento" (escopo host): "X GB recuperáveis" + lista de órfãos; chip na régua; alimenta a projeção do módulo Capacidade. Com B10: botão "prune (dry-run)" atrás da trava |
| B2 Histórico de stats | **Sim — destrava o existente** | É exatamente o backend que faltava para as sparklines do módulo Métricas nos escopos container/stack (pendência do doc 10 §3). Nenhum módulo novo |
| B3 Eventos SSE | **Sim — módulo novo** | Módulo "Eventos" nos 3 escopos (timeline die→start ao vivo); no cockpit do container substitui adivinhação por sequência real. Chip: idade do último evento |
| B4 Health + score segurança | **Sim — enriquece 3 pontos** | Coluna/badge na lista de containers; linha "Score de segurança" no módulo Configuração da subtela (com violações nomeadas); chip host "Segurança n/15". Vira achado quando crítico |
| B5 Logs FTS + follow | **Sim — upgrade do módulo Logs** | Campo de busca com highlight + follow real via SSE no módulo Logs (stack/container); busca global no host |
| B6 Imagem desatualizada | **Sim — enriquece** | Badge "desatualizada + data" na linha 2 (profundidade A) e no módulo Configuração; chip host "Updates: n". `consultado_em` atende a regra de idade do dado (doc 10 §4) |
| B7 Notificações | Quase só dev | UI mínima: marca "notificado às hh:mm" no achado + tela de canais/regras (fora do cockpit, em configurações). O motor em si é invisível |
| B8 Drift detection | **Sim — módulo novo** | Módulo "Drift" no cockpit do projeto (esperado vs atual por serviço); lista "fora de projeto" no host — casa com o aviso existente de stacks paradas |
| B9 /metrics Prometheus | **Não — só dev** | Nada na tela (no máximo uma linha em configurações/integrações) |
| B10 Ações opt-in | **Sim — fecha o ciclo da trava** | Botões restart/stop na subtela do container e prune no Armazenamento — todos atrás do destravamento já desenhado (barra lateral). A auditoria deles já tem módulo |
| B11 Hardening | Não — só dev | Exceção: alerta de brute-force chega como achado crítico (via B7), na faixa/fila existentes |

## Leitura de arquitetura (para o dev validar junto)

- A compilação **confirma o registro de módulos** do doc 10: B1, B3 e B8 entram como
  `{id, escopos, chip, render}` novos — zero `if` no núcleo. B2/B4/B5/B6 só preenchem read
  models que a UI já declara.
- **Ordem de valor para a interface** (diferente da ordem de implementação dos sprints):
  B2 primeiro (sparklines reais), depois B4 (score na subtela), B3 (eventos), B1+B10
  (armazenamento + ações), B5, B6, B8.
- Régua/summary (doc 09 §B): B1, B4 e B6 acrescentam 3 chaves ao `summary`
  (`storage.reclaimable`, `security.min_score`, `updates.outdated`) — mesma economia de
  1 chamada.
- Invariantes preservados: nada disso toca a régua do kernel nem a faixa crítica; ações do
  B10 obedecem a trava fail-closed já desenhada.

## Instrução para o desenvolvedor (integração UI)

```xml
<lang>Vanilla JS ES modules (app/static/js) + FastAPI Python 3.11</lang>
<task>Integrar B1–B10 ao registro de módulos do Cockpit Vivo (doc 10): módulos novos Armazenamento (host), Eventos (3 escopos) e Drift (stack); enriquecer Métricas (B2), Configuração/lista (B4, B6) e Logs (B5); ações B10 atrás do unlock existente.</task>
<context>Contrato do módulo: {id, nome, escopos, span, chip(escopo), render(escopo, dados)} — doc 10 §1. Endpoints novos: /api/storage, /api/containers/{id}/history, /api/events/stream, /api/security, /api/logs/search, /api/updates. summary ganha storage.reclaimable, security.min_score, updates.outdated (doc 09 §B).</context>
<rules>
- Módulo novo = arquivo novo no registro; proibido if por módulo no núcleo.
- Chips continuam lendo só o summary; módulo oculto = zero fetch.
- Botões do B10 só renderizam com ENABLE_ACTIONS=1 e sessão destravada; toda ação confirma inline (sem modal de sistema).
- SSE (B3, B5) com heartbeat 15s e reconexão — o ingress corta stream ocioso.
- Saída: apenas os blocos de código.
</rules>
<aceite>
- Ocultar qualquer módulo novo mantém o chip vivo na régua.
- Score < 60 em um container gera badge na lista e linha em Configuração com violações nomeadas.
- Timeline de eventos mostra die→start de um restart em <2s nos 3 escopos.
- Sem ENABLE_ACTIONS: nenhum botão de ação existe no DOM (não é display:none).
</aceite>
<testes>
- summary sem as chaves novas (backend antigo) → chips omitidos, console limpo.
- /api/storage 503 → módulo mostra indisponibilidade com idade do último dado, não zero.
- Busca FTS com operadores ("erro NEAR/2") → tratada como literal na UI também (encode).
</testes>
```

Registro: esta análise foi feita sobre a compilação B1–B11 (validada pelo autor contra a
arquitetura FastAPI + socket-proxy do repo). Os prompts B1–B11 originais seguem com o dev;
este doc cobre apenas a face de interface.
