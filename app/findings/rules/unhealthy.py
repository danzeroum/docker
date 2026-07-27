SEVERITY = "high"
SCOPE = "container"
MIN_INTERVAL = 10
DEBOUNCE = {"samples": 2}


def evaluate(ctx):
    findings = []
    for c in ctx.containers:
        if not isinstance(c, dict):
            continue
        state = c.get("State", {})
        name = c.get("Name", "").lstrip("/")
        if not name:
            continue
        if not state.get("Running"):
            continue
        health_status = state.get("Health", {}).get("Status")
        if health_status != "unhealthy":
            continue
        image = c.get("Config", {}).get("Image", "")
        findings.append({
            "target": name,
            "title": f"{name} com sa\u00fade falhando — {health_status}",
            "title_plain": f"Container {name} n\u00e3o est\u00e1 saud\u00e1vel",
            "interpretation": f"Health check retornou {health_status}",
            "interpretation_plain": "O container est\u00e1 rodando mas o servi\u00e7o n\u00e3o responde",
            "recommendation": "Verificar logs do container e investigar a causa do health check falho",
            "evidence": f"Image: {image}",
            "impact": "Servi\u00e7o pode estar degradado",
            "facts": [
                {"key": "Health", "value": health_status, "tone": "bad"},
            ],
            "actions": [
                {
                    "title": "Verificar logs do container",
                    "detail": "docker logs para identificar a causa",
                    "command": f"docker logs {name} --tail 50",
                    "risk": "nenhum",
                    "applies_via": "manual",
                }
            ],
        })
    return findings or None
