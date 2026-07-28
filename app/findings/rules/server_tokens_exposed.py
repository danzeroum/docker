SEVERITY = "low"
SCOPE = "ingress"
MIN_INTERVAL = 60


def evaluate(ctx):
    cat = getattr(ctx, "ingress", None)
    if not cat:
        return None
    st = cat.global_config.get("server_tokens")
    if st == "on" or st is None:
        target = "_"
        st_display = st if st else "on (padrao)"
        return {
            "target": target,
            "title": "Versao do nginx exposta via server_tokens",
            "title_plain": "server_tokens ativo — versao do nginx visivel em respostas HTTP",
            "interpretation": "A diretiva server_tokens esta ativa (ou ausente, o que equivale a on). "
                "Isso expoe a versao exata do nginx no header Server das respostas HTTP, "
                "facilitando reconhecimento de versoes vulneraveis por atacantes",
            "interpretation_plain": "Qualquer requisicao revela a versao do nginx — informacao util para ataques dirigidos",
            "recommendation": "Adicionar 'server_tokens off;' no bloco http para ocultar a versao do nginx",
            "impact": "Baixo — versao do nginx e informacao publica, mas facilita fingerprint de vulnerabilidades",
            "evidence": f"server_tokens {st_display}",
            "facts": [
                {"key": "Diretiva", "value": f"server_tokens {st_display}", "tone": "warn"},
                {"key": "Risco", "value": "fingerprint de versao", "tone": "info"},
            ],
            "actions": [
                {
                    "title": "Ocultar versao do nginx",
                    "detail": "Adicionar 'server_tokens off;' no bloco http do nginx.conf",
                    "command": "",
                    "risk": "baixo — nenhum impacto funcional",
                    "applies_via": "editar nginx.conf",
                }
            ],
        }
    return None
