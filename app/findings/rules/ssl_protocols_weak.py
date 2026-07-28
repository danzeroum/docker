SEVERITY = "high"
SCOPE = "ingress"
MIN_INTERVAL = 60

_WEAK = {"TLSv1", "TLSv1.1", "SSLv2", "SSLv3"}


def evaluate(ctx):
    cat = getattr(ctx, "ingress", None)
    if not cat:
        return None
    findings = []
    for s in cat.servers:
        name = s.primary_name
        if name == "_":
            continue
        if not s.ssl_protocols:
            continue
        protos = [p.strip() for p in s.ssl_protocols.split()]
        weak = [p for p in protos if p in _WEAK]
        if not weak:
            continue
        findings.append({
            "target": name,
            "title": f"{name}: protocolos TLS obsoletos habilitados",
            "title_plain": f"{name} permite {', '.join(weak)}",
            "interpretation": f"O servidor {name} permite os protocolos obsoletos "
                f"{', '.join(weak)}. TLS 1.0 e 1.1 sao vulneraveis a ataques como POODLE, "
                f"BEAST e downgrade — navegadores modernos ja os desabilitam",
            "interpretation_plain": f"Protocolos TLS antigos em {name} — vulneraveis a ataques conhecidos",
            "recommendation": "Remover TLSv1 e TLSv1.1 da diretiva ssl_protocols. "
                "Manter apenas TLSv1.2 e TLSv1.3",
            "impact": f"{', '.join(weak)} permitem ataques de downgrade e exposicao de dados",
            "evidence": f"ssl_protocols {s.ssl_protocols} em {name}",
            "facts": [
                {"key": "Host", "value": name, "tone": "warn"},
                {"key": "Protocolos", "value": ", ".join(weak), "tone": "error"},
                {"key": "Recomendado", "value": "TLSv1.2 TLSv1.3", "tone": "info"},
            ],
            "actions": [
                {
                    "title": "Atualizar ssl_protocols",
                    "detail": f"Alterar ssl_protocols para 'TLSv1.2 TLSv1.3' em {name}",
                    "command": "",
                    "risk": "medio — browsers muito antigos perdem acesso",
                    "applies_via": "editar nginx.conf",
                }
            ],
        })
    return findings or None
