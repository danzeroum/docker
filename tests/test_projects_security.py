import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

os.environ.setdefault("UNLOCK_TOKEN", "test-token-123")

from app import app

client = TestClient(app)

FAKE_PROJECTS = {
    "meu-app": {"path": "/opt/btv/meu-app", "compose_file": "/opt/btv/meu-app/docker-compose.yml"},
}


@pytest.fixture(autouse=True)
def mock_db():
    """Mock add_audit_entry to avoid needing a real database."""
    with patch("routers.projects.add_audit_entry", new=AsyncMock()):
        yield


def test_list_projects_sem_unlock():
    with patch("routers.projects._find_projects", return_value=FAKE_PROJECTS):
        with patch("routers.projects._get_compose_services", return_value=([], None)):
            r = client.get("/api/projects")
    assert r.status_code == 200
    data = r.json()
    assert "projects" in data
    assert data["projects"][0]["name"] == "meu-app"


def test_start_sem_header():
    r = client.post("/api/projects/meu-app/start")
    assert r.status_code == 403
    assert "ausente" in r.json()["detail"].lower()


def test_start_header_invalido():
    r = client.post(
        "/api/projects/meu-app/start",
        headers={"X-Cockpit-Unlock": "senha-errada"},
    )
    assert r.status_code == 403
    assert "invalido" in r.json()["detail"].lower()


def test_start_header_valido():
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("routers.projects._find_projects", return_value=FAKE_PROJECTS):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            r = client.post(
                "/api/projects/meu-app/start",
                headers={"X-Cockpit-Unlock": "test-token-123"},
            )
    assert r.status_code == 200
    assert r.json()["status"] == "started"


def test_stop_sem_header():
    r = client.post("/api/projects/meu-app/stop")
    assert r.status_code == 403


def test_stop_header_valido():
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("routers.projects._find_projects", return_value=FAKE_PROJECTS):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            r = client.post(
                "/api/projects/meu-app/stop",
                headers={"X-Cockpit-Unlock": "test-token-123"},
            )
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"


def test_projeto_inexistente():
    with patch("routers.projects._find_projects", return_value=FAKE_PROJECTS):
        r = client.post(
            "/api/projects/nao-existe/start",
            headers={"X-Cockpit-Unlock": "test-token-123"},
        )
    assert r.status_code == 404


def test_path_traversal():
    with patch("routers.projects._find_projects", return_value=FAKE_PROJECTS):
        r = client.post(
            "/api/projects/../../etc/passwd/start",
            headers={"X-Cockpit-Unlock": "test-token-123"},
        )
    assert r.status_code == 404


def test_subprocess_recebe_lista():
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("routers.projects._find_projects", return_value=FAKE_PROJECTS):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)) as mock_exec:
            client.post(
                "/api/projects/meu-app/start",
                headers={"X-Cockpit-Unlock": "test-token-123"},
            )
            args, kwargs = mock_exec.call_args
            assert isinstance(args, tuple)
            assert args[0] == "docker"
            assert "compose" in args
            assert "-f" in args
            assert all(isinstance(a, str) for a in args)


def test_audit_log_mocked():
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("routers.projects._find_projects", return_value=FAKE_PROJECTS):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            client.post(
                "/api/projects/meu-app/start",
                headers={"X-Cockpit-Unlock": "test-token-123"},
            )
    from routers.projects import add_audit_entry
    add_audit_entry.assert_awaited_with("start", "meu-app", "success", "unlock", "testclient")
