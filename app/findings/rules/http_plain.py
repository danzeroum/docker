SEVERITY = "critical"
SCOPE = "ingress"
MIN_INTERVAL = 30


def _hosts_serving_http(cat):
    """Return hosts that serve content on port 80 without HTTPS redirect."""
    results = []
    seen = set()
    for s in cat.servers:
        port_80 = any(l["port"] == 80 for l in s.listen)
        if not port_80:
            continue
        name = s.primary_name
        if name == "_" or name in seen:
            continue
        seen.add(name)
        has_redirect = False
        serves_content = False
        for loc in s.locations:
            if loc.path == "/" and loc.return_code == 301:
                has_redirect = True
            if loc.proxy_pass_resolved and loc.path != "/.well-known/acme-challenge/":
                serves_content = True
        if not has_redirect and serves_content:
            results.append(name)
    return results


def evaluate(ctx):
    cat = getattr(ctx, "ingress", None)
    if not cat:
        return None
    findings = []
    for host in _hosts_serving_http(cat):
        upstream = None
        for s in cat.servers:
            if s.primary_name != host:
                continue
            for loc in s.locations:
                if loc.proxy_pass_resolved and loc.path != "/.well-known/acme-challenge/":
                    upstream = loc.proxy_pass_resolved
        payload = {
            "title": f"{host}: HTTP sem redirecionamento HTTPS",
            # Sem o dominio: o _plain e a frase do gestor, e o Resumo executivo
            # nomeia servico pelo mapa de negocio, nunca pelo host tecnico.
            "title_plain": "Um servico esta acessivel sem criptografia",
            "interpretation": f"{host} expoe servicos em HTTP (porta 80) sem redirecionar para HTTPS",
            "interpretation_plain": (
                "Quem enviar senha ou dados nesse endereco trafega em texto "
                "aberto, visivel para quem estiver no caminho da rede"
            ),
            "impact_plain": "Senhas e dados de clientes podem ser interceptados",
            "recommendation_plain": (
                "Forcar o acesso criptografado; pode exigir avisar quem integra "
                "com o servico hoje"
            ),
            "requires_approval": True,
            "recommendation": "Adicionar location / { return 301 https://$host$request_uri; } no server de porta 80 — cookies de sessao, credenciais de login e payloads trafegam em texto claro",
            "impact": "Cada requisicao HTTP expoe cookies de sessao e corpos de requisicao em texto claro para qualquer um no caminho da rede",
            "evidence": f"Servidor HTTP em {host} nao redireciona para HTTPS",
            "facts": [
                {"key": "Porta", "value": "80", "tone": "warn"},
                {"key": "Host", "value": host, "tone": "neutral"},
                {"key": "Redirecionamento", "value": "ausente", "tone": "warn"},
            ],
            "actions": [
                {
                    "title": "Migrar servico para HTTPS",
                    "detail": "Incluir location / { return 301 https://$host$request_uri; } no server de porta 80 e garantir que o SSL esta configurado no server 443",
                    "command": "",
                    "risk": "medio — redirecionamento quebra clientes HTTP puro, verificar logs de acesso antes",
                    "applies_via": "editar nginx.conf",
                }
            ],
        }
        if upstream:
            payload["upstream"] = upstream
        findings.append({"target": host, **payload})
    return findings or None
