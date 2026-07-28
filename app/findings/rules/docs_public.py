import re

SEVERITY = "high"
SCOPE = "ingress"
MIN_INTERVAL = 30

_DOCS_KEYWORDS = ("docs", "redoc", "openapi.json")


def _is_docs_path(path):
    if not path:
        return False
    # Literal paths
    if path in ("/docs", "/docs/", "/redoc", "/redoc/", "/openapi.json"):
        return True
    # Regex patterns that contain docs keywords
    for kw in _DOCS_KEYWORDS:
        if kw in path:
            return True
    return False


def _public_docs_hosts(cat):
    results = []
    for s in cat.servers:
        name = s.primary_name
        if name == "_":
            continue
        if s.auth_basic:
            continue
        exposed = [loc.path for loc in s.locations if _is_docs_path(loc.path)]
        if exposed:
            results.append((name, exposed))
    return results


def evaluate(ctx):
    cat = getattr(ctx, "ingress", None)
    if not cat:
        return None
    findings = []
    for host, paths in _public_docs_hosts(cat):
        evidence = ", ".join(paths)
        upstream = None
        for s in cat.servers:
            if s.primary_name != host:
                continue
            for loc in s.locations:
                if loc.proxy_pass_resolved and _is_docs_path(loc.path):
                    upstream = loc.proxy_pass_resolved
        payload = {
            "title": f"{host}: documentacao da API exposta sem autenticacao",
            "title_plain": f"Documentacao da API de {host} esta publica",
            "interpretation": f"{host} expoe {evidence} sem auth_basic — rotas de mutacao da API sao reconheciveis por qualquer visitante",
            "interpretation_plain": "Qualquer pessoa na internet pode ler a documentacao da API, incluindo rotas de alteracao de dados",
            "recommendation": "Adicionar auth_basic no location das docs, nao remover os endpoints — desenvolvedores precisam deles",
            "impact": "Reconhecimento gratuito da superficie de ataque da API — incluindo rotas POST/PUT/DELETE",
            "evidence": evidence,
            "facts": [
                {"key": "Host", "value": host, "tone": "warn"},
                {"key": "Endpoints expostos", "value": evidence, "tone": "warn"},
                {"key": "Autenticacao", "value": "ausente", "tone": "warn"},
            ],
            "actions": [
                {
                    "title": "Adicionar auth_basic nas docs",
                    "detail": "Incluir auth_basic e auth_basic_user_file no location ~ ^/(docs|redoc)/ e location = /openapi.json",
                    "command": "",
                    "risk": "baixo — desenvolvedores autenticados continuam acessando",
                    "applies_via": "editar nginx.conf",
                }
            ],
        }
        if upstream:
            payload["upstream"] = upstream
        findings.append({"target": host, **payload})
    return findings or None
