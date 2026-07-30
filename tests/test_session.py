import os
import re
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta

# Valor que existia no env de producao antes da v8. Continua aqui de proposito:
# e o exato payload que os testes de regressao abaixo exigem que seja negado.
STATIC_ENV_TOKEN = "test-unlock-token-valido"


@pytest.fixture(autouse=True)
def set_env():
    os.environ["TRUSTED_GATEWAY_CIDR"] = "172.19.0.0/16"
    with patch("routers.session._get_client_ip", return_value="172.19.0.9"):
        yield
    os.environ.pop("TRUSTED_GATEWAY_CIDR", None)


@pytest.fixture
def client():
    from app import app
    return TestClient(app)


def _valid_session(token="tok-de-sessao", remote_user="admin"):
    now = datetime.now(timezone.utc)
    return {
        "token_hash": "irrelevante-no-mock",
        "remote_user": remote_user,
        "ip": "172.19.0.9",
        "motivo": "",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
    }


def _auth_headers(extra=None):
    h = {"Remote-User": "admin"}
    if extra:
        h.update(extra)
    return h


def _mock_create(token="tok-de-sessao"):
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    return AsyncMock(return_value=(token, expires))


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
    with patch("routers.session.create_unlock_session", new=_mock_create()):
        resp = client.post(
            "/api/session/unlock",
            json={"motivo": "janela X"},
            headers=_auth_headers(),
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"] == "tok-de-sessao"
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
    """Com Remote-User + gateway CIDR valido → 200 + token de sessao."""
    with patch("routers.session.create_unlock_session", new=_mock_create()):
        resp = client.post(
            "/api/session/unlock",
            json={"motivo": "janela X"},
            headers=_auth_headers(),
        )
    assert resp.status_code == 200
    assert resp.json()["token"] == "tok-de-sessao"


def test_unlock_sem_motivo(client):
    """Motivo opcional — sem motivo funciona (contrato do modal Destravar)."""
    with patch("routers.session.create_unlock_session", new=_mock_create()):
        resp = client.post("/api/session/unlock", json={}, headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json()["token"] == "tok-de-sessao"


def test_unlock_expires_at_30_min(client):
    """expires_at ~30 min a partir de agora."""
    with patch("routers.session.create_unlock_session", new=_mock_create()):
        resp = client.post("/api/session/unlock", json={}, headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", data["expires_at"])
    expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
    diff = (expires - datetime.now(timezone.utc)).total_seconds()
    assert 29 * 60 <= diff <= 31 * 60, f"expected ~30 min, got {diff}s"


def test_unlock_vai_para_audit(client):
    """Cada unlock gera linha em audit_log com usuario e motivo."""
    mock_audit = AsyncMock()
    with patch("routers.session.create_unlock_session", new=_mock_create()):
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
# require_unlock — validacao por sessao
# -------------------------------------------------------------------

FAKE_PROJECTS = {"meu-app": {"path": "/opt/btv/meu-app", "compose_file": "/opt/btv/meu-app/docker-compose.yml"}}


def _do_start(client, token, session_mock, audit_mock=None):
    """Dispara start de stack com a auditoria mockada.

    Na v12 a auditoria virou o par iniciar->concluir: a linha nasce ANTES da
    execucao, porque `docker compose up` pode travar ate o timeout de 60s e
    auditar depois perderia exatamente essa linha.
    """
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))
    inicio = audit_mock or AsyncMock(return_value=1)
    with patch("auth.get_valid_unlock_session", new=session_mock):
        with patch("routers.projects.audit_iniciar", new=inicio), \
             patch("routers.projects.audit_concluir", new=AsyncMock()):
            with patch("routers.projects._find_projects", return_value=FAKE_PROJECTS):
                with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
                    return client.post(
                        "/api/projects/meu-app/start",
                        headers={"X-Cockpit-Unlock": token} if token else {},
                    )


def test_mutation_com_sessao_valida_passa(client):
    """Token de sessao vivo → 200."""
    r = _do_start(client, "tok-de-sessao", AsyncMock(return_value=_valid_session()))
    assert r.status_code == 200


def test_mutation_com_sessao_expirada_falha(client):
    """Sessao expirada → 403."""
    r = _do_start(client, "tok-de-sessao", AsyncMock(return_value=None))
    assert r.status_code == 403
    assert "expirada" in r.json()["detail"].lower()


def test_mutation_sem_header_falha(client):
    """Sem X-Cockpit-Unlock → 403."""
    r = _do_start(client, None, AsyncMock(return_value=None))
    assert r.status_code == 403
    assert "ausente" in r.json()["detail"].lower()


def test_auditoria_registra_o_usuario_da_sessao(client):
    """O 'quem' da auditoria vem do basic auth, nao da string 'unlock'."""
    audit = AsyncMock(return_value=1)
    r = _do_start(
        client, "tok-de-sessao",
        AsyncMock(return_value=_valid_session(remote_user="danniel")),
        audit_mock=audit,
    )
    assert r.status_code == 200
    # audit_iniciar(action, project, ator, ip) — o resultado vai no concluir
    args, _ = audit.call_args
    assert args[0] == "start"
    assert args[1] == "meu-app"
    assert args[2] == "danniel", f"esperava o usuario do ingress, veio {args[2]!r}"
