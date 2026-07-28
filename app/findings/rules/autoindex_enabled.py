SEVERITY = "medium"
SCOPE = "ingress"
MIN_INTERVAL = 60


def evaluate(ctx):
    cat = getattr(ctx, "ingress", None)
    if not cat:
        return None
    findings = []
    for s in cat.servers:
        name = s.primary_name
        if name == "_":
            continue
        for loc in s.locations:
            if loc.autoindex == "on":
                findings.append({
                    "target": name,
                    "title": f"{name}{loc.path}: listagem de diretorio publica",
                    "title_plain": f"Listagem de diretorio habilitada em {name}{loc.path}",
                    "interpretation": f"O location {loc.path} em {name} tem autoindex on — "
                        f"qualquer visitante pode navegar pela arvore de diretorios e "
                        f"descobrir arquivos nao previstos",
                    "interpretation_plain": f"Diretorio {loc.path} em {name} exibe seu conteudo para qualquer visitante",
                    "recommendation": "Remover autoindex on ou restringir o location com auth_basic. "
                        "Se o servico precisa de listagem, limitar por IP interno",
                    "impact": "Vazamento de estrutura de diretorios e arquivos nao intencionais",
                    "evidence": f"autoindex on em {name}{loc.path}",
                    "facts": [
                        {"key": "Host", "value": name, "tone": "warn"},
                        {"key": "Location", "value": loc.path, "tone": "warn"},
                        {"key": "autoindex", "value": "on", "tone": "error"},
                    ],
                    "actions": [
                        {
                            "title": "Desabilitar autoindex",
                            "detail": f"Remover autoindex on do location {loc.path} em {name}",
                            "command": "",
                            "risk": "baixo — nenhum impacto",
                            "applies_via": "editar nginx.conf",
                        }
                    ],
                })
    return findings or None
