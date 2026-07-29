from fastapi import Header, HTTPException, Request
from db import get_valid_unlock_session


async def require_unlock(
    request: Request,
    x_cockpit_unlock: str = Header(None, alias="X-Cockpit-Unlock"),
):
    """Guard de toda mutacao.

    A UNICA credencial aceita e um token de sessao emitido por
    POST /api/session/unlock: aleatorio, guardado so como hash, com prazo de
    30 min e usuario do basic auth do ingress atrelado.

    Nao existe token vindo de configuracao. Um valor estatico de env
    apresentado aqui nao casa com nenhum hash em unlock_state e cai no 403 —
    que e exatamente o furo que a v8 fecha.
    """
    if not x_cockpit_unlock:
        raise HTTPException(status_code=403, detail="Header X-Cockpit-Unlock ausente")
    session = await get_valid_unlock_session(x_cockpit_unlock)
    if not session:
        raise HTTPException(
            status_code=403,
            detail="Sessao de destravamento invalida ou expirada — refaca o unlock",
        )
    return session
