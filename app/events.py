import asyncio
import json
import httpx
from routers._proxy import SOCKET_PROXY

# Cada cliente é (fila, filtro). O filtro vive no SERVIDOR: o cliente pede
# `?container=x` e nunca recebe evento de outro container — filtrar no navegador
# significaria mandar a timeline inteira do host por cada aba aberta.
_clients: list[tuple[asyncio.Queue, dict]] = []
_backoff = 1
_MAX_BACKOFF = 30


async def events_loop():
    """Consumer ÚNICO do stream do daemon.

    O mesmo laço alimenta o SSE e a persistência. Abrir um segundo `/events`
    para gravar dobraria a carga no daemon e criaria duas verdades: a timeline
    da tela e a do banco poderiam divergir por um evento perdido em um dos dois.
    """
    global _backoff
    while True:
        try:
            async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=None) as client:
                async with client.stream("GET", "/events") as resp:
                    if resp.status_code == 403:
                        _broadcast({"type": "error", "detail": "EVENTS nao habilitado no socket-proxy"})
                        await asyncio.sleep(300)
                        continue
                    _backoff = 1
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            event = json.loads(line) if line.startswith("{") else None
                        except json.JSONDecodeError:
                            event = None
                        if event:
                            gravado = await _persistir(event)
                            _avaliar_notificacao(gravado)
                            _broadcast({"type": "docker_event", "data": event, "row": gravado})
                            _invalidate_caches(event)
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.TimeoutException):
            _backoff = min(_backoff * 2, _MAX_BACKOFF)
            await asyncio.sleep(_backoff)


async def _persistir(event):
    """Grava o evento; falha de banco não pode calar o stream ao vivo.

    A ordem importa: persistir ANTES de transmitir. Se o processo morrer entre
    as duas coisas, o pior caso é um evento no banco que ninguém viu ao vivo —
    o inverso perderia o evento para sempre, que é o que a v11 existe para
    evitar.
    """
    try:
        from db import insert_event
        return await insert_event(event)
    except Exception:
        return None


def _avaliar_notificacao(linha):
    """Enfileira o que a regra do B7 reconhecer. Síncrono e sem I/O de rede.

    Roda aqui dentro do `async for` porque é aqui que o evento existe — mas só
    enfileira. A entrega é do despachante: um webhook lento não pode segurar o
    stream, senão a timeline inteira para para mandar uma mensagem de chat.
    """
    if not linha:
        return
    try:
        from notify import avaliar_evento
        avaliar_evento(linha)
    except Exception:
        # Notificação que falha não pode calar o stream, pela mesma razão que
        # a persistência não pode.
        pass


def _invalidate_caches(event):
    etype = event.get("Type", "")
    action = event.get("Action", "")
    if etype == "container" and action in ("start", "stop", "die", "restart", "oom"):
        from cache import invalidate
        invalidate("overview")
        invalidate("containers_list")
        invalidate("stats_all")
        _broadcast({"type": "invalidate", "targets": ["overview", "containers_list", "stats_all"]})


def _casa(msg, filtro) -> bool:
    """Decide se uma mensagem passa pelo filtro de um cliente.

    `invalidate` e `error` passam SEMPRE: são plano de controle, não eventos. Um
    cliente que pediu só um container ainda precisa saber que o cache virou,
    senão a tela dele congela sem motivo aparente.
    """
    if not filtro:
        return True
    if msg.get("type") != "docker_event":
        return True
    linha = msg.get("row")
    if not isinstance(linha, dict):
        # Evento que não virou linha (ação fora da lista) não interessa a quem
        # pediu filtro — quem quer tudo não tem filtro e já saiu acima.
        return False
    for chave, campo in (("container", "actor_name"), ("stack", "stack"),
                         ("action", "action"), ("severity", "severity")):
        esperado = filtro.get(chave)
        if esperado and linha.get(campo) != esperado:
            return False
    return True


def _broadcast(msg):
    mortos = []
    for par in _clients:
        fila, filtro = par
        if not _casa(msg, filtro):
            continue
        try:
            fila.put_nowait(msg)
        except asyncio.QueueFull:
            mortos.append(par)
    for par in mortos:
        if par in _clients:
            _clients.remove(par)


async def subscribe(filtro: dict = None):
    q = asyncio.Queue(maxsize=256)
    _clients.append((q, filtro or {}))
    return q


def unsubscribe(q):
    for par in list(_clients):
        if par[0] is q:
            _clients.remove(par)
