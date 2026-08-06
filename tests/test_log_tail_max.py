"""Teto declarado da janela de log — LOG_TAIL_MAX.

O `tail` de log e a leitura mais densa em dado pessoal do cockpit: stdout de
aplicacao de terceiro, que chega aqui sem ninguem ter coletado. Mascarar nao
resolve — texto livre nao tem chave para casar, e adivinhar produz falso
negativo silencioso. O que sobra e reduzir o que se expoe de uma vez.

O teto era `min(tail, 5000)` embutido no handler da rota nao-streaming, com o
parametro pedindo 500 por padrao: o pior caso era dez vezes o caso comum. E a
rota de STREAM nao tinha teto nenhum — `?tail=999999` ia do query string direto
para o daemon.

Estes casos guardam as duas metades: o teto vale nas duas rotas, e o piso do
_env_int impede que um .env mal editado o zere.
"""

import importlib
import os
import sys

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

from app import app  # noqa: E402
import db as db_mod  # noqa: E402

client = TestClient(app)
PROXY = "http://docker-socket-proxy:2375"


def _frame(texto: str) -> bytes:
    """Um frame do protocolo multiplexado do daemon: 8 bytes de cabecalho."""
    payload = texto.encode("utf-8")
    return b"\x01\x00\x00\x00" + len(payload).to_bytes(4, "big") + payload


# ---------------------------------------------------------------------------
# O teto morde na rota nao-streaming
# ---------------------------------------------------------------------------

@respx.mock
def test_pedido_acima_do_teto_e_cortado_no_teto():
    """A defesa e no SERVIDOR. Cortar no cliente deixaria o daemon entregar as
    50 mil linhas de qualquer jeito — e o dado ja teria saido do container."""
    rota = respx.get(f"{PROXY}/containers/abc/logs").mock(
        return_value=httpx.Response(200, content=_frame("linha\n"))
    )
    r = client.get("/api/containers/abc/logs?tail=50000")
    assert r.status_code == 200
    assert rota.calls[0].request.url.params["tail"] == str(db_mod.LOG_TAIL_MAX)


@respx.mock
def test_pedido_abaixo_do_teto_passa_intacto():
    """O caso comum nao muda: a tela pede 500, e 500 e o que o daemon recebe."""
    rota = respx.get(f"{PROXY}/containers/abc/logs").mock(
        return_value=httpx.Response(200, content=_frame("linha\n"))
    )
    client.get("/api/containers/abc/logs?tail=120")
    assert rota.calls[0].request.url.params["tail"] == "120"


# ---------------------------------------------------------------------------
# O teto morde tambem no STREAM, onde ele nao existia
# ---------------------------------------------------------------------------

@respx.mock
def test_o_stream_tambem_respeita_o_teto():
    """Era o buraco maior dos dois: `tail` ia do query string direto para o
    daemon, entao `?tail=999999` despejava o log inteiro antes do primeiro
    evento de follow. A janela inicial de um stream e uma leitura como outra —
    o que muda depois e que ela continua, nao que ela comeca maior."""
    rota = respx.get(f"{PROXY}/containers/abc/logs").mock(
        return_value=httpx.Response(200, content=_frame("linha\n"))
    )
    with client.stream("GET", "/api/containers/abc/logs/stream?tail=999999") as r:
        assert r.status_code == 200
        r.read()
    assert rota.calls[0].request.url.params["tail"] == str(db_mod.LOG_TAIL_MAX)


# ---------------------------------------------------------------------------
# O piso do _env_int — variavel de ambiente nao vira surpresa
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("valor,esperado", [
    ("0", 1),        # zero seria "nenhuma linha" e quebraria a tela em silencio
    ("-10", 1),      # negativo o daemon interpreta como "todas", o oposto do teto
    ("2000", 2000),  # quem precisa de mais para depurar sobe deliberadamente
    ("", 500),       # vazia volta ao padrao
    ("abacaxi", 500),  # ilegivel volta ao padrao em vez de explodir no import
])
def test_o_piso_segura_a_variavel_de_ambiente(monkeypatch, valor, esperado):
    """`LOG_TAIL_MAX=-10` sem piso viraria `tail=-10`, e o daemon trata numero
    negativo como "todas as linhas" — a variavel que existe para LIMITAR passaria
    a remover o limite. E o modo de falha e mudo: a resposta vem, maior."""
    monkeypatch.setenv("LOG_TAIL_MAX", valor)
    recarregado = importlib.reload(db_mod)
    try:
        assert recarregado.LOG_TAIL_MAX == esperado
    finally:
        monkeypatch.delenv("LOG_TAIL_MAX", raising=False)
        importlib.reload(db_mod)


def test_o_teto_e_declarado_e_nao_embutido_no_handler():
    """A guarda contra a volta do numero magico. O 5000 vivia dentro do handler,
    onde nenhuma revisao de configuracao o encontrava."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fonte = open(os.path.join(raiz, "app", "routers", "containers.py"), encoding="utf-8").read()
    assert "min(tail, 5000)" not in fonte, "o teto voltou a ser numero magico no handler"
    assert fonte.count("min(tail, LOG_TAIL_MAX)") == 2, "as duas rotas de log usam o teto declarado"
