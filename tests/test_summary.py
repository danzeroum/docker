"""Sprint 2a — bloco `summary` do /api/overview (doc 09 §B).

O summary existe para duas coisas ao mesmo tempo, e os testes cobram as duas:
a régua custa 1 chamada (não 6 fetches por poll), e o chip de um módulo oculto
continua vivo. A segunda é o que obriga o aquecimento em background — sem ele,
módulo oculto nunca seria buscado e o chip morreria.
"""

import os
import sys
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

from app import app  # noqa: E402
import cache as cache_mod  # noqa: E402
import summary as summary_mod  # noqa: E402

client = TestClient(app)
PROXY = "http://docker-socket-proxy:2375"
GB = 1024 ** 3

CHAVES_DOC_09 = ("findings", "stacks", "ingress", "capacity", "audit", "tasks")
CHAVES_SPRINT_2A = ("storage", "security", "drift")


CONTAINERS = [
    {"Id": "c1", "Names": ["/api"], "State": "running", "Image": "nginx:1.25",
     "Labels": {"com.docker.compose.project": "web"}, "Ports": [], "Mounts": []},
    {"Id": "c2", "Names": ["/worker"], "State": "exited", "Image": "app:1",
     "Labels": {"com.docker.compose.project": "batch"}, "Ports": [], "Mounts": []},
]


@pytest.fixture(autouse=True)
def _limpa():
    cache_mod.invalidate()
    yield
    cache_mod.invalidate()
    os.environ.pop("ENABLE_ACTIONS", None)


def _sem_banco():
    """Neutraliza as 3 leituras SQLite; o summary não é teste de banco."""
    return (
        patch("db.get_findings", AsyncMock(return_value=[
            {"severity": "critical"}, {"severity": "high"}, {"severity": "medium"},
        ])),
        patch("db.get_tasks", AsyncMock(return_value=[
            {"col": "todo"}, {"col": "todo"}, {"col": "done"},
        ])),
        patch("db.get_audit_log", AsyncMock(return_value=[
            {"created_at": "2026-07-30T12:00:00Z", "token_label": "dz"},
        ])),
    )


def _grava_cache(chave, dado, ttl=30.0):
    """Escreve direto no cache, como o aquecimento faria."""
    entrada = cache_mod._entry(chave)
    agora = time.monotonic()
    entrada.update({"data": dado, "expires": agora + ttl, "stale_until": agora + ttl * 3})


def _pede_overview():
    with respx.mock:
        respx.get(f"{PROXY}/containers/json").mock(
            return_value=httpx.Response(200, json=CONTAINERS)
        )
        for c in CONTAINERS:
            respx.get(f"{PROXY}/containers/{c['Id']}/json").mock(
                return_value=httpx.Response(200, json={
                    "Id": c["Id"], "Name": c["Names"][0], "State": {"Status": c["State"]},
                    "Config": {"Image": c["Image"], "Labels": c["Labels"]},
                    "HostConfig": {}, "Mounts": [],
                })
            )
        p1, p2, p3 = _sem_banco()
        with p1, p2, p3:
            return client.get("/api/overview")


# --- contrato --------------------------------------------------------------

def test_summary_traz_as_9_chaves_mais_capabilities():
    body = _pede_overview().json()
    s = body["summary"]
    assert s is not None, "summary ausente do /api/overview"
    for chave in CHAVES_DOC_09 + CHAVES_SPRINT_2A:
        assert chave in s, f"chave {chave} ausente do summary"
    assert "capabilities" in s
    assert "stale_since" in s


def test_findings_tasks_e_audit_vem_do_sqlite():
    s = _pede_overview().json()["summary"]
    assert s["findings"] == {"open": 3, "critical": 1}
    assert s["tasks"] == {"total": 3, "todo": 2}
    assert s["audit"]["last_actor"] == "dz"


def test_stacks_derivam_dos_containers_nao_do_scan_de_projects():
    """/api/projects roda `docker compose ps` por projeto — fora do caminho da régua."""
    s = _pede_overview().json()["summary"]
    assert s["stacks"]["total"] == 2
    assert s["stacks"]["up"] == 1, "só a stack web está inteira no ar"


def test_drift_nasce_null_mas_a_chave_existe():
    """B8 pendente: a régua não deve mudar de forma quando o drift chegar."""
    s = _pede_overview().json()["summary"]
    assert s["drift"] == {"count": None}


def test_certificado_sem_fonte_sai_null_e_nao_zero():
    """Não há regra de expiração nem certbot montado — inventar dia é proibido."""
    _grava_cache("ingress", {
        "hosts": {"a.com": {"port_80": {"https_redirect": True}}, "b.com": {}},
        "totals": {"total": 2, "public": 2},
    }, ttl=60.0)
    s = _pede_overview().json()["summary"]
    assert s["ingress"]["certs_expiring"] is None
    assert s["ingress"]["cert_window_days"] is None
    assert s["ingress"]["https_forced"] == 1


