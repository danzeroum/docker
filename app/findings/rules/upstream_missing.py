import re

SEVERITY = "high"
SCOPE = "ingress"
MIN_INTERVAL = 60


def _extract_container_name(url):
    m = re.match(r"https?://([^:/]+)(?::\d+)?", url)
    return m.group(1) if m else None


def evaluate(ctx):
    cat = getattr(ctx, "ingress", None)
    if not cat:
        return None
    containers = getattr(ctx, "containers", [])
    # O inventario vem de /containers/json?all=1: inclui PARADOS. Container
    # parado nao atende, entao contar como presente era sub-reportar — em
    # producao, criptotrade e prompte davam 502 com a fila em silencio.
    # Guardamos os dois conjuntos para dizer QUAL e o conserto: subir a stack
    # ou corrigir o proxy_pass.
    rodando, existentes = set(), set()
    for c in containers:
        if not isinstance(c, dict):
            continue
        name = (c.get("Name") or "").lstrip("/")
        if not name:
            continue
        existentes.add(name)
        if (c.get("State") or {}).get("Running"):
            rodando.add(name)
    if not existentes:
        return None
    container_names = rodando
    findings = []
    seen = set()
    for s in cat.servers:
        for loc in s.locations:
            upstream = loc.proxy_pass_resolved or loc.proxy_pass
            if not upstream:
                continue
            cname = _extract_container_name(upstream)
            if cname and cname not in container_names:
                key = (s.primary_name, cname)
                if key in seen:
                    continue
                seen.add(key)
                parado = cname in existentes
                situacao = "esta parado" if parado else "nao existe"
                conserto = (
                    f"Subir a stack de {cname}"
                    if parado else
                    f"Verificar se {cname} foi renomeado ou removido do docker-compose"
                )
                findings.append({
                    "target": s.primary_name,
                    "title": f"{s.primary_name}: upstream {cname} {situacao}",
                    "title_plain": f"Upstream {cname} em {s.primary_name} nao corresponde a nenhum container ativo",
                    "interpretation": f"O servico {s.primary_name} faz proxy_pass para {upstream}, "
                        f"mas o container {cname} nao consta no inventario do Docker. "
                        f"O proxy encaminhara requisicoes para um destino inexistente",
                    "interpretation_plain": f"O nginx encaminha trafego para {cname}, que nao e um container em execucao",
                    "recommendation": f"{conserto}. O nginx encaminha {s.primary_name} para {upstream}",
                    "impact": f"Requisicoes para {s.primary_name} sao encaminhadas para um destino inexistente — "
                        f"erro 502 Bad Gateway para o usuario",
                    "evidence": f"proxy_pass={upstream} em {s.primary_name}/ — container {cname} {situacao}",
                    "facts": [
                        {"key": "Host", "value": s.primary_name, "tone": "warn"},
                        {"key": "Upstream ausente", "value": cname, "tone": "error"},
                        {"key": "Endereco", "value": upstream, "tone": "neutral"},
                    ],
                    "actions": [
                        {
                            "title": "Corrigir proxy_pass",
                            "detail": f"Atualizar proxy_pass em {s.primary_name} para apontar para container existente",
                            "command": "",
                            "risk": "baixo — apenas redireciona para o container correto",
                            "applies_via": "editar nginx.conf",
                        }
                    ],
                    "upstream": upstream,
                })
    return findings or None
