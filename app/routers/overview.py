import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter
from routers._proxy import proxy_get
from cache import cached_or_fetch
from stats_util import calc_cpu_percent
from sampler import get_last_sample

router = APIRouter(prefix="/api", tags=["overview"])

_SEM = asyncio.Semaphore(8)

def _normalize_created(raw):
    created = raw.get("Created")
    if not created:
        return None
    if isinstance(created, (int, float)):
        return datetime.fromtimestamp(created, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    if created.endswith("Z"):
        return created
    return created.replace("+00:00", "Z") if "+" in created else created + "Z"

def _pick_exposure(ports):
    for host_port in ports:
        if host_port.get("IP") == "0.0.0.0":
            return "internet"
    return "pendente"

def _container_health_state(inspect_data):
    state = inspect_data.get("State", {})
    health = state.get("Health")
    if health:
        return health.get("Status", "none")
    if state.get("Running"):
        return "none"
    if state.get("ExitCode") == 0:
        return "healthy"
    return "unhealthy"

async def _fetch_container_data(c_id, c_raw):
    stack = c_raw.get("Labels", {}).get("com.docker.compose.project") or "sem stack"
    name = (c_raw.get("Names") or ["/"])[0].lstrip("/")
    state = c_raw.get("State", "unknown")
    image = c_raw.get("Image", "")
    raw_ports = c_raw.get("Ports") or []
    async with _SEM:
        insp, stats_raw = await asyncio.gather(
            proxy_get(f"/containers/{c_id}/json"),
            proxy_get(f"/containers/{c_id}/stats?stream=false"),
            return_exceptions=True,
        )
    health = "none"
    mem_limit = None
    if isinstance(insp, dict):
        health = _container_health_state(insp)
        host_config = insp.get("HostConfig", {})
        ml = host_config.get("Memory", 0)
        mem_limit = ml if ml and ml > 0 else None
    cpu_pct = 0.0
    mem_pct = None
    mem_usage = 0
    if isinstance(stats_raw, dict):
        cpu_pct = calc_cpu_percent(stats_raw)
        ms = stats_raw.get("memory_stats", {})
        mem_usage = ms.get("usage", 0)
        if mem_limit is not None:
            mem_pct = round((mem_usage / mem_limit) * 100, 1) if mem_limit else 0.0
        else:
            mem_pct = None
    return {
        "id": c_id,
        "name": name,
        "stack": stack,
        "image": image,
        "state": state,
        "health": health,
        "restart_count": c_raw.get("RestartCount", 0),
        "created": _normalize_created(c_raw),
        "cpu_pct": cpu_pct,
        "mem_pct": mem_pct,
        "mem_usage": mem_usage,
        "mem_limit": mem_limit,
        "ports": ", ".join(f"{p.get('PublicPort', '?')}/{p.get('Type', 'tcp')}" for p in raw_ports if p.get("PublicPort")),
        "exposure": _pick_exposure(raw_ports),
        "finding_ids": [],
    }

@router.get("/overview")
async def get_overview():
    async def factory():
        containers_raw, _ = await cached_or_fetch("containers_list", ttl=2.0, factory=lambda: proxy_get("/containers/json?all=1"))
        tasks = [asyncio.create_task(_fetch_container_data(c["Id"], c)) for c in containers_raw]
        containers = await asyncio.gather(*tasks)

        sample = get_last_sample()
        host_info = {"name": "", "cpus": 0, "mem_total_gb": 0, "os": "", "docker": "", "uptime_seconds": 0}
        vitals = {"cpu_pct": 0, "mem_pct": 0, "mem_used_gb": 0, "swap_pct": 0, "disk": {"mountpoint": "/", "pct": 0, "used_gb": 0, "total_gb": 0}, "net_rx_bps": 0, "net_tx_bps": 0}
        if sample:
            host_info["name"] = sample.get("platform", "")
            host_info["cpus"] = (sample.get("cpu") or {}).get("count", 0)
            host_info["mem_total_gb"] = round(((sample.get("memory") or {}).get("total", 0) or 0) / (1024**3), 2)
            host_info["os"] = f"{sample.get('platform', '')} {sample.get('platform_version', '')}"
            host_info["uptime_seconds"] = sample.get("uptime_seconds", 0)
            cpu = sample.get("cpu", {})
            vitals["cpu_pct"] = cpu.get("percent", 0)
            mem = sample.get("memory", {})
            vitals["mem_pct"] = mem.get("percent", 0)
            vitals["mem_used_gb"] = round((mem.get("used", 0) or 0) / (1024**3), 2)
            swap = sample.get("swap", {})
            vitals["swap_pct"] = swap.get("percent", 0)
            disks = sample.get("disks", [])
            root = next((d for d in disks if d.get("mountpoint") == "/"), None) or (disks[0] if disks else None)
            if root:
                vitals["disk"] = {"mountpoint": root["mountpoint"], "pct": root["percent"], "used_gb": round((root.get("used", 0) or 0) / (1024**3), 2), "total_gb": round((root.get("total", 0) or 0) / (1024**3), 2)}
            net = sample.get("network", {})
            vitals["net_rx_bps"] = net.get("bytes_recv", 0)
            vitals["net_tx_bps"] = net.get("bytes_sent", 0)

        stacks_map = {}
        for c in containers:
            sk = c["stack"]
            if sk not in stacks_map:
                stacks_map[sk] = {"id": sk, "running": 0, "total": 0, "worst": "ok", "containers": []}
            stacks_map[sk]["total"] += 1
            stacks_map[sk]["containers"].append(c["name"])
            if c["state"] == "running":
                stacks_map[sk]["running"] += 1
            worst = "ok"
            if c["health"] == "unhealthy" or c["state"] == "restarting":
                worst = "bad"
            elif c["state"] != "running" and worst != "bad":
                worst = "warn"
            if worst == "bad":
                stacks_map[sk]["worst"] = "bad"
            elif worst == "warn" and stacks_map[sk]["worst"] != "bad":
                stacks_map[sk]["worst"] = "warn"

        stacks = sorted(stacks_map.values(), key=lambda s: (s["id"] == "sem stack", s["id"]))

        counters = {"total": len(containers), "running": 0, "exited": 0, "attention": 0}
        for c in containers:
            if c["state"] == "running":
                counters["running"] += 1
            else:
                counters["exited"] += 1
            if c["state"] == "restarting" or c["health"] == "unhealthy":
                counters["attention"] += 1

        return {
            "host": host_info,
            "vitals": vitals,
            "stacks": stacks,
            "containers": containers,
            "counters": counters,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "cache_ttl_s": 5,
        }

    data, _ = await cached_or_fetch("overview", ttl=5.0, factory=factory, timeout=30.0)
    return data


@router.get("/stats/all")
async def get_stats_all():
    async def factory():
        containers_raw, _ = await cached_or_fetch("containers_list", ttl=2.0, factory=lambda: proxy_get("/containers/json?all=1"))

        async def _fetch_stats(c_id, c_raw):
            async with _SEM:
                stats_raw = await proxy_get(f"/containers/{c_id}/stats?stream=false")
            if not isinstance(stats_raw, dict):
                return {"id": c_id, "name": (c_raw.get("Names") or ["/"])[0].lstrip("/"), "cpu_pct": 0, "mem_pct": 0, "mem_usage": 0, "mem_limit": None}
            ms = stats_raw.get("memory_stats", {})
            mem_usage = ms.get("usage", 0)
            insp = None
            try:
                insp = await asyncio.wait_for(asyncio.shield(proxy_get(f"/containers/{c_id}/json")), timeout=10)
            except Exception:
                pass
            mem_limit = None
            if isinstance(insp, dict):
                ml = insp.get("HostConfig", {}).get("Memory", 0)
                mem_limit = ml if ml and ml > 0 else None
            mem_pct = None
            if mem_limit is not None:
                mem_pct = round((mem_usage / mem_limit) * 100, 1) if mem_limit else 0.0
            return {
                "id": c_id,
                "name": (c_raw.get("Names") or ["/"])[0].lstrip("/"),
                "stack": c_raw.get("Labels", {}).get("com.docker.compose.project") or "sem stack",
                "cpu_pct": calc_cpu_percent(stats_raw),
                "mem_pct": mem_pct,
                "mem_usage": mem_usage,
                "mem_limit": mem_limit,
            }

        tasks = [asyncio.create_task(_fetch_stats(c["Id"], c)) for c in containers_raw]
        return await asyncio.gather(*tasks)

    data, _ = await cached_or_fetch("stats_all", ttl=5.0, factory=factory, timeout=30.0)
    return data
