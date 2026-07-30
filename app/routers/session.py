import ipaddress
import logging
import os
from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel
from db import add_audit_entry, create_unlock_session
from hardening import LIMITE, bloqueado, origem, registra_e_notifica, zera

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
    # O 429 vem ANTES de qualquer verificacao: responder o motivo exato da
    # recusa a quem ja estourou o limite continuaria entregando o oraculo que o
    # limite existe para calar.
    if bloqueado(origem(request)):
        raise HTTPException(
            status_code=429,
            detail=f"Muitas tentativas — aguarde antes de tentar de novo (limite: {LIMITE}/min)",
            headers={"Retry-After": "60"},
        )

    if not remote_user:
        registra_e_notifica(request, "unlock")
        raise HTTPException(status_code=401, detail="Autenticacao necessaria — acesso apenas via ingress com basic auth")
    cidr = os.environ.get("TRUSTED_GATEWAY_CIDR", "").strip()
    if not cidr:
        # Ma configuracao NOSSA, e nao tentativa de acesso: nao conta contra o
        # IP de quem so tentou usar o cockpit.
        logger.warning("TRUSTED_GATEWAY_CIDR nao configurado — bloqueando unlock")
        raise HTTPException(status_code=403, detail="Gateway nao configurado — defina TRUSTED_GATEWAY_CIDR")
    client_ip = _get_client_ip(request)
    if not _check_gateway_cidr(client_ip):
        registra_e_notifica(request, "unlock")
        raise HTTPException(status_code=401, detail="Requisicao rejeitada — origem nao autorizada")

    token, expires_at = await create_unlock_session(remote_user, client_ip, body.motivo)
    # Credencial correta limpa o contador: quatro erros de digitacao seguidos de
    # um acerto nao podem deixar o operador a uma falha do 429.
    zera(origem(request))
    await add_audit_entry("unlock", body.motivo or "", "success", remote_user, client_ip)
    return UnlockResponse(token=token, expires_at=expires_at)
