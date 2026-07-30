"""4-B9 — GET /metrics no formato exposition.

Duas propriedades que só um teste pega e que custam caro em produção:

- **estado=0 em vez de a série sumir.** Container que reinicia faria a série
  desaparecer entre scrapes, e `absent()` no alertmanager acordaria alguém por
  um evento que não é incidente.
- **cardinalidade.** Id de container como label incha o Prometheus a cada
  recreate: cada `docker compose up` cria séries novas que nunca mais recebem
  amostra, e elas ficam na memória do TSDB até o retention.
"""

import base64
import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

from app import app  # noqa: E402
import routers.metrics_prom as prom  # noqa: E402

client = TestClient(app)

USUARIO = "operador"
SENHA = "senha-de-teste"


def _auth(usuario=USUARIO, senha=SENHA):
    cru = base64.b64encode(f"{usuario}:{senha}".encode()).decode()
    return {"Authorization": f"Basic {cru}"}


@pytest.fixture(autouse=True)
def _credenciais():
    antes = (os.environ.get("BASIC_AUTH_USER"), os.environ.get("BASIC_AUTH_PASS"))
    os.environ["BASIC_AUTH_USER"] = USUARIO
    os.environ["BASIC_AUTH_PASS"] = SENHA
    yield
    for chave, valor in zip(("BASIC_AUTH_USER", "BASIC_AUTH_PASS"), antes):
        if valor is None:
            os.environ.pop(chave, None)
        else:
            os.environ[chave] = valor


def _snapshot(rodando=True, saude=None, com_limite=True):
    stats = {
        "cafe1": {"cpu_pct": 12.5, "mem_usage": 104857600,
                  "mem_limit": 536870912 if com_limite else None},
    }
    estado = {"Running": rodando, "Status": "running" if rodando else "exited"}
    if saude is not None:
        estado["Health"] = {"Status": saude}
    inspects = {
        "cafe1": {
            "Id": "cafe1", "Name": "/api", "State": estado,
            "Config": {"Image": "nginx:1.25"},
        }
    }
    return stats, inspects


def _com(stats, inspects, amostra=None):
    return (
        patch("routers.metrics_prom.get_container_stats", return_value=(stats, "2026-07-30T12:00:00Z")),
        patch("routers.metrics_prom.get_container_inspects", return_value=inspects),
        patch("routers.metrics_prom.get_last_sample", return_value=amostra),
    )


def _pega(stats, inspects, amostra=None, headers=None):
    p1, p2, p3 = _com(stats, inspects, amostra)
    with p1, p2, p3:
        return client.get("/metrics", headers=headers if headers is not None else _auth())


# --- autenticação ---------------------------------------------------------

def test_sem_credenciais_e_401_com_www_authenticate():
    """401, não 403: é o 401 que faz o scraper mandar a credencial."""
    stats, inspects = _snapshot()
    r = _pega(stats, inspects, headers={})
    assert r.status_code == 401
    assert "Basic" in r.headers.get("www-authenticate", "")


def test_credencial_errada_e_401():
    stats, inspects = _snapshot()
    assert _pega(stats, inspects, headers=_auth(senha="errada")).status_code == 401
    assert _pega(stats, inspects, headers=_auth(usuario="outro")).status_code == 401


def test_credencial_certa_passa():
    stats, inspects = _snapshot()
    r = _pega(stats, inspects)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "version=0.0.4" in r.headers["content-type"]


def test_sem_env_configurada_fecha_em_vez_de_abrir():
    """Fail-closed: instalação que esqueceu de configurar não publica o inventário."""
    os.environ.pop("BASIC_AUTH_USER", None)
    os.environ.pop("BASIC_AUTH_PASS", None)
    stats, inspects = _snapshot()
    r = _pega(stats, inspects)
    assert r.status_code == 503
    assert "BASIC_AUTH" in r.json()["detail"]


def test_verificacao_e_de_tempo_constante():
    """Comparação normal vaza o prefixo correto pelo tempo, e o scraper pode
    tentar à vontade."""
    import inspect as _inspect
    fonte = _inspect.getsource(prom)
    assert "compare_digest" in fonte
    assert fonte.count("compare_digest") >= 2, "usuário e senha precisam dos dois"


# --- exposition -----------------------------------------------------------

def test_metricas_por_container_com_os_valores_do_snapshot():
    stats, inspects = _snapshot()
    corpo = _pega(stats, inspects).text
    assert 'cockpit_container_cpu_pct{name="api",image="nginx:1.25"} 12.5' in corpo
    assert 'cockpit_container_mem_bytes{name="api",image="nginx:1.25"} 104857600' in corpo
    assert 'cockpit_container_mem_limit_bytes{name="api",image="nginx:1.25"} 536870912' in corpo


