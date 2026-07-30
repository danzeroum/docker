"""Barreira de ações de escrita (B10).

`ENABLE_ACTIONS=0` faz as rotas de mutação **não serem registradas** — 404, não
403. A diferença importa: 403 confirma que a rota existe e que só falta
credencial; 404 não confirma nada. Fail-closed de verdade é a rota não existir.

Cobre as 7 rotas que tocam o daemon:
  - container: start, stop, restart, DELETE (as 4 da F5);
  - stack: start, stop (as 2 do gerenciador de projetos);
  - prune.

**Não** cobre `ack` de achado, tarefas nem `unlock`. Essas mutam o banco do
próprio cockpit, não a infraestrutura: barrá-las deixaria o quadro de achados
somente-leitura sem ganho nenhum de segurança, já que nenhuma delas alcança o
daemon.

O padrão é `0` desde a Sprint 2b: instalação nova nasce sem superfície de
escrita, e ligar é ato deliberado. O compose de produção fixa `1` explicitamente
no MESMO commit que inverteu este padrão — separar as duas coisas derrubaria o
fluxo unlock→reiniciar entre um deploy e outro.
"""

import os


def habilitadas() -> bool:
    return (os.getenv("ENABLE_ACTIONS", "0") or "").strip().lower() in ("1", "true", "yes", "on")
