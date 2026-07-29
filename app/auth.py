import os
from fastapi import Header, HTTPException, Request


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
    return x_cockpit_unlock
