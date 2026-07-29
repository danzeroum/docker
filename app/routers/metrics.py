from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Query
from db import get_host_series, get_findings, get_first_sample_time
from sampler import get_container_stats

router = APIRouter(prefix="/api", tags=["metrics"])


def _ols(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2 = sum(x * x for x in xs)
    sy2 = sum(y * y for y in ys)
    denom = n * sx2 - sx * sx
    if denom == 0:
        return None
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    r2_num = (n * sxy - sx * sy) ** 2
    r2_den = denom * (n * sy2 - sy * sy)
    r2 = r2_num / r2_den if r2_den > 0 else 0.0
    return {"slope_per_day": round(slope, 4), "intercept": round(intercept, 2), "r2": round(r2, 4)}


def _days_to(threshold, slope, intercept):
    if slope <= 0:
        return None
    d = (threshold - intercept) / slope
    return max(1, round(d)) if d > 0 else None


_REPLAY_CACHE = {}


@router.get("/metrics/history")
async def get_metrics_history(
    series: str = Query("disk_pct", pattern="^(cpu_pct|mem_pct|disk_pct|swap_pct)$"),
    range_days: int = Query(30, alias="range", ge=1, le=365),
    step: str = Query("1d", pattern="^(1d|raw)$"),
):
    points = await get_host_series(series, days=range_days, step=step)
    first_sample = await get_first_sample_time()

    result = {"series": points, "projection": None, "coletando_desde": first_sample}

    if not first_sample:
        return result

    try:
        first_dt = datetime.fromisoformat(first_sample.replace("Z", "+00:00"))
        days_collecting = (datetime.now(timezone.utc) - first_dt).days
    except Exception:
        days_collecting = 0

    if days_collecting < 7:
        return result

    daily = await get_host_series(series, days=min(days_collecting, 60), step="1d")
    if len(daily) < 7:
        return result

    last_20 = daily[-20:] if len(daily) >= 20 else daily
    xs = list(range(len(last_20)))
    ys = [p["v"] for p in last_20]
    ols = _ols(xs, ys)
    if not ols or ols.get("r2", 0) < 0.7:
        result["projection"] = {"method": "ols", "r2": ols["r2"] if ols else 0, "stable": False}
        return result

    result["projection"] = {
        "method": "ols",
        "slope_per_day": ols["slope_per_day"],
        "r2": ols["r2"],
        "stable": True,
        "days_to_80": _days_to(80, ols["slope_per_day"], ols["intercept"]),
        "days_to_90": _days_to(90, ols["slope_per_day"], ols["intercept"]),
        "days_to_100": _days_to(100, ols["slope_per_day"], ols["intercept"]),
    }
    return result


@router.get("/capacity")
async def get_capacity():
    findings = await get_findings(status="open")
    critical = [f for f in findings if f.get("severity") in ("critical", "high")]
    cert_findings = [f for f in critical if "cert_" in (f.get("rule") or "")]
    first_sample = await get_first_sample_time()

    containers, _ = get_container_stats()
    mem_limit_sum = 0
    mem_used_sum = 0
    stack_mem = {}
    for cid, data in containers.items():
        if not isinstance(data, dict):
            continue
        insp = data.get("inspect") if isinstance(data.get("inspect"), dict) else {}
        if not isinstance(insp, dict):
            continue
        name = (insp.get("Name") or "").lstrip("/")
        stack = (insp.get("Config", {}).get("Labels", {}) or {}).get("com.docker.compose.project") or "outros"
        if stack not in stack_mem:
            stack_mem[stack] = {"used": 0, "limit": 0, "containers": 0}
        stack_mem[stack]["containers"] += 1
        mu = data.get("mem_usage", 0) or 0
        ml = data.get("mem_limit") or 0
        stack_mem[stack]["used"] += mu
        stack_mem[stack]["limit"] += ml if ml and ml > 0 else 0
        mem_used_sum += mu
        mem_limit_sum += ml if ml and ml > 0 else 0

    memory_by_stack = [
        {
            "name": sk,
            "used_mb": round(v["used"] / (1024 * 1024), 1),
            "limit_mb": round(v["limit"] / (1024 * 1024), 1) if v["limit"] else None,
            "pct": round((v["used"] / v["limit"]) * 100, 1) if v["limit"] else None,
        }
        for sk, v in sorted(stack_mem.items(), key=lambda x: -x[1]["used"])
    ]

    windows = [
        {"label": "24h", "severity": "high", "items": []},
        {"label": "7d", "severity": "medium", "items": []},
        {"label": "30d", "severity": "low", "items": []},
    ]

    for f in cert_findings:
        text = f.get("payload", "{}")
        try:
            import json
            p = json.loads(text) if isinstance(text, str) else text
        except Exception:
            p = {}
        domain = p.get("server_name") or f.get("target", "?")
        expires = p.get("expires_at", "")
        item = {"text": f"Certificado de {domain} vence em {expires}", "source": f"finding:{f['rule']}:{f['id']}"}
        windows[0]["items"].append(item)

    for f in critical:
        if f.get("rule", "").startswith("disk_"):
            pct = json.loads(f.get("payload", "{}")).get("pct", "?") if isinstance(f.get("payload"), str) else "?"
            item = {"text": f"Disco em {f.get('target', '?')}: {pct}%", "source": f"finding:{f['rule']}:{f['id']}"}
            windows[0]["items"].append(item)
        elif f.get("rule", "").startswith("oom") or f.get("rule", "").startswith("restart"):
            item = {"text": f"Container {f.get('target', '?')} em {f.get('rule', '?')}", "source": f"finding:{f['rule']}:{f['id']}"}
            windows[1]["items"].append(item)

    disk_high = [f for f in findings if f.get("rule", "").startswith("disk_") and f.get("severity") == "medium"]
    for f in disk_high:
        item = {"text": f"Disco {f.get('target', '?')} com tendencia de crescimento", "source": f"finding:{f['rule']}:{f['id']}"}
        windows[2]["items"].append(item)

    postura = []
    cert_count = len(cert_findings)
    if cert_count == 0:
        postura.append({"item": "Certificados TLS em dia", "valor": "OK", "status": "ok"})
    else:
        postura.append({"item": "Certificados proximos do vencimento", "valor": str(cert_count), "status": "bad"})

    has_oom = any(f.get("rule", "").startswith("oom") for f in findings)
    postura.append({
        "item": "Containers com OOM",
        "valor": "Sim" if has_oom else "Nao",
        "status": "bad" if has_oom else "ok",
    })

    disk_crit = [f for f in critical if f.get("rule", "").startswith("disk_")]
    postura.append({
        "item": "Discos criticos",
        "valor": str(len(disk_crit)),
        "status": "bad" if disk_crit else "ok",
    })

    no_ssl = [f for f in findings if f.get("rule") == "http_plain"]
    postura.append({
        "item": "HTTP sem TLS",
        "valor": str(len(no_ssl)),
        "status": "warn" if no_ssl else "ok",
    })

    total_containers = sum(v["containers"] for v in stack_mem.values())
    unhealthy = len([c for cid, data in containers.items() if isinstance(data, dict) and data.get("inspect") and isinstance(data["inspect"], dict) and data["inspect"].get("State", {}).get("Health", {}).get("Status") == "unhealthy"])
    postura.append({
        "item": "Containers com saude",
        "valor": f"{total_containers - unhealthy}/{total_containers}" if total_containers else "0/0",
        "status": "warn" if unhealthy else "ok",
    })

    containers_com_restart = 0
    for cid, data in containers.items():
        if not isinstance(data, dict):
            continue
        insp = data.get("inspect")
        if not isinstance(insp, dict):
            continue
        rc = insp.get("RestartCount", 0) or 0
        if rc >= 5:
            containers_com_restart += 1
    if containers_com_restart:
        postura.append({
            "item": "Containers com rein\u00edcio frequente (\u22655 restarts)",
            "valor": str(containers_com_restart),
            "status": "warn",
        })

    return {
        "windows": windows,
        "memory_by_stack": memory_by_stack,
        "postura": postura,
        "coletando_desde": first_sample,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
