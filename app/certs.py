"""Validade de certificado, lida do X.509 (5-certs).

Fecha a decisão que a Sprint 2a deixou aberta: `certs_expiring` e
`cert_window_days` saem do `null` **quando há mount**, e continuam saindo
`null` — com `stale_since` — quando não há. Os dois ramos são legítimos; o que
não podia é o `null` da 2a virar permanente sem ninguém decidir.

`notAfter` vem do próprio certificado, nunca da saída do `certbot certificates`.
Parsear a saída de uma CLI amarra o cockpit ao formato de texto de outro projeto
— formato que muda entre versões sem aviso, e cuja quebra apareceria aqui como
"nenhum certificado expirando", que é a pior falha possível nesta medida.

Dois casos do dia a dia do certbot que o código trata como normais:

- **`live/` é feito de symlinks** para `archive/`, e symlink quebrado acontece
  toda vez que alguém apaga um lineage à mão. Ele é ignorado com aviso, não
  levanta.
- **diretório ausente ou vazio** devolve `None`, não erro: instalação sem TLS
  local é legítima, e a maioria das VPS com ingress externo é assim.
"""

import os
from datetime import datetime, timezone

# Onde o certbot põe os lineages. Vazio desliga a leitura por completo — é o
# modo "sem mount", em que o cockpit continua sem afirmar nada sobre validade.
DIR_CERTS = os.getenv("CERTS_DIR", "")

# Janela do "expirando". 14 dias porque a renovação automática do certbot roda
# aos 30: um cert com menos de 14 significa que a renovação já falhou pelo menos
# uma vez, e aí é achado — não rotina.
JANELA_DIAS = int(os.getenv("CERT_WINDOW_DAYS", "14") or 14)

_NOMES = ("fullchain.pem", "cert.pem", "cert.crt", "fullchain.crt")


def _agora():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def le_not_after(caminho: str):
    """`notAfter` de um PEM. Devolve `(datetime, erro)`; nunca levanta."""
    try:
        from cryptography import x509
    except ImportError:  # pragma: no cover - dependência declarada
        return None, "cryptography ausente"

    try:
        with open(caminho, "rb") as fh:
            bruto = fh.read()
    except FileNotFoundError:
        # Em `live/` isto é quase sempre symlink apontando para um `archive/`
        # que já não existe — rotina do certbot, não incidente.
        return None, "symlink quebrado ou arquivo ausente"
    except (PermissionError, OSError) as exc:
        return None, f"ilegivel ({type(exc).__name__})"

    try:
        cert = x509.load_pem_x509_certificate(bruto)
    except Exception:
        return None, "nao e um certificado PEM valido"

    try:
        quando = cert.not_valid_after_utc
    except AttributeError:  # cryptography < 42
        quando = cert.not_valid_after.replace(tzinfo=timezone.utc)
    return quando, ""


def _certificado_do_lineage(diretorio: str):
    for nome in _NOMES:
        caminho = os.path.join(diretorio, nome)
        if os.path.exists(caminho) or os.path.islink(caminho):
            return caminho
    return ""


def coletar(diretorio: str = None, janela: int = None) -> dict | None:
    """Varre os lineages. `None` quando não há fonte — nunca zero.

    `None` e não `{"expiring": 0}` pelo mesmo motivo de `updates` e
    `notifications`: zero afirma "nenhum certificado está para vencer", e a
    verdade pode ser "não estou olhando certificado nenhum".
    """
    raiz = diretorio if diretorio is not None else DIR_CERTS
    dias = janela or JANELA_DIAS
    if not raiz or not os.path.isdir(raiz):
        return None

    try:
        entradas = sorted(os.listdir(raiz))
    except (PermissionError, OSError):
        return None

    certificados, avisos = [], []
    agora = _agora()
    for entrada in entradas:
        caminho_lineage = os.path.join(raiz, entrada)
        if not os.path.isdir(caminho_lineage):
            continue
        pem = _certificado_do_lineage(caminho_lineage)
        if not pem:
            avisos.append(f"{entrada}: sem cert legivel no lineage")
            continue
        quando, erro = le_not_after(pem)
        if erro:
            avisos.append(f"{entrada}: {erro}")
            continue
        restantes = (quando - agora).total_seconds() / 86400.0
        certificados.append({
            "name": entrada,
            "not_after": _iso(quando),
            # Arredonda para baixo: um cert com 13,9 dias tem 13, e não 14. A
            # direção do arredondamento importa quando o número decide se alguém
            # é acordado.
            "days": int(restantes // 1),
            "expiring": restantes <= dias,
        })

    if not certificados and not avisos:
        # Diretório existe mas está vazio: instalação sem TLS local. Continua
        # sendo ausência de fonte, não "zero certificados vencendo".
        return None

    return {
        "certs": sorted(certificados, key=lambda c: c["days"]),
        "expiring": sum(1 for c in certificados if c["expiring"]),
        "window_days": dias,
        "avisos": avisos,
        "generated_at": _iso(agora),
    }


async def calcular() -> dict | None:
    import asyncio
    # `os.listdir` + N leituras de arquivo num diretório do host: fora da thread
    # do loop, como o sampler faz.
    return await asyncio.to_thread(coletar)


# --- ponte para o motor de notificações (B7) ------------------------------

def achados_de_cert(dados: dict | None) -> list[dict]:
    """Um achado por certificado dentro da janela.

    Dedup DIÁRIO, e não os 30 min do padrão: certificado expira em dias, e
    repetir o mesmo aviso a cada meia hora martelaria o canal sem trazer
    informação nova nenhuma — o caminho mais curto para o operador silenciar o
    canal inteiro justamente antes do aviso que importa.
    """
    if not isinstance(dados, dict):
        return []
    return [
        {"regra": "cert_expirando", "alvo": c["name"], "ts": _iso(_agora()),
         "detalhe": f"expira em {c['days']} dia(s)"}
        for c in dados.get("certs") or [] if c.get("expiring")
    ]
