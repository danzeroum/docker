from datetime import datetime, timezone
from fastapi import APIRouter
from db import get_telemetry_summary, get_findings

router = APIRouter(prefix="/api", tags=["backend"])


@router.get("/backend")
async def get_backend():
    telemetry = await get_telemetry_summary(hours=1)
    findings = await get_findings(status="open")
    rules = {}
    for f in findings:
        r = f.get("rule", "?")
        rules[r] = rules.get(r, 0) + 1
    return {
        "telemetry": telemetry,
        "findings": {"open": len(findings), "by_rule": rules},
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
