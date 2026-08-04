import asyncio
import json
import re
from fastapi import APIRouter, HTTPException, Query, Response, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.responses import StreamingResponse
import httpx

from routers._proxy import proxy_get, proxy_post, proxy_delete, SOCKET_PROXY, ENABLE_TERMINAL
from masking import mask_inspect
from cache import cached_or_fetch
from stats_util import calc_cpu_percent, health_status
from auth import require_unlock
from db import (
    audit_iniciar, audit_concluir, get_container_history, search_logs,
    MAX_HISTORY_POINTS, BUSCA_MINIMA, MARCA_INICIO, MARCA_FIM,
)
from actions import habilitadas as acoes_habilitadas
from sampler import get_container_inspects

router = APIRouter(prefix="/api/containers", tags=["containers"])
# A busca e por HOST, nao por container: `/api/logs/search` responde sobre o
# indice inteiro e filtra por container via query param.
busca_router = APIRouter(prefix="/api/logs", tags=["logs"])


# ---------------------------------------------------------------------------
# Demux
# ---------------------------------------------------------------------------

def _demux_frame(data: bytes):
    idx = 0
    while idx + 8 <= len(data):
        frame_size = int.from_bytes(data[idx + 4 : idx + 8], "big")
        payload = data[idx + 8 : idx + 8 + frame_size]
        stream_id = data[idx]
        yield stream_id, payload.decode("utf-8", errors="replace")
        idx += 8 + frame_size


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

# Esta funcao era a UNICA implementacao correta da leitura de State.Health, e por ser
# privada deste modulo os outros consumidores reescreveram a sua — dois com
# `.get("Health", {})`, que quebra quando a chave existe valendo null. Agora a versao
# canonica vive em stats_util (ao lado de calc_cpu_percent) e este nome permanece como
# alias, para nao mexer nas chamadas existentes.
_health_do_inspect = health_status


@router.get("")
async def list_containers():
    data, _ = await cached_or_fetch("containers_list", ttl=2.0, factory=lambda: proxy_get("/containers/json?all=1"))
    if not isinstance(data, list):
        return data
    # O inspect ja foi coletado pelo sampler; ler daqui deixa a rota com zero
    # chamada extra ao daemon. Copia rasa por item porque `data` e o objeto
    # cacheado sob "containers_list", compartilhado com /api/overview e
    # /api/stats/all — mutar no lugar vazaria o campo para os dois.
    inspects = get_container_inspects()
    if not inspects:
        return data
    enriquecidos = []
    for c in data:
        if not isinstance(c, dict):
            enriquecidos.append(c)
            continue
        enriquecidos.append({**c, "Health": _health_do_inspect(inspects.get(c.get("Id")))})
    return enriquecidos


# ---------------------------------------------------------------------------
# Inspect (ambas as rotas aplicam mascara de segredos)
# ---------------------------------------------------------------------------

async def _do_inspect(container_id: str):
    data = await proxy_get(f"/containers/{container_id}/json")
    return mask_inspect(data)


@router.get("/{container_id}")
async def inspect_container(container_id: str):
    return await _do_inspect(container_id)


@router.get("/{container_id}/json")
async def inspect_container_json(container_id: str):
    return await _do_inspect(container_id)


# ---------------------------------------------------------------------------
# Logs (texto)
# ---------------------------------------------------------------------------

