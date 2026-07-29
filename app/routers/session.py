import ipaddress
import logging
import os
from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel
from db import add_audit_entry, create_unlock_session

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
    client_ip = _get_client_ip(request)
    if not _check_gateway_cidr(client_ip):
        raise HTTPException(status_code=401, detail="Requisicao rejeitada — origem nao autorizada")
    token, expires_at = await create_unlock_session(remote_user, client_ip, body.motivo)
    await add_audit_entry("unlock", body.motivo or "", "success", remote_user, client_ip)
    return UnlockResponse(token=token, expires_at=expires_at)
