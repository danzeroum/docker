import os
import pytest
from unittest.mock import patch, AsyncMock
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


@pytest.fixture(autouse=True)
def mock_events():
    with patch("app.events_loop", new=AsyncMock()):
        with patch("app.flush_telemetry_loop", new=AsyncMock()):
            yield


def test_backend_endpoint_sem_telemetria(client):
    """GET /api/backend retorna telemetria vazia + findings."""
    with patch("routers.backend.get_telemetry_summary", new=AsyncMock(return_value=[])):
        with patch("routers.backend.get_findings", new=AsyncMock(return_value=[])):
            resp = client.get("/api/backend")
    assert resp.status_code == 200
    data = resp.json()
    assert "telemetry" in data
    assert data["telemetry"] == []
    assert data["findings"]["open"] == 0


def test_backend_com_telemetria(client):
    """Telemetria com uma rota → campos corretos."""
    fake_telemetry = [
        {"route": "GET /api/containers", "total": 100, "errors": 2,
         "avg_ms": 15.0, "p95_ms": 45.0, "dur_max_ms": 120.0, "error_rate": 2.0},
    ]
    with patch("routers.backend.get_telemetry_summary", new=AsyncMock(return_value=fake_telemetry)):
        with patch("routers.backend.get_findings", new=AsyncMock(return_value=[])):
            resp = client.get("/api/backend")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["telemetry"]) == 1
    t = data["telemetry"][0]
    assert t["route"] == "GET /api/containers"
    assert t["total"] == 100
    assert t["errors"] == 2


def test_events_invalidate_cache():
    """container start/stop/die/restart/oom invalida caches e broadcast."""
    from events import _invalidate_caches, _clients, _broadcast
    from unittest.mock import patch
    q = __import__("asyncio").Queue()
    _clients.append(q)
    with patch("cache.invalidate") as mock_inv:
        for action in ("start", "stop", "die", "restart", "oom"):
            _invalidate_caches({"Type": "container", "Action": action})
    assert mock_inv.call_count >= 5, f"invalidate chamada {mock_inv.call_count} vez(es)"
    # broadcast de invalidate
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    assert any(m.get("type") == "invalidate" for m in msgs), "broadcast invalidate"
    _clients.remove(q) if q in _clients else None


def test_events_nao_invalida_outros_eventos():
    """eventos nao-container nao chamam invalidate."""
    from events import _invalidate_caches
    from unittest.mock import patch
    with patch("cache.invalidate") as mock_inv:
        _invalidate_caches({"Type": "network", "Action": "create"})
    mock_inv.assert_not_called()


def test_events_subscribe_unsubscribe():
    """subscribe retorna queue; unsubscribe remove."""
    from events import subscribe, unsubscribe, _clients
    import asyncio
    q = asyncio.run(subscribe())
    assert q in _clients
    assert q.maxsize == 256
    unsubscribe(q)
    assert q not in _clients


def test_telemetry_middleware_histograma(client):
    """Middleware coleta (rota_template, status, duracao) no histograma."""
    from telemetry import _histogram
    _histogram.clear()
    with patch("routers.backend.get_telemetry_summary", new=AsyncMock(return_value=[])):
        with patch("routers.backend.get_findings", new=AsyncMock(return_value=[])):
            resp = client.get("/api/backend")
    assert resp.status_code == 200
    key = "GET /api/backend"
    assert key in _histogram
    entries = _histogram[key]
    assert len(entries) >= 1
    dur, status = entries[0]
    assert status == 200
    assert dur >= 0
