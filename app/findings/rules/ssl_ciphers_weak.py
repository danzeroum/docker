SEVERITY = "high"
SCOPE = "ingress"
MIN_INTERVAL = 60

_WEAK_KEYWORDS = {"LOW", "MEDIUM", "RC4", "DES", "3DES", "EXPORT", "NULL", "aNULL",
                   "eNULL", "ADH", "AECDH", "MD5"}


def _has_weak_ciphers(ciphers_str):
    if not ciphers_str:
        return False
    upper = ciphers_str.upper()
    for kw in _WEAK_KEYWORDS:
        if kw in upper:
            return True
    return False


def evaluate(ctx):
    cat = getattr(ctx, "ingress", None)
    if not cat:
        return None
    findings = []
    for s in cat.servers:
        name = s.primary_name
        if name == "_":
            continue
        if not s.ssl_ciphers:
            continue
        if _has_weak_ciphers(s.ssl_ciphers):
            findings.append({
                "target": name,
                "title": f"{name}: cifras TLS fracas configuradas",
                "title_plain": f"{name} permite cifras criptograficas fracas",
                "interpretation": f"O servidor {name} permite cifras TLS consideradas fracas "
                    f"({s.ssl_ciphers}). Cifras LOW, RC4, DES e MD5 sao vulneraveis "
                    f"a ataques como BEAST, Lucky13 e colisao de hash",
                "interpretation_plain": f"Cifras fracas em {name} — comunicacao pode ser decifrada",
                "recommendation": "Alterar ssl_ciphers para 'HIGH:!aNULL:!MD5' ou "
                    "remover a diretiva para usar o padrao seguro do nginx",
                "impact": "Cifras fracas permitem decifragem passiva do trafego TLS",
                "evidence": f"ssl_ciphers {s.ssl_ciphers} em {name}",
                "facts": [
                    {"key": "Host", "value": name, "tone": "warn"},
                    {"key": "Cifras", "value": s.ssl_ciphers, "tone": "error"},
                    {"key": "Recomendado", "value": "HIGH:!aNULL:!MD5", "tone": "info"},
                ],
                "actions": [
                    {
                        "title": "Atualizar ssl_ciphers",
                        "detail": f"Alterar ssl_ciphers para 'HIGH:!aNULL:!MD5' em {name}",
                        "command": "",
                        "risk": "medio — browsers muito antigos podem falhar handshake",
                        "applies_via": "editar nginx.conf",
                    }
                ],
            })
    return findings or None
