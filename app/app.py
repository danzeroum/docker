import os
import json
import time
import asyncio
import httpx
import platform
import psutil
from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

SOCKET_PROXY = os.getenv("SOCKET_PROXY", "http://docker-socket-proxy:2375")
ENABLE_TERMINAL = os.getenv("ENABLE_TERMINAL", "").lower() in ("1", "true", "yes")

# Resolve o diretorio static relativo ao proprio app.py,
# independente de onde o processo e iniciado (CI, Docker, local)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="Docker Cockpit", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# ---------- health ----------
@app.get("/health")
async def health():
    return {"ok": True}

# ---------- static (cockpit HTML) ----------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

# ---------- helpers ----------
async def _get(path: str):
    async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=10) as client:
        r = await client.get(path)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

# ---------- containers ----------
@app.get("/api/containers")
async def list_containers():
    """Lista todos os containers (running + stopped)."""
    return await _get("/containers/json?all=1")

@app.get("/api/containers/{container_id}")
async def inspect_container(container_id: str):
    """Retorna docker inspect de um container."""
    return await _get(f"/containers/{container_id}/json")

@app.get("/api/containers/{container_id}/json")
async def inspect_container_json(container_id: str):
    """Alias explicito — frontend chama /api/containers/{id}/json."""
    return await _get(f"/containers/{container_id}/json")

@app.get("/api/containers/{container_id}/logs")
async def container_logs(container_id: str, tail: int = 500):
    """
    Retorna ate `tail` linhas de log (padrao 500).
    Desempacota o formato multiplexado do Docker (8-byte header por frame).
    """
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
            frame_size = int.from_bytes(raw[idx + 4:idx + 8], "big")
            payload = raw[idx + 8:idx + 8 + frame_size]
            lines.append(payload.decode("utf-8", errors="replace"))
            idx += 8 + frame_size
        text = "".join(lines) if lines else raw.decode("utf-8", errors="replace")
        return Response(content=text, media_type="text/plain")

# ---------- logs streaming (SSE) ----------
def _demux_frame(data: bytes):
    """Itera sobre dados multiplexados do Docker, gerando (stream_id, text)."""
    idx = 0
    while idx + 8 <= len(data):
        frame_size = int.from_bytes(data[idx + 4:idx + 8], "big")
        payload = data[idx + 8:idx + 8 + frame_size]
        stream_id = data[idx]  # 1=stdout, 2=stderr
        yield stream_id, payload.decode("utf-8", errors="replace")
        idx += 8 + frame_size

async def _log_stream_proxy(container_id: str, tail: int):
    """Faz proxy do stream de logs do Docker via httpx, gerando SSE."""
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
                    frame = buf[:8 + frame_size]
                    buf = buf[8 + frame_size:]
                    for sid, text in _demux_frame(frame):
                        event_type = "stdout" if sid == 1 else "stderr"
                        for line in text.split("\n"):
                            if line:
                                yield f"event: {event_type}\ndata: {line}\n\n"

@app.get("/api/containers/{container_id}/logs/stream")
async def container_logs_stream(container_id: str, tail: int = 100):
    """Streaming SSE de logs do container (stdout/stderr em tempo real)."""
    return StreamingResponse(
        _log_stream_proxy(container_id, tail),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )

@app.get("/api/containers/{container_id}/stats")
async def container_stats(container_id: str):
    """Stats snapshot (stream=false) — CPU, memoria, rede."""
    return await _get(f"/containers/{container_id}/stats?stream=false")

# ---------- WebSocket stats ----------
@app.websocket("/api/containers/{container_id}/stats/ws")
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
                                # Extract key metrics
                                cpu_delta = raw.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
                                sys_delta = raw.get("cpu_stats", {}).get("system_cpu_usage", 0)
                                precpu = raw.get("precpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
                                presys = raw.get("precpu_stats", {}).get("system_cpu_usage", 0)
                                num_cpus = raw.get("cpu_stats", {}).get("online_cpus", 1)

                                cpu_percent = 0.0
                                if sys_delta and presys:
                                    cpu_delta_val = cpu_delta - precpu
                                    sys_delta_val = sys_delta - presys
                                    if cpu_delta_val > 0 and sys_delta_val > 0:
                                        cpu_percent = round((cpu_delta_val / sys_delta_val) * num_cpus * 100, 1)

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
                                    "ts": raw.get("read", "")
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

# ---------- container lifecycle (admin) ----------
async def _post(path: str, params: dict | None = None, json_body: dict | None = None):
    async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=30) as client:
        r = await client.post(path, params=params, json=json_body)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json() if r.content else {"ok": True}

async def _delete(path: str, params: dict | None = None):
    async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=30) as client:
        r = await client.delete(path, params=params)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return {"ok": True, "status_code": r.status_code}

