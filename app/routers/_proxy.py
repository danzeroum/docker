import os
import httpx
from fastapi import HTTPException

SOCKET_PROXY: str = os.getenv("SOCKET_PROXY", "http://docker-socket-proxy:2375")
ENABLE_TERMINAL: bool = os.getenv("ENABLE_TERMINAL", "").lower() in ("1", "true", "yes")


def configure(proxy_url: str, terminal_enabled: bool):
    global SOCKET_PROXY, ENABLE_TERMINAL
    SOCKET_PROXY = proxy_url
    ENABLE_TERMINAL = terminal_enabled


async def proxy_get(path: str, timeout: int = 10):
    async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=timeout) as client:
        r = await client.get(path)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()


async def proxy_post(path: str, params: dict | None = None, json_body: dict | None = None, timeout: int = 30):
    async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=timeout) as client:
        r = await client.post(path, params=params, json=json_body)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json() if r.content else {"ok": True}


async def proxy_delete(path: str, params: dict | None = None, timeout: int = 30):
    async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=timeout) as client:
        r = await client.delete(path, params=params)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return {"ok": True, "status_code": r.status_code}
