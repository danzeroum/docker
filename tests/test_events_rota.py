"""2b-B3 — GET /api/events e o filtro server-side do stream.

A regra que estes testes protegem: cliente filtrado NUNCA recebe evento fora do
filtro. Filtrar no navegador significaria mandar a timeline inteira do host por
cada aba aberta — e num crash loop isso é o stream inteiro por cliente.
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

from app import app  # noqa: E402
import events as events_mod  # noqa: E402

client = TestClient(app)


def linha(id_=1, action="die", nome="api", stack="web", severity="critical"):
    return {
        "id": id_, "ts": "2026-07-30T12:00:00Z", "type": "container",
        "action": action, "actor_id": "abc", "actor_name": nome,
        "stack": stack, "exit_code": "137", "severity": severity,
    }


@pytest.fixture(autouse=True)
def _limpa_clientes():
    events_mod._clients.clear()
    yield
    events_mod._clients.clear()


# --- GET /api/events ------------------------------------------------------

def test_lista_devolve_eventos_e_filtros_ecoados():
    falso = AsyncMock(return_value=[linha(3), linha(2, action="start", severity="info")])
    with patch("routers.events.get_events", falso):
        r = client.get("/api/events?container=api&severity=critical")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    assert body["filters"] == {"container": "api", "severity": "critical"}
    # o filtro chegou ao servidor, não ficou no cliente
    assert falso.await_args.kwargs["container"] == "api"
    assert falso.await_args.kwargs["severity"] == "critical"


def test_pagina_cheia_devolve_cursor_para_a_proxima():
    falso = AsyncMock(return_value=[linha(i) for i in range(10, 0, -1)])
    with patch("routers.events.get_events", falso):
        body = client.get("/api/events?limit=10").json()
    assert body["next_before_id"] == 1, "sem cursor o cliente não consegue paginar"


def test_pagina_incompleta_nao_promete_proxima():
    falso = AsyncMock(return_value=[linha(3), linha(2)])
    with patch("routers.events.get_events", falso):
        body = client.get("/api/events?limit=10").json()
    assert body["next_before_id"] is None, "cursor em página incompleta faria o cliente pedir vazio"


def test_severidade_invalida_e_422():
    r = client.get("/api/events?severity=urgentissimo")
    assert r.status_code == 422


def test_limite_fora_da_faixa_e_422():
    assert client.get("/api/events?limit=0").status_code == 422
    assert client.get("/api/events?limit=99999").status_code == 422


def test_sem_filtro_devolve_tudo():
    falso = AsyncMock(return_value=[])
    with patch("routers.events.get_events", falso):
        body = client.get("/api/events").json()
    assert body["filters"] == {}
    assert body["events"] == []


# --- filtro server-side do broadcast --------------------------------------

def _cliente(filtro):
    q = asyncio.Queue(maxsize=32)
    events_mod._clients.append((q, filtro or {}))
    return q


def test_cliente_filtrado_nao_recebe_evento_de_outro_container():
    so_api = _cliente({"container": "api"})
    tudo = _cliente({})

    events_mod._broadcast({"type": "docker_event", "data": {}, "row": linha(nome="worker")})

    assert so_api.empty(), "cliente filtrado recebeu evento de outro container"
    assert not tudo.empty(), "cliente sem filtro deixou de receber"


def test_cliente_filtrado_recebe_o_que_pediu():
    so_api = _cliente({"container": "api"})
    events_mod._broadcast({"type": "docker_event", "data": {}, "row": linha(nome="api")})
    assert not so_api.empty()


def test_filtro_combina_varios_campos():
    q = _cliente({"stack": "web", "severity": "critical"})
    events_mod._broadcast({"type": "docker_event", "data": {}, "row": linha(stack="web", severity="info")})
    assert q.empty(), "severidade errada passou"
    events_mod._broadcast({"type": "docker_event", "data": {}, "row": linha(stack="batch", severity="critical")})
    assert q.empty(), "stack errada passou"
    events_mod._broadcast({"type": "docker_event", "data": {}, "row": linha(stack="web", severity="critical")})
    assert not q.empty()


def test_invalidate_passa_por_qualquer_filtro():
    """Plano de controle, não evento: sem ele a tela do cliente filtrado congela."""
    q = _cliente({"container": "api"})
    events_mod._broadcast({"type": "invalidate", "targets": ["overview"]})
    assert not q.empty(), "cliente filtrado ficou sem saber que o cache virou"


def test_erro_passa_por_qualquer_filtro():
    q = _cliente({"container": "api"})
    events_mod._broadcast({"type": "error", "detail": "EVENTS nao habilitado"})
    assert not q.empty()


def test_evento_sem_linha_gravada_nao_chega_a_cliente_filtrado():
    """Ação fora da lista (exec_create) não vira linha — e não interessa a filtro."""
    filtrado = _cliente({"container": "api"})
    tudo = _cliente({})
    events_mod._broadcast({"type": "docker_event", "data": {"Action": "exec_create"}, "row": None})
    assert filtrado.empty()
    assert not tudo.empty(), "quem não filtrou continua vendo o stream cru"


def test_fila_cheia_derruba_so_o_cliente_lento():
    lento = asyncio.Queue(maxsize=1)
    events_mod._clients.append((lento, {}))
    saudavel = _cliente({})

    for _ in range(3):
        events_mod._broadcast({"type": "docker_event", "data": {}, "row": linha()})

    assert not saudavel.empty(), "um cliente lento derrubou a entrega dos outros"
    assert all(par[0] is not lento for par in events_mod._clients), "cliente lento não foi removido"


def test_unsubscribe_remove_o_par_certo():
    a = _cliente({"container": "api"})
    b = _cliente({"container": "front"})
    events_mod.unsubscribe(a)
    assert len(events_mod._clients) == 1
    assert events_mod._clients[0][0] is b


# --- stream ---------------------------------------------------------------
#
# O gerador SSE é infinito por desenho (heartbeat a cada 15s), e o TestClient
# não fecha a conexão sozinho: abrir o stream de verdade aqui trava a suíte.
# O que importa é verificável sem abri-lo — que o filtro da query chega ao
# `subscribe`, e que a resposta declara os cabeçalhos certos.


def test_filtro_da_query_chega_ao_subscribe():
    """É o que garante o filtro no SERVIDOR: o cliente não recebe e descarta."""
    from routers.events import _filtro
    assert _filtro("api", None, None, "critical") == {"container": "api", "severity": "critical"}
    assert _filtro(None, None, None, None) == {}


@pytest.mark.asyncio
async def test_stream_registra_cliente_com_o_filtro_pedido():
    """Chama o handler direto: o gerador não é consumido, só a resposta inspecionada."""
    from starlette.requests import Request
    from routers.events import event_stream

    pedido = Request({"type": "http", "method": "GET", "path": "/api/events/stream",
                      "headers": [], "query_string": b""})
    resp = await event_stream(pedido, container="api", stack=None, action=None, severity="critical")

    assert resp.media_type == "text/event-stream"
    # sem X-Accel-Buffering o nginx entrega o SSE em blocos, não ao vivo
    assert resp.headers.get("x-accel-buffering") == "no"
    assert resp.headers.get("cache-control") == "no-cache"

    # e o cliente entrou na lista JÁ com o filtro — é o que faz o corte ser no
    # servidor e não no navegador
    assert events_mod._clients, "o stream não registrou cliente"
    assert events_mod._clients[-1][1] == {"container": "api", "severity": "critical"}


def test_evento_fora_do_filtro_nao_entra_na_fila_do_cliente_do_stream():
    """Aceite: stream de container inexistente abre e não recebe nada dos outros."""
    q = _cliente({"container": "nao_existe"})
    events_mod._broadcast({"type": "docker_event", "data": {}, "row": linha(nome="api")})
    assert q.empty(), "evento de outro container vazou para o cliente filtrado"
