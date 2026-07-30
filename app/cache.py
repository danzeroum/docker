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


def peek(key: str):
    """Le o cache SEM disparar o factory. None quando nunca houve dado.

    Existe para o `summary` da regua: ele monta a resposta a partir de caches que
    outras rotas ja preenchem, e nao pode virar a rota que dispara `/system/df`
    a cada poll — seria trocar os 6 fetches que o summary economiza por 6
    varreduras de disco.

    Devolve {"data", "age", "fresh"}. `fresh` distingue "dado do ciclo atual" de
    "dado velho que ainda serve": quem chama decide se degrada a chave.
    """
    entry = _store.get(key)
    if not entry or "data" not in entry:
        return None
    now = time.monotonic()
    expires = entry.get("expires", 0)
    ttl_restante = expires - now
    ttl = _ttl_de(entry)
    return {
        "data": entry["data"],
        # idade desde a ultima gravacao, derivada do proprio TTL guardado
        "age": max(0.0, now - (expires - ttl)),
        "ttl": ttl,
        "fresh": ttl_restante > 0,
        # Dentro da janela de stale-while-revalidate: velho mas ainda servivel.
        "servivel": now < entry.get("stale_until", expires),
    }


def _ttl_de(entry: dict) -> float:
    """TTL com que a entrada foi gravada: stale_until = expires + ttl*2."""
    expires = entry.get("expires", 0)
    stale_until = entry.get("stale_until", expires)
    return max(0.0, (stale_until - expires) / 2.0)


def invalidate(key_prefix: str = ""):
    if key_prefix:
        to_del = [k for k in _store if k.startswith(key_prefix)]
        for k in to_del:
            del _store[k]
        _access[:] = [k for k in _access if k not in to_del]
    else:
        _store.clear()
        _access.clear()
