"""Bloco `summary` da régua do kernel (doc 09 §B, Sprint 2a).

A régua de chips do Cockpit Vivo lê ESTE payload e mais nada. É o que sustenta
dois compromissos dos docs ao mesmo tempo:

- doc 09 §B: "alimenta a régua inteira em 1 chamada, sem 6 fetches por poll";
- doc 10, invariante 3: "módulo oculto nunca oculta o dado — o chip continua
  vivo na régua".

O segundo é o que obriga o desenho a ter duas metades. Se o summary lesse os
dados sob demanda, um módulo oculto nunca seria buscado e seu chip ficaria morto
para sempre — a régua viraria decoração. Se lesse chamando o daemon no request,
cada poll dispararia `/system/df`, que é a varredura mais cara que existe aqui.

Então: `montar()` só lê cache em memória e SQLite (zero daemon no request), e
`aquecer()` roda no loop de fundo para manter esses caches quentes independente
de qualquer módulo estar visível. Chip vivo sem custo por request.

Chave sem fonte real sai como `null` e entra em `summary.stale_since` — nunca
como zero. Dado inventado é pior que campo ausente (doc 05 regra 7, doc 01).
"""

import os
from datetime import datetime, timezone

from cache import cached_or_fetch, peek

# Espelho de ENABLE_ACTIONS, lido de `actions.habilitadas` — fonte unica.
#
# O padrao virou 0 nesta sprint, junto com a barreira que faz a flag desligada
# DESREGISTRAR as rotas (404, nao 403). Como prometido no doc 14 §15, a inversao
# do padrao e o pin `ENABLE_ACTIONS: "1"` no compose de producao entraram no
# MESMO commit — separa-los derrubaria o fluxo unlock->reiniciar entre um deploy
# e outro.
def _flag(nome: str, padrao: str = "") -> bool:
    return (os.getenv(nome, padrao) or "").strip().lower() in ("1", "true", "yes", "on")


def _padrao_acoes() -> bool:
    """Fonte unica da flag: `actions.habilitadas`.

    O summary NAO reimplementa a leitura. Duas leituras da mesma env sao duas
    verdades esperando divergir, e aqui a divergencia seria a pior possivel: a
    UI escondendo botao de rota que existe, ou mostrando botao de rota que nao
    existe.
    """
    from actions import habilitadas
    return habilitadas()


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def actions_enabled() -> bool:
    return _padrao_acoes()


def _do_cache(chave: str):
    """(dado, stale_since) de um cache, sem nunca disparar fetch.

    A fronteira do "velho demais" é o próprio TTL com que a entrada foi gravada,
    não uma constante global: a projeção de disco é cacheada por 5 min e o
    storage por 30 s, e um teto único marcaria a projeção como podre enquanto ela
    ainda está em dia. Reaproveita a janela de stale-while-revalidate que o
    `cache` já mantém.

    stale_since preenchido significa "esta chave não está em dia"; quem lê a
    régua precisa saber disso para não apresentar número velho como atual.
    """
    espiada = peek(chave)
    if espiada is None:
        # Nunca houve dado: o aquecimento ainda não rodou ou está falhando.
        return None, _agora()
    if espiada["fresh"]:
        return espiada["data"], None
    if espiada.get("servivel"):
        # Velho mas dentro da janela: a régua prefere dado de 1 min a lacuna,
        # desde que se declare velho.
        return espiada["data"], _agora()
    return None, _agora()


def _gb(bytes_) -> float | None:
    if not isinstance(bytes_, (int, float)):
        return None
    return round(bytes_ / (1024 ** 3), 2)


# --- montadores por chave -------------------------------------------------
# Cada um devolve (valor, stale_since). Nenhum levanta: o summary não pode ser o
# motivo de /api/overview responder 500 — a régua degrada, a tela não cai.

async def _findings():
    from db import get_findings
    abertos = await get_findings(status="open")
    return {
        "open": len(abertos),
        "critical": sum(1 for f in abertos if f.get("severity") == "critical"),
    }, None


async def _tasks():
    from db import get_tasks
    todas = await get_tasks()
    return {
        "total": len(todas),
        "todo": sum(1 for t in todas if t.get("col") == "todo"),
    }, None


async def _events():
    """Resumo da timeline, para o chip do módulo Eventos.

    Lê SQLite direto, sem peek: é uma contagem e um SELECT de 1 linha em tabela
    indexada, mais barato que a maquinaria de cache. O `peek` existe para o que
    custa I/O de disco ou rede — usá-lo aqui seria cerimônia.
    """
    from db import get_events_resumo
    return await get_events_resumo(), None


async def _updates():
    """`summary.updates`. None quando o job nunca rodou — nao zero.

    Zero afirmaria "nenhuma imagem desatualizada", que e conclusao; o job pode
    simplesmente ainda nao ter rodado. Mesmo padrao de `certs_expiring`.
    """
    from db import get_updates_resumo
    return await get_updates_resumo(), None


