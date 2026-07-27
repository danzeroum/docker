SEVERITY = "critical"
SCOPE = "container"
MIN_INTERVAL = 10


def evaluate(ctx):
    findings = []
    for c in ctx.containers:
        if not isinstance(c, dict):
            continue
        state = c.get("State", {})
        name = c.get("Name", "").lstrip("/")
        if not name:
            continue
        oom = state.get("OOMKilled") is True
        exit_code = state.get("ExitCode")
        if not oom and exit_code != 137:
            continue
        oom_text = "sim" if oom else "n\u00e3o"
        image = c.get("Config", {}).get("Image", "")
        findings.append({
            "target": name,
            "title": f"{name} morto pelo kernel — OOMKilled" if oom else f"{name} encerrado com exit {exit_code}",
            "title_plain": f"Container {name} parou de funcionar",
            "interpretation": "OOMKilled pelo kernel" if oom else f"Exit code {exit_code}",
            "interpretation_plain": "O kernel interrompeu o container por falta de mem\u00f3ria",
            "recommendation": "Aumentar o limite de mem\u00f3ria do container ou investigar vazamento",
            "evidence": f"Image: {image}",
            "impact": "Servi\u00e7o pode estar fora do ar",
            "facts": [
                {"key": "Exit code", "value": str(exit_code), "tone": "bad"},
                {"key": "OOMKilled", "value": oom_text, "tone": "bad"},
            ],
            "actions": [
                {
                    "title": "Subir o limite de mem\u00f3ria e reiniciar",
                    "detail": "Ajustar mem_limit no docker-compose.yml e reiniciar o container",
                    "command": (
                        f"docker compose up -d --no-deps {name.split('_')[0] if '_' in name else name}"
                    ),
                    "risk": "rein\u00edcio de ~8s",
                    "applies_via": "manual",
                }
            ],
        })
    return findings or None
