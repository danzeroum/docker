"""GET /api/executive — a tela do gestor.

Esta e a unica tela que fala para quem nao opera a VPS. Duas regras moldam o
endpoint inteiro:

- **Nada de jargao.** O hero e os riscos saem dos campos `_plain` do motor de
  achados, nunca do texto tecnico. Se um achado nao tem `_plain`, ele nao entra
  aqui — melhor a tela mostrar menos do que mostrar "exit 137" para um gestor.
- **Campo sem fonte real nao entra.** Disponibilidade so vira numero quando a
  serie tem 30 dias; custo so aparece com `COST_MONTHLY` configurado. Sem isso,
  o campo some ou diz desde quando esta coletando — nunca um zero inventado.
"""
import json
import os
from fastapi import APIRouter

from db import get_findings, get_first_sample_time, get_host_series

router = APIRouter(prefix="/api", tags=["executive"])

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICOS_PATH = os.getenv(
    "SERVICOS_CONFIG", os.path.join(APP_DIR, "config", "servicos.json")
)

# Dias de serie exigidos antes de a tela afirmar uma disponibilidade.
DIAS_PARA_DISPONIBILIDADE = 30

SEVERIDADE_ORDEM = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def carregar_servicos(caminho=None):
    """Devolve (mapa, erro). `erro` e o caminho que falta, quando falta.

    Nunca levanta: config ausente e estado esperado numa instalacao nova, e a
    tela precisa renderizar o resto mesmo assim.
    """
    caminho = caminho or SERVICOS_PATH
    if not os.path.isfile(caminho):
        return {}, caminho
    try:
        with open(caminho, "r", encoding="utf-8") as fh:
            dados = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}, caminho
    servicos = dados.get("servicos")
    if not isinstance(servicos, dict):
        return {}, caminho
    return servicos, None


def _payload(finding):
    bruto = finding.get("payload") or "{}"
    if isinstance(bruto, dict):
        return bruto
    try:
        return json.loads(bruto)
    except (json.JSONDecodeError, TypeError):
        return {}


def _plain(payload, campo):
    """So o texto para leigo. Sem fallback para o tecnico, de proposito."""
    valor = payload.get(f"{campo}_plain")
    if isinstance(valor, str) and valor.strip():
        return valor
    return None


def _custo_mensal():
    bruto = (os.getenv("COST_MONTHLY") or "").strip()
    if not bruto:
        return None
    try:
        return float(bruto.replace(",", "."))
    except ValueError:
        return None


def montar_hero(findings):
    """O achado mais grave que sabe se explicar sem jargao."""
    candidatos = []
    for f in findings:
        p = _payload(f)
        titulo = _plain(p, "title")
        if not titulo:
            continue
        candidatos.append((
            SEVERIDADE_ORDEM.get(f.get("severity"), 9),
            -(f.get("score") or 0),
            f,
            p,
            titulo,
        ))
    if not candidatos:
        return None
    candidatos.sort(key=lambda x: (x[0], x[1]))
    _, _, f, p, titulo = candidatos[0]
    return {
        "finding_id": f.get("id"),
        "severity": f.get("severity"),
        "title": titulo,
        "text": _plain(p, "interpretation"),
        "impact": _plain(p, "impact"),
        "recommendation": _plain(p, "recommendation"),
    }


def _nome_de_negocio(finding, mapa):
    """Alvo tecnico -> nome de negocio, ou None.

    Sem entrada no mapa devolve None e o risco fica sem nome de servico. Vazar
    o alvo tecnico aqui derrubaria a unica regra que esta tela tem: o gestor nao
    le nome de container nem dominio.
    """
    alvo = finding.get("target")
    if not alvo:
        return None
    entrada = mapa.get(alvo)
    if isinstance(entrada, dict):
        nome = (entrada.get("nome") or "").strip()
        if nome:
            return nome
    return None


def montar_riscos(findings, mapa=None):
    """Achados que pedem uma DECISAO, nao um conserto tecnico.

    Ordenados por prazo: quem tem horizonte em dias vem antes, do mais curto
    para o mais longo. Sem horizonte declarado significa "nao tem prazo, e
    agora" — entao vai para o topo, nao para o fim.
    """
    mapa = mapa or {}
    riscos = []
    for f in findings:
        p = _payload(f)
        if not p.get("requires_approval"):
            continue
        titulo = _plain(p, "title")
        if not titulo:
            continue
        horizonte = p.get("horizon_days")
        if not isinstance(horizonte, (int, float)):
            horizonte = 0
        riscos.append({
            "finding_id": f.get("id"),
            "severity": f.get("severity"),
            "service": _nome_de_negocio(f, mapa),
            "title": titulo,
            "decision": _plain(p, "recommendation"),
            "impact": _plain(p, "impact"),
            "horizon_days": horizonte,
        })
    riscos.sort(key=lambda r: (r["horizon_days"], SEVERIDADE_ORDEM.get(r["severity"], 9)))
    return riscos