async def _audit():
    from db import get_audit_log
    ultimas = await get_audit_log(limit=1)
    if not ultimas:
        return {"last_at": None, "last_actor": None}, None
    u = ultimas[0]
    return {
        "last_at": u.get("created_at"),
        "last_actor": u.get("token_label") or None,
    }, None


def _stacks(containers: list, ingress_data):
    """up/total das stacks, derivado dos containers que o overview já montou.

    Não usa /api/projects de propósito: aquela rota roda `docker compose ps` por
    projeto via subprocess, e chamá-la por poll colocaria ~12 subprocessos no
    caminho de cada request da régua.
    """
    stacks = {}
    for c in containers:
        nome = c.get("stack") or "sem stack"
        alvo = stacks.setdefault(nome, {"up": 0, "total": 0})
        alvo["total"] += 1
        if c.get("state") == "running":
            alvo["up"] += 1

    up = sum(1 for v in stacks.values() if v["up"] == v["total"] and v["total"] > 0)
    valor = {"up": up, "total": len(stacks), "stopped_with_domain": None}

    # stopped_with_domain cruza stack parada com domínio publicado; sem o
    # inventário do ingress a pergunta não tem resposta, e a chave fica null em
    # vez de virar 0 — que a régua leria como "nenhuma stack parada exposta".
    if isinstance(ingress_data, dict):
        hosts = ingress_data.get("hosts")
        if isinstance(hosts, dict):
            upstreams = set()
            for cfg in hosts.values():
                if not isinstance(cfg, dict):
                    continue
                for u in cfg.get("upstreams") or []:
                    alvo = str(u).split("//")[-1].split(":")[0]
                    if alvo:
                        upstreams.add(alvo)
            paradas = {
                nome for nome, v in stacks.items()
                if v["up"] == 0 and v["total"] > 0 and nome != "sem stack"
            }
            nomes_containers = {
                (c.get("name") or ""): (c.get("stack") or "") for c in containers
            }
            expostas = {
                stack for nome, stack in nomes_containers.items()
                if nome in upstreams and stack in paradas
            }
            valor["stopped_with_domain"] = len(expostas)
    return valor


def _ingress(ingress_data):
    if not isinstance(ingress_data, dict):
        return None
    hosts = ingress_data.get("hosts") if isinstance(ingress_data.get("hosts"), dict) else {}
    publicos = {k: v for k, v in hosts.items() if isinstance(v, dict) and not v.get("internal")}
    forcados = sum(
        1 for v in publicos.values()
        if isinstance(v.get("port_80"), dict) and v["port_80"].get("https_redirect")
    )
    totais = ingress_data.get("totals") if isinstance(ingress_data.get("totals"), dict) else {}
    return {
        "hosts": totais.get("public", len(publicos)),
        "https_forced": forcados,
        # NÃO existe fonte para validade de certificado: não há regra de
        # expiração entre as 17 do motor, e o diretório do certbot não está
        # montado no container (o compose monta só nginx e /opt/btv). Inventar
        # dias aqui seria exatamente o que o doc 01 proíbe. Fica null até o B?
        # que ler o cert de verdade.
        "certs_expiring": None,
        "cert_window_days": None,
    }


def _disco_agora():
    """disk_pct do sampler — em memória, sempre fresco, custo zero.

    Não vem do mesmo cache da projeção de propósito: a projeção é uma agregação
    de 30 dias que só muda de hora em hora, e o percentual atual do disco é o
    número que o operador olha para decidir agir agora.
    """
    from sampler import get_last_sample
    amostra = get_last_sample()
    if not isinstance(amostra, dict):
        return None
    discos = amostra.get("disks") or []
    raiz = next((d for d in discos if d.get("mountpoint") == "/"), None)
    if raiz is None and discos:
        raiz = discos[0]
    return raiz.get("percent") if isinstance(raiz, dict) else None


def _capacity(historico):
    """days_to_90 e r² da projeção de disco de /api/metrics/history.

    A projeção se cala sozinha com r²<0.7 (`stable: false`, decisão do doc 00), e
    a régua respeita isso: sem tendência sustentada, `days_to_90` sai null em vez
    de um prazo que o dado não sustenta.
    """
    disco = _disco_agora()
    if not isinstance(historico, dict):
        return {"days_to_90": None, "r2": None, "disk_pct": disco} if disco is not None else None
    proj = historico.get("projection")
    if not isinstance(proj, dict) or not proj.get("stable"):
        return {
            "days_to_90": None,
            "r2": proj.get("r2") if isinstance(proj, dict) else None,
            "disk_pct": disco,
        }
    return {
        "days_to_90": proj.get("days_to_90"),
        "r2": proj.get("r2"),
        "disk_pct": disco,
    }


