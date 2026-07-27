from datetime import datetime, timezone

SEVERITY = "medium"
SCOPE = "container"
MIN_INTERVAL = 30


def _parse_ts(ts_str):
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def evaluate(ctx):
    findings = []
    now = datetime.now(timezone.utc)
    for c in ctx.containers:
        if not isinstance(c, dict):
            continue
        state = c.get("State", {})
        health = state.get("Health")
        if not health:
            continue
        if health.get("Status") != "unhealthy":
            continue
        failing_streak = health.get("FailingStreak", 0)
        if failing_streak < 10:
            continue
        log = health.get("Log", [])
        if not log:
            continue
        if any(e.get("ExitCode") == 0 for e in log):
            continue
        started = state.get("StartedAt", "")
        started_dt = _parse_ts(started)
        if not started_dt:
            continue
        uptime_s = (now - started_dt).total_seconds()
        if uptime_s <= 0:
            continue
        timestamps = []
        for entry in log:
            ts = _parse_ts(entry.get("Start", ""))
            if ts:
                timestamps.append(ts)
        if len(timestamps) < 2:
            continue
        timestamps.sort()
        gaps = [(timestamps[i+1] - timestamps[i]).total_seconds() for i in range(len(timestamps)-1)]
        avg_int = sum(gaps) / len(gaps)
        if avg_int <= 0:
            continue
        ratio = failing_streak * avg_int / uptime_s
        if ratio < 0.7:
            continue
        name = c.get("Name", "").lstrip("/")
        if not name:
            continue
        evidence_lines = []
        for e in log[-3:]:
            out = (e.get("Output") or "")[:80].replace("\n", " ")
            if out:
                evidence_lines.append(out)
        findings.append({
            "target": name,
            "supersedes": [f"unhealthy.{name}"],
            "title": f"{name}: sonda de sa\u00fade nunca passou",
            "title_plain": f"Healthcheck de {name} nunca teve sucesso",
            "interpretation": f"FailingStreak={failing_streak} em {uptime_s/3600:.1f}h de uptime, intervalo {avg_int:.0f}s \u2014 sonda falhou desde o deploy",
            "interpretation_plain": "A sonda de sa\u00fade nunca acertou \u2014 o servi\u00e7o pode estar saud\u00e1vel",
            "recommendation": "Corrigir o healthcheck no Dockerfile (porta/comando), n\u00e3o reiniciar o container",
            "evidence": "; ".join(evidence_lines) if evidence_lines else f"Sonda falhou {failing_streak}x consecutivas desde o \u00faltimo deploy",
            "impact": "Alarme falso \u2014 mascara incidentes reais na fila",
            "facts": [
                {"key": "FailingStreak", "value": str(failing_streak), "tone": "warn"},
                {"key": "Uptime", "value": f"{uptime_s/3600:.1f}h", "tone": "neutral"},
                {"key": "Intervalo", "value": f"{avg_int:.0f}s", "tone": "neutral"},
            ],
            "actions": [
                {
                    "title": "Corrigir healthcheck",
                    "detail": "Atualizar comando e porta no Dockerfile do servi\u00e7o",
                    "command": "",
                    "risk": "altera\u00e7\u00e3o de build",
                    "applies_via": "manual",
                }
            ],
        })
    return findings or None
