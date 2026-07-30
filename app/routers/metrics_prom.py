"""GET /metrics — exposition Prometheus (B9).

Lê o último snapshot do `sampler`. **Zero chamada ao daemon no scrape**, mesmo
padrão do `summary`: um Prometheus com `scrape_interval: 15s` transformaria cada
scrape em 15 chamadas ao daemon, e o coletor já tem esse dado em memória.

## Sobre o basic auth

O bloco pede "o mesmo basic auth do app", e aqui há um fato incômodo: **o app não
tem basic auth**. Ela vive no nginx do ingress, e o cockpit confia no header
`Remote-User` que ele injeta. Para toda outra rota isso basta — o tráfego chega
pelo ingress.

`/metrics` é diferente: é a rota que um scraper foi *feito* para chamar
diretamente. Um Prometheus dentro de `btv-prod-net` alcança
`http://docker-cockpit:8000/metrics` sem passar pelo nginx, e levaria embora o
inventário inteiro de containers do host sem credencial nenhuma. É exatamente a
dívida registrada no doc 00 ("leitura segue alcançável de dentro da rede interna
sem credencial"), e nesta rota ela deixa de ser teórica.

Por isso a verificação acontece **no app**, contra `BASIC_AUTH_USER`/
`BASIC_AUTH_PASS` — as mesmas credenciais que o `init.sh` usa para gerar o
htpasswd do ingress. Uma senha, dois lugares que a checam.

Sem as env definidas, a rota responde 503 em vez de abrir: fail-closed, como o
`unlock`. Uma instalação que esqueceu de configurar não deve publicar métricas
para quem passar.
"""

import hmac
import os

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from sampler import get_container_inspects, get_container_stats, get_last_sample

router = APIRouter(tags=["metrics"])

# `auto_error=False`: sem isto o FastAPI devolve 403 quando falta o header, e o
# contrato do Prometheus (e o aceite deste bloco) é 401 com WWW-Authenticate —
# é o 401 que faz o scraper mandar a credencial na segunda tentativa.
_basic = HTTPBasic(auto_error=False)

CABECALHO_401 = {"WWW-Authenticate": 'Basic realm="Docker Cockpit metrics"'}


def _confere(credenciais: HTTPBasicCredentials = Depends(_basic)):
    usuario = os.getenv("BASIC_AUTH_USER", "")
    senha = os.getenv("BASIC_AUTH_PASS", "")
    if not usuario or not senha:
        raise HTTPException(
            status_code=503,
            detail="BASIC_AUTH_USER/PASS nao configurados — /metrics fica fechado",
        )
    if credenciais is None:
        raise HTTPException(status_code=401, detail="credenciais ausentes", headers=CABECALHO_401)
    # compare_digest nos dois campos: comparação normal vaza o prefixo correto
    # pelo tempo de resposta, e um scraper pode tentar à vontade.
    ok_usuario = hmac.compare_digest(credenciais.username or "", usuario)
    ok_senha = hmac.compare_digest(credenciais.password or "", senha)
    if not (ok_usuario and ok_senha):
        raise HTTPException(status_code=401, detail="credenciais invalidas", headers=CABECALHO_401)
    return credenciais.username


