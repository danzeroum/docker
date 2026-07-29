from fastapi import APIRouter, Query
from db import get_audit_log

router = APIRouter(prefix="/api", tags=["audit"])


@router.get("/audit")
async def list_audit(limit: int = Query(100, ge=1, le=1000)):
    rows = await get_audit_log(limit=limit)
    return rows
