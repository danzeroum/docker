import os
import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

SOCKET_PROXY = os.getenv("SOCKET_PROXY", "http://docker-socket-proxy:2375")

app = FastAPI(title="Docker Cockpit", docs_url=None, redoc_url=None)

# Permite que o cockpit HTML (mesmo origin) consuma a API sem erros de CORS
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
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("static/index.html")

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
    """Retorna docker inspect de um container (GET /containers/{id}/json)."""
    return await _get(f"/containers/{container_id}/json")

# Alias explícito para o frontend que chama /api/containers/{id}/json
@app.get("/api/containers/{container_id}/json")
async def inspect_container_json(container_id: str):
    return await _get(f"/containers/{container_id}/json")

@app.get("/api/containers/{container_id}/logs")
async def container_logs(container_id: str, tail: int = 500):
    """
    Retorna até `tail` linhas de log (padrão 500).
    Sem streaming — buffer seguro para dashboards read-only.
    """
    async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=20) as client:
        r = await client.get(
            f"/containers/{container_id}/logs",
            params={"stdout": 1, "stderr": 1, "tail": tail},
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        # Docker multiplex header (8 bytes por frame): strip para texto limpo
        raw = r.content
        lines = []
        idx = 0
        while idx + 8 <= len(raw):
            frame_size = int.from_bytes(raw[idx+4:idx+8], "big")
            payload = raw[idx+8:idx+8+frame_size]
            lines.append(payload.decode("utf-8", errors="replace"))
            idx += 8 + frame_size
        text = "".join(lines) if lines else raw.decode("utf-8", errors="replace")
        return Response(content=text, media_type="text/plain")

@app.get("/api/containers/{container_id}/stats")
async def container_stats(container_id: str):
    """Stats snapshot (stream=false) — CPU, memória, rede."""
    return await _get(f"/containers/{container_id}/stats?stream=false")

# ---------- images / info ----------
@app.get("/api/images")
async def list_images():
    return await _get("/images/json")

@app.get("/api/info")
async def docker_info():
    return await _get("/info")
