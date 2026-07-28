SEVERITY = "medium"
SCOPE = "ingress"
MIN_INTERVAL = 30

_LOW_TIMEOUT = 120


def _low_timeout_hosts(cat):
    results = []
    for s in cat.servers:
        name = s.primary_name
        if name == "_":
            continue
        for loc in s.locations:
            raw = loc.proxy_read_timeout
            if not raw:
                continue
            val = _parse_seconds(raw)
            if val is not None and 0 < val < _LOW_TIMEOUT:
                results.append((name, loc.path, val, loc.proxy_pass_resolved))
    return results


def _parse_seconds(raw):
    raw = raw.strip().lower()
    try:
        if raw.endswith("s"):
            return int(float(raw[:-1]))
        if raw.endswith("m"):
            return int(float(raw[:-1]) * 60)
        if raw.endswith("h"):
            return int(float(raw[:-1]) * 3600)
        return int(float(raw))
    except (ValueError, TypeError):
        return None


def evaluate(ctx):
    cat = getattr(ctx, "ingress", None)
    if not cat:
        return None
    findings = []
    for host, path, timeout, upstream in _low_timeout_hosts(cat):
        payload = {
            "title": f"{host}: proxy_read_timeout {timeout}s pode interromper streaming",
            "title_plain": f"proxy_read_timeout de {timeout}s em {host} afeta conexoes longas",
            "interpretation": f"Location {path} em {host} tem proxy_read_timeout={timeout}s — "
                f"conexoes SSE (logs) e WebSocket (metricas) serao cortadas apos {timeout}s de inatividade",
            "interpretation_plain": f"Timeout de {timeout}s em proxy_pass encerra streamings como logs e metricas em tempo real",
            "recommendation": f"Aumentar proxy_read_timeout para 3600s ou remover o parametro. "
                f"Com {timeout}s, o servidor corta SSE de logs e WebSocket de metricas — "
                f"o cockpit perde a capacidade de streaming continuo",
            "impact": f"Conexoes SSE (logs) e WebSocket (stats) sao encerradas apos {timeout}s sem dados",
            "evidence": f"proxy_read_timeout={timeout}s em {host}{path}",
            "facts": [
                {"key": "Host", "value": host, "tone": "warn"},
                {"key": "Location", "value": path, "tone": "neutral"},
                {"key": "Timeout", "value": f"{timeout}s", "tone": "warn"},
                {"key": "Afeta", "value": "SSE logs + WebSocket metricas", "tone": "warn"},
            ],
            "actions": [
                {
                    "title": "Aumentar proxy_read_timeout",
                    "detail": f"Alterar proxy_read_timeout para 3600s ou remover em {host}{path}",
                    "command": "",
                    "risk": "baixo — apenas conexoes ociosas passam a durar mais",
                    "applies_via": "editar nginx.conf",
                }
            ],
        }
        if upstream:
            payload["upstream"] = upstream
        findings.append({"target": host, **payload})
    return findings or None
