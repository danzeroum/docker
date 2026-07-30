"""B1 — /api/storage: agregacao do /system/df e deteccao de orfaos."""

import os
import sys
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

from app import app  # noqa: E402
import cache as cache_mod  # noqa: E402

client = TestClient(app)
PROXY = "http://docker-socket-proxy:2375"

GB = 1024 ** 3


def _epoch_dias_atras(dias: int) -> int:
    return int((datetime.now(timezone.utc) - timedelta(days=dias)).timestamp())


DF_COM_SOBRA = {
    "LayersSize": 6 * GB,
    "Images": [
        {"Id": "sha256:aaa", "RepoTags": ["nginx:1.25"], "Size": 2 * GB, "Containers": 1},
        # dangling nas duas formas que o daemon usa
        {"Id": "sha256:bbb", "RepoTags": ["<none>:<none>"], "Size": 1 * GB, "Containers": 0},
        {"Id": "sha256:ccc", "RepoTags": None, "Size": 3 * GB, "Containers": 0},
    ],
    "Containers": [
        {"Id": "c1", "SizeRw": 100},
        {"Id": "c2", "SizeRw": 200},
    ],
    "Volumes": [
        {"Name": "usado_por_container_parado", "UsageData": {"Size": 5 * GB, "RefCount": 0}},
        {"Name": "orfao_de_verdade", "UsageData": {"Size": 2 * GB, "RefCount": 0}},
        {"Name": "tamanho_nao_calculado", "UsageData": {"Size": -1, "RefCount": 0}},
    ],
    "BuildCache": [
        {"ID": "bc1", "Size": 500 * 1024 * 1024, "InUse": False},
        {"ID": "bc2", "Size": 100 * 1024 * 1024, "InUse": True},
    ],
}

CONTAINERS_COM_SOBRA = [
    {
        "Id": "c1",
        "Names": ["/ativo"],
        "State": "running",
        "Created": _epoch_dias_atras(30),
        "SizeRw": 100,
        "Mounts": [{"Type": "volume", "Name": "usado_por_container_parado", "Source": "/v", "Destination": "/d"}],
    },
    {
        "Id": "c2",
        "Names": ["/zumbi"],
        "State": "exited",
        "Created": _epoch_dias_atras(40),
        "SizeRw": 200,
        "Mounts": [],
    },
    {
        "Id": "c3",
        "Names": ["/parado_ontem"],
        "State": "exited",
        "Created": _epoch_dias_atras(1),
        "SizeRw": 50,
        "Mounts": [],
    },
]

DF_LIMPO = {
    "LayersSize": 2 * GB,
    "Images": [{"Id": "sha256:aaa", "RepoTags": ["nginx:1.25"], "Size": 2 * GB, "Containers": 1}],
    "Containers": [{"Id": "c1", "SizeRw": 0}],
    # secoes vazias vem como null, nao []
    "Volumes": None,
    "BuildCache": None,
}

CONTAINERS_LIMPO = [
    {
        "Id": "c1",
        "Names": ["/ativo"],
        "State": "running",
        "Created": _epoch_dias_atras(5),
        "SizeRw": 0,
        "Mounts": [],
    }
]


@pytest.fixture(autouse=True)
def _limpa_cache():
    """O TTL de 30 s da rota vazaria estado de um teste para o outro."""
    cache_mod.invalidate()
    yield
    cache_mod.invalidate()


def _mocka(df, containers):
    respx.get(f"{PROXY}/system/df").mock(return_value=httpx.Response(200, json=df))
    respx.get(f"{PROXY}/containers/json").mock(return_value=httpx.Response(200, json=containers))


@respx.mock
def test_storage_devolve_todas_as_secoes():
    _mocka(DF_COM_SOBRA, CONTAINERS_COM_SOBRA)
    r = client.get("/api/storage")
    assert r.status_code == 200, r.text
    body = r.json()
    for secao in ("images", "containers", "volumes", "build_cache"):
        assert secao in body, f"secao {secao} ausente"
    assert "reclaimable_bytes" in body
    assert isinstance(body["orphans"], list)
    # orfao tipado: os quatro campos que a UI consome
    for o in body["orphans"]:
        assert o["type"] in ("image", "volume", "container")
        assert isinstance(o["size_bytes"], int)
        assert o["name"]
        assert o["reason"]


