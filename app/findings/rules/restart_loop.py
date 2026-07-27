SEVERITY = "critical"
SCOPE = "container"
MIN_INTERVAL = 10
DEBOUNCE = {"window_min": 30, "count": 3}

# In-memory tracking of restart count per container between cycles
_prev_restart = {}


def evaluate(ctx):
    findings = []
    for c in ctx.containers:
        if not isinstance(c, dict):
            continue
        state = c.get("State", {})
        name = c.get("Name", "").lstrip("/")
        if not name:
            continue
        restart_count = state.get("RestartCount", 0)
        if restart_count < 1:
            continue
        prev = _prev_restart.get(name, 0)
        if restart_count <= prev:
            continue
        _prev_restart[name] = restart_count
        image = c.get("Config", {}).get("Image", "")
        health = state.get("Health", {}).get("Status", "none")
        findings.append({
            "target": name,
            "supersedes": [f"oom.{name}"],
            "title": f"{name} em ciclo de rein\u00edcio ({restart_count}x)",
            "title_plain": f"Container {name} reiniciando repetidamente",
            "interpretation": f"Reiniciou {restart_count} vezes (ant: {prev})",
            "interpretation_plain": "O servi\u00e7o n\u00e3o consegue manter-se em execu\u00e7\u00e3o",
            "recommendation": "Verificar logs do container e sa\u00fade do servi\u00e7o",
            "evidence": f"Image: {image} | Health: {health}",
            "impact": "Servi\u00e7o inst\u00e1vel",
            "facts": [
                {"key": "Restarts", "value": str(restart_count), "tone": "bad"},
                {"key": "Health", "value": health, "tone": "bad" if health == "unhealthy" else "neutral"},
            ],
            "actions": [
                {
                    "title": "Inspecionar logs do container",
                    "detail": "docker logs para identificar a causa do rein\u00edcio",
                    "command": f"docker logs {name} --tail 50",
                    "risk": "nenhum",
                    "applies_via": "manual",
                }
            ],
        })
    return findings or None
