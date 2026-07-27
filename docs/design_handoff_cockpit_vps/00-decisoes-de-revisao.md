# 00 · Registro de decisões de revisão

O que foi decidido durante a implementação, com o motivo. Leia antes de discordar de algo nos
outros documentos — vários pontos aqui **corrigem** a primeira versão deles.

## Estado

| Fase | PR | Situação |
|---|---|---|
| F0a — backend | [#3](https://github.com/danzeroum/docker/pull/3) | concluída |
| F0b — frontend | [#4](https://github.com/danzeroum/docker/pull/4) | em revisão |
| F1 → F6 | — | não iniciadas |

---

## Correções à primeira versão do handoff

**1. CORS não pode derivar a origem da requisição.** `CORSMiddleware` é configurado no
startup; não existe `request` naquele ponto. E como o frontend é servido pelo próprio FastAPI,
é mesma origem: `allow_origins = ALLOWED_ORIGINS or []`.

**2. `psutil` estava travando o event loop.** `cpu_percent(interval=0.1)` dentro de rota async
custa 100 ms de loop parado por requisição. Resolvido com sampler em background usando
`asyncio.to_thread`, mais uma amostra síncrona antes do `yield` do lifespan — mover a chamada
para dentro de uma task **não** resolve sozinho, porque a task roda no mesmo loop.

**3. Nomes de token: os do repositório, não os do protótipo.** Importar `--sf`/`--txd`
obrigaria a reescrever os 12,8 KB de `components.css`. Mapeamento em `03-frontend.md`.

**4. Service worker precisava de mais que um bump.** Nome de cache gerado em runtime não força
reinstalação (o navegador compara bytes do arquivo) e ainda acumula caches órfãos. Solução:
versão estática, limpeza no `activate`, network-first, `skipWaiting()` + `clients.claim()`.

**5. Cache exige single-flight.** Sem lock por chave, 20 clientes no instante do vencimento
geram 20 fan-outs — exatamente o pico que o cache deveria evitar. O lock mora dentro da
entrada, para sumir junto na evicção LRU.

**6. Máscara de segredos tem quatro portas, não uma.** As duas rotas de inspect
(`/{id}` e `/{id}/json`), mais `Cmd`, `Entrypoint` e `Labels`. Em valores com forma de URI,
mascare só `user:senha@` e preserve host e path — senão você perde o diagnóstico de "está
apontando para o banco errado". Teste negativo obrigatório: `SITE_URL` e `LOG_LEVEL` **não**
podem ser mascarados; sobre-máscara é regressão que ninguém reporta.

**7. "24 testes" no critério da F0 era dado falso.** Veio da tela simulada do protótipo, não
do repositório. Use `pytest --collect-only -q`.

**8. São 11 telas, não 9.** Faltavam `#/tarefas` e o plantão mobile.

**9. Polling: um loop compartilhado que pausa com a aba oculta.** Não um `setInterval` por
tela.

---

## Decisões de arquitetura tomadas

**`EXEC` no socket-proxy: não.** Para ler o nginx, o arquivo é montado `:ro`. O `nginx.conf`
atual só tem um `include` (`mime.types`), então ler o arquivo dá o mesmo resultado que
`nginx -T`. Guarda a implementar: se o parser encontrar `include` fora de `mime.types`, emitir
achado "parse pode estar incompleto".

**`EVENTS: 1` e `SYSTEM: 1` habilitados já na F0a**, mesmo sem uso até F4/F6. São permissões
de leitura, e recriar o socket-proxy derruba o cockpit junto (`depends_on: service_healthy`) —
não vale uma segunda janela de manutenção.

**Montagem do ingress: `/opt/btv/ingress/nginx`, nunca o diretório pai.** O pai contém o
`.htpasswd` do gateway e do squad.

**Certificados: job no host escrevendo metadados**, em vez de montar `/etc/letsencrypt` no
container. O cockpit nunca precisa de acesso de leitura a chave privada.

**Terminal web: permanece desligado, e `terminal.js` foi removido do frontend.** Decisão
consciente — com `POST` habilitado no socket-proxy, `exec` é o caminho mais curto entre um
cookie vazado e a VPS inteira. Se alguém reencontrar o endpoint atrás do `ENABLE_TERMINAL`,
isto aqui é a explicação.

**Padrão de alerta: híbrido.** Fila priorizada sempre visível; a faixa no topo só aparece
quando existe achado `critical`. O layout só se mexe quando é grave de verdade.

**Seletor de cenário: atrás de `?demo=1`.** Sai do caminho em produção e continua útil para
treinar plantonista.

---

---

## Pendências para fases seguintes

**Autenticação entre containers na rede interna.** O ingress nginx protege `/api/*` contra
acesso externo, mas qualquer container em `btv-prod-net` — são doze — alcança
`http://docker-cockpit:8000/api/containers/{id}/json` sem autenticação. No futuro, também
`POST /stop`. O token de destravamento (F5) cobre operações de escrita; cabe avaliar se todas
as rotas `/api/*` devem exigir um cabeçalho compartilhado injetado pelo ingress. (registrado
em F0b, carry para F5)

---

## Mudanças quebradas de contrato

| Quando | O quê | Impacto |
|---|---|---|
| F0a (PR #3) | `/api/system`: `memory.used_gb/total_gb/free_gb` → `used/total/free` em bytes; mesmo padrão em `disks[]` | único consumidor (`system.js`) corrigido no mesmo PR. Script ou alerta externo batendo nesse endpoint quebra em silêncio |
| F0b (PR #4) | frontend migrado para módulos ES; `helpers.js`, `state.js`, `api.js`, `containers.js`, `system.js`, `logs.js`, `stats.js`, `terminal.js` removidos | qualquer patch local sobre esses arquivos precisa ser reescrito |

---

## Bug preexistente encontrado na revisão

`system.js` chamava `fmtBytes(sys.memory.used)` enquanto a API devolvia `used_gb` — os
subtítulos de memória e disco renderizavam "—" desde sempre. Corrigido junto da padronização
de unidades da F0a.
