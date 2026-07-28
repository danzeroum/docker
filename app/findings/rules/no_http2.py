SEVERITY = "low"
SCOPE = "ingress"
MIN_INTERVAL = 60
AGGREGATE = True


def evaluate(ctx):
    cat = getattr(ctx, "ingress", None)
    if not cat:
        return None
    any_http2 = False
    public = []
    for s in cat.public_servers:
        if s.has_http2:
            any_http2 = True
        if not any(l.get("ssl", False) for l in s.listen) and not s.has_ssl:
            continue
        public.append(s.primary_name)
    if any_http2 or not public:
        return None
    return {
        "targets": public,
        "title": "Nenhum host com HTTP/2 habilitado",
        "title_plain": "HTTP/2 desabilitado em todos os hosts",
        "interpretation": f"Nenhum dos {len(public)} hosts publicos tem HTTP/2 "
            "habilitado. HTTP/2 reduz latencia com multiplexacao e compressao "
            "de headers, especialmente benefico em conexoes TLS com muitos requests",
        "interpretation_plain": "HTTP/2 esta desligado em toda a frota — "
            "oportunidade de performance perdida em conexoes TLS",
        "recommendation": "Avaliar habilitacao gradual de HTTP/2 comecando por "
            "hosts com maior volume de requests TLS. Requer listen 443 ssl http2 "
            "e compatibilidade com o upstream",
        "impact": "Cada conexao TLS sequencia requests em fila — sem multiplexacao "
            "real, o tempo de carregamento de paginas com multiplos assets e maior",
        "evidence": f"nenhum dos {len(public)} hosts publicos tem http2 no listen",
        "facts": [
            {"key": "Hosts sem HTTP/2", "value": str(len(public)), "tone": "info"},
            {"key": "Oportunidade", "value": "reducao de latencia em TLS", "tone": "info"},
        ],
        "actions": [
            {
                "title": "Habilitar HTTP/2 progressivamente",
                "detail": "Adicionar http2 ao final do listen 443 ssl em 1-2 hosts piloto",
                "command": "",
                "risk": "baixo — HTTP/2 e retrocompativel com HTTP/1.1",
                "applies_via": "editar nginx.conf",
            }
        ],
    }
