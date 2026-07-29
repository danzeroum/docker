import json
from fastapi import APIRouter, Query, HTTPException, Body, Depends, Request
from auth import require_unlock
from db import get_findings, get_finding, ack_finding, add_audit_entry

ACK_REASONS = ("aceito_estrutural", "monitorando", "falso_positivo")

router = APIRouter(prefix="/api", tags=["findings"])


@router.get("/findings")
async def list_findings(
    status: str = Query(None, pattern="^(open|acked|resolved)?$"),
    scope: str = Query(None, pattern="^(container|host|ingress|cert)?$"),
):
    rows = await get_findings(status=status, scope=scope)
    result = []
    for r in rows:
        item = {
            "id": r["id"],
            "rule": r["rule"],
            "target": r["target"],
            "scope": r["scope"],
            "severity": r["severity"],
            "score": r["score"],
            "status": r["status"],
            "first_seen": r["first_seen"],
            "last_seen": r["last_seen"],
            "occurrences": r["occurrences"],
            "ack_reason": r.get("ack_reason"),
            "ack_note": r.get("ack_note"),
            "ack_until": r.get("ack_until"),
        }
        if r.get("targets"):
            try:
                item["targets"] = json.loads(r["targets"])
            except (json.JSONDecodeError, TypeError):
                item["targets"] = []
        try:
            payload = json.loads(r["payload"]) if r["payload"] else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}
        for k in ("title", "title_plain", "interpretation", "interpretation_plain",
                   "recommendation", "evidence", "impact", "facts", "actions",
                   "caused_by", "chain", "explainer", "related_container"):
            if k in payload:
                item[k] = payload[k]
        result.append(item)
    return result


@router.get("/findings/{finding_id}")
async def get_finding_detail(finding_id: str):
    r = await get_finding(finding_id)
    if not r:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Finding not found"}, status_code=404)
    item = dict(r)
    if r.get("targets"):
        try:
            item["targets"] = json.loads(r["targets"])
        except (json.JSONDecodeError, TypeError):
            item["targets"] = []
    try:
        payload = json.loads(r["payload"]) if r["payload"] else {}
    except (json.JSONDecodeError, TypeError):
        payload = {}
    for k in ("title", "title_plain", "interpretation", "interpretation_plain",
               "recommendation", "evidence", "impact", "facts", "actions",
               "caused_by", "chain", "explainer", "related_container"):
        item[k] = payload.get(k)
    item.pop("payload", None)
    return item


@router.post("/findings/{finding_id}/ack")
async def ack_finding_endpoint(
    finding_id: str,
    request: Request,
    reason: str = Body(..., embed=True),
    note: str = Body("", embed=True),
    until: str = Body("", embed=True),
    session: dict = Depends(require_unlock),
):
    """Silenciar e mutacao: passa pelo destravamento e deixa linha de auditoria."""
    ip = request.client.host if request.client else ""
    ator = session.get("remote_user") or "—"
    if not reason:
        raise HTTPException(status_code=400, detail="reason é obrigatório")
    if reason not in ACK_REASONS:
        raise HTTPException(
            status_code=400,
            detail=f"reason inválido — use um de {', '.join(ACK_REASONS)}",
        )
    r = await get_finding(finding_id)
    if not r:
        await add_audit_entry("ack", finding_id, "error: 404 nao encontrado", ator, ip)
        raise HTTPException(status_code=404, detail="Finding não encontrado")
    if r["status"] == "resolved":
        await add_audit_entry("ack", finding_id, "error: 400 ja resolvido", ator, ip)
        raise HTTPException(status_code=400, detail="Finding já resolvido")
    await ack_finding(finding_id, reason, note, until)
    # Resultado carrega o prazo — e o que a tela Auditoria mostra na coluna resultado.
    await add_audit_entry("ack", finding_id, f"{reason} · {until or 'sem prazo'}", ator, ip)
    return {"status": "acked", "id": finding_id, "reason": reason, "until": until}