@app.post("/api/containers/{container_id}/stop")
async def stop_container(container_id: str, t: int = 10):
    """Para o container (timeout em segundos, default 10)."""
    return await _post(f"/containers/{container_id}/stop", params={"t": t})

@app.post("/api/containers/{container_id}/start")
async def start_container(container_id: str):
    """Inicia o container."""
    return await _post(f"/containers/{container_id}/start")

@app.post("/api/containers/{container_id}/restart")
async def restart_container(container_id: str, t: int = 10):
    """Reinicia o container (timeout em segundos, default 10)."""
    return await _post(f"/containers/{container_id}/restart", params={"t": t})

@app.delete("/api/containers/{container_id}")
async def remove_container(container_id: str, v: bool = False, force: bool = False):
    """
    Remove o container.
    - v=true: remove volumes associados
    - force=true: remove mesmo se estiver rodando (SIGKILL)
    """
    return await _delete(f"/containers/{container_id}", params={"v": v, "force": force})

# ---------- images / info ----------
@app.get("/api/images")
async def list_images():
    return await _get("/images/json")

@app.get("/api/info")
async def docker_info():
    return await _get("/info")

# ---------- system / host ----------
@app.get("/api/system")
async def system_info():
    """Health geral do host/VPS (read-only)."""
    # CPU
    cpu_percent = psutil.cpu_percent(interval=0.1)
    cpu_count = psutil.cpu_count(logical=True)
    load_avg = os.getloadavg() if hasattr(os, 'getloadavg') else (0.0, 0.0, 0.0)

    # Memoria
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # Disco (por mount)
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_gb": round(usage.total / (1024**3), 2),
                "used_gb": round(usage.used / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
                "percent": round(usage.percent, 1)
            })
        except PermissionError:
            continue

    # Rede
    net_io = psutil.net_io_counters()
    net_if = psutil.net_if_addrs()

    # Uptime
    boot_time = psutil.boot_time()
    uptime_seconds = time.time() - boot_time

    # Warnings simples
    warnings = []
    if cpu_percent > 80:
        warnings.append({"level": "warn", "message": f"CPU alta: {cpu_percent:.1f}%"})
    if mem.percent > 85:
        warnings.append({"level": "warn", "message": f"Memória alta: {mem.percent:.1f}%"})
    if swap.percent > 80:
        warnings.append({"level": "warn", "message": f"Swap alta: {swap.percent:.1f}%"})
    for d in disks:
        if d["percent"] > 90:
            warnings.append({"level": "crit", "message": f"Disco cheio: {d['mountpoint']} ({d['percent']:.1f}%)"})
    if load_avg[0] > cpu_count * 2:
        warnings.append({"level": "warn", "message": f"Load average alto: {load_avg[0]:.2f} (CPUs: {cpu_count})"})

    return {
        "cpu": {
            "percent": round(cpu_percent, 1),
            "count": cpu_count,
            "load_1m": round(load_avg[0], 2),
            "load_5m": round(load_avg[1], 2),
            "load_15m": round(load_avg[2], 2)
        },
        "memory": {
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "free_gb": round(mem.available / (1024**3), 2),
            "percent": round(mem.percent, 1)
        },
        "swap": {
            "total_gb": round(swap.total / (1024**3), 2),
            "used_gb": round(swap.used / (1024**3), 2),
            "free_gb": round(swap.free / (1024**3), 2),
            "percent": round(swap.percent, 1)
        },
        "disks": disks,
        "network": {
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv,
            "packets_sent": net_io.packets_sent,
            "packets_recv": net_io.packets_recv,
            "interfaces": {name: [addr.address for addr in addrs if addr.family == 2] for name, addrs in net_if.items()}
        },
        "uptime_seconds": round(uptime_seconds),
        "platform": platform.system(),
        "platform_version": platform.version(),
        "warnings": warnings
    }

# ---------- terminal (docker exec via WebSocket) ----------
@app.websocket("/api/containers/{container_id}/terminal")
async def container_terminal(websocket: WebSocket, container_id: str):
    if not ENABLE_TERMINAL:
        await websocket.close(code=4003, reason="Terminal desabilitado")
        return
    await websocket.accept()
    try:
        # 1. Create exec instance
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

        # 2. Start exec and proxy stdin/stdout
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
                        pass  # Docker exec resize not supported via socket proxy
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
            yield b"\x04"  # EOT

        async def stdout_to_ws():
            try:
                async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=None) as client:
                    async with client.stream(
                        "POST",
                        f"/exec/{exec_id}/start",
                        json={"Detach": False, "Tty": True},
                    ) as resp:
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
                    await client.post(
                        f"/exec/{exec_id}/start",
                        content=stdin_gen(),
                        headers={"Content-Type": "application/json"},
                    )
            except Exception:
                pass

        await asyncio.gather(
            ws_to_stdin(),
            stdout_to_ws(),
            stdin_sender(),
        )
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
