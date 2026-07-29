import os
import json
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
def mock_db():
    """Mock all db calls to avoid needing a real database."""
    targets = [
        "routers.metrics.get_host_series",
        "routers.metrics.get_first_sample_time",
        "routers.metrics.get_findings",
        "routers.metrics.get_container_stats",
    ]
    with patch(targets[0], new=AsyncMock()) as m1, \
         patch(targets[1], new=AsyncMock()) as m2, \
         patch(targets[2], new=AsyncMock()) as m3, \
         patch(targets[3], return_value=({}, None)):
        yield {"get_host_series": m1, "get_first_sample_time": m2, "get_findings": m3}


# -------------------------------------------------------------------
# OLS projection logic (unit)
# -------------------------------------------------------------------

def _ols(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2 = sum(x * x for x in xs)
    sy2 = sum(y * y for y in ys)
    denom = n * sx2 - sx * sx
    if denom == 0:
        return None
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    r2_num = (n * sxy - sx * sy) ** 2
    r2_den = denom * (n * sy2 - sy * sy)
    r2 = r2_num / r2_den if r2_den > 0 else 0.0
    return {"slope_per_day": round(slope, 4), "intercept": round(intercept, 2), "r2": round(r2, 4)}


def test_ols_linear_subindo():
    """Serie subindo 1.2 pt/dia → slope coerente, r2 alto."""
    ys = [50 + 1.2 * i for i in range(20)]
    xs = list(range(20))
    ols = _ols(xs, ys)
    assert ols is not None
    assert abs(ols["slope_per_day"] - 1.2) < 0.01
    assert ols["r2"] > 0.99


def test_ols_ruido_alto_r2_baixo():
    """Serie achatada com ruido → r2 < 0.7 (instavel)."""
    import random
    random.seed(42)
    ys = [50 + random.uniform(-5, 5) for _ in range(20)]
    xs = list(range(20))
    ols = _ols(xs, ys)
    assert ols is not None
    slope = abs(ols["slope_per_day"])
    assert slope < 1.5  # baixa inclinacao devido ao ruido
    assert ols["r2"] < 0.7


def test_ols_poucos_pontos():
    """Menos de 2 pontos → None."""
    assert _ols([0], [50]) is None
    assert _ols([], []) is None


# -------------------------------------------------------------------
# /api/metrics/history — series curta
# -------------------------------------------------------------------

def test_history_coletando_curto(client, mock_db):
    """Menos de 7 dias de coleta → sem projecao."""
    mock_db["get_first_sample_time"].return_value = "2026-07-26T12:00:00Z"
    mock_db["get_host_series"].side_effect = lambda *a, **kw: [
        {"ts": "2026-07-26", "v": 45.0},
        {"ts": "2026-07-27", "v": 46.0},
    ]
    resp = client.get("/api/metrics/history?series=disk_pct&range=30")
    assert resp.status_code == 200
    data = resp.json()
    assert data["coletando_desde"] == "2026-07-26T12:00:00Z"
    assert data["projection"] is None


# -------------------------------------------------------------------
# /api/metrics/history — serie com projecao estavel
# -------------------------------------------------------------------

def test_history_com_projecao_estavel(client, mock_db):
    """20+ dias de dados, r2 alto → projecao com days_to_90."""
    mock_db["get_first_sample_time"].return_value = "2026-06-01T12:00:00Z"
    mock_db["get_host_series"].side_effect = lambda *a, **kw: [
        {"ts": f"2026-06-{d:02d}", "v": 50 + 1.2 * d}
        for d in range(1, 26)
    ]
    resp = client.get("/api/metrics/history?series=disk_pct&range=30")
    assert resp.status_code == 200
    data = resp.json()
    proj = data["projection"]
    assert proj is not None
    assert proj["stable"] is True
    assert proj["r2"] > 0.99
    assert proj["days_to_90"] is not None
    assert proj["days_to_90"] > 0


# -------------------------------------------------------------------
# /api/metrics/history — serie instavel
# -------------------------------------------------------------------

def test_history_serie_instavel(client, mock_db):
    """r2 < 0.7 → stable=False, sem days_to_N."""
    mock_db["get_first_sample_time"].return_value = "2026-06-01T12:00:00Z"
    import random
    random.seed(42)
    mock_db["get_host_series"].side_effect = lambda *a, **kw: [
        {"ts": f"2026-06-{d:02d}", "v": 50 + random.uniform(-5, 5)}
        for d in range(1, 26)
    ]
    resp = client.get("/api/metrics/history?series=disk_pct&range=30")
    assert resp.status_code == 200
    data = resp.json()
    proj = data["projection"]
    assert proj is not None
    assert proj["stable"] is False


# -------------------------------------------------------------------
# /api/capacity
# -------------------------------------------------------------------

def test_capacity_endpoint(client, mock_db):
    """Endpoint retorna janelas + memoria + postura."""
    mock_db["get_first_sample_time"].return_value = "2026-06-01T12:00:00Z"
    mock_db["get_findings"].return_value = []
    resp = client.get("/api/capacity")
    assert resp.status_code == 200
    data = resp.json()
    assert "windows" in data
    assert len(data["windows"]) == 3
    assert data["windows"][0]["label"] == "24h"
    assert "memory_by_stack" in data
    assert "postura" in data
    assert data["coletando_desde"] == "2026-06-01T12:00:00Z"


def test_capacity_com_findings(client, mock_db):
    """Findings abertos aparecem nas janelas e postura."""
    mock_db["get_first_sample_time"].return_value = "2026-06-01T12:00:00Z"
    mock_db["get_findings"].return_value = [
        {"id": "c1", "rule": "cert_expiring", "target": "example.com", "severity": "critical",
         "scope": "tls", "status": "open", "score": 90,
         "payload": json.dumps({"server_name": "example.com", "expires_at": "2026-08-01"})},
        {"id": "d1", "rule": "disk_pressure", "target": "/", "severity": "critical",
         "scope": "host", "status": "open", "score": 85,
         "payload": json.dumps({"pct": 92})},
    ]
    resp = client.get("/api/capacity")
    assert resp.status_code == 200
    data = resp.json()
    items_24h = data["windows"][0]["items"]
    texts = [i["text"] for i in items_24h]
    assert any("example.com" in t for t in texts)
    assert any("92%" in t for t in texts)


# -------------------------------------------------------------------
# days_to_N helper
# -------------------------------------------------------------------

def _days_to(threshold, slope, intercept):
    if slope <= 0:
        return None
    d = (threshold - intercept) / slope
    return max(1, round(d)) if d > 0 else None


def test_days_to_90():
    """Serie subindo 1.2/dia, intercept 50 → ~34 dias ate 90."""
    d = _days_to(90, 1.2, 50)
    assert d is not None
    assert 30 <= d <= 40


def test_days_to_slope_zero():
    """Slope <= 0 → None."""
    assert _days_to(90, 0, 50) is None
    assert _days_to(90, -0.5, 50) is None


def test_days_to_ja_passou():
    """Threshold ja atingido → None."""
    d = _days_to(50, 1.2, 60)
    assert d is None
