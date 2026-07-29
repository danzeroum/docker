from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from auth import require_unlock
from db import (TASK_COLUNAS, add_audit_entry, create_task, get_task, get_tasks,
                update_task)

router = APIRouter(prefix="/api", tags=["tasks"])


def _ator(session: dict) -> str:
    return session.get("remote_user") or "—"


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.get("/tasks")
async def list_tasks(col: str = Query(None), origem: str = Query(None)):
    """Board agrupado por coluna. Leitura livre, como toda leitura do cockpit."""
    if col and col not in TASK_COLUNAS:
        raise HTTPException(status_code=400, detail=f"coluna invalida — use {', '.join(TASK_COLUNAS)}")
    if origem and origem not in ("auto", "manual"):
        raise HTTPException(status_code=400, detail="origem invalida — use auto ou manual")
    linhas = await get_tasks(col=col, origem=origem)
    colunas = {c: [] for c in TASK_COLUNAS}
    for t in linhas:
        colunas.setdefault(t["col"], []).append(t)
    return {
        "columns": [{"key": c, "tasks": colunas.get(c, [])} for c in TASK_COLUNAS],
        "total": len(linhas),
    }


@router.post("/tasks")
async def criar_task(
    request: Request,
    title: str = Body(..., embed=True),
    detail: str = Body("", embed=True),
    col: str = Body("todo", embed=True),
    target: str = Body(None, embed=True),
    owner: str = Body("", embed=True),
    due: str = Body(None, embed=True),
    finding_id: str = Body(None, embed=True),
    session: dict = Depends(require_unlock),
):
    """Cria tarefa MANUAL. O board nunca cria 'auto' por HTTP — isso e do motor."""
    ator, ip = _ator(session), _ip(request)
    if not title or not title.strip():
        await add_audit_entry("task_create", "-", "error: 400 titulo vazio", ator, ip)
        raise HTTPException(status_code=400, detail="title e obrigatorio")
    if col not in TASK_COLUNAS:
        await add_audit_entry("task_create", "-", f"error: 400 coluna {col}", ator, ip)
        raise HTTPException(status_code=400, detail=f"coluna invalida — use {', '.join(TASK_COLUNAS)}")
    tarefa = await create_task(
        title=title.strip(), detail=detail, col=col, origem="manual",
        finding_id=finding_id, target=target, owner=owner, due=due,
    )
    await add_audit_entry("task_create", tarefa["id"], f"{col} · {title.strip()}", ator, ip)
    return tarefa


@router.patch("/tasks/{task_id}")
async def mover_task(
    task_id: str,
    request: Request,
    col: str = Body(None, embed=True),
    title: str = Body(None, embed=True),
    detail: str = Body(None, embed=True),
    owner: str = Body(None, embed=True),
    due: str = Body(None, embed=True),
    note: str = Body(None, embed=True),
    session: dict = Depends(require_unlock),
):
    ator, ip = _ator(session), _ip(request)
    if col is not None and col not in TASK_COLUNAS:
        await add_audit_entry("task_move", task_id, f"error: 400 coluna {col}", ator, ip)
        raise HTTPException(status_code=400, detail=f"coluna invalida — use {', '.join(TASK_COLUNAS)}")
    atual = await get_task(task_id)
    if not atual:
        await add_audit_entry("task_move", task_id, "error: 404 nao encontrada", ator, ip)
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    tarefa = await update_task(
        task_id, col=col, title=title, detail=detail, owner=owner, due=due, note=note,
    )
    if col is not None and col != atual["col"]:
        resultado = f"{atual['col']} -> {col}"
    else:
        resultado = "editada"
    await add_audit_entry("task_move", task_id, resultado, ator, ip)
    return tarefa
