import os
import re
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta

UNLOCK_TOKEN = "test-unlock-token-valido"


@pytest.fixture(autouse=True)
def set_env():
    os.environ["UNLOCK_TOKEN"] = UNLOCK_TOKEN
    os.environ["TRUSTED_GATEWAY_CIDR"] = "172.19.0.0/16"
    with patch("routers.session._get_client_ip", return_value="172.19.0.9"):
        yield
    os.environ.pop("UNLOCK_TOKEN", None)
    os.environ.pop("TRUSTED_GATEWAY_CIDR", None)


@pytest.fixture
def client():
    from app import app
    return TestClient(app)


def _valid_session(created_at=None):
    return {"token": UNLOCK_TOKEN, "remote_user": "admin", "ip": "", "motivo": "", "created_at": created_at or "2026-07-28T12:00:00Z"}


def _auth_headers(extra=None):
    h = {"Remote-User": "admin"}
    if extra:
        h.update(extra)
    return h


# -------------------------------------------------------------------
# /api/session/unlock
# -------------------------------------------------------------------

def test_unlock_sem_auth(client):
    """Sem Remote-User → 401."""
    resp = client.post("/api/session/unlock", json={"motivo": "teste"})
    assert resp.status_code == 401


def test_unlock_sem_gateway_cidr(client, caplog):
    """TRUSTED_GATEWAY_CIDR ausente → 403 + log de alerta."""
    os.environ.pop("TRUSTED_GATEWAY_CIDR", None)
    with patch("routers.session._get_client_ip", return_value="172.19.0.9"):
        caplog.set_level("WARNING")
        resp = client.post(
            "/api/session/unlock",
            json={"motivo": "teste"},
            headers=_auth_headers(),
        )
    assert resp.status_code == 403
    assert "nao configurado" in resp.json()["detail"].lower()
    assert any("nao configurado" in rec.message.lower() for rec in caplog.records)


def test_unlock_dentro_do_cidr(client):
    """client.host dentro do CIDR do gateway → 200."""
    with patch("routers.session.set_unlock_state", new=AsyncMock()):
        resp = client.post(
            "/api/session/unlock",
            json={"motivo": "janela X"},
            headers=_auth_headers(),
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"] == UNLOCK_TOKEN
    assert data["expires_at"]


def test_unlock_fora_do_cidr(client):
    """client.host fora do CIDR do gateway → 401."""
    with patch("routers.session._get_client_ip", return_value="172.20.0.5"):
        resp = client.post(
            "/api/session/unlock",
            json={"motivo": "ataque"},
            headers=_auth_headers(),
        )
    assert resp.status_code == 401
    assert "nao autorizada" in resp.json()["detail"].lower()


def test_unlock_com_auth_success(client):
    """Com Remote-User + gateway CIDR valido + token configurado → 200 + token."""
    with patch("routers.session.set_unlock_state", new=AsyncMock()):
        resp = client.post(
            "/api/session/unlock",
            json={"motivo": "janela X"},
            headers=_auth_headers(),
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"] == UNLOCK_TOKEN
    assert data["expires_at"]


def test_unlock_sem_motivo(client):
    """Motivo opcional — sem motivo funciona."""
    with patch("routers.session.set_unlock_state", new=AsyncMock()):
        resp = client.post(
            "/api/session/unlock",
            json={},
            headers=_auth_headers(),
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"] == UNLOCK_TOKEN


def test_unlock_sem_token_configurado(client):
    """UNLOCK_TOKEN nao configurado → 403."""
    os.environ.pop("UNLOCK_TOKEN", None)
    resp = client.post(
        "/api/session/unlock",
        json={},
        headers=_auth_headers(),
    )
    assert resp.status_code == 403


def test_unlock_expires_at_30_min(client):
    """expires_at ~30 min a partir de agora."""
    with patch("routers.session.set_unlock_state", new=AsyncMock()):
        resp = client.post(
            "/api/session/unlock",
            json={},
            headers=_auth_headers(),
        )
    assert resp.status_code == 200
    data = resp.json()
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", data["expires_at"])
    expires = datetime.fromisoformat(data["expires_at"])
    now = datetime.now(timezone.utc)
    diff = (expires - now).total_seconds()
    assert 29 * 60 <= diff <= 31 * 60, f"expected ~30 min, got {diff}s"


def test_unlock_vai_para_audit(client):
    """Cada unlock gera linha em audit_log com usuario e motivo."""
    mock_audit = AsyncMock()
    with patch("routers.session.set_unlock_state", new=AsyncMock()):
        with patch("routers.session.add_audit_entry", new=mock_audit):
            client.post(
                "/api/session/unlock",
                json={"motivo": "janela X"},
                headers=_auth_headers(),
            )
    mock_audit.assert_awaited_once()
    args, _ = mock_audit.call_args
    assert args[0] == "unlock"
    assert args[1] == "janela X"
    assert args[2] == "success"
    assert args[3] == "admin"


# -------------------------------------------------------------------
# require_unlock — server-side expiration
# -------------------------------------------------------------------

FAKE_PROJECTS = {"meu-app": {"path": "/opt/btv/meu-app", "compose_file": "/opt/btv/meu-app/docker-compose.yml"}}


def _do_start(client, token, session_mock):
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))
    with patch("auth.get_valid_unlock_session", new=session_mock):
        with patch("routers.projects.add_audit_entry", new=AsyncMock()):
            with patch("routers.projects._find_projects", return_value=FAKE_PROJECTS):
                with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
                    return client.post(
                        "/api/projects/meu-app/start",
                        headers={"X-Cockpit-Unlock": token} if token else {},
                    )


def test_mutation_com_token_valido_passa(client):
    """Token valido + sessao valida → 200."""
    r = _do_start(client, UNLOCK_TOKEN, AsyncMock(return_value=_valid_session()))
    assert r.status_code == 200


def test_mutation_com_token_expirado_falha(client):
    """Token valido mas sessao expirada → 403."""
    r = _do_start(client, UNLOCK_TOKEN, AsyncMock(return_value=None))
    assert r.status_code == 403
    assert "expirada" in r.json()["detail"].lower()


def test_mutation_sem_sessao_falha(client):
    """Token valido mas nenhuma sessao registrada → 403."""
    r = _do_start(client, UNLOCK_TOKEN, AsyncMock(return_value=None))
    assert r.status_code == 403
    assert "expirada" in r.json()["detail"].lower()