# --- mapeamento de nomes (decisão do doc 14 §2) ---------------------------

def test_score_minimo_e_traduzido_para_min_score():
    _grava_cache("security", {
        "summary": {"score_minimo": 55, "violacoes_por_severidade": {"critical": 1, "high": 2}},
    })
    s = _pede_overview().json()["summary"]
    assert s["security"] == {"min_score": 55, "critical": 1}


def test_reclaimable_bytes_e_traduzido_para_gb():
    _grava_cache("storage", {"reclaimable_bytes": 6 * GB, "orphans": [1, 2, 3, 4]})
    s = _pede_overview().json()["summary"]
    assert s["storage"] == {"reclaimable_gb": 6.0, "orphans": 4}


def test_projecao_instavel_nao_promete_prazo():
    """r²<0.7 → days_to_90 null; a régua não mostra prazo que o dado não sustenta."""
    _grava_cache("capacity", {"projection": {"r2": 0.42, "stable": False}}, ttl=300.0)
    with patch("sampler.get_last_sample", return_value={"disks": [{"mountpoint": "/", "percent": 71.0}]}):
        s = _pede_overview().json()["summary"]
    assert s["capacity"]["days_to_90"] is None
    assert s["capacity"]["r2"] == 0.42
    assert s["capacity"]["disk_pct"] == 71.0


def test_projecao_estavel_entrega_o_prazo():
    _grava_cache("capacity", {"projection": {"r2": 0.86, "stable": True, "days_to_90": 24}}, ttl=300.0)
    with patch("sampler.get_last_sample", return_value={"disks": [{"mountpoint": "/", "percent": 71.0}]}):
        s = _pede_overview().json()["summary"]
    assert s["capacity"]["days_to_90"] == 24
    assert s["capacity"]["r2"] == 0.86


# --- degradação ------------------------------------------------------------

def test_fonte_fria_vira_null_com_stale_since_preenchido():
    """Aquecimento nunca rodou: chave presente, null, e stale_since datado."""
    body = _pede_overview()
    assert body.status_code == 200, body.text
    s = body.json()["summary"]
    assert s["storage"] is None
    assert s["stale_since"]["storage"], "stale_since de storage vazio"
    assert s["security"] is None
    assert s["stale_since"]["security"]


def test_storage_derrubado_nao_derruba_o_overview():
    """Aceite do bloco: overview 200, summary.storage=null, stale_since preenchido."""
    _grava_cache("security", {"summary": {"score_minimo": 90, "violacoes_por_severidade": {}}})
    body = _pede_overview()
    assert body.status_code == 200
    s = body.json()["summary"]
    assert s["storage"] is None
    assert s["stale_since"]["storage"]
    # e o resto do summary continua servindo
    assert s["security"]["min_score"] == 90
    assert s["findings"]["open"] == 3


def test_cache_expirado_mas_servivel_entrega_dado_velho_declarado():
    """A régua prefere dado de 1 min a lacuna — desde que se declare velho."""
    _grava_cache("storage", {"reclaimable_bytes": GB, "orphans": []}, ttl=30.0)
    entrada = cache_mod._store["storage"]
    entrada["expires"] = time.monotonic() - 1  # expirou, mas stale_until no futuro
    s = _pede_overview().json()["summary"]
    assert s["storage"]["reclaimable_gb"] == 1.0
    assert s["stale_since"]["storage"], "dado velho entregue sem se declarar velho"


def test_falha_no_sqlite_nao_derruba_o_overview():
    with respx.mock:
        respx.get(f"{PROXY}/containers/json").mock(return_value=httpx.Response(200, json=[]))
        with patch("db.get_findings", AsyncMock(side_effect=RuntimeError("banco travado"))), \
             patch("db.get_tasks", AsyncMock(return_value=[])), \
             patch("db.get_audit_log", AsyncMock(return_value=[])):
            r = client.get("/api/overview")
    assert r.status_code == 200
    s = r.json()["summary"]
    assert s["findings"] is None
    assert s["stale_since"]["findings"]


# --- capabilities ----------------------------------------------------------

def test_actions_enabled_padrao_ligado_na_2a():
    """As 4 rotas de mutação da F5 existem hoje; a UI não pode mentir sobre isso."""
    os.environ.pop("ENABLE_ACTIONS", None)
    s = _pede_overview().json()["summary"]
    assert s["capabilities"]["actions_enabled"] is True


