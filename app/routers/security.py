"""Score de postura de seguranca por container (B4).

As regras sao DADOS, nao `if` encadeado: cada checagem e uma entrada de
`CHECKS` com nome estavel, severidade e um predicado sobre o inspect. Essa
lista cresce (a de achados do motor F2 ja passou de 17), e o ponto de extensao
precisa ser "acrescentar uma linha" em vez de "achar onde enfiar mais um elif".

Fonte de dado: o inspect que o `sampler` ja coleta a cada 10 s. Nenhuma chamada
extra ao daemon — avaliar 15 containers por inspect proprio custaria ~18 s.

Aqui NAO passa mascara de segredo porque nenhuma regra le valor de variavel de
ambiente: as checagens olham estrutura (User, Privileged, Binds, CapAdd), e o
payload de saida so carrega nome de regra e evidencia estrutural.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from routers._proxy import proxy_get
from sampler import get_container_inspects

router = APIRouter(prefix="/api", tags=["security"])

# Peso por severidade. Fixado aqui porque o score e comparavel entre hosts e
# entre semanas — mudar o peso muda o historico inteiro, e isso tem de ser uma
# decisao explicita, nao um numero solto no meio de uma funcao.
PESOS = {"critical": 30, "high": 15, "medium": 5}

CAPS_PERIGOSAS = {"SYS_ADMIN", "NET_ADMIN", "SYS_PTRACE", "SYS_MODULE", "DAC_READ_SEARCH"}

SOCKET_DOCKER = "/var/run/docker.sock"


# --- leitores de inspect ---------------------------------------------------
# Cada um tolera inspect parcial: container recem-criado tem secoes ausentes, e
# uma regra nao pode virar 500 por causa de um dict que ainda nao existe.

def _host_config(insp: dict) -> dict:
    hc = insp.get("HostConfig")
    return hc if isinstance(hc, dict) else {}


def _config(insp: dict) -> dict:
    cfg = insp.get("Config")
    return cfg if isinstance(cfg, dict) else {}


def _binds(insp: dict) -> list:
    """Montagens como lista de strings `origem:destino[:modo]`.

    Le `HostConfig.Binds` e `Mounts` porque compose e `docker run -v` nao
    populam o mesmo campo: um bind declarado no compose aparece em Mounts com
    Source/Destination, e olhar so Binds deixaria passar o socket montado pelo
    caminho mais comum nesta infraestrutura.
    """
    saida = []
    binds = _host_config(insp).get("Binds")
    if isinstance(binds, list):
        saida.extend(str(b) for b in binds if b)
    mounts = insp.get("Mounts")
    if isinstance(mounts, list):
        for m in mounts:
            if isinstance(m, dict) and m.get("Source"):
                saida.append(f"{m.get('Source')}:{m.get('Destination', '')}")
    return saida


def _caps(insp: dict) -> set:
    bruto = _host_config(insp).get("CapAdd")
    if not isinstance(bruto, list):
        return set()
    return {str(c).upper().replace("CAP_", "") for c in bruto if c}


# --- predicados das regras ------------------------------------------------

def _monta_socket(insp) -> bool:
    return any(b.split(":")[0] == SOCKET_DOCKER for b in _binds(insp))


def _privileged(insp) -> bool:
    return bool(_host_config(insp).get("Privileged"))


def _network_host(insp) -> bool:
    return str(_host_config(insp).get("NetworkMode") or "").lower() == "host"


def _roda_como_root(insp) -> bool:
    """User vazio conta como root: e o default do Docker, nao um dado ausente."""
    user = str(_config(insp).get("User") or "").strip()
    if not user:
        return True
    return user.split(":")[0] in ("0", "root")


def _sem_limite_memoria(insp) -> bool:
    mem = _host_config(insp).get("Memory") or 0
    try:
        return int(mem) <= 0
    except (TypeError, ValueError):
        return True


def _caps_perigosas(insp) -> bool:
    return bool(_caps(insp) & CAPS_PERIGOSAS)


# --- as regras, como dados ------------------------------------------------

CHECKS = [
    {
        "rule": "docker_socket_mounted",
        "severity": "critical",
        "title": "Socket do Docker montado no container",
        "predicate": _monta_socket,
        "interpretation": (
            "Quem executa codigo neste container fala com o daemon do host: da para "
            "criar container privilegiado, montar / e virar root da maquina."
        ),
        "recommendation": (
            "Remover o bind do socket. Se o container precisa ler o daemon, use um "
            "socket-proxy read-only, como o proprio cockpit faz."
        ),
        "evidence": lambda insp: next(
            (b for b in _binds(insp) if b.split(":")[0] == SOCKET_DOCKER), SOCKET_DOCKER
        ),
    },
    {
        "rule": "privileged",
        "severity": "critical",
        "title": "Container em modo privilegiado",
        "predicate": _privileged,
        "interpretation": (
            "Privileged desliga praticamente todo o isolamento: capabilities, "
            "seccomp e acesso a devices do host."
        ),
        "recommendation": "Trocar privileged por cap_add com a capability especifica que falta.",
        "evidence": lambda insp: "HostConfig.Privileged=true",
    },
    {
        "rule": "network_host",
        "severity": "high",
        "title": "Container na rede do host",
        "predicate": _network_host,
        "interpretation": (
            "Sem namespace de rede o container alcanca qualquer porta em localhost, "
            "incluindo servico que so deveria escutar interno."
        ),
        "recommendation": "Usar rede bridge/definida no compose e publicar apenas as portas necessarias.",
        "evidence": lambda insp: "HostConfig.NetworkMode=host",
    },
    {
        "rule": "cap_add_dangerous",
        "severity": "high",
        "title": "Capability perigosa concedida",
        "predicate": _caps_perigosas,
        "interpretation": (
            "Estas capabilities permitem montar filesystem, alterar rede do host ou "
            "inspecionar processos alheios — caminhos conhecidos de escape."
        ),
        "recommendation": "Remover a capability, ou justificar e isolar o container em rede propria.",
        "evidence": lambda insp: "cap_add: " + ", ".join(sorted(_caps(insp) & CAPS_PERIGOSAS)),
    },
    {
        "rule": "run_as_root",
        "severity": "high",
        "title": "Processo roda como root",
        "predicate": _roda_como_root,
        "interpretation": (
            "Uma falha na aplicacao vira root dentro do container, que e o primeiro "
            "degrau para escapar dele."
        ),
        "recommendation": "Declarar `user:` no compose (ou USER no Dockerfile) com uid nao-zero.",
        "evidence": lambda insp: f"Config.User={_config(insp).get('User') or '(vazio = root)'}",
    },
    {
        "rule": "no_memory_limit",
        "severity": "medium",
        "title": "Sem limite de memoria",
        "predicate": _sem_limite_memoria,
        "interpretation": (
            "Sem teto, um vazamento neste container leva o host inteiro a pressao de "
            "memoria e o OOM killer escolhe a vitima."
        ),
        "recommendation": "Definir `mem_limit` (ou deploy.resources.limits.memory) no compose.",
        "evidence": lambda insp: "HostConfig.Memory=0",
    },
]


def _evidencia(check: dict, insp: dict) -> str:
    """Evidencia da regra, tolerante a inspect torto.

    A regra ja disparou quando isto roda; deixar o formatador de evidencia
    derrubar a resposta trocaria um achado real por um 500.
    """
    fn = check.get("evidence")
    if not callable(fn):
        return ""
    try:
        return str(fn(insp) or "")
    except Exception:
        return ""


def avalia_container(insp: dict) -> dict:
    """Aplica CHECKS a um inspect e devolve score + violacoes."""
    nome = str(insp.get("Name") or "").lstrip("/")
    violations = []
    for check in CHECKS:
        try:
            se_aplica = bool(check["predicate"](insp))
        except Exception:
            # Regra que estoura nao pode calar as outras nem inflar o score:
            # ela simplesmente nao opina sobre este container.
            continue
        if not se_aplica:
            continue
        violations.append({
            "rule": check["rule"],
            "severity": check["severity"],
            "weight": PESOS.get(check["severity"], 0),
            "title": check["title"],
            "interpretation": check["interpretation"],
            "recommendation": check["recommendation"],
            "evidence": _evidencia(check, insp),
        })

    penalidade = sum(v["weight"] for v in violations)
    estado = insp.get("State") if isinstance(insp.get("State"), dict) else {}
    saude = estado.get("Health") if isinstance(estado.get("Health"), dict) else None

    return {
        "id": insp.get("Id") or "",
        "name": nome,
        "image": _config(insp).get("Image") or "",
        "state": estado.get("Status") or "",
        # Ausencia de healthcheck e null, nao "healthy" — o aceite do bloco
        # cobra exatamente isso.
        "health": (saude.get("Status") or None) if saude else None,
        "score": max(0, 100 - penalidade),
        "penalty": penalidade,
        "violations": violations,
    }


def _resumo(avaliados: list) -> dict:
    contagem = {"critical": 0, "high": 0, "medium": 0}
    for c in avaliados:
        for v in c["violations"]:
            if v["severity"] in contagem:
                contagem[v["severity"]] += 1
    scores = [c["score"] for c in avaliados]
    return {
        "containers_avaliados": len(avaliados),
        "score_medio": round(sum(scores) / len(scores), 1) if scores else 100,
        "score_minimo": min(scores) if scores else 100,
        "conformes": sum(1 for c in avaliados if not c["violations"]),
        "violacoes_por_severidade": contagem,
        "unhealthy": sum(1 for c in avaliados if c["health"] == "unhealthy"),
        "sem_healthcheck": sum(1 for c in avaliados if c["health"] is None),
    }


@router.get("/security")
async def get_security():
    inspects = get_container_inspects()
    if not inspects:
        # Boot: o coletor ainda nao rodou. Buscar direto e melhor que devolver
        # "tudo conforme", que e a resposta que mais engana num painel.
        try:
            lista = await proxy_get("/containers/json?all=1")
        except Exception:
            lista = []
        inspects = {}
        for c in lista if isinstance(lista, list) else []:
            cid = c.get("Id") if isinstance(c, dict) else None
            if not cid:
                continue
            try:
                inspects[cid] = await proxy_get(f"/containers/{cid}/json")
            except Exception:
                continue

    avaliados = [
        avalia_container(insp)
        for insp in inspects.values()
        if isinstance(insp, dict)
    ]
    # Pior primeiro: a tela mostra os primeiros N e o operador precisa que os N
    # primeiros sejam os que importam.
    avaliados.sort(key=lambda c: (c["score"], c["name"]))

    return {
        "containers": avaliados,
        "summary": _resumo(avaliados),
        "checks": [
            {"rule": c["rule"], "severity": c["severity"], "title": c["title"], "weight": PESOS.get(c["severity"], 0)}
            for c in CHECKS
        ],
        "pesos": PESOS,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
