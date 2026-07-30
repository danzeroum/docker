import asyncio
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from db import get_events
from events import subscribe, unsubscribe

router = APIRouter(prefix="/api/events", tags=["events"])

# Heartbeat mais curto que os 60s de `proxy_read_timeout` default do nginx. O
# bloco do cockpit já sobe com 3600s, mas o heartbeat é a garantia que não
# depende de o ingress estar configurado certo — e o próprio motor de achados
# tem uma regra (`stream_timeout`) para quando ele não está.
HEARTBEAT_S = 15


def _filtro(container, stack, action, severity) -> dict:
    return {k: v for k, v in (
        ("container", container), ("stack", stack),
        ("action", action), ("severity", severity),
    ) if v}


@router.get("")
async def listar_eventos(
    container: str = Query(None, description="nome do container"),
    stack: str = Query(None, description="projeto compose"),
    action: str = Query(None),
    severity: str = Query(None, pattern="^(info|warn|critical)$"),
    limit: int = Query(100, ge=1, le=500),
    before_id: int = Query(None, ge=1, description="paginação keyset: id do último item da página anterior"),
):
    """Histórico paginado, com os filtros aplicados no servidor."""
    linhas = await get_events(
        container=container, stack=stack, action=action,
        severity=severity, limit=limit, before_id=before_id,
    )
    # `next_before_id` sai no payload para o cliente não precisar saber que a
    # paginação é keyset — ele só devolve o valor que recebeu.
    proximo = linhas[-1]["id"] if len(linhas) == limit else None
    return {
        "events": linhas,
        "count": len(linhas),
        "next_before_id": proximo,
        "filters": _filtro(container, stack, action, severity),
    }


@router.get("/stream")
async def event_stream(
    request: Request,
    container: str = Query(None),
    stack: str = Query(None),
    action: str = Query(None),
    severity: str = Query(None, pattern="^(info|warn|critical)$"),
):
    filtro = _filtro(container, stack, action, severity)
    q = await subscribe(filtro)

    async def generate():
        try:
            # A primeira mensagem declara o filtro em vigor. Sem ela, um cliente
            # que recebe silêncio não distingue "nada aconteceu" de "meu filtro
            # não casa com nada" — e o segundo é erro de quem chamou.
            yield f"data: {json.dumps({'type': 'ready', 'filters': filtro})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        # X-Accel-Buffering: o stream de logs já setava, este não — e é o mesmo
        # nginx na frente dos dois. Sem o header o SSE chega em blocos.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
