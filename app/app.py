import os
import time
import httpx
import platform
import psutil
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

SOCKET_PROXY = os.getenv("SOCKET_PROXY", "http://docker-socket-proxy:2375")

# Resolve o diretorio static relativo ao proprio app.py,
# independente de onde o processo e iniciado (CI, Docker, local)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="Docker Cockpit", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
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

@app.get("/api/containers/{container_id}/stats")
async def container_stats(container_id: str):
    """Stats snapshot (stream=false) — CPU, memoria, rede."""
    return await _get(f"/containers/{container_id}/stats?stream=false")

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
