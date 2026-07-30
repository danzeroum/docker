import os
import json
import subprocess
import asyncio
from fastapi import APIRouter, HTTPException, Request, Depends
from auth import require_unlock
from db import audit_iniciar, audit_concluir
from actions import habilitadas as acoes_habilitadas

router = APIRouter(prefix="/api", tags=["projects"])

PROJECTS_ROOT = os.getenv("PROJECTS_ROOT", "/opt/btv")
COMPOSE_TIMEOUT = int(os.getenv("COMPOSE_TIMEOUT", "60"))


def _find_projects():
    projects = {}
    if not os.path.isdir(PROJECTS_ROOT):
        return projects
    for entry in sorted(os.listdir(PROJECTS_ROOT)):
        project_dir = os.path.join(PROJECTS_ROOT, entry)
        if not os.path.isdir(project_dir):
            continue
        for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml", "compose.yml"):
            path = os.path.join(project_dir, name)
            if os.path.isfile(path):
                projects[entry] = {"path": project_dir, "compose_file": path}
                break
    return projects


def _get_compose_services(compose_file):
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "ps", "--format", "json"],
            capture_output=True, text=True, timeout=COMPOSE_TIMEOUT
        )
        if result.returncode != 0:
            return None, result.stderr.strip()
        services = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                svc = json.loads(line)
                services.append(svc)
            except json.JSONDecodeError:
                pass
        return services, None
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "docker compose not available"
    except Exception as e:
        return None, str(e)


@router.get("/projects")
async def list_projects():
    projects = _find_projects()
    result = []
    for name, info in projects.items():
        services, err = _get_compose_services(info["compose_file"])
        if err and err != "docker compose not available":
            result.append({"name": name, "path": info["path"], "status": "error", "error": err})
        elif services is None:
            result.append({"name": name, "path": info["path"], "status": "unknown"})
        else:
            running = sum(1 for s in services if s.get("State") == "running")
            total = len(services)
            status = "running" if total > 0 and running == total else ("partial" if running > 0 else "stopped")
            result.append({
                "name": name, "path": info["path"],
                "status": status,
                "services": services,
                "running": running, "total": total,
            })
    return {"projects": result}


# ---------------------------------------------------------------------------
# As 2 rotas de stack seguem a mesma barreira das 4 de container: com
# ENABLE_ACTIONS desligado elas nao existem. Uma flag que cobrisse so o prune
# daria falsa sensacao de read-only com a superficie da F5 aberta ao lado.
# ---------------------------------------------------------------------------

if acoes_habilitadas():

    @router.post("/projects/{name}/start")
    async def start_project(
        name: str,
        request: Request,
        session: dict = Depends(require_unlock),
    ):
        projects = _find_projects()
        if name not in projects:
            raise HTTPException(status_code=404, detail=f"Projeto '{name}' nao encontrado")
        info = projects[name]
        client_ip = request.client.host if request.client else ""
        ator = session.get("remote_user") or "—"
        # ANTES de executar: `docker compose up` pode travar até o timeout de
        # 60s, e auditar depois perderia exatamente essa linha.
        audit_id = await audit_iniciar("start", name, ator, client_ip)
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "-f", info["compose_file"], "up", "-d",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=COMPOSE_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                raise HTTPException(status_code=504, detail="Comando docker compose timed out")
            if proc.returncode != 0:
                detail = stderr.decode().strip() or stdout.decode().strip() or f"exit code {proc.returncode}"
                await audit_concluir(audit_id, f"error: {detail}", status="error")
                raise HTTPException(status_code=502, detail=detail)
            await audit_concluir(audit_id, "success")
            return {"status": "started", "name": name}
        except HTTPException:
            raise
        except FileNotFoundError:
            msg = "Docker compose nao disponivel no container"
            await audit_concluir(audit_id, f"error: {msg}", status="error")
            raise HTTPException(status_code=500, detail=msg)
        except Exception as e:
            msg = str(e)
            await audit_concluir(audit_id, f"error: {msg}", status="error")
            raise HTTPException(status_code=500, detail=msg)


    @router.post("/projects/{name}/stop")
    async def stop_project(
        name: str,
        request: Request,
        session: dict = Depends(require_unlock),
    ):
        projects = _find_projects()
        if name not in projects:
            raise HTTPException(status_code=404, detail=f"Projeto '{name}' nao encontrado")
        info = projects[name]
        client_ip = request.client.host if request.client else ""
        ator = session.get("remote_user") or "—"
        audit_id = await audit_iniciar("stop", name, ator, client_ip)
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "-f", info["compose_file"], "down",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=COMPOSE_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                raise HTTPException(status_code=504, detail="Comando docker compose timed out")
            if proc.returncode != 0:
                detail = stderr.decode().strip() or stdout.decode().strip() or f"exit code {proc.returncode}"
                await audit_concluir(audit_id, f"error: {detail}", status="error")
                raise HTTPException(status_code=502, detail=detail)
            await audit_concluir(audit_id, "success")
            return {"status": "stopped", "name": name}
        except HTTPException:
            raise
        except FileNotFoundError:
            msg = "Docker compose nao disponivel no container"
            await audit_concluir(audit_id, f"error: {msg}", status="error")
            raise HTTPException(status_code=500, detail=msg)
        except Exception as e:
            msg = str(e)
            await audit_concluir(audit_id, f"error: {msg}", status="error")
            raise HTTPException(status_code=500, detail=msg)
