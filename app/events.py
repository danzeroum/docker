import asyncio
import json
import httpx
from routers._proxy import SOCKET_PROXY

_clients: list[asyncio.Queue] = []
_backoff = 1
_MAX_BACKOFF = 30


async def events_loop():
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
                            _broadcast({"type": "docker_event", "data": event})
                            _invalidate_caches(event)
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.TimeoutException):
            _backoff = min(_backoff * 2, _MAX_BACKOFF)
            await asyncio.sleep(_backoff)


def _invalidate_caches(event):
    etype = event.get("Type", "")
    action = event.get("Action", "")
    if etype == "container" and action in ("start", "stop", "die", "restart", "oom"):
        from cache import invalidate
        invalidate("overview")
        invalidate("containers_list")
        invalidate("stats_all")
        _broadcast({"type": "invalidate", "targets": ["overview", "containers_list", "stats_all"]})


def _broadcast(msg):
    dead = []
    for q in _clients:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _clients.remove(q)


async def subscribe():
    q = asyncio.Queue(maxsize=256)
    _clients.append(q)
    return q


def unsubscribe(q):
    if q in _clients:
        _clients.remove(q)