@respx.mock
def test_duas_imagens_dangling_aparecem_com_tamanho():
    _mocka(DF_COM_SOBRA, CONTAINERS_COM_SOBRA)
    body = client.get("/api/storage").json()

    imagens = [o for o in body["orphans"] if o["type"] == "image"]
    assert len(imagens) == 2, f"esperava 2 dangling, veio {len(imagens)}"
    assert {o["size_bytes"] for o in imagens} == {1 * GB, 3 * GB}
    assert body["images"]["dangling_count"] == 2
    assert body["images"]["dangling_bytes"] == 4 * GB


@respx.mock
def test_volume_de_container_parado_nao_e_orfao():
    """RefCount=0 no df, mas um container exited ainda monta — nao e sobra."""
    _mocka(DF_COM_SOBRA, CONTAINERS_COM_SOBRA)
    body = client.get("/api/storage").json()

    nomes = {o["name"] for o in body["orphans"] if o["type"] == "volume"}
    assert "orfao_de_verdade" in nomes
    assert "usado_por_container_parado" not in nomes, (
        "volume montado por container existente foi classificado como orfao"
    )


@respx.mock
def test_container_parado_ha_pouco_nao_conta_como_zumbi():
    _mocka(DF_COM_SOBRA, CONTAINERS_COM_SOBRA)
    body = client.get("/api/storage").json()

    zumbis = {o["name"] for o in body["orphans"] if o["type"] == "container"}
    assert zumbis == {"zumbi"}, f"esperava so o zumbi de 40 dias, veio {zumbis}"


@respx.mock
def test_reclaimable_soma_os_orfaos_classificados():
    _mocka(DF_COM_SOBRA, CONTAINERS_COM_SOBRA)
    body = client.get("/api/storage").json()

    esperado = sum(o["size_bytes"] for o in body["orphans"])
    assert body["reclaimable_bytes"] == esperado
    # 4 GB de imagem + 2 GB de volume + 200 B do container zumbi
    assert body["reclaimable_bytes"] == 4 * GB + 2 * GB + 200
    # build cache fica fora do numero unico de proposito
    assert body["build_cache"]["reclaimable_bytes"] == 500 * 1024 * 1024


@respx.mock
def test_ambiente_limpo_nao_inventa_orfao():
    """Secoes null e host sem sobra: orphans=[] e reclaimable coerente com o df."""
    _mocka(DF_LIMPO, CONTAINERS_LIMPO)
    r = client.get("/api/storage")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["orphans"] == []
    assert body["reclaimable_bytes"] == 0
    assert body["volumes"]["count"] == 0
    assert body["build_cache"]["count"] == 0
    assert body["images"]["size_bytes"] == 2 * GB
    assert body["images"]["dangling_count"] == 0


@respx.mock
def test_proxy_indisponivel_vira_503_sem_stacktrace():
    respx.get(f"{PROXY}/system/df").mock(side_effect=httpx.ConnectError("connection refused"))
    respx.get(f"{PROXY}/containers/json").mock(return_value=httpx.Response(200, json=[]))

    r = client.get("/api/storage")
    assert r.status_code == 503, r.text
    detalhe = r.json()["detail"]
    assert "socket-proxy" in detalhe
    assert "Traceback" not in detalhe
    assert "/system/df" in detalhe


@respx.mock
def test_cache_evita_segunda_varredura_de_disco():
    rota = respx.get(f"{PROXY}/system/df").mock(
        return_value=httpx.Response(200, json=DF_LIMPO)
    )
    respx.get(f"{PROXY}/containers/json").mock(
        return_value=httpx.Response(200, json=CONTAINERS_LIMPO)
    )

    for _ in range(5):
        assert client.get("/api/storage").status_code == 200

    assert rota.call_count == 1, (
        f"/system/df foi chamado {rota.call_count}x — o cache de 30 s nao pegou"
    )
