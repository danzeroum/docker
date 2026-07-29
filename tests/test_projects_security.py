import os
import pytest
import respx
import httpx
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app import app
from routers._proxy import SOCKET_PROXY

client = TestClient(app)

SESSION_TOKEN = "tok-emitido-pela-sessao"

FAKE_PROJECTS = {
    "meu-app": {"path": "/opt/btv/meu-app", "compose_file": "/opt/btv/meu-app/docker-compose.yml"},
}


@pytest.fixture(autouse=True)
def mock_db():
    """Mock add_audit_entry and unlock session to avoid needing a real database."""
    valid_session = {
        "remote_user": "test", "ip": "", "motivo": "",
        "created_at": "2026-01-01T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z",
    }

    async def _sessao(token):
        # so o token emitido pela sessao vale; qualquer outro valor e negado
        return valid_session if token == SESSION_TOKEN else None

    with patch("routers.projects.add_audit_entry", new=AsyncMock()):
        with patch("routers.containers.add_audit_entry", new=AsyncMock()):
            with patch("auth.get_valid_unlock_session", new=_sessao):
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
    assert "invalida" in r.json()["detail"].lower()


def test_start_header_valido():
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("routers.projects._find_projects", return_value=FAKE_PROJECTS):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)):
            r = client.post(
                "/api/projects/meu-app/start",
                headers={"X-Cockpit-Unlock": SESSION_TOKEN},
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
                headers={"X-Cockpit-Unlock": SESSION_TOKEN},
            )
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"


def test_projeto_inexistente():
    with patch("routers.projects._find_projects", return_value=FAKE_PROJECTS):
        r = client.post(
            "/api/projects/nao-existe/start",
            headers={"X-Cockpit-Unlock": SESSION_TOKEN},
        )
    assert r.status_code == 404


def test_path_traversal():
    with patch("routers.projects._find_projects", return_value=FAKE_PROJECTS):
        r = client.post(
            "/api/projects/../../etc/passwd/start",
            headers={"X-Cockpit-Unlock": SESSION_TOKEN},
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
                headers={"X-Cockpit-Unlock": SESSION_TOKEN},
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
                headers={"X-Cockpit-Unlock": SESSION_TOKEN},
            )
    from routers.projects import add_audit_entry
    # o "quem" e o usuario do basic auth guardado na sessao, nao a string "unlock"
    add_audit_entry.assert_awaited_with("start", "meu-app", "success", "test", "testclient")


CONTAINER_ID = "abc123"


@respx.mock
def test_container_stop_sem_header():
    """POST /api/containers/x/stop sem unlock → 403, nada no proxy."""
    r = client.post(f"/api/containers/{CONTAINER_ID}/stop")
    assert r.status_code == 403
    assert len(respx.calls) == 0


@respx.mock
def test_container_stop_com_unlock():
    """POST /api/containers/x/stop com unlock → 200."""
    proxy_url = f"{SOCKET_PROXY}/containers/{CONTAINER_ID}/stop"
    respx.post(proxy_url).mock(return_value=httpx.Response(204))

    r = client.post(
        f"/api/containers/{CONTAINER_ID}/stop",
        headers={"X-Cockpit-Unlock": SESSION_TOKEN},
    )
    assert r.status_code == 200


@respx.mock
def test_container_start_com_unlock():
    """POST /api/containers/x/start com unlock → 200."""
    proxy_url = f"{SOCKET_PROXY}/containers/{CONTAINER_ID}/start"
    respx.post(proxy_url).mock(return_value=httpx.Response(204))

    r = client.post(
        f"/api/containers/{CONTAINER_ID}/start",
        headers={"X-Cockpit-Unlock": SESSION_TOKEN},
    )
    assert r.status_code == 200


@respx.mock
def test_container_restart_com_unlock():
    """POST /api/containers/x/restart com unlock → 200."""
    proxy_url = f"{SOCKET_PROXY}/containers/{CONTAINER_ID}/restart"
    respx.post(proxy_url).mock(return_value=httpx.Response(204))

    r = client.post(
        f"/api/containers/{CONTAINER_ID}/restart",
        headers={"X-Cockpit-Unlock": SESSION_TOKEN},
    )
    assert r.status_code == 200


@respx.mock
def test_container_remove_com_unlock():
    """DELETE /api/containers/x com unlock → 200."""
    proxy_url = f"{SOCKET_PROXY}/containers/{CONTAINER_ID}"
    respx.delete(proxy_url).mock(return_value=httpx.Response(204))

    r = client.delete(
        f"/api/containers/{CONTAINER_ID}",
        headers={"X-Cockpit-Unlock": SESSION_TOKEN},
    )
    assert r.status_code == 200


@respx.mock
def test_container_get_sem_unlock():
    """GET /api/containers/x fica livre (sem unlock)."""
    proxy_url = f"{SOCKET_PROXY}/containers/{CONTAINER_ID}/json"
    respx.get(proxy_url).mock(return_value=httpx.Response(200, json={"Id": CONTAINER_ID, "Name": "/test", "Config": {"Labels": {}, "Env": [], "Cmd": [], "Entrypoint": None}, "State": {"Running": True}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}, "Mounts": []}))

    r = client.get(f"/api/containers/{CONTAINER_ID}")
    assert r.status_code == 200


def test_all_mutation_routes_have_guard():
    """Verifica que toda POST/DELETE/PATCH de container tem Depends(require_unlock)."""
    import inspect
    from routers.containers import router

    mutation_methods = {"POST", "DELETE"}
    for route in router.routes:
        if not hasattr(route, "methods"):
            continue
        methods = set(route.methods or set())
        if not (methods & mutation_methods):
            continue
        route_str = f"{route.path} [{','.join(route.methods or [])}]"
        sig = inspect.signature(route.endpoint)
        params = list(sig.parameters.values())
        has_depends = any(
            "require_unlock" in str(p.default)
            for p in params
            if p.default is not inspect.Parameter.empty
        )
        if not has_depends:
            import textwrap
            src = textwrap.dedent(inspect.getsource(route.endpoint))
            assert "require_unlock" in src, f"{route_str} falta require_unlock"
