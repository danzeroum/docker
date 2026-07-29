import ipaddress
import logging
import os
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel
from auth import _unlock_token
from db import add_audit_entry, set_unlock_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/session", tags=["session"])


class UnlockRequest(BaseModel):
    motivo: str = ""


class UnlockResponse(BaseModel):
    token: str
    expires_at: str


def _get_client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _check_gateway_cidr(client_ip: str) -> bool:
    cidr = os.environ.get("TRUSTED_GATEWAY_CIDR", "").strip()
    if not cidr:
        logger.warning("TRUSTED_GATEWAY_CIDR nao configurado — bloqueando unlock")
        return False
    try:
        network = ipaddress.ip_network(cidr, strict=False)
        ip = ipaddress.ip_address(client_ip)
        return ip in network
    except ValueError:
        return False


@router.post("/unlock", response_model=UnlockResponse)
async def unlock(
    body: UnlockRequest,
    request: Request,
    remote_user: str = Header(None, alias="Remote-User"),
):
    if not remote_user:
        raise HTTPException(status_code=401, detail="Autenticacao necessaria — acesso apenas via ingress com basic auth")
    cidr = os.environ.get("TRUSTED_GATEWAY_CIDR", "").strip()
    if not cidr:
        logger.warning("TRUSTED_GATEWAY_CIDR nao configurado — bloqueando unlock")
        raise HTTPException(status_code=403, detail="Gateway nao configurado — defina TRUSTED_GATEWAY_CIDR")
    if not _check_gateway_cidr(_get_client_ip(request)):
        raise HTTPException(status_code=401, detail="Requisicao rejeitada — origem nao autorizada")
    token = _unlock_token()
    if not token:
        raise HTTPException(status_code=403, detail="Unlock nao configurado no servidor")
    client_ip = _get_client_ip(request)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    await set_unlock_state(token, remote_user, client_ip, body.motivo)
    await add_audit_entry("unlock", body.motivo or "", "success", remote_user, client_ip)
    return UnlockResponse(token=token, expires_at=expires_at)
