import asyncio
import json
import os
import time
from datetime import datetime, timezone
from sampler import get_container_inspects, get_last_sample
from db import upsert_finding, resolve_finding, get_findings, get_finding

_rules = []
_last_run = {}
_debounce_state = {}

_SEVERITY_MAP = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _discover_rules():
    global _rules
    rules_dir = os.path.join(os.path.dirname(__file__), "rules")
    for f in sorted(os.listdir(rules_dir)):
        if not f.endswith(".py") or f.startswith("_"):
            continue
        mod_name = f[:-3]
        import importlib.util
        spec = importlib.util.spec_from_file_location(mod_name, os.path.join(rules_dir, f))
        if not spec or not spec.loader:
            continue
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            import traceback
            traceback.print_exc()
            continue
        if hasattr(mod, "evaluate"):
            _rules.append(mod)


def _calc_score(severity, urgency=1, reach=1):
    return _SEVERITY_MAP.get(severity, 1) * 10 + urgency + min(reach, 3)


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _eval_rule(mod, ctx):
    try:
        return mod.evaluate(ctx)
    except Exception:
        import traceback
        traceback.print_exc()
        return None


def _check_debounce(rule_name, target, mod, existing_history):
    debounce = getattr(mod, "DEBOUNCE", None)
    if not debounce:
        return True
    key = f"{rule_name}.{target}"
    state = _debounce_state.get(key, {"samples": 0, "window_start": None, "window_count": 0})
    samples = debounce.get("samples", 1)
    window_min = debounce.get("window_min")
    window_count = debounce.get("count", 1)

    state["samples"] += 1
    if state["samples"] < samples:
        _debounce_state[key] = state
        return False

    if window_min and window_count > 1:
        now_ts = time.monotonic()
        if state["window_start"] is None:
            state["window_start"] = now_ts
            state["window_count"] = 1
            _debounce_state[key] = state
            if 1 < window_count:
                return False
        else:
            elapsed = (now_ts - state["window_start"]) / 60
            if elapsed > window_min:
                state["window_start"] = now_ts
                state["window_count"] = 1
                _debounce_state[key] = state
                if 1 < window_count:
                    return False
            else:
                state["window_count"] += 1
                _debounce_state[key] = state
                if state["window_count"] < window_count:
                    return False

    _debounce_state[key] = {"samples": 0, "window_start": None, "window_count": 0}
    return True


def _reset_debounce(rule_name, target):
    key = f"{rule_name}.{target}"
    _debounce_state.pop(key, None)


async def _run_cycle():
    containers_map = get_container_inspects()
    host = get_last_sample()
    history = await get_findings(status="open")
    history_by_id = {r["id"]: r for r in history}
    seen_ids = set()
    now = time.monotonic()

    class Ctx:
        pass

    ctx = Ctx()
    ctx.containers = list(containers_map.values())
    ctx.host = host
    ctx.history = history_by_id

    for mod in _rules:
        rule_file = os.path.basename(mod.__file__) if hasattr(mod, "__file__") else ""
        rule_name = rule_file.replace(".py", "") if rule_file else mod.__name__
        min_int = getattr(mod, "MIN_INTERVAL", 10)
        last = _last_run.get(rule_name, 0)
        if now - last < min_int:
            continue
        _last_run[rule_name] = now

        severity = getattr(mod, "SEVERITY", "medium")
        scope = getattr(mod, "SCOPE", "container")

        result = await _eval_rule(mod, ctx)
        if result is None:
            continue

        results = result if isinstance(result, list) else [result]

        for res in results:
            target = res.get("target") if isinstance(res, dict) else None
            if not target:
                continue

            finding_id = f"{rule_name}.{target}"
            seen_ids.add(finding_id)

            if not _check_debounce(rule_name, target, mod, history_by_id.get(finding_id)):
                continue

            payload = {k: v for k, v in res.items() if k not in ("target", "caused_by", "supersedes", "score_override")}
            score = res.get("score_override") or _calc_score(severity)

            finding = {
                "id": finding_id,
                "rule": rule_name,
                "target": target,
                "scope": scope,
                "severity": severity,
                "score": score,
                "caused_by": res.get("caused_by"),
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
            }

            await upsert_finding(finding)

            supersedes = res.get("supersedes")
            if supersedes:
                targets = supersedes if isinstance(supersedes, list) else [supersedes]
                for sid in targets:
                    if sid in history_by_id:
                        await resolve_finding(sid)

    for h_id in history_by_id:
        if h_id not in seen_ids:
            _reset_debounce(*h_id.split(".", 1)) if "." in h_id else None
            await resolve_finding(h_id)


async def findings_loop(interval=10.0):
    _discover_rules()
    while True:
        try:
            await _run_cycle()
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception:
            import traceback
            traceback.print_exc()
            await asyncio.sleep(interval)