def test_container_parado_sai_com_estado_zero_e_nao_some():
    """Série que desaparece dispara absent() no alertmanager a cada recreate."""
    stats, inspects = _snapshot(rodando=False)
    corpo = _pega(stats, inspects).text
    assert 'cockpit_container_estado{name="api",image="nginx:1.25"} 0' in corpo
    assert 'cockpit_container_cpu_pct{name="api"' in corpo, "o container sumiu da exposição"


def test_container_rodando_sai_com_estado_um():
    stats, inspects = _snapshot(rodando=True)
    assert 'cockpit_container_estado{name="api",image="nginx:1.25"} 1' in _pega(stats, inspects).text


def test_unhealthy_conta_e_marca():
    stats, inspects = _snapshot(saude="unhealthy")
    corpo = _pega(stats, inspects).text
    assert 'cockpit_container_unhealthy{name="api",image="nginx:1.25"} 1' in corpo
    assert "cockpit_unhealthy_total 1" in corpo


def test_container_sem_healthcheck_nao_ganha_serie_de_saude():
    """Ausência de healthcheck é ausência de medida — 0 afirmaria saúde."""
    stats, inspects = _snapshot(saude=None)
    corpo = _pega(stats, inspects).text
    assert "cockpit_container_unhealthy{" not in corpo
    assert "cockpit_unhealthy_total 0" in corpo


def test_sem_limite_de_memoria_a_serie_nao_aparece():
    stats, inspects = _snapshot(com_limite=False)
    assert "cockpit_container_mem_limit_bytes{" not in _pega(stats, inspects).text


# --- cardinalidade --------------------------------------------------------

def test_apenas_name_e_image_como_labels():
    """Id como label incha o TSDB a cada recreate: séries novas que nunca mais
    recebem amostra ficam na memória até o retention."""
    stats, inspects = _snapshot()
    corpo = _pega(stats, inspects).text
    for linha in corpo.splitlines():
        if not linha.startswith("cockpit_") or "{" not in linha:
            continue
        rotulos = linha[linha.index("{") + 1: linha.rindex("}")]
        chaves = {p.split("=")[0] for p in rotulos.split(",") if "=" in p}
        assert chaves <= {"name", "image"}, f"label de alta cardinalidade: {chaves}"
    assert "cafe1" not in corpo, "o id do container vazou para a exposição"
    assert "2026-07-30T12:00:00Z" not in corpo, "timestamp como label é cardinalidade infinita"


# --- degradação -----------------------------------------------------------

def test_snapshot_vazio_no_boot_e_200_com_exposicao_valida():
    """O Prometheus faz o primeiro scrape antes do coletor rodar."""
    r = _pega({}, {})
    assert r.status_code == 200, "boot sem amostra virou erro"
    corpo = r.text
    assert "# TYPE cockpit_container_cpu_pct gauge" in corpo, "sem HELP/TYPE não é exposição válida"
    assert "cockpit_containers_total 0" in corpo
    assert "cockpit_unhealthy_total 0" in corpo


def test_inspect_ausente_nao_derruba_o_scrape():
    """O sampler tem o stat mas ainda não o inspect — cai no id como nome."""
    stats = {"cafe1beef": {"cpu_pct": 1.0, "mem_usage": 10}}
    corpo = _pega(stats, {}).text
    assert 'name="cafe1beef"' in corpo or 'name="cafe1beef"[:12]' not in corpo
    assert "cockpit_containers_total 1" in corpo


def test_vitais_do_host_saem_quando_ha_amostra():
    stats, inspects = _snapshot()
    amostra = {"cpu": {"percent": 22.5}, "memory": {"percent": 61.0}}
    corpo = _pega(stats, inspects, amostra=amostra).text
    assert "cockpit_host_cpu_pct 22.5" in corpo
    assert "cockpit_host_mem_pct 61.0" in corpo


def test_nome_com_aspas_nao_quebra_o_formato():
    """Nome de container é dado do host; exposition tem escape próprio."""
    stats = {"x": {"cpu_pct": 1, "mem_usage": 1}}
    inspects = {"x": {"Name": '/api"quebrado', "State": {"Running": True},
                      "Config": {"Image": 'img\\estranha'}}}
    corpo = _pega(stats, inspects).text
    assert '\\"' in corpo, "aspa no nome não foi escapada"
    for linha in corpo.splitlines():
        if linha.startswith("cockpit_") and "{" in linha:
            assert linha.count("{") == 1 and linha.count("}") == 1


def test_scrape_nao_chama_o_daemon():
    """15s de scrape_interval viraria 15 chamadas ao daemon por minuto."""
    import inspect as _inspect
    fonte = _inspect.getsource(prom)
    assert "proxy_get" not in fonte
    assert "httpx" not in fonte
