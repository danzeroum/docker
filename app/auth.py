import os
from fastapi import Header, HTTPException, Request
from db import get_valid_unlock_session


def _unlock_token():
    return os.environ.get("UNLOCK_TOKEN", "")


async def require_unlock(
    request: Request,
    x_cockpit_unlock: str = Header(None, alias="X-Cockpit-Unlock"),
):
    token = _unlock_token()
    if not token:
        raise HTTPException(status_code=403, detail="Unlock nao configurado no servidor")
    if not x_cockpit_unlock:
        raise HTTPException(status_code=403, detail="Header X-Cockpit-Unlock ausente")
    if x_cockpit_unlock != token:
        raise HTTPException(status_code=403, detail="Token de destravamento invalido")
    session = await get_valid_unlock_session(x_cockpit_unlock)
    if not session:
        raise HTTPException(status_code=403, detail="Sessao de destravamento expirada — refaca o unlock")
    return x_cockpit_unlock
