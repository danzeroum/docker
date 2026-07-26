"""Testes de integração das rotas FastAPI.

Usa `respx` para mockar as chamadas httpx ao docker-socket-proxy,
permitindo rodar sem Docker real instalado.
"""
import json
import struct
import pytest
import respx
import httpx
from fastapi.testclient import TestClient

# Garante que o import funciona independente de SOCKET_PROXY estar definido
import os
os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from app import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CONTAINER_ID = "abc123def456abc123def456abc123def456abc123def456abc123def456abc1"

FAKE_CONTAINERS = [
    {
        "Id": CONTAINER_ID,
        "Names": ["/meu-container"],
        "Image": "nginx:stable-alpine",
        "State": "running",
        "Status": "Up 2 hours",
    }
]

FAKE_INSPECT = {
    "Id": CONTAINER_ID,
    "Name": "/meu-container",
    "State": {
        "Status": "running",
        "Running": True,
        "Paused": False,
        "Pid": 1234,
        "ExitCode": 0,
        "Error": "",
        "StartedAt": "2026-07-25T20:00:00Z",
        "RestartCount": 0,
        "Health": None,
    },
    "Config": {
        "Image": "nginx:stable-alpine",
        "Cmd": ["nginx", "-g", "daemon off;"],
        "Env": ["PATH=/usr/local/sbin", "SECRET_KEY=super-secret"],
        "Entrypoint": None,
    },
    "HostConfig": {
        "PortBindings": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]},
        "RestartPolicy": {"Name": "unless-stopped"},
    },
    "NetworkSettings": {
        "IPAddress": "172.17.0.2",
        "Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]},
        "Networks": {
            "bridge": {
                "IPAddress": "172.17.0.2",
                "Gateway": "172.17.0.1",
                "Driver": "bridge",
            }
        },
    },
    "Mounts": [
        {
            "Type": "bind",
            "Source": "/etc/nginx/nginx.conf",
            "Destination": "/etc/nginx/nginx.conf",
            "Mode": "ro",
            "RW": False,
            "Propagation": "rprivate",
        }
    ],
}

FAKE_IMAGES = [{"Id": "sha256:abcdef", "RepoTags": ["nginx:stable-alpine"]}]
FAKE_INFO = {"ID": "node-1", "Containers": 3, "ContainersRunning": 1}


def _make_docker_log_frame(text: str, stream: int = 1) -> bytes:
    """Gera um frame no formato multiplexado do Docker (8-byte header + payload)."""
    payload = text.encode()
    header = struct.pack(">BxxxI", stream, len(payload))
    return header + payload


PROXY = "http://docker-socket-proxy:2375"

# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------


def test_health():
    """GET /health deve retornar {ok: true} sem depender do proxy."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@respx.mock
def test_list_containers():
    """GET /api/containers deve repassar a lista do socket-proxy."""
    respx.get(f"{PROXY}/containers/json").mock(
        return_value=httpx.Response(200, json=FAKE_CONTAINERS)
    )
    r = client.get("/api/containers")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["Id"] == CONTAINER_ID


@respx.mock
def test_inspect_container():
    """GET /api/containers/{id} deve retornar o inspect completo."""
    respx.get(f"{PROXY}/containers/{CONTAINER_ID}/json").mock(
        return_value=httpx.Response(200, json=FAKE_INSPECT)
    )
    r = client.get(f"/api/containers/{CONTAINER_ID}")
    assert r.status_code == 200
    data = r.json()
    assert data["Name"] == "/meu-container"
    assert data["State"]["Running"] is True


@respx.mock
def test_inspect_container_json_alias():
    """GET /api/containers/{id}/json (alias) deve funcionar igual."""
    respx.get(f"{PROXY}/containers/{CONTAINER_ID}/json").mock(
        return_value=httpx.Response(200, json=FAKE_INSPECT)
    )
    r = client.get(f"/api/containers/{CONTAINER_ID}/json")
    assert r.status_code == 200
    assert r.json()["Id"] == CONTAINER_ID


@respx.mock
def test_container_logs_multiplexed():
    """GET /api/containers/{id}/logs deve desempacotar frames multiplexados."""
    raw_frame = _make_docker_log_frame("linha de log\n", stream=1)
    raw_frame += _make_docker_log_frame("erro aqui\n", stream=2)
    respx.get(f"{PROXY}/containers/{CONTAINER_ID}/logs").mock(
        return_value=httpx.Response(200, content=raw_frame)
    )
    r = client.get(f"/api/containers/{CONTAINER_ID}/logs")
    assert r.status_code == 200
    assert "linha de log" in r.text
    assert "erro aqui" in r.text


@respx.mock
def test_container_logs_default_tail():
    """Tail padrão deve ser 500."""
    raw_frame = _make_docker_log_frame("ok\n")
    route = respx.get(f"{PROXY}/containers/{CONTAINER_ID}/logs").mock(
        return_value=httpx.Response(200, content=raw_frame)
    )
    client.get(f"/api/containers/{CONTAINER_ID}/logs")
    assert route.called
    # verifica que tail=500 foi enviado na query string
    called_url = str(route.calls[0].request.url)
    assert "tail=500" in called_url


@respx.mock
def test_container_stats():
    """GET /api/containers/{id}/stats deve retornar snapshot de métricas."""
    fake_stats = {"cpu_stats": {}, "memory_stats": {"usage": 1024}, "networks": {}}
    respx.get(f"{PROXY}/containers/{CONTAINER_ID}/stats").mock(
        return_value=httpx.Response(200, json=fake_stats)
    )
    r = client.get(f"/api/containers/{CONTAINER_ID}/stats")
    assert r.status_code == 200
    assert r.json()["memory_stats"]["usage"] == 1024


@respx.mock
def test_list_images():
    """GET /api/images deve retornar lista de imagens."""
    respx.get(f"{PROXY}/images/json").mock(
        return_value=httpx.Response(200, json=FAKE_IMAGES)
    )
    r = client.get("/api/images")
    assert r.status_code == 200
    assert r.json()[0]["RepoTags"] == ["nginx:stable-alpine"]


@respx.mock
def test_docker_info():
    """GET /api/info deve retornar info do daemon Docker."""
    respx.get(f"{PROXY}/info").mock(
        return_value=httpx.Response(200, json=FAKE_INFO)
    )
    r = client.get("/api/info")
    assert r.status_code == 200
    assert r.json()["Containers"] == 3


@respx.mock
def test_proxy_error_propagates():
    """Erros do socket-proxy (4xx/5xx) devem virar HTTPException."""
    respx.get(f"{PROXY}/containers/nao-existe/json").mock(
        return_value=httpx.Response(404, text="No such container")
    )
    r = client.get("/api/containers/nao-existe/json")
    assert r.status_code == 404


@respx.mock
def test_static_index_html():
    """GET / deve servir o cockpit HTML."""
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Cockpit Docker" in r.text
