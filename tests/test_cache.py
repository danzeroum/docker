import asyncio
import time
import pytest
from cache import cached_or_fetch, invalidate, _store, _access, _MAX_KEYS

pytestmark = pytest.mark.asyncio


async def test_cache_hit():
    invalidate()
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        return "data"

    data, stale = await cached_or_fetch("k1", ttl=60, factory=factory)
    assert data == "data"
    assert stale is False
    assert call_count == 1

    data, stale = await cached_or_fetch("k1", ttl=60, factory=factory)
    assert data == "data"
    assert stale is False
    assert call_count == 1


async def test_cache_expiry_and_stale():
    invalidate()
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        return f"v{call_count}"

    data, stale = await cached_or_fetch("k2", ttl=0.05, factory=factory)
    assert data == "v1"
    await asyncio.sleep(0.06)
    data, stale = await cached_or_fetch("k2", ttl=0.05, factory=factory)
    assert data == "v1"
    assert stale is True
    assert call_count == 1


async def test_cache_force_refresh():
    invalidate()

    async def factory():
        return "fresh"

    await cached_or_fetch("k3", ttl=0.01, factory=factory)
    await asyncio.sleep(0.03)
    await cached_or_fetch("k3", ttl=0.01, factory=factory)
    await asyncio.sleep(0.03)
    data, stale = await cached_or_fetch("k3", ttl=0.01, factory=factory)
    assert data == "fresh"
    assert stale is False


async def test_cache_concurrency():
    invalidate()
    call_count = 0

    async def factory():
        nonlocal call_count
        await asyncio.sleep(0.05)
        call_count += 1
        return "result"

    async def fetch():
        return await cached_or_fetch("concurrent", ttl=60, factory=factory)

    results = await asyncio.gather(*[fetch() for _ in range(20)])
    assert call_count == 1
    for data, stale in results:
        assert data == "result"
        assert stale is False


async def test_cache_concurrent_expired():
    invalidate()
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        return "data"

    await cached_or_fetch("exp", ttl=0.02, factory=factory)
    await asyncio.sleep(0.03)

    async def fetch():
        return await cached_or_fetch("exp", ttl=0.02, factory=factory)

    results = await asyncio.gather(*[fetch() for _ in range(20)])
    assert call_count == 1
    for data, stale in results:
        assert data == "data"
        assert stale is True


async def test_invalidate_prefix():
    invalidate()

    async def factory():
        return "x"

    await cached_or_fetch("img:a", ttl=60, factory=factory)
    await cached_or_fetch("img:b", ttl=60, factory=factory)
    await cached_or_fetch("sys", ttl=60, factory=factory)
    assert len(_store) == 3

    invalidate("img:")
    assert "img:a" not in _store
    assert "img:b" not in _store
    assert "sys" in _store


async def test_max_keys_eviction():
    invalidate()

    created = 0
    async def factory():
        nonlocal created
        val = f"v{created}"
        created += 1
        return val

    for i in range(_MAX_KEYS + 50):
        await cached_or_fetch(f"key{i}", ttl=60, factory=factory)

    assert len(_store) <= _MAX_KEYS



