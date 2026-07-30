"""B4 — /api/security: score de postura e enriquecimento de saude."""

import os
import sys
from unittest.mock import patch

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

from app import app  # noqa: E402
import cache as cache_mod  # noqa: E402
from routers.security import avalia_container, PESOS  # noqa: E402

client = TestClient(app)
PROXY = "http://docker-socket-proxy:2375"

MB = 1024 * 1024


def inspect(
    cid="abc123",
    nome="servico",
    user="1000",
    privileged=False,
    memory=512 * MB,
    network="bridge",
    binds=None,
    caps=None,
    health=None,
    tem_healthcheck=False,
):
    """Inspect minimo mas realista. O default e um container CONFORME."""
    estado = {"Status": "running", "Running": True}
    if tem_healthcheck:
        estado["Health"] = {"Status": health or "healthy", "FailingStreak": 0}
    return {
        "Id": cid,
        "Name": f"/{nome}",
        "State": estado,
        "Config": {"Image": "nginx:1.25", "User": user},
        "HostConfig": {
            "Privileged": privileged,
            "Memory": memory,
            "NetworkMode": network,
            "Binds": binds or [],
            "CapAdd": caps,
        },
        "Mounts": [],
    }


@pytest.fixture(autouse=True)
def _limpa_cache():
    cache_mod.invalidate()
    yield
    cache_mod.invalidate()


def _com_inspects(mapa):
    return patch("routers.security.get_container_inspects", return_value=mapa)


# --- score -----------------------------------------------------------------

def test_container_conforme_tem_score_100_e_lista_vazia():
    r = avalia_container(inspect())
    assert r["violations"] == [], r["violations"]
    assert r["score"] == 100


def test_privileged_mais_root_da_55_com_duas_violacoes():
    """Fixa a aritmetica: 100 - 30 (critica) - 15 (alta) = 55."""
    r = avalia_container(inspect(user="", privileged=True))

    assert len(r["violations"]) == 2, [v["rule"] for v in r["violations"]]
    assert {v["rule"] for v in r["violations"]} == {"privileged", "run_as_root"}
    assert r["penalty"] == 45
    assert r["score"] == 55


def test_socket_montado_e_violacao_critica_com_nome_de_regra():
    r = avalia_container(inspect(binds=["/var/run/docker.sock:/var/run/docker.sock:ro"]))

    critica = [v for v in r["violations"] if v["severity"] == "critical"]
    assert len(critica) == 1
    assert critica[0]["rule"] == "docker_socket_mounted"
    assert "/var/run/docker.sock" in critica[0]["evidence"]
    assert critica[0]["weight"] == PESOS["critical"] == 30


def test_socket_montado_via_mounts_tambem_detecta():
    """Compose popula Mounts, nao HostConfig.Binds — olhar so Binds deixaria passar."""
    insp = inspect()
    insp["Mounts"] = [
        {"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock"}
    ]
    r = avalia_container(insp)
    assert "docker_socket_mounted" in {v["rule"] for v in r["violations"]}


def test_sem_limite_de_memoria_e_media_de_5():
    r = avalia_container(inspect(memory=0))
    assert {v["rule"] for v in r["violations"]} == {"no_memory_limit"}
    assert r["score"] == 95


def test_network_host_e_cap_perigosa_sao_altas():
    r = avalia_container(inspect(network="host", caps=["NET_ADMIN"]))
    regras = {v["rule"] for v in r["violations"]}
    assert regras == {"network_host", "cap_add_dangerous"}
    assert r["score"] == 70
    cap = next(v for v in r["violations"] if v["rule"] == "cap_add_dangerous")
    assert "NET_ADMIN" in cap["evidence"]


def test_cap_com_prefixo_cap_e_normalizada():
    r = avalia_container(inspect(caps=["CAP_SYS_ADMIN"]))
    assert "cap_add_dangerous" in {v["rule"] for v in r["violations"]}


def test_user_root_explicito_conta_como_root():
    for valor in ("root", "0", "0:0", ""):
        r = avalia_container(inspect(user=valor))
        assert "run_as_root" in {v["rule"] for v in r["violations"]}, f"user={valor!r}"


def test_score_nao_fica_negativo():
    r = avalia_container(
        inspect(
            user="root",
            privileged=True,
            memory=0,
            network="host",
            binds=["/var/run/docker.sock:/var/run/docker.sock"],
            caps=["SYS_ADMIN"],
        )
    )
    assert len(r["violations"]) == 6
    assert r["penalty"] == 110
    assert r["score"] == 0


# --- saude -----------------------------------------------------------------

def test_container_sem_healthcheck_tem_health_null():
    r = avalia_container(inspect(tem_healthcheck=False))
    assert r["health"] is None


