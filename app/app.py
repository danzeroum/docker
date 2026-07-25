import os
import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

SOCKET_PROXY = os.getenv("SOCKET_PROXY", "http://docker-socket-proxy:2375")

app = FastAPI(title="Docker Cockpit", docs_url=None, redoc_url=None)

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
    return await _get("/containers/json?all=1")

@app.get("/api/containers/{container_id}")
async def inspect_container(container_id: str):
    return await _get(f"/containers/{container_id}/json")

@app.get("/api/containers/{container_id}/logs")
async def container_logs(container_id: str, tail: int = 100):
    async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=15) as client:
        r = await client.get(
            f"/containers/{container_id}/logs",
            params={"stdout": 1, "stderr": 1, "tail": tail},
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return Response(content=r.content, media_type="text/plain")

@app.get("/api/containers/{container_id}/stats")
async def container_stats(container_id: str):
    return await _get(f"/containers/{container_id}/stats?stream=false")

# ---------- images / info ----------
@app.get("/api/images")
async def list_images():
    return await _get("/images/json")

@app.get("/api/info")
async def docker_info():
    return await _get("/info")
