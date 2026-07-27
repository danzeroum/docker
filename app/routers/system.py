import asyncio
from fastapi import APIRouter
from routers._proxy import proxy_get
from sampler import get_last_sample, take_sample
from cache import cached_or_fetch

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/images")
async def list_images():
    data, _ = await cached_or_fetch("images", ttl=30.0, factory=lambda: proxy_get("/images/json"))
    return data


@router.get("/info")
async def docker_info():
    data, _ = await cached_or_fetch("info", ttl=30.0, factory=lambda: proxy_get("/info"))
    return data


@router.get("/system")
async def system_info():
    sample = get_last_sample()
    if sample is None:
        sample = await take_sample()
    return sample