def _storage(storage_data):
    if not isinstance(storage_data, dict):
        return None
    return {
        "reclaimable_gb": _gb(storage_data.get("reclaimable_bytes")),
        "orphans": len(storage_data.get("orphans") or []),
    }


def _security(security_data):
    """Mapeia score_minimo → min_score.

    Decisão registrada (doc 14 §2): as chaves do summary seguem os docs 09/12
    verbatim, porque é o contrato que a régua e o protótipo referenciam; os
    payloads de /api/security e /api/storage ficam como entregues na Sprint 1.
    A tradução vive aqui, num lugar só.
    """
    if not isinstance(security_data, dict):
        return None
    resumo = security_data.get("summary") if isinstance(security_data.get("summary"), dict) else {}
    sev = resumo.get("violacoes_por_severidade") or {}
    return {
        "min_score": resumo.get("score_minimo"),
        "critical": sev.get("critical"),
    }


async def montar(containers: list) -> dict:
    """Monta o summary. Zero chamada ao daemon: só cache em memória e SQLite.

    `containers` é a lista que /api/overview já computou no mesmo request —
    passar por parâmetro em vez de reconsultar mantém a regra "um dado, uma
    origem" do doc 10 §4: chip e módulo nunca divergem na mesma tela.
    """
    stale: dict = {}

    def registra(chave: str, par):
        valor, quando = par
        if quando:
            stale[chave] = quando
        return valor

    ingress_data, ingress_stale = _do_cache("ingress")
    capacity_data, capacity_stale = _do_cache("capacity")
    storage_data, storage_stale = _do_cache("storage")
    security_data, security_stale = _do_cache("security")

    resultado = {
        "findings": registra("findings", await _seguro(_findings)),
        "stacks": _stacks(containers, ingress_data),
        "ingress": _ingress(ingress_data),
        "capacity": _capacity(capacity_data),
        "audit": registra("audit", await _seguro(_audit)),
        "tasks": registra("tasks", await _seguro(_tasks)),
        "events": registra("events", await _seguro(_events)),
        "updates": registra("updates", await _seguro(_updates)),
        "storage": _storage(storage_data),
        "security": _security(security_data),
        # B8 pendente. A chave já sai no contrato para a régua não precisar
        # mudar de forma quando o drift chegar.
        "drift": {"count": None},
        "capabilities": {
            "actions_enabled": actions_enabled(),
            "terminal_enabled": _flag("ENABLE_TERMINAL"),
        },
    }

    for chave, quando in (
        ("ingress", ingress_stale),
        ("capacity", capacity_stale),
        ("storage", storage_stale),
        ("security", security_stale),
    ):
        if quando or resultado.get(chave) is None:
            stale[chave] = quando or _agora()

    resultado["stale_since"] = stale
    resultado["generated_at"] = _agora()
    return resultado


async def _seguro(fn):
    """Executa um montador; falha vira (None, agora) em vez de 500."""
    try:
        return await fn()
    except Exception:
        return None, _agora()


# --- aquecimento ----------------------------------------------------------

AQUECIMENTO_INTERVALO_S = float(os.getenv("SUMMARY_WARM_INTERVAL", "60") or 60)


async def aquecer():
    """Preenche os caches que o summary lê, fora do caminho do request.

    É esta função que faz o invariante 3 valer: o chip de Armazenamento fica
    vivo mesmo com o módulo oculto e ninguém nunca tendo aberto a tela. As
    chamadas caras ao daemon acontecem aqui, uma vez por minuto, não por poll.

    Cada fonte é isolada: /system/df fora do ar não pode impedir o aquecimento
    do score de segurança.
    """
    from routers.ingress import get_ingress
    from routers.metrics import get_metrics_history
    from routers.security import get_security
    from routers.storage import get_storage

    async def projecao_disco():
        # A mesma janela que a tela Capacidade desenha: 30 d por dia.
        return await get_metrics_history(series="disk_pct", range_days=30, step="1d")

    for chave, ttl, fn in (
        ("ingress", 60.0, get_ingress),
        ("capacity", 300.0, projecao_disco),
        ("security", 30.0, get_security),
        ("storage", 30.0, get_storage),
    ):
        try:
            await cached_or_fetch(chave, ttl=ttl, factory=fn, timeout=45.0)
        except Exception:
            # Silencioso por fonte: o stale_since da chave já conta a história
            # para quem lê a régua, e um traceback por minuto no log de uma VPS
            # com o Hub fora do ar não ajuda ninguém.
            continue


async def aquecer_loop(intervalo: float = None):
    import asyncio
    espera = intervalo or AQUECIMENTO_INTERVALO_S
    while True:
        try:
            await aquecer()
            await asyncio.sleep(espera)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(espera)
