import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from routers._proxy import configure as configure_proxy
from routers.containers import router as containers_router
from routers.system import router as system_router
from routers.overview import router as overview_router
from routers.findings import router as findings_router
from routers.ingress import router as ingress_router
from routers.projects import router as projects_router
from routers.audit import router as audit_router
from routers.session import router as session_router
from sampler import sampler_loop
from findings.engine import findings_loop
from db import init_db, close_db

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")

SOCKET_PROXY = os.getenv("SOCKET_PROXY", "http://docker-socket-proxy:2375")
ENABLE_TERMINAL = os.getenv("ENABLE_TERMINAL", "").lower() in ("1", "true", "yes")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else []


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_proxy(SOCKET_PROXY, ENABLE_TERMINAL)
    from sampler import take_sample
    await take_sample()
    await init_db()
    interval = float(os.getenv("SAMPLER_INTERVAL", "5"))
    container_interval = float(os.getenv("SAMPLER_CONTAINER_INTERVAL", "10"))
    sampler_task = asyncio.create_task(sampler_loop(interval, container_interval))
    findings_interval = float(os.getenv("FINDINGS_INTERVAL", "10"))
    findings_task = asyncio.create_task(findings_loop(findings_interval))
    yield
    sampler_task.cancel()
    findings_task.cancel()
    try:
        await sampler_task
    except asyncio.CancelledError:
        pass
    try:
        await findings_task
    except asyncio.CancelledError:
        pass
    await close_db()


app = FastAPI(title="Docker Cockpit", docs_url=None, redoc_url=None, lifespan=lifespan)

cors_origins = ALLOWED_ORIGINS if ALLOWED_ORIGINS else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


# ---------- health ----------
@app.get("/health")
async def health():
    return {"ok": True}


# ---------- static ----------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ---------- routers ----------
app.include_router(containers_router)
app.include_router(system_router)
app.include_router(overview_router)
app.include_router(findings_router)
app.include_router(ingress_router)
app.include_router(projects_router)
app.include_router(audit_router)
app.include_router(session_router)
