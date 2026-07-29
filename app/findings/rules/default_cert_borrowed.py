SEVERITY = "medium"
SCOPE = "ingress"
MIN_INTERVAL = 60


def _find_borrowed_default(cat):
    """
    Detecta default_server SSL que usa certificado de um host nomeado.
    Retorna (default_name, cert_host, cert_path) ou None.
    """
    default_ssl = None
    named_certs = {}
    for s in cat.servers:
        name = s.primary_name
        if name == "_" and s.ssl_cert:
            if any(l.get("default") for l in s.listen):
                default_ssl = s
        elif s.ssl_cert:
            named_certs[name] = s.ssl_cert
    if not default_ssl or not default_ssl.ssl_cert:
        return None
    for host_name, host_cert in named_certs.items():
        if default_ssl.ssl_cert == host_cert:
            return (host_name, default_ssl.ssl_cert)
    return None


def evaluate(ctx):
    cat = getattr(ctx, "ingress", None)
    if not cat:
        return None
    borrowed = _find_borrowed_default(cat)
    if not borrowed:
        return None
    cert_host, cert_path = borrowed
    return {
        "target": "_",
        "title": "Certificado emprestado ao default_server SSL",
        "title_plain": "Um endereco responde com certificado de outro servico",
        "impact_plain": "O navegador do cliente pode acusar site inseguro",
        "recommendation_plain": (
            "Emitir um certificado proprio para esse endereco — pode exigir "
            "ajuste de DNS"
        ),
        "requires_approval": True,
        "interpretation": (
            f"O server default SSL (server_name _) usa o certificado de {cert_host} "
            f"({cert_path}). Acessos por IP ou dominio nao configurado exibem "
            f"aviso de certificado no navegador — nao ha falha de servico, "
            f"mas a confianca do visitante e quebrada"
        ),
        "interpretation_plain": (
            "Acesso por IP ou dominio nao listado mostra certificado de outro site — "
            "o usuario ve aviso de seguranca mesmo que o servico esteja funcionando"
        ),
        "recommendation": (
            "Nao emprestar certificado de host nomeado ao default_server. "
            "Criar certificado autoassinado para o default_server ou "
            "manter return 444 sem certificado — o importante e nao "
            "apresentar um certificado alheio ao visitante"
        ),
        "impact": "Visitantes por IP ou dominio nao configurado veem alarme de certificado",
        "evidence": f"default_server SSL usa certificado de {cert_host}: {cert_path}",
        "facts": [
            {"key": "Certificado emprestado de", "value": cert_host, "tone": "warn"},
            {"key": "Caminho", "value": cert_path, "tone": "neutral"},
            {"key": "Tipo", "value": "falha de confianca", "tone": "warn"},
        ],
        "actions": [
            {
                "title": "Criar certificado autoassinado para o default_server",
                "detail": "Gerar certificado autoassinado ou configurar return 444 sem ssl_certificate",
                "command": "openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/nginx/ssl/default.key -out /etc/nginx/ssl/default.crt",
                "risk": "baixo — apenas substitui o certificado emprestado",
                "applies_via": "shell no host",
            }
        ],
    }