def _escapa(valor: str) -> str:
    """Escape de label do formato exposition: barra, aspas e quebra de linha."""
    return (
        str(valor or "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def _linhas_de_container(nome: str, imagem: str, dados: dict, estado: int, saude) -> list:
    rotulos = f'name="{_escapa(nome)}",image="{_escapa(imagem)}"'
    cpu = float(dados.get("cpu_pct") or 0)
    mem = int(dados.get("mem_usage") or 0)
    limite = dados.get("mem_limit")
    linhas = [
        f"cockpit_container_cpu_pct{{{rotulos}}} {cpu}",
        f"cockpit_container_mem_bytes{{{rotulos}}} {mem}",
        # Estado 0 em vez de a série sumir: quando um container reinicia, uma
        # série que desaparece dispara `absent()` no alertmanager e acorda
        # alguém por um evento que não é incidente.
        f"cockpit_container_estado{{{rotulos}}} {estado}",
    ]
    if limite:
        linhas.append(f"cockpit_container_mem_limit_bytes{{{rotulos}}} {int(limite)}")
    if saude is not None:
        linhas.append(
            f"cockpit_container_unhealthy{{{rotulos}}} {1 if saude == 'unhealthy' else 0}"
        )
    return linhas


def montar_exposition() -> str:
    """Snapshot do sampler -> texto no formato exposition 0.0.4."""
    stats, _as_of = get_container_stats()
    inspects = get_container_inspects()

    corpo = []
    unhealthy_total = 0
    avaliados = 0

    for cid, dados in (stats or {}).items():
        if not isinstance(dados, dict):
            continue
        insp = inspects.get(cid) if isinstance(inspects, dict) else None
        insp = insp if isinstance(insp, dict) else {}
        nome = (insp.get("Name") or "").lstrip("/") or str(cid)[:12]
        imagem = (insp.get("Config") or {}).get("Image") or ""
        estado_docker = (insp.get("State") or {})
        rodando = 1 if estado_docker.get("Running") else 0
        saude_bloco = estado_docker.get("Health")
        saude = saude_bloco.get("Status") if isinstance(saude_bloco, dict) else None
        if saude == "unhealthy":
            unhealthy_total += 1
        avaliados += 1
        corpo.extend(_linhas_de_container(nome, imagem, dados, rodando, saude))

    vitais = []
    amostra = get_last_sample()
    if isinstance(amostra, dict):
        cpu = (amostra.get("cpu") or {}).get("percent")
        mem = (amostra.get("memory") or {}).get("percent")
        if cpu is not None:
            vitais.append(f"cockpit_host_cpu_pct {float(cpu)}")
        if mem is not None:
            vitais.append(f"cockpit_host_mem_pct {float(mem)}")

    # HELP/TYPE saem SEMPRE, mesmo sem amostra: um scrape de exposição vazia
    # ainda é uma resposta válida, e é o que o Prometheus recebe no boot.
    saida = [
        "# HELP cockpit_container_cpu_pct CPU do container em percentual",
        "# TYPE cockpit_container_cpu_pct gauge",
        "# HELP cockpit_container_mem_bytes Memoria residente do container em bytes",
        "# TYPE cockpit_container_mem_bytes gauge",
        "# HELP cockpit_container_mem_limit_bytes Limite de memoria declarado, quando ha",
        "# TYPE cockpit_container_mem_limit_bytes gauge",
        "# HELP cockpit_container_estado 1 se rodando, 0 caso contrario",
        "# TYPE cockpit_container_estado gauge",
        "# HELP cockpit_container_unhealthy 1 se o healthcheck falha; ausente sem healthcheck",
        "# TYPE cockpit_container_unhealthy gauge",
        "# HELP cockpit_unhealthy_total Containers com healthcheck falhando",
        "# TYPE cockpit_unhealthy_total gauge",
        "# HELP cockpit_containers_total Containers no ultimo snapshot do coletor",
        "# TYPE cockpit_containers_total gauge",
        "# HELP cockpit_host_cpu_pct CPU do host em percentual",
        "# TYPE cockpit_host_cpu_pct gauge",
        "# HELP cockpit_host_mem_pct Memoria do host em percentual",
        "# TYPE cockpit_host_mem_pct gauge",
    ]
    saida.extend(corpo)
    saida.extend(vitais)
    saida.append(f"cockpit_unhealthy_total {unhealthy_total}")
    saida.append(f"cockpit_containers_total {avaliados}")
    return "\n".join(saida) + "\n"


@router.get("/metrics")
async def metrics(_usuario: str = Depends(_confere)):
    return Response(
        content=montar_exposition(),
        # `version=0.0.4` no content-type é o que o Prometheus espera; sem ele
        # alguns scrapers tratam a resposta como texto opaco.
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
