SEVERITY = "low"
SCOPE = "ingress"
MIN_INTERVAL = 60
AGGREGATE = True


def _host_has_explicit_body_size(server):
    if server.client_max_body_size:
        return True
    for loc in server.locations:
        if loc.path == "/" and not loc.is_regex and loc.client_max_body_size:
            return True
    return False


def evaluate(ctx):
    cat = getattr(ctx, "ingress", None)
    if not cat:
        return None
    affected = []
    for s in cat.servers:
        name = s.primary_name
        if name == "_":
            continue
        if not any(l.get("ssl", False) for l in s.listen) and not s.has_ssl:
            continue
        if _host_has_explicit_body_size(s):
            continue
        affected.append(name)
    if not affected:
        return None
    return {
        "targets": affected,
        "title": f"{len(affected)} hosts usam client_max_body_size padrao (1MB)",
        "title_plain": "client_max_body_size nao configurado em nenhum location",
        "interpretation": f"{len(affected)} hosts nao definem client_max_body_size "
            "explicitamente em nenhum location — herdam o padrao de 1MB do nginx. "
            "Isso pode rejeitar uploads legitimos sem feedback claro ao usuario",
        "interpretation_plain": "Limite de upload padrao de 1MB ativo em "
            f"{len(affected)} hosts — uploads maiores sao rejeitados silenciosamente",
        "recommendation": "Configurar client_max_body_size explicitamente nos "
            "locations que aceitam upload, ajustando ao tamanho esperado dos arquivos. "
            "Incluir um location = /50x.html com pagina de erro amigavel para 413",
        "impact": "Uploads acima de 1MB sao rejeitados com 413 Request Entity Too Large",
        "evidence": f"{len(affected)} hosts sem client_max_body_size explicito",
        "facts": [
            {"key": "Hosts afetados", "value": str(len(affected)), "tone": "info"},
            {"key": "Limite atual", "value": "1MB (padrao nginx)", "tone": "info"},
        ],
        "actions": [
            {
                "title": "Configurar client_max_body_size",
                "detail": "Adicionar client_max_body_size nos locations de upload",
                "command": "",
                "risk": "baixo — ajustar ao tamanho esperado dos arquivos",
                "applies_via": "editar nginx.conf",
            }
        ],
    }