def test_enable_actions_zero_desliga_a_capability():
    """Coerente com as rotas 404 que o B10-residual vai instalar na 2b."""
    os.environ["ENABLE_ACTIONS"] = "0"
    s = _pede_overview().json()["summary"]
    assert s["capabilities"]["actions_enabled"] is False


@pytest.mark.parametrize("valor,esperado", [
    ("1", True), ("true", True), ("YES", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("nao", False),
])
def test_leitura_da_flag_e_tolerante(valor, esperado):
    os.environ["ENABLE_ACTIONS"] = valor
    assert summary_mod.actions_enabled() is esperado


# --- economia: zero chamada ao daemon no request --------------------------

def test_dois_polls_nao_geram_chamada_nova_ao_daemon():
    """O summary não pode transformar cada poll da régua numa varredura de disco."""
    _grava_cache("storage", {"reclaimable_bytes": GB, "orphans": []})
    _grava_cache("security", {"summary": {"score_minimo": 80, "violacoes_por_severidade": {}}})
    _grava_cache("ingress", {"hosts": {}, "totals": {"public": 0}}, ttl=60.0)
    _grava_cache("capacity", {"projection": None}, ttl=300.0)

    with respx.mock:
        lista = respx.get(f"{PROXY}/containers/json").mock(
            return_value=httpx.Response(200, json=[])
        )
        df = respx.get(f"{PROXY}/system/df").mock(
            return_value=httpx.Response(200, json={"Images": [], "Containers": [], "Volumes": [], "BuildCache": []})
        )
        p1, p2, p3 = _sem_banco()
        with p1, p2, p3:
            for _ in range(2):
                assert client.get("/api/overview").status_code == 200

    assert df.call_count == 0, (
        f"/system/df foi chamado {df.call_count}x pelo summary — o peek disparou fetch"
    )
    # a listagem sai 1x: o cache de 5s do overview cobre o segundo poll
    assert lista.call_count <= 1, f"listagem chamada {lista.call_count}x em 2 polls"


def test_peek_nunca_dispara_o_factory():
    chamou = {"n": 0}

    async def factory():
        chamou["n"] += 1
        return {"x": 1}

    assert cache_mod.peek("inexistente") is None
    assert chamou["n"] == 0


def test_peek_reporta_idade_e_frescor():
    _grava_cache("alvo", {"v": 1}, ttl=10.0)
    espiada = cache_mod.peek("alvo")
    assert espiada["fresh"] is True
    assert espiada["servivel"] is True
    assert espiada["ttl"] == pytest.approx(10.0, abs=0.5)
    assert espiada["age"] < 1.0

    cache_mod._store["alvo"]["expires"] = time.monotonic() - 1
    espiada = cache_mod.peek("alvo")
    assert espiada["fresh"] is False
    assert espiada["servivel"] is True, "ainda dentro de stale_until"


# --- aquecimento -----------------------------------------------------------

@pytest.mark.asyncio
async def test_aquecimento_preenche_os_caches_que_a_regua_le():
    """É o que mantém o chip vivo com o módulo oculto (invariante 3, doc 10)."""
    async def falso_storage():
        return {"reclaimable_bytes": 2 * GB, "orphans": []}

    async def falso_security():
        return {"summary": {"score_minimo": 70, "violacoes_por_severidade": {}}}

    async def falso_ingress():
        return {"hosts": {}, "totals": {"public": 0}}

    async def falso_hist(**kwargs):
        return {"projection": {"r2": 0.9, "stable": True, "days_to_90": 30}}

    with patch("routers.storage.get_storage", falso_storage), \
         patch("routers.security.get_security", falso_security), \
         patch("routers.ingress.get_ingress", falso_ingress), \
         patch("routers.metrics.get_metrics_history", falso_hist):
        await summary_mod.aquecer()

    assert cache_mod.peek("storage")["data"]["reclaimable_bytes"] == 2 * GB
    assert cache_mod.peek("security")["data"]["summary"]["score_minimo"] == 70
    assert cache_mod.peek("capacity")["data"]["projection"]["days_to_90"] == 30


@pytest.mark.asyncio
async def test_uma_fonte_quebrada_nao_impede_as_outras():
    """/system/df fora do ar não pode calar o aquecimento do score."""
    async def explode():
        raise RuntimeError("proxy fora")

    async def falso_security():
        return {"summary": {"score_minimo": 42, "violacoes_por_severidade": {}}}

    async def vazio(**kwargs):
        return {}

    with patch("routers.storage.get_storage", explode), \
         patch("routers.security.get_security", falso_security), \
         patch("routers.ingress.get_ingress", vazio), \
         patch("routers.metrics.get_metrics_history", vazio):
        await summary_mod.aquecer()

    assert cache_mod.peek("storage") is None
    assert cache_mod.peek("security")["data"]["summary"]["score_minimo"] == 42
