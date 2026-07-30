# 12 · Protótipo completo — roteiro de validação B1–B11 na tela

Protótipo: `Cockpit Vivo Completo.dc.html`. É o Cockpit Vivo (doc 10) + a face de interface
dos blocos B1–B11 (doc 11). Tudo continua sendo módulo do mesmo registro; nada tocou a
régua do kernel nem a faixa crítica.

## O que conferir, bloco a bloco

| Bloco | Onde ver no protótipo |
|---|---|
| B1 Armazenamento | Módulo "Armazenamento" no host: 9.8 GB recuperáveis + 4 órfãos tipados; `prune dry-run` livre; `prune real` cinza até destravar a sessão (barra lateral). No cenário Disco cheio, nota separando prune da rotação de log |
| B2 Histórico | Módulo "Métricas" (sub "raw 24h · agregado 30d") — sparkline por escopo: host, soma da stack, série do container na subtela |
| B3 Eventos | Módulo "Eventos" nos 3 escopos. Cenário API caindo: sequência die→start→die do criptotrade-app com exit 137; filtrada por stack e por container |
| B4 Score de segurança | Coluna `S{n}` colorida na lista e nos cartões (tooltip lista as violações); linha "Score segurança" na Configuração da subtela; score mínimo no chip e no subtítulo do módulo Containers. Pior caso: docker-cockpit-proxy S70 (docker.sock, por função) |
| B5 Logs FTS + follow | Módulo "Logs" (stack e container): campo de busca com highlight (digite `502` ou `oom` no cenário API caindo) + selo ● follow |
| B6 Updates | Chip kernel-side "Updates 3"; linha "Atualização" na Configuração (com `consultado há 3h`); na profundidade A a linha 2 mostra a versão disponível (prompte, familia-web, giva-api) |
| B7 Notificações | Selo "notificado 04:13 · telegram" no achado crítico (API caindo e Disco cheio) |
| B8 Drift | Módulo "Drift": no host (oculto por padrão — chip "1 · 1 fora" na régua, clique para exibir) lista familia-web (image) + redis-teste fora de projeto; no cockpit do projeto familia-web mostra esperado × atual |
| B10 Ações opt-in | Subtela do container: botões reiniciar/parar — cinza com dica quando travado; destravado → confirmação inline → entrada "agora · dz" na Auditoria. Prune real idem |
| B9 / B11 | Sem face de UI (por design — doc 11). Brute-force chegaria como achado via B7 |

## Roteiro de 2 minutos

1. Cenário **API caindo** → faixa crítica + achado com selo "notificado".
2. Clique em `criptotrade-app` → subtela: métricas em serra, eventos die→start, logs com
   `oom` (busque), config com limite 512 MB.
3. Destrave a sessão na barra lateral → botões reiniciar/parar acendem → confirme →
   auditoria registra "agora · dz".
4. Volte (Esc) → chip "Drift 1 · 1 fora" na régua → clique → módulo aparece.
5. Personalizar → arraste módulos, aplique presets (Executivo esconde 4 módulos — chips
   continuam vivos), restaurar padrão.

## Contrato de dados (sem mock na implementação)

Fontes por módulo: docs 09 §C e 11 (§ mapa). Novos endpoints exigidos: `/api/storage` (B1),
`/api/containers/{id}/history` (B2), `/api/events/stream` (B3), `/api/security` (B4),
`/api/logs/search` (B5), `/api/updates` (B6). `summary` ganha `storage.reclaimable`,
`security.min_score`, `updates.outdated`. Os cenários de demo deste protótipo morrem na
implementação (regra do doc 01: grep não encontra dado de negócio no JS).

Prompt de integração UI: doc 11. Prompts de backend B1–B11: anexo.