def montar_servicos(hosts_publicos, mapa):
    """Nome de negocio ou 'nao mapeado'. Dominio nunca sai daqui."""
    mapeados = []
    nao_mapeados = 0
    for host in hosts_publicos:
        entrada = mapa.get(host)
        if isinstance(entrada, dict) and (entrada.get("nome") or "").strip():
            mapeados.append({
                "name": entrada["nome"],
                "description": entrada.get("descricao") or "",
                "critical": bool(entrada.get("critico")),
            })
        else:
            nao_mapeados += 1
    mapeados.sort(key=lambda s: (not s["critical"], s["name"].lower()))
    return mapeados, nao_mapeados


async def montar_disponibilidade():
    """Cobertura de coleta nos ultimos 30 dias, ou desde quando esta coletando.

    ATENCAO ao que este numero e e ao que ele NAO e. `host_samples` guarda CPU,
    memoria e disco — nao uptime de servico. O que da para afirmar com essa
    fonte e quantos dos ultimos 30 dias tiveram coleta: dia sem amostra e dia em
    que o cockpit (e provavelmente a VPS) esteve fora. E um piso observado, nao
    a disponibilidade dos servicos publicados, e o campo `source` diz isso.

    Chamar isso de "disponibilidade dos servicos" seria inventar numero — a
    mesma razao que tirou latencia por salto e CVEs das telas.
    """
    desde = await get_first_sample_time()
    if not desde:
        return {"value": None, "coletando_desde": None, "dias": 0, "source": None}

    from datetime import datetime, timezone
    try:
        inicio = datetime.fromisoformat(str(desde).replace("Z", "+00:00"))
        dias = (datetime.now(timezone.utc) - inicio).days
    except (ValueError, TypeError):
        return {"value": None, "coletando_desde": desde, "dias": 0, "source": None}

    if dias < DIAS_PARA_DISPONIBILIDADE:
        return {"value": None, "coletando_desde": desde, "dias": dias, "source": None}

    try:
        serie = await get_host_series("cpu_pct", days=DIAS_PARA_DISPONIBILIDADE, step="1d")
    except Exception:
        serie = []
    dias_com_coleta = len([p for p in serie if p])
    valor = round((dias_com_coleta / DIAS_PARA_DISPONIBILIDADE) * 100, 1)
    return {
        "value": valor,
        "coletando_desde": desde,
        "dias": dias,
        "source": "cobertura de coleta (host_samples), nao uptime de servico",
    }


def _hosts_publicos():
    """Dominios servidos pelo ingress. Lista vazia se o nginx.conf nao for legivel."""
    caminho = os.getenv("NGINX_CONFIG_PATH", "/etc/nginx/nginx.conf")
    if not os.path.isfile(caminho):
        return []
    try:
        from ingress.parser import parse_file
        catalogo = parse_file(caminho)
    except Exception:
        return []
    nomes = []
    for servidor in getattr(catalogo, "servers", []) or []:
        primario = getattr(servidor, "primary_name", "")
        if not primario or primario == "_":
            continue
        if "localhost" in (getattr(servidor, "server_name", "") or ""):
            continue
        if primario not in nomes:
            nomes.append(primario)
    return nomes


@router.get("/executive")
async def get_executive():
    findings = await get_findings(status="open")
    mapa, config_faltando = carregar_servicos()
    hosts = _hosts_publicos()
    servicos, nao_mapeados = montar_servicos(hosts, mapa)
    custo = _custo_mensal()
    disponibilidade = await montar_disponibilidade()
    riscos = montar_riscos(findings, mapa)

    faltando = []
    if config_faltando:
        faltando.append(config_faltando)

    return {
        "hero": montar_hero(findings),
        "services": servicos,
        "services_unmapped": nao_mapeados,
        "risks": riscos,
        "availability": disponibilidade,
        # None significa "sem fonte" — a tela omite o cartao em vez de mostrar zero.
        "cost_monthly": custo,
        "open_findings": len(findings),
        "config_missing": faltando,
    }
