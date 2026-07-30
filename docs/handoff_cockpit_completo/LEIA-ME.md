# Handoff completo — Cockpit Vivo + blocos B1–B11

Pacote fechado em 2026-07-30. Substitui o zip anterior ("Cockpit Vivo"): inclui tudo dele
mais o protótipo completo com a face de interface dos blocos B1–B11 e os docs 11/12/anexo.

> **A verdade é o repositório, não o zip.** Este pacote já ficou defasado uma vez depois de
> ser distribuído por arquivo: o zip externo continuou circulando enquanto os docs 00 e 14
> mudavam a cada sprint. Se você recebeu isto como `.zip`, confira contra
> `danzeroum/docker`, em `docs/handoff_cockpit_completo/` — em caso de divergência, o repo
> vale e o zip não.

## Protótipos (abrem direto no navegador, Chrome/Edge desktop)

| Arquivo | O que é |
|---|---|
| `Cockpit Vivo Completo.dc.html` | **Versão final para validar** — Cockpit Vivo + B1–B11: Armazenamento (prune), Eventos, Drift, score de segurança, busca em logs, updates, ações opt-in atrás da trava |
| `Cockpit Vivo.dc.html` | Base aprovada (doc 10) — módulos por escopo, drag, presets, subtela central |
| `Cockpit Claro Modular.dc.html` | Primeira iteração (tema claro + módulos na Visão geral) |

`support.js` precisa estar na mesma pasta (já está).

## Documentos

| Doc | Conteúdo |
|---|---|
| `docs/00` | Registro de decisões das fases anteriores |
| `docs/01` | Contrato de dados — regra "zero mock" campo a campo |
| `docs/08` | Tema claro-minimal (tokens) + validação de densidade |
| `docs/09` | Diff frontend/backend + mapa dado→endpoint + plano de 2 PRs |
| `docs/10` | Modelo DDD da interface + validações UI/frontend + prompt do dev |
| `docs/11` | B1–B11 × interface: o que vira módulo, o que é só backend + prompt de integração UI |
| `docs/12` | **Roteiro de validação do protótipo completo** (comece por aqui) |
| `docs/13` | Blocos agregados (compilação final B1–B11) |
| `docs/14` | **Plano consolidado** — §15 a §19, uma seção por sprint executada; §19 fecha o plano |
| `docs/anexo-blocos-b1-b11` | Resumo dos prompts de backend do autor, com as decisões que a UI assume |
| `github.md` | Vínculo com danzeroum/docker e histórico |

Para reconstruir o ciclo inteiro — o que foi feito, por quem, onde e por quê — bastam os
**docs 00 e 14**. O 00 tem as decisões datadas e assinadas de cada sprint; o 14 tem o que
cada uma executou.

## Roteiro rápido (2 min) — docs/12

Cenário "API caindo" → clicar em `criptotrade-app` (subtela) → buscar `oom` nos logs →
destravar sessão → reiniciar (confirmação → auditoria) → Esc → chip "Drift" na régua →
Personalizar (arrastar, presets, restaurar).

## Regras que valem para qualquer implementação

1. Zero mock: todo campo tem endpoint mapeado (docs 09 §C, 11, 12). Os cenários de demo
   morrem na implementação.
2. Kernel é invariante: vitais + faixa crítica visíveis em qualquer cockpit.
3. Módulo oculto mantém chip vivo na régua (via `summary`).
4. Ações de escrita: fail-closed, atrás do unlock, auditadas ANTES de executar (B10);
   sem `capabilities.actions_enabled` os botões nem existem no DOM.
5. Prune: a confirmação sempre parte da lista do dry-run — o protótipo exige dry-run
   antes de habilitar o prune real.
6. Ausência de dado nunca vira afirmação: `null` = sem fonte, `0` = a fonte rodou e diz que
   está limpo, `N` = a fonte acusa. A diferença entre os dois primeiros é alguém ser
   acordado ou não.
7. Toda migração passa por teste sobre banco POPULADO — a v3 perdeu `first_seen` em
   produção, e a regra nasceu daí.

## Status (2026-07-30) — plano B1–B11 CONCLUÍDO

Os onze blocos estão em `main`, entregues em 6 sprints e 6 PRs (#25 a #30). **894 testes**,
`SCHEMA_VERSION = 15`, migrações v10 a v15 todas com teste sobre banco populado.

A tabela sprint→blocos→PR está no **doc 00, seção "Fechamento do plano B1–B11"** — e é por
número de PR que se recupera cada diff, porque todo merge foi squash e os commits
individuais das sprints não existem mais no remoto.

O que mudou desde a última versão deste arquivo:

- **Roteiro do doc 12 executa por inteiro no código**, verificado por teste. Os dois passos
  que faltavam fecharam: a busca `oom` no B5 (Sprint 3) e o **chip Drift** no B8
  (Sprint 5), que saiu de "ausência esperada" para dado real.
- **`certs_expiring` deixou de ser backlog de fonte.** A decisão fechou nos dois ramos: com
  o diretório de certificados montado read-only, a chave ganha fonte; sem ele, continua
  `null` — mas agora com `stale_since` e um motivo na rota, e `null` documentado como
  "não estou olhando", nunca "nenhum certificado está para vencer".
- **Chip Drift com fonte**, percorrendo os três estados do contrato: `null` sem fonte,
  `0` como afirmação de que está limpo, `N` como achado.

**Pendente, e não é do dev:** executar o roteiro do doc 12 **na VPS**, com os 15 containers
reais (item (d) do doc 00, dono: operador). Vale mais agora do que quando foi aberto —
drift e certificados são os dois blocos cujo comportamento depende do que existe no disco
daquele host, e nenhuma fixture prova isso.

**Em aberto por decisão de prioridade:** o acabamento visual de 9 módulos que herdaram o
corpo das telas de página cheia. Dado real desde a 2a; o que falta é forma. Dono: dono do
produto.
