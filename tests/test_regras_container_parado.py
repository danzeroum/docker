"""Container parado no inventario: a mesma licao, duas regras que nao a tinham.

`sampler` busca /containers/json?all=1, entao `ctx.containers` inclui PARADOS.
O `00-decisoes` ja registrava isso para a regra de OOM ("janela de recencia e
obrigatoria em regra baseada em estado"), mas duas outras nunca receberam:

- `upstream_missing` contava parado como presente e SUB-reportava. Em producao,
  criptotrade e prompte davam 502 com a fila em silencio.
- `healthcheck_never_passed` acusava sonda de container morto ha 30h —
  arqueologia apresentada como incidente aberto.

Os dois casos vem da VPS real, nao de fixture inventada.
"""
from datetime import datetime, timedelta, timezone

import pytest

from findings.rules import upstream_missing, healthcheck_never_passed


class Ctx:
    def __init__(self, containers, ingress=None):
        self.containers = containers
        self.ingress = ingress
        self.host = None
        self.history = {}


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _container(nome, rodando=True, health=None):
    # StartedAt ha 1h: a regra compara o tempo de sonda falhando com o uptime.
    inicio = datetime.now(timezone.utc) - timedelta(hours=1)
    estado = {"Running": rodando, "StartedAt": _iso(inicio)}
    if health:
        estado["Health"] = health
    return {"Name": "/" + nome, "State": estado, "Config": {"Image": "x", "Labels": {}}}


# --- catalogo minimo de ingress -------------------------------------------

class _Loc:
    def __init__(self, upstream):
        self.proxy_pass_resolved = upstream
        self.proxy_pass = upstream
        self.path = "/"


class _Server:
    def __init__(self, nome, upstream):
        self.primary_name = nome
        self.server_name = nome
        self.locations = [_Loc(upstream)]


class _Cat:
    def __init__(self, servers):
        self.servers = servers


# ---------------------------------------------------------------------------
# upstream_missing
# ---------------------------------------------------------------------------

def test_upstream_parado_e_reportado():
    """Caso real: criptotrade-frontend existe, esta na rede, e esta exited."""
    cat = _Cat([_Server("criptotrade.exemplo.com", "http://criptotrade-frontend:80")])
    ctx = Ctx([_container("criptotrade-frontend", rodando=False),
               _container("outro-qualquer")], ingress=cat)
    r = upstream_missing.evaluate(ctx)
    assert r, "upstream parado passou batido — 502 com a fila em silencio"
    assert "parado" in r[0]["title"]
    assert "Subir a stack" in r[0]["recommendation"], \
        "o conserto de container parado e subir, nao mexer no proxy_pass"


def test_upstream_inexistente_pede_outro_conserto():
    """Stack removida: mexer no proxy_pass, nao 'subir a stack'."""
    cat = _Cat([_Server("squad.exemplo.com", "http://btv-squad-dashboard:7878")])
    ctx = Ctx([_container("outro-qualquer")], ingress=cat)
    r = upstream_missing.evaluate(ctx)
    assert r
    assert "nao existe" in r[0]["title"]
    assert "renomeado ou removido" in r[0]["recommendation"]


def test_upstream_rodando_nao_dispara():
    cat = _Cat([_Server("ok.exemplo.com", "http://app-web:80")])
    ctx = Ctx([_container("app-web", rodando=True)], ingress=cat)
    assert upstream_missing.evaluate(ctx) is None


def test_sem_inventario_a_regra_se_cala():
    """Sem leitura do daemon nao da para afirmar que o upstream sumiu."""
    cat = _Cat([_Server("x.exemplo.com", "http://qualquer:80")])
    assert upstream_missing.evaluate(Ctx([], ingress=cat)) is None


def test_sem_ingress_a_regra_se_cala():
    assert upstream_missing.evaluate(Ctx([_container("a")], ingress=None)) is None


def test_texto_plain_condiz_com_a_checagem():
    """O _plain ja dizia 'nao e um container em execucao' — agora e verdade."""
    cat = _Cat([_Server("x.exemplo.com", "http://parado:80")])
    r = upstream_missing.evaluate(Ctx([_container("parado", rodando=False)], ingress=cat))
    assert "execucao" in r[0]["interpretation_plain"]


# ---------------------------------------------------------------------------
# healthcheck_never_passed
# ---------------------------------------------------------------------------

def _health_ruim():
    """Sonda falhando a cada 30s desde que o container subiu, ha 1h.

    A regra exige que a falha cubra o uptime quase inteiro (ratio >= 0.7): e o
    que separa "nunca passou" de "passou e piorou depois".
    """
    agora = datetime.now(timezone.utc)
    log = [
        {"ExitCode": 1, "Start": _iso(agora - timedelta(seconds=30 * i)), "Output": "connection refused"}
        for i in range(6)
    ]
    return {"Status": "unhealthy", "FailingStreak": 120, "Log": log}


def test_nao_acusa_sonda_de_container_parado():
    """Caso real: criptotrade-dashboard, exited ha 30h, com achado aberto.

    Arqueologia apresentada como incidente e pior que ausencia de achado — o
    operador aprende a ignorar, e o proximo de verdade fica invisivel.
    """
    ctx = Ctx([_container("criptotrade-dashboard", rodando=False, health=_health_ruim())])
    assert healthcheck_never_passed.evaluate(ctx) is None


def test_ainda_acusa_container_rodando():
    ctx = Ctx([_container("vivo", rodando=True, health=_health_ruim())])
    r = healthcheck_never_passed.evaluate(ctx)
    assert r, "a regra parou de pegar o caso legitimo"


@pytest.mark.parametrize("regra", [upstream_missing, healthcheck_never_passed])
def test_entrada_malformada_nao_derruba(regra):
    cat = _Cat([_Server("x.com", "http://a:80")])
    assert regra.evaluate(Ctx(["lixo", None, 42], ingress=cat)) in (None, [])
