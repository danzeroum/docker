"""Capacidade dava 500 e a tela dizia "Erro ao carregar dados de capacidade".

Em producao a tela nao abria. A hipotese natural era serie de host_samples
curta demais (horas, nao dias) derrubando /api/capacity. Nao era: com 8
amostras em 2 horas a rota devolve 200 e `coletando_desde` preenchido.

A causa era `import json` DENTRO do laco de achados de certificado. Sem nenhum
achado de certificado o laco nao roda, o nome nunca e ligado, e a leitura de
`payload` do primeiro achado de disco levanta UnboundLocalError. Ou seja: a
rota funcionava enquanto houvesse certificado vencendo, e quebrava justamente
quando havia problema de disco — o caso em que a tela mais importa.

Producao tinha exatamente essa combinacao: achados de disco abertos, nenhum de
certificado.

Os testes abaixo cobrem as duas coisas separadamente, porque sao duas
afirmacoes diferentes: a rota nao quebra por falta de dado (serie curta), e a
rota nao quebra por causa da ORDEM em que os achados aparecem.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def set_env():
    os.environ["TRUSTED_GATEWAY_CIDR"] = "172.19.0.0/16"
    yield
    os.environ.pop("TRUSTED_GATEWAY_CIDR", None)


@pytest.fixture
def client():
    from app import app
    return TestClient(app)


def _achado(rule, severity="critical", payload=None, id_="1"):
    return {
        "id": id_,
        "rule": rule,
        "severity": severity,
        "target": "/",
        "scope": "host",
        "status": "open",
        "payload": json.dumps(payload) if payload is not None else None,
    }


def _serie_de_duas_horas():
    """8 amostras em 2h, todas no mesmo dia — o que a VPS tinha apos o deploy."""
    agora = datetime.now(timezone.utc)
    return [
        {"ts": (agora - timedelta(minutes=15 * i)).isoformat().replace("+00:00", "Z"), "v": 41.0 + i * 0.1}
        for i in range(8)
    ][::-1]


def _mock(findings, serie=None, primeira=None):
    return (
        patch("routers.metrics.get_findings", new=AsyncMock(return_value=findings)),
        patch("routers.metrics.get_first_sample_time", new=AsyncMock(return_value=primeira)),
        patch("routers.metrics.get_host_series", new=AsyncMock(return_value=serie or [])),
        patch("routers.metrics.get_container_stats", return_value=({}, None)),
    )


# ---------------------------------------------------------------------------
# A regressao: achado de disco sem achado de certificado
# ---------------------------------------------------------------------------

def test_achado_de_disco_sem_certificado_nao_quebra(client):
    """O caso de producao. Antes: UnboundLocalError -> 500 -> tela em erro."""
    primeira = datetime.now(timezone.utc) - timedelta(hours=2)
    findings = [_achado("disk_pressure", payload={"pct": 91.4})]
    a, b, c, d = _mock(findings, primeira=primeira.isoformat().replace("+00:00", "Z"))
    with a, b, c, d:
        r = client.get("/api/capacity")
    assert r.status_code == 200, r.text
    corpo = r.json()
    itens = [i["text"] for w in corpo["windows"] for i in w["items"]]
    assert any("91.4" in t for t in itens), \
        "o pct do achado de disco tem de chegar na tela, nao so nao quebrar"


def test_disco_depois_de_certificado_continua_funcionando(client):
    """A ordem inversa passava antes e tem de continuar passando."""
    findings = [
        _achado("cert_expiring", payload={"server_name": "x.exemplo.com", "expires_at": "2026-08-01"}, id_="c1"),
        _achado("disk_pressure", payload={"pct": 88.0}, id_="d1"),
    ]
    a, b, c, d = _mock(findings, primeira=None)
    with a, b, c, d:
        r = client.get("/api/capacity")
    assert r.status_code == 200, r.text


def test_payload_corrompido_e_dado_que_falta_nao_erro(client):
    """Payload truncado no banco nao pode virar 500 numa tela de leitura."""
    findings = [
        _achado("disk_pressure", id_="d1"),
        {"id": "d2", "rule": "disk_pressure", "severity": "critical", "target": "/",
         "scope": "host", "status": "open", "payload": '{"pct": 9'},
        {"id": "c9", "rule": "cert_expiring", "severity": "high", "target": "x",
         "scope": "cert", "status": "open", "payload": "isto nao e json"},
    ]
    a, b, c, d = _mock(findings, primeira=None)
    with a, b, c, d:
        r = client.get("/api/capacity")
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Serie curta: ausencia de dado e "coletando desde X", nunca erro
# ---------------------------------------------------------------------------

def test_serie_de_duas_horas_devolve_200_com_aviso_de_coleta(client):
    primeira = datetime.now(timezone.utc) - timedelta(hours=2)
    iso = primeira.isoformat().replace("+00:00", "Z")
    a, b, c, d = _mock([], serie=_serie_de_duas_horas(), primeira=iso)
    with a, b, c, d:
        r = client.get("/api/capacity")
    assert r.status_code == 200, r.text
    assert r.json()["coletando_desde"] == iso, \
        "sem isso a tela nao tem como dizer 'coletando desde' e cai no vazio"


def test_historico_de_serie_curta_nao_projeta_e_nao_erra(client):
    """< 7 dias de coleta: projection None e o aviso de desde quando."""
    primeira = datetime.now(timezone.utc) - timedelta(hours=2)
    iso = primeira.isoformat().replace("+00:00", "Z")
    a, b, c, d = _mock([], serie=_serie_de_duas_horas(), primeira=iso)
    with a, b, c, d:
        r = client.get("/api/metrics/history?series=disk_pct&range=30")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["projection"] is None, "2h de coleta nao autorizam projetar nada"
    assert corpo["coletando_desde"] == iso
    assert corpo["series"], "a serie curta ainda e serie — a tela desenha o que tem"


def test_sem_amostra_alguma_ainda_e_200(client):
    """Banco recem-criado: nada coletado nao e falha de servidor."""
    a, b, c, d = _mock([], serie=[], primeira=None)
    with a, b, c, d:
        r = client.get("/api/capacity")
        h = client.get("/api/metrics/history?series=disk_pct&range=30")
    assert r.status_code == 200
    assert h.status_code == 200
    assert r.json()["coletando_desde"] is None
    assert h.json()["projection"] is None


def test_alias_range_e_aceito_na_url(client):
    """O parametro se chama range_days no Python e `range` na URL.

    A tela chama ?range=30. Se o alias sumir, a tela recebe 422 e mostra erro
    onde deveria mostrar grafico.
    """
    a, b, c, d = _mock([], serie=[], primeira=None)
    with a, b, c, d:
        assert client.get("/api/metrics/history?range=30").status_code == 200
        assert client.get("/api/metrics/history?range=0").status_code == 422


# ---------------------------------------------------------------------------
# Projecao estavel: a tela desenha barras com intercept + slope*x
# ---------------------------------------------------------------------------

def test_projecao_estavel_traz_o_intercept(client):
    """Sem intercept, a altura das barras projetadas virava NaN silenciosamente."""
    agora = datetime.now(timezone.utc)
    primeira = agora - timedelta(days=40)
    # 40 dias de crescimento limpo: r2 alto, projecao estavel.
    serie = [
        {"ts": (primeira + timedelta(days=i)).isoformat().replace("+00:00", "Z"), "v": 40.0 + i * 0.8}
        for i in range(40)
    ]
    a, b, c, d = _mock([], serie=serie, primeira=primeira.isoformat().replace("+00:00", "Z"))
    with a, b, c, d:
        r = client.get("/api/metrics/history?series=disk_pct&range=30")
    corpo = r.json()
    proj = corpo["projection"]
    assert proj and proj["stable"], f"serie limpa de 40 dias deveria projetar: {proj}"
    assert "intercept" in proj, \
        "a tela usa proj.intercept para desenhar; ausente, a barra fica com altura NaN"
    assert isinstance(proj["intercept"], (int, float))
