import os
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def set_env():
    os.environ["UNLOCK_TOKEN"] = "test-token"
    os.environ["TRUSTED_GATEWAY_CIDR"] = "172.19.0.0/16"
    yield
    os.environ.pop("UNLOCK_TOKEN", None)
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


def test_ingress_hosts_retorna_lista():
    """GET /api/ingress/hosts retorna {'hosts': [...]}."""
    resp = TestClient(__import__("app").app).get("/api/ingress/hosts")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data.get("hosts"), list)


def test_finding_aggregado_ingress():
    """GET /api/findings traz aggregated finding com rule no_http2 e targets array."""
    fake_rows = [{
        "id": "agg-test",
        "rule": "no_http2",
        "target": "",
        "targets": '["a.com","b.com"]',
        "scope": "ingress",
        "severity": "medium",
        "score": 5,
        "status": "open",
        "first_seen": "2026-01-01T00:00:00Z",
        "last_seen": "2026-07-29T00:00:00Z",
        "occurrences": 2,
        "payload": "{}",
    }]
    with patch("routers.findings.get_findings", new=AsyncMock(return_value=fake_rows)):
        resp = TestClient(__import__("app").app).get("/api/findings?status=open")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["targets"] == ["a.com", "b.com"]
    assert data[0]["scope"] == "ingress"


def test_events_broadcast_error():
    """broadcast de EVENTS desabilitado propaga mensagem de erro."""
    from events import _broadcast, _clients
    import asyncio
    q = asyncio.Queue()
    _clients.append(q)
    _broadcast({"type": "error", "detail": "EVENTS nao habilitado no socket-proxy"})
    msg = q.get_nowait()
    assert msg["type"] == "error"
    assert "EVENTS" in msg["detail"]
    _clients.remove(q)


def test_events_subscribe_fanout():
    """subscribe cria queue, broadcast chega em todos os clientes.
    simulated evento start → invalidate broadcast."""
    from events import subscribe, unsubscribe, _broadcast, _clients
    import asyncio

    async def run():
        q1 = await subscribe()
        q2 = await subscribe()
        _broadcast({"type": "docker_event", "data": {"Type": "container", "Action": "start"}})
        m1 = await asyncio.wait_for(q1.get(), timeout=0.5)
        m2 = await asyncio.wait_for(q2.get(), timeout=0.5)
        assert m1["type"] == "docker_event"
        assert m2["type"] == "docker_event"
        unsubscribe(q1)
        unsubscribe(q2)
        assert q1 not in _clients

    asyncio.run(run())
