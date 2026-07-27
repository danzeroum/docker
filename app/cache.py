import asyncio
import time

_MAX_KEYS = 500
_store: dict = {}
_access: list = []


def _entry(key: str) -> dict:
    if key not in _store:
        _store[key] = {"lock": asyncio.Lock()}
    return _store[key]


def _evict_if_needed():
    if len(_store) < _MAX_KEYS:
        return
    cutoff = _MAX_KEYS // 2
    evict = set(_access[:cutoff])
    for k in evict:
        del _store[k]
    _access[:] = _access[cutoff:]


def _touch(key: str):
    _access.append(key)
    if len(_access) > _MAX_KEYS * 2:
        _access[:] = _access[-_MAX_KEYS:]


async def cached_or_fetch(key: str, ttl: float, factory, timeout: float = 10.0):
    now = time.monotonic()
    entry = _entry(key)
    if "data" in entry and now < entry["expires"]:
        _touch(key)
        return entry["data"], False
    stale = "data" in entry
    if stale and now < entry.get("stale_until", 0):
        _touch(key)
        return entry["data"], True
    lock = entry["lock"]
    if lock.locked():
        if stale:
            _touch(key)
            return entry["data"], True
        await asyncio.wait_for(lock.acquire(), timeout=timeout)
        lock.release()
        if "data" in entry:
            _touch(key)
            return entry["data"], False
    async with lock:
        if "data" in entry and now < entry["expires"]:
            _touch(key)
            return entry["data"], False
        try:
            data = await asyncio.wait_for(factory(), timeout=timeout)
        except asyncio.TimeoutError:
            if stale:
                _touch(key)
                return entry["data"], True
            raise
        _evict_if_needed()
        entry.update({
            "data": data,
            "expires": now + ttl,
            "stale_until": now + ttl * 3,
        })
        _touch(key)
        return data, False


def invalidate(key_prefix: str = ""):
    if key_prefix:
        to_del = [k for k in _store if k.startswith(key_prefix)]
        for k in to_del:
            del _store[k]
        _access[:] = [k for k in _access if k not in to_del]
    else:
        _store.clear()
        _access.clear()
