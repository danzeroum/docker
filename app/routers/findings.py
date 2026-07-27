import json
from fastapi import APIRouter, Query
from db import get_findings, get_finding

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
        }
        try:
            payload = json.loads(r["payload"]) if r["payload"] else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}
        for k in ("title", "title_plain", "interpretation", "interpretation_plain",
                   "recommendation", "evidence", "impact", "facts", "actions",
                   "caused_by", "chain", "explainer"):
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
    try:
        payload = json.loads(r["payload"]) if r["payload"] else {}
    except (json.JSONDecodeError, TypeError):
        payload = {}
    for k in ("title", "title_plain", "interpretation", "interpretation_plain",
               "recommendation", "evidence", "impact", "facts", "actions",
               "caused_by", "chain", "explainer"):
        item[k] = payload.get(k)
    item.pop("payload", None)
    return item
