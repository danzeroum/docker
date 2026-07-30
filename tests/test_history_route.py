"""B2 — a rota GET /api/containers/{id}/history e o parse de `range`."""

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

from app import app  # noqa: E402
from routers.containers import _range_para_horas  # noqa: E402

client = TestClient(app)


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("1h", 1),
        ("24h", 24),
        ("7d", 168),
        ("30d", 720),
        ("  24H  ", 24),
    ],
)
def test_range_valido(entrada, esperado):
    assert _range_para_horas(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "ontem", "24", "h24", "-3d", "1w", "0h", "1.5h", None])
def test_range_invalido_e_422_em_vez_de_default_silencioso(entrada):
    """Adivinhar 24 h faria a tela rotular a janela errada como se fosse a pedida."""
    with pytest.raises(HTTPException) as exc:
        _range_para_horas(entrada)
    assert exc.value.status_code == 422


def test_range_absurdo_e_limitado_sem_erro():
    assert _range_para_horas("9999d") == 366 * 24


def test_rota_repassa_horas_e_teto_de_pontos():
    falso = AsyncMock(return_value={"points": [], "resolution": "hourly"})
    with patch("routers.containers.get_container_history", falso):
        r = client.get("/api/containers/cafe1/history?range=7d&max_points=50")

    assert r.status_code == 200, r.text
    falso.assert_awaited_once()
    assert falso.await_args.args[0] == "cafe1"
    assert falso.await_args.kwargs == {"hours": 168, "max_points": 50}


def test_rota_recusa_range_invalido():
    r = client.get("/api/containers/cafe1/history?range=semana")
    assert r.status_code == 422
    assert "range" in r.json()["detail"]


def test_max_points_acima_do_teto_e_cortado():
    falso = AsyncMock(return_value={"points": []})
    with patch("routers.containers.get_container_history", falso):
        client.get("/api/containers/cafe1/history?max_points=99999")
    assert falso.await_args.kwargs["max_points"] == 500


def test_history_nao_colide_com_a_rota_de_inspect():
    """`/{id}` e `/{id}/history` convivem: um id chamado 'history' nao existe."""
    falso = AsyncMock(return_value={"points": [], "resolution": "raw"})
    with patch("routers.containers.get_container_history", falso):
        r = client.get("/api/containers/abc/history")
    assert r.status_code == 200
    assert falso.await_args.args[0] == "abc"
