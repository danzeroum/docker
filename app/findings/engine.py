import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from sampler import get_container_inspects, get_last_sample
from db import (upsert_finding, resolve_finding, get_findings, get_finding,
                create_task_from_finding, resolve_task_for_finding,
                reopen_task_for_finding)

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


def _extract_container_from_upstream(url):
    if not url:
        return None
    m = re.match(r"https?://([^:/]+)(?::\d+)?", url)
    return m.group(1) if m else None


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


async def _sync_task(mod, finding, payload, estado):
    """Espelha o achado no board, para regras que declaram AUTO_TASK = True.

    `estado` vem do upsert: "created" | "reopened" | "updated".

    - created  -> abre o cartao (idempotente; o indice unico parcial protege)
    - reopened -> o achado voltou dentro dos 30 min: tira o cartao de done em vez
                  de abrir um segundo. Sem isto o cartao ficaria orfao em done com
                  o problema vivo.
    - updated  -> nada; e so mais uma observacao do mesmo achado.
    """
    if not getattr(mod, "AUTO_TASK", False):
        return
    dados = dict(finding)
    dados["title"] = payload.get("title") or finding.get("rule")
    dados["recommendation"] = payload.get("recommendation") or ""
    if estado == "created":
        await create_task_from_finding(dados)
    elif estado == "reopened":
        movidos = await reopen_task_for_finding(finding["id"])
        if not movidos:
            # cartao nunca existiu (regra ganhou AUTO_TASK depois do achado)
            await create_task_from_finding(dados)


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

    nginx_path = os.getenv("NGINX_CONFIG_PATH", "/etc/nginx/nginx.conf")
    try:
        if os.path.isfile(nginx_path):
            from ingress.parser import parse_file
            ctx.ingress = parse_file(nginx_path)
        else:
            ctx.ingress = None
    except Exception:
        ctx.ingress = None

    container_names = set()
    for c in ctx.containers:
        if isinstance(c, dict):
            name = c.get("Name", "")
            if name.startswith("/"):
                container_names.add(name[1:])

    pending_supersedes = []
    rules_run = set()

    for mod in _rules:
        rule_file = os.path.basename(mod.__file__) if hasattr(mod, "__file__") else ""
        rule_name = rule_file.replace(".py", "") if rule_file else mod.__name__
        min_int = getattr(mod, "MIN_INTERVAL", 10)
        last = _last_run.get(rule_name, 0)
        if now - last < min_int:
            continue
        _last_run[rule_name] = now
        rules_run.add(rule_name)

        severity = getattr(mod, "SEVERITY", "medium")
        scope = getattr(mod, "SCOPE", "container")
        aggregate = getattr(mod, "AGGREGATE", False)

        result = await _eval_rule(mod, ctx)
        if result is None:
            continue

        results = result if isinstance(result, list) else [result]

        for res in results:
            if aggregate:
                targets_list = res.get("targets") if isinstance(res, dict) else None
                if not targets_list:
                    continue
                finding_id = rule_name
                seen_ids.add(finding_id)
                if not _check_debounce(rule_name, "_", mod, history_by_id.get(finding_id)):
                    continue
                payload = {k: v for k, v in res.items() if k not in ("targets", "target", "caused_by", "supersedes", "score_override")}
                score = res.get("score_override") or _calc_score(severity)
                finding = {
                    "id": finding_id,
                    "rule": rule_name,
                    "target": None,
                    "targets": json.dumps(targets_list, ensure_ascii=False),
                    "scope": scope,
                    "severity": severity,
                    "score": score,
                    "caused_by": res.get("caused_by"),
                    "payload": json.dumps(payload, ensure_ascii=False, default=str),
                }
                estado = await upsert_finding(finding)
                await _sync_task(mod, finding, payload, estado)
                supersedes = res.get("supersedes")
                if supersedes:
                    targets = supersedes if isinstance(supersedes, list) else [supersedes]
                    pending_supersedes.extend(targets)
                continue

            target = res.get("target") if isinstance(res, dict) else None
            if not target:
                continue

            finding_id = f"{rule_name}.{target}"
            seen_ids.add(finding_id)

            if not _check_debounce(rule_name, target, mod, history_by_id.get(finding_id)):
                continue

            payload = {k: v for k, v in res.items() if k not in ("target", "caused_by", "supersedes", "score_override")}
            score = res.get("score_override") or _calc_score(severity)

            if scope == "ingress":
                upstream_url = payload.get("upstream")
                if upstream_url:
                    cname = _extract_container_from_upstream(upstream_url)
                    if cname and cname in container_names:
                        payload["related_container"] = cname

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

            estado = await upsert_finding(finding)
            await _sync_task(mod, finding, payload, estado)

            supersedes = res.get("supersedes")
            if supersedes:
                targets = supersedes if isinstance(supersedes, list) else [supersedes]
                pending_supersedes.extend(targets)

    # Supersede NAO fecha cartao. `oom` suplantar `restart_loop` significa que os
    # dois sao sintoma do mesmo problema — que continua vivo. Fechar o cartao aqui
    # marcaria como feito um trabalho que ninguem fez.
    for sid in pending_supersedes:
        if sid in history_by_id or sid in seen_ids:
            await resolve_finding(sid)

    for h_id in history_by_id:
        if h_id not in seen_ids:
            if "." in h_id:
                rule_of = h_id.split(".", 1)[0]
            else:
                rule_of = h_id
            if rule_of and rule_of not in rules_run:
                continue
            if "." in h_id:
                _reset_debounce(*h_id.split(".", 1))
            else:
                _reset_debounce(rule_of, "_")
            await resolve_finding(h_id)
            # Unico ponto que fecha cartao: o achado sumiu do ciclo por conta
            # propria. Distinto do supersede acima, de proposito.
            await resolve_task_for_finding(h_id)


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
