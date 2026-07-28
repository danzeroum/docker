SEVERITY = "low"
SCOPE = "ingress"
MIN_INTERVAL = 60
AGGREGATE = True


def evaluate(ctx):
    cat = getattr(ctx, "ingress", None)
    if not cat:
        return None
    if cat.global_config.get("gzip") == "on":
        return None
    public = []
    for s in cat.servers:
        name = s.primary_name
        if name == "_":
            continue
        if not any(l.get("ssl", False) for l in s.listen) and not s.has_ssl:
            continue
        public.append(name)
    if not public:
        return None
    return {
        "targets": public,
        "title": "Compressao gzip global desabilitada",
        "title_plain": "Gzip global esta off",
        "interpretation": f"A compressao gzip nao esta habilitada globalmente "
            "no http block. Assets estaticos (CSS, JS, fontes) sao servidos "
            "sem compressao, aumentando o consumo de banda e o tempo de carga",
        "interpretation_plain": "Gzip desligado — assets estaticos trafegam sem compressao",
        "recommendation": "Adicionar 'gzip on; gzip_types text/plain text/css "
            "application/javascript image/svg+xml;' no http block do nginx.conf. "
            "Evitar gzip em respostas de API que retornam dados sensiveis",
        "impact": "Banda maior e tempo de carregamento maior para recursos estaticos",
        "evidence": "gzip nao esta habilitado no http block global",
        "facts": [
            {"key": "Compressao", "value": "desabilitada", "tone": "info"},
            {"key": "Impacto", "value": "assets servidos sem compressao", "tone": "info"},
        ],
        "actions": [
            {
                "title": "Habilitar gzip para estaticos",
                "detail": "Adicionar gzip on; gzip_types text/plain text/css application/javascript; no http block",
                "command": "",
                "risk": "baixo — aumento marginal de CPU, reducao significativa de banda",
                "applies_via": "editar nginx.conf",
            }
        ],
    }
