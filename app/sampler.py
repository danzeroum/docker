import asyncio
from datetime import datetime, timezone
import time
import platform
import os
import psutil
from stats_util import calc_cpu_percent

_last_sample = None
_container_stats = {}
_container_stats_as_of = None
_last_container_collection = 0.0
_SEM_STATS = asyncio.Semaphore(4)


def _sample():
    cpu_percent = psutil.cpu_percent(interval=0.0)
    cpu_count = psutil.cpu_count(logical=True)
    load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": round(usage.percent, 1),
            })
        except PermissionError:
            continue

    net_io = psutil.net_io_counters()
    net_if = psutil.net_if_addrs()
    boot_time = psutil.boot_time()
    uptime_seconds = time.time() - boot_time

    warnings = []
    if cpu_percent > 80:
        warnings.append({"level": "warn", "message": f"CPU alta: {cpu_percent:.1f}%"})
    if mem.percent > 85:
        warnings.append({"level": "warn", "message": f"Memoria alta: {mem.percent:.1f}%"})
    if swap.percent > 80:
        warnings.append({"level": "warn", "message": f"Swap alta: {swap.percent:.1f}%"})
    for d in disks:
        if d["percent"] > 90:
            warnings.append({"level": "crit", "message": f"Disco cheio: {d['mountpoint']} ({d['percent']:.1f}%)"})
    if load_avg[0] > cpu_count * 2:
        warnings.append({"level": "warn", "message": f"Load average alto: {load_avg[0]:.2f} (CPUs: {cpu_count})"})

    return {
        "sampled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "cpu": {
            "percent": round(cpu_percent, 1),
            "count": cpu_count,
            "load_1m": round(load_avg[0], 2),
            "load_5m": round(load_avg[1], 2),
            "load_15m": round(load_avg[2], 2),
        },
        "memory": {
            "total": mem.total,
            "used": mem.used,
            "free": mem.available,
            "percent": round(mem.percent, 1),
        },
        "swap": {
            "total": swap.total,
            "used": swap.used,
            "free": swap.free,
            "percent": round(swap.percent, 1),
        },
        "disks": disks,
        "network": {
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv,
            "packets_sent": net_io.packets_sent,
            "packets_recv": net_io.packets_recv,
            "interfaces": {
                name: [addr.address for addr in addrs if addr.family == 2]
                for name, addrs in net_if.items()
            },
        },
        "uptime_seconds": round(uptime_seconds),
        "platform": platform.system(),
        "platform_version": platform.version(),
        "warnings": warnings,
    }


def get_last_sample():
    global _last_sample
    return _last_sample


def get_container_stats():
    return _container_stats, _container_stats_as_of

def get_container_inspects():
    return {
        cid: data.get("inspect")
        for cid, data in _container_stats.items()
        if data.get("inspect")
    }


async def take_sample():
    global _last_sample
    _last_sample = await asyncio.to_thread(_sample)
    return _last_sample


async def _fetch_one_container(c):
    from routers._proxy import proxy_get
    c_id = c["Id"]
    try:
        async with _SEM_STATS:
            stats_raw = await proxy_get(f"/containers/{c_id}/stats?stream=false")
        if not isinstance(stats_raw, dict):
            return c_id, None
        cpu_pct = calc_cpu_percent(stats_raw)
        ms = stats_raw.get("memory_stats", {})
        mem_usage = ms.get("usage", 0)
        async with _SEM_STATS:
            insp = await proxy_get(f"/containers/{c_id}/json")
        mem_limit = None
        if isinstance(insp, dict):
            ml = insp.get("HostConfig", {}).get("Memory", 0)
            mem_limit = ml if ml and ml > 0 else None
        return c_id, {
            "cpu_pct": cpu_pct,
            "mem_usage": mem_usage,
            "mem_limit": mem_limit,
            "inspect": insp if isinstance(insp, dict) else None,
        }
    except Exception:
        return c_id, None


async def _fetch_all_container_stats():
    global _container_stats, _container_stats_as_of
    from routers._proxy import proxy_get
    try:
        containers_raw = await proxy_get("/containers/json?all=1")
    except Exception:
        return
    tasks = [asyncio.create_task(_fetch_one_container(c)) for c in containers_raw]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for c_id, data in results:
        if isinstance(data, dict):
            _container_stats[c_id] = {**data, "sampled_at": now}
    _container_stats_as_of = now


async def sampler_loop(interval: float = 5.0, container_interval: float = 10.0):
    global _last_container_collection
    await take_sample()
    await _fetch_all_container_stats()
    _last_container_collection = time.monotonic()
    while True:
        try:
            now = time.monotonic()
            if now - _last_container_collection >= container_interval:
                await _fetch_all_container_stats()
                _last_container_collection = now
            await take_sample()
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception:
            import traceback
            traceback.print_exc()
            await asyncio.sleep(interval)