def test_container_unhealthy_reporta_status():
    r = avalia_container(inspect(tem_healthcheck=True, health="unhealthy"))
    assert r["health"] == "unhealthy"


def test_inspect_torto_nao_derruba_a_avaliacao():
    """Container recem-criado tem secoes ausentes; regra nao pode virar 500."""
    r = avalia_container({"Id": "x", "Name": "/novo"})
    assert r["score"] <= 100
    assert r["health"] is None
    assert isinstance(r["violations"], list)


# --- rota ------------------------------------------------------------------

def test_rota_ordena_pior_primeiro_e_resume():
    mapa = {
        "bom": inspect(cid="bom", nome="bom"),
        "ruim": inspect(cid="ruim", nome="ruim", user="", privileged=True),
        "medio": inspect(cid="medio", nome="medio", memory=0),
    }
    with _com_inspects(mapa):
        r = client.get("/api/security")

    assert r.status_code == 200, r.text
    body = r.json()
    scores = [c["score"] for c in body["containers"]]
    assert scores == sorted(scores), f"nao veio pior primeiro: {scores}"
    assert body["containers"][0]["name"] == "ruim"

    s = body["summary"]
    assert s["containers_avaliados"] == 3
    assert s["conformes"] == 1
    assert s["score_minimo"] == 55
    assert s["violacoes_por_severidade"]["critical"] == 1
    assert s["sem_healthcheck"] == 3


def test_rota_expoe_o_catalogo_de_regras_como_dado():
    """A UI precisa listar as regras sem reimplementar a tabela de pesos."""
    with _com_inspects({}):
        body = client.get("/api/security").json()

    regras = {c["rule"] for c in body["checks"]}
    assert "docker_socket_mounted" in regras
    assert body["pesos"] == {"critical": 30, "high": 15, "medium": 5}
    for c in body["checks"]:
        assert c["weight"] == body["pesos"][c["severity"]]


@respx.mock
def test_host_sem_container_devolve_resumo_neutro():
    respx.get(f"{PROXY}/containers/json").mock(return_value=httpx.Response(200, json=[]))
    with _com_inspects({}):
        body = client.get("/api/security").json()

    assert body["containers"] == []
    assert body["summary"]["score_medio"] == 100
    assert body["summary"]["containers_avaliados"] == 0


@respx.mock
def test_boot_sem_coletor_busca_do_daemon():
    """Cache vazio no boot nao pode responder 'tudo conforme'."""
    respx.get(f"{PROXY}/containers/json").mock(
        return_value=httpx.Response(200, json=[{"Id": "abc123"}])
    )
    respx.get(f"{PROXY}/containers/abc123/json").mock(
        return_value=httpx.Response(200, json=inspect(user="", privileged=True))
    )

    with _com_inspects({}):
        body = client.get("/api/security").json()

    assert body["summary"]["containers_avaliados"] == 1
    assert body["containers"][0]["score"] == 55


# --- enriquecimento de /api/containers ------------------------------------

@respx.mock
def test_listagem_ganha_campo_health_explicito():
    respx.get(f"{PROXY}/containers/json").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"Id": "abc123", "Names": ["/doente"], "State": "running", "Status": "Up 2 hours"},
                {"Id": "def456", "Names": ["/sem_check"], "State": "running", "Status": "Up 1 hour"},
            ],
        )
    )
    mapa = {
        "abc123": inspect(cid="abc123", tem_healthcheck=True, health="unhealthy"),
        "def456": inspect(cid="def456", tem_healthcheck=False),
    }
    with patch("routers.containers.get_container_inspects", return_value=mapa):
        body = client.get("/api/containers").json()

    por_id = {c["Id"]: c for c in body}
    assert por_id["abc123"]["Health"] == "unhealthy"
    # sem healthcheck e ausencia de dado, nao saude confirmada
    assert por_id["def456"]["Health"] is None


@respx.mock
def test_enriquecimento_nao_contamina_o_cache_compartilhado():
    """`containers_list` e lido por /api/overview e /api/stats/all tambem."""
    respx.get(f"{PROXY}/containers/json").mock(
        return_value=httpx.Response(
            200, json=[{"Id": "abc123", "Names": ["/x"], "State": "running"}]
        )
    )
    mapa = {"abc123": inspect(cid="abc123", tem_healthcheck=True, health="healthy")}
    with patch("routers.containers.get_container_inspects", return_value=mapa):
        client.get("/api/containers")

    entrada = cache_mod._store.get("containers_list") or {}
    dados = entrada.get("data")
    assert isinstance(dados, list) and dados, "o cache nao guardou a listagem"
    assert "Health" not in dados[0], "o objeto cacheado foi mutado no lugar"
