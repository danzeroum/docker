# Handoff completo — Cockpit Vivo + blocos B1–B11

Pacote fechado em 2026-07-30. Substitui o zip anterior ("Cockpit Vivo"): inclui tudo dele
mais o protótipo completo com a face de interface dos blocos B1–B11 e os docs 11/12/anexo.

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
| `docs/anexo-blocos-b1-b11` | Resumo dos prompts de backend do autor, com as decisões que a UI assume |
| `github.md` | Vínculo com danzeroum/docker e histórico |

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

## Status (2026-07-30)

Sprint 2a merged (kernel + summary + capabilities); 2b autorizada (v11 eventos, v12
audit-antes, UI armazenamento/eventos/subtela). Pós-2b o roteiro do doc 12 executa contra
dados reais, exceto a busca `oom` (B5, Sprint 3). `certs_expiring`: backlog de fonte.