@router.get("/{container_id}/logs")
async def container_logs(container_id: str, tail: int = 500):
    tail = min(tail, 5000)
    async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=20) as client:
        r = await client.get(
            f"/containers/{container_id}/logs",
            params={"stdout": 1, "stderr": 1, "tail": tail},
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        raw = r.content
        lines = []
        idx = 0
        while idx + 8 <= len(raw):
            frame_size = int.from_bytes(raw[idx + 4 : idx + 8], "big")
            payload = raw[idx + 8 : idx + 8 + frame_size]
            lines.append(payload.decode("utf-8", errors="replace"))
            idx += 8 + frame_size
        text = "".join(lines) if lines else raw.decode("utf-8", errors="replace")
        return Response(content=text, media_type="text/plain")


# ---------------------------------------------------------------------------
# Busca full-text (B5) — o follow continua direto do daemon, logo abaixo
# ---------------------------------------------------------------------------

@busca_router.get("/search")
async def buscar_logs(
    q: str = Query(..., description="termo; operadores FTS viram literal"),
    container: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Trechos com o termo destacado, do indice FTS5.

    Termo com menos de 3 caracteres e 400: num indice de milhoes de linhas ele
    devolve tudo e nao responde nada, e o custo cai no SQLite.
    """
    if len((q or "").strip()) < BUSCA_MINIMA:
        raise HTTPException(
            status_code=400,
            detail=f"termo precisa de pelo menos {BUSCA_MINIMA} caracteres",
        )
    linhas, expressao = await search_logs(q, container=container, limit=limit, offset=offset)
    return {
        "results": linhas,
        "count": len(linhas),
        # A expressao efetivamente usada volta no payload: o operador digitou
        # `erro NEAR/2 falha` e precisa ver que virou busca por tres palavras
        # literais, em vez de achar que o NEAR funcionou e o log e que nao tem.
        "query": q,
        "expression": expressao,
        "marks": {"start": MARCA_INICIO, "end": MARCA_FIM},
        "next_offset": (offset + len(linhas)) if len(linhas) == limit else None,
    }


# ---------------------------------------------------------------------------
# Logs streaming (SSE)
# ---------------------------------------------------------------------------

async def _log_stream_proxy(container_id: str, tail: int):
    params = {"stdout": 1, "stderr": 1, "follow": 1, "tail": tail}
    async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=None) as client:
        async with client.stream("GET", f"/containers/{container_id}/logs", params=params) as resp:
            if resp.status_code >= 400:
                yield f"event: error\ndata: {resp.status_code}\n\n"
                return
            buf = b""
            async for chunk in resp.aiter_bytes():
                buf += chunk
                while True:
                    if len(buf) < 8:
                        break
                    frame_size = int.from_bytes(buf[4:8], "big")
                    if len(buf) < 8 + frame_size:
                        break
                    frame = buf[: 8 + frame_size]
                    buf = buf[8 + frame_size :]
                    for sid, text in _demux_frame(frame):
                        event_type = "stdout" if sid == 1 else "stderr"
                        for line in text.split("\n"):
                            if line:
                                yield f"event: {event_type}\ndata: {line}\n\n"


@router.get("/{container_id}/logs/stream")
async def container_logs_stream(container_id: str, tail: int = 100):
    return StreamingResponse(
        _log_stream_proxy(container_id, tail),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/{container_id}/stats")
async def container_stats(container_id: str):
    return await proxy_get(f"/containers/{container_id}/stats?stream=false")


# ---------------------------------------------------------------------------
# Historico (serie persistida pelo coletor — nao toca o daemon)
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"^(\d{1,4})([hd])$")


def _range_para_horas(valor: str) -> int:
    """`24h` / `7d` -> horas. Fora do formato e 422, nao um default silencioso.

    Um `range=ontem` respondido com 24 h por omissao faz a tela mostrar uma
    janela que ninguem pediu; o operador le o grafico como se fosse o intervalo
    dele. Errar alto aqui e mais honesto que adivinhar.
    """
    m = _RANGE_RE.match((valor or "").strip().lower())
    if not m:
        raise HTTPException(
            status_code=422,
            detail="range invalido — use Nh ou Nd (ex.: 1h, 24h, 7d, 30d)",
        )
    quantidade, unidade = int(m.group(1)), m.group(2)
    if quantidade < 1:
        raise HTTPException(status_code=422, detail="range precisa ser >= 1")
    horas = quantidade if unidade == "h" else quantidade * 24
    return min(horas, 366 * 24)


@router.get("/{container_id}/history")
async def container_history(container_id: str, range: str = "24h", max_points: int = 500):
    horas = _range_para_horas(range)
    max_points = max(1, min(max_points, MAX_HISTORY_POINTS))
    return await get_container_history(container_id, hours=horas, max_points=max_points)


# ---------------------------------------------------------------------------
# WebSocket stats
# ---------------------------------------------------------------------------

@router.websocket("/{container_id}/stats/ws")
async def container_stats_ws(websocket: WebSocket, container_id: str):
    await websocket.accept()
    try:
        async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=None) as client:
            async with client.stream(
                "GET", f"/containers/{container_id}/stats?stream=true"
            ) as resp:
                if resp.status_code >= 400:
                    await websocket.send_json({"error": f"HTTP {resp.status_code}"})
                    return
                buf = b""
                async for chunk in resp.aiter_bytes():
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line.strip():
                            try:
                                raw = json.loads(line)
                                cpu_percent = calc_cpu_percent(raw)
                                mem = raw.get("memory_stats", {})
                                mem_usage = mem.get("usage", 0)
                                mem_limit = mem.get("limit", 1)
                                mem_percent = round((mem_usage / mem_limit) * 100, 1) if mem_limit else 0
                                net = raw.get("networks", {})
                                net_rx = sum(n.get("rx_bytes", 0) for n in net.values())
                                net_tx = sum(n.get("tx_bytes", 0) for n in net.values())
                                await websocket.send_json({
                                    "cpu_percent": cpu_percent,
                                    "mem_percent": mem_percent,
                                    "mem_usage": mem_usage,
                                    "mem_limit": mem_limit,
                                    "net_rx": net_rx,
                                    "net_tx": net_tx,
                                    "ts": raw.get("read", ""),
                                })
                            except json.JSONDecodeError:
                                pass
                    await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def _mutate_container(ctid: str, action: str, ip: str, ator: str, proxy_fn, *args, **kwargs):
    """Executa uma mutacao com auditoria gravada ANTES (B10).

    A ordem e o ponto do bloco. Ate a v11 a linha nascia depois do proxy
    retornar, o que perde exatamente o caso grave: acao que trava o daemon nao
    gerava linha nenhuma e o incidente ficava sem rastro de quem pediu o que.
    Auditar depois audita o que deu certo.

    Se algo travar aqui, a linha fica em `running` para sempre — e essa linha
    orfa e o rastro, nao sujeira. Nada neste codigo a limpa.
    """
    audit_id = await audit_iniciar(action, ctid, ator, ip)
    try:
        result = await proxy_fn(*args, **kwargs)
        await audit_concluir(audit_id, "success")
        return result
    except HTTPException as exc:
        await audit_concluir(audit_id, f"error: {exc.status_code} {exc.detail}", status="error")
        raise
    except Exception as e:
        await audit_concluir(audit_id, f"error: {e}", status="error")
        raise


# ---------------------------------------------------------------------------
# As 4 rotas abaixo so sao REGISTRADAS com ENABLE_ACTIONS ligado. Com a flag
# desligada elas nao existem: 404, nao 403. Um 403 confirmaria que a rota esta
# la e que so falta credencial; o 404 nao confirma nada.
# ---------------------------------------------------------------------------

if acoes_habilitadas():

    @router.post("/{container_id}/stop")
    async def stop_container(
        container_id: str,
        request: Request,
        session: dict = Depends(require_unlock),
        t: int = 10,
    ):
        ip = request.client.host if request.client else ""
        ator = session.get("remote_user") or "—"
        return await _mutate_container(
            container_id, "container_stop", ip, ator,
            proxy_post, f"/containers/{container_id}/stop", params={"t": t},
        )


    @router.post("/{container_id}/start")
    async def start_container(
        container_id: str,
        request: Request,
        session: dict = Depends(require_unlock),
    ):
        ip = request.client.host if request.client else ""
        ator = session.get("remote_user") or "—"
        return await _mutate_container(
            container_id, "container_start", ip, ator,
            proxy_post, f"/containers/{container_id}/start",
        )


    @router.post("/{container_id}/restart")
    async def restart_container(
        container_id: str,
        request: Request,
        session: dict = Depends(require_unlock),
        t: int = 10,
    ):
        ip = request.client.host if request.client else ""
        ator = session.get("remote_user") or "—"
        return await _mutate_container(
            container_id, "container_restart", ip, ator,
            proxy_post, f"/containers/{container_id}/restart", params={"t": t},
        )


    @router.delete("/{container_id}")
    async def remove_container(
        container_id: str,
        request: Request,
        session: dict = Depends(require_unlock),
        v: bool = False,
        force: bool = False,
    ):
        ip = request.client.host if request.client else ""
        ator = session.get("remote_user") or "—"
        return await _mutate_container(
            container_id, "container_remove", ip, ator,
            proxy_delete, f"/containers/{container_id}", params={"v": v, "force": force},
        )


# ---------------------------------------------------------------------------
# Terminal (desligado por padrao)
# ---------------------------------------------------------------------------

@router.websocket("/{container_id}/terminal")
async def container_terminal(websocket: WebSocket, container_id: str):
    if not ENABLE_TERMINAL:
        await websocket.close(code=4003, reason="Terminal desabilitado")
        return
    await websocket.accept()
    try:
        exec_body = {
            "Cmd": ["/bin/sh"],
            "AttachStdin": True,
            "AttachStdout": True,
            "AttachStderr": True,
            "Tty": True,
        }
        async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=10) as client:
            r = await client.post(f"/containers/{container_id}/exec", json=exec_body)
            if r.status_code >= 400:
                await websocket.send_json({"type": "error", "message": f"Falha ao criar exec: {r.status_code}"})
                return
            exec_id = r.json().get("Id", "")
            if not exec_id:
                await websocket.send_json({"type": "error", "message": "Resposta sem exec ID"})
                return
            await websocket.send_json({"type": "started", "exec_id": exec_id})
        stdin_queue = asyncio.Queue()
        stop_event = asyncio.Event()

        async def ws_to_stdin():
            try:
                while not stop_event.is_set():
                    msg = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                    data = json.loads(msg)
                    if data.get("type") == "stdin":
                        stdin_bytes = data.get("data", "")
                        if isinstance(stdin_bytes, str):
                            stdin_bytes = stdin_bytes.encode("utf-8")
                        await stdin_queue.put(stdin_bytes)
                    elif data.get("type") == "resize":
                        pass
                    elif data.get("type") == "stop":
                        stop_event.set()
                        break
            except (WebSocketDisconnect, asyncio.TimeoutError):
                stop_event.set()

        async def stdin_gen():
            while not stop_event.is_set():
                try:
                    data = await asyncio.wait_for(stdin_queue.get(), timeout=1)
                    yield data
                except asyncio.TimeoutError:
                    continue
            yield b"\x04"

        async def stdout_to_ws():
            try:
                async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=None) as client:
                    async with client.stream("POST", f"/exec/{exec_id}/start", json={"Detach": False, "Tty": True}) as resp:
                        if resp.status_code >= 400:
                            await websocket.send_json({"type": "error", "message": f"Falha ao iniciar exec: {resp.status_code}"})
                            return
                        async for chunk in resp.aiter_bytes():
                            if chunk:
                                await websocket.send_json({"type": "stdout", "data": chunk.decode("utf-8", errors="replace")})
                await websocket.send_json({"type": "exit", "code": 0})
            except Exception as e:
                await websocket.send_json({"type": "error", "message": str(e)})
            finally:
                stop_event.set()

        async def stdin_sender():
            try:
                async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=None) as client:
                    await client.post(f"/exec/{exec_id}/start", content=stdin_gen(), headers={"Content-Type": "application/json"})
            except Exception:
                pass

        await asyncio.gather(ws_to_stdin(), stdout_to_ws(), stdin_sender())
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
