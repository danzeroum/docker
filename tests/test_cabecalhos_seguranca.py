"""Os tres cabecalhos de seguranca que a regua cobrava — e o CSP que a app usa.

`X-Content-Type-Options`, protecao contra clickjacking e `Content-Security-Policy`
eram as ultimas tres reprovacoes de perimetro. A regua as atribuiu ao ingress, e
para as duas primeiras tanto faz; o CSP nao, porque ele e uma DESCRICAO dos
recursos que este front carrega — e quem sabe quais sao e este repositorio.

O que torna estes testes necessarios, e nao decorativos: CSP errado NAO devolve
erro de servidor. O navegador recusa o recurso e a tela fica pela metade, calada.
E o mesmo modo de falha do roteador do rail e do `Health` nulo — os dois defeitos
que custaram mais caro neste projeto. Uma politica que ninguem cobra em CI vira
armadilha no dia em que o front ganhar uma dependencia nova.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")

from fastapi.testclient import TestClient  # noqa: E402

from app import app, _PAGINA_404  # noqa: E402
from cabecalhos_seguranca import (  # noqa: E402
    SegurancaHeadersMiddleware, hash_de_estilo, montar_csp,
)

client = TestClient(app)


def _diretivas(csp: str) -> dict[str, str]:
    fora = {}
    for parte in csp.split(";"):
        parte = parte.strip()
        if not parte:
            continue
        nome, _, valor = parte.partition(" ")
        fora[nome] = valor.strip()
    return fora


# ---------------------------------------------------------------------------
# os tres cabecalhos, na resposta de verdade
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caminho", ["/", "/health", "/favicon.ico", "/nao-existe"])
def test_os_tres_cabecalhos_saem_em_toda_resposta(caminho):
    r = client.get(caminho)
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("content-security-policy")


def test_clickjacking_tem_as_duas_defesas():
    """`frame-ancestors` e a protecao real; `X-Frame-Options` acompanha para
    navegador que ainda nao le a diretiva. Dizem a mesma coisa de proposito."""
    r = client.get("/")
    assert r.headers["x-frame-options"] == "DENY"
    assert _diretivas(r.headers["content-security-policy"])["frame-ancestors"] == "'none'"


# ---------------------------------------------------------------------------
# o CSP descreve o que a app REALMENTE usa
# ---------------------------------------------------------------------------

def test_script_src_nao_afrouxa():
    """A diretiva que importa de verdade. A casca tem UM `<script src>` e nada
    inline — nao ha desculpa para `unsafe-inline` nem `unsafe-eval` aqui."""
    d = _diretivas(client.get("/").headers["content-security-policy"])
    assert d["script-src"] == "'self'"
    assert "unsafe-inline" not in d["script-src"]
    assert "unsafe-eval" not in d["script-src"]


def test_a_casca_nao_tem_script_inline():
    """O teste acima so continua valido enquanto isto for verdade."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(raiz, "app", "static", "index.html")).read()
    assert "<script>" not in html, (
        "apareceu script inline na casca; `script-src 'self'` vai bloquea-lo em silencio")


@pytest.mark.parametrize("diretiva,esperado", [
    ("default-src", "'self'"),
    ("base-uri", "'self'"),
    ("object-src", "'none'"),
    ("form-action", "'self'"),
    ("connect-src", "'self'"),
    ("font-src", "'self'"),
    ("worker-src", "'self'"),
])
def test_diretivas_fechadas(diretiva, esperado):
    d = _diretivas(client.get("/").headers["content-security-policy"])
    assert d[diretiva] == esperado


def test_connect_src_cobre_as_rotas_que_transmitem():
    """`connect-src` governa `fetch` E `EventSource`. Errado aqui, a timeline ao
    vivo morre sem um erro sequer no servidor — falha silenciosa de novo."""
    d = _diretivas(client.get("/").headers["content-security-policy"])
    assert d["connect-src"] == "'self'", "o SSE de /api/events sai por connect-src"


def test_unsafe_inline_so_existe_para_estilo():
    """A unica concessao, e ela e forcada: os `style="…"` nascem em runtime dos
    moldes JS, e hash so cobre conteudo estatico — nonce nem se aplica a atributo."""
    csp = client.get("/").headers["content-security-policy"]
    d = _diretivas(csp)
    com_unsafe = [k for k, v in d.items() if "unsafe-inline" in v]
    assert set(com_unsafe) <= {"style-src", "style-src-attr"}, (
        f"unsafe-inline vazou para diretiva que nao e de estilo: {com_unsafe}")


# ---------------------------------------------------------------------------
# o hash do <style> da 404, derivado da string servida
# ---------------------------------------------------------------------------

def test_style_src_elem_nao_aceita_inline():
    """Estreita a concessao onde o navegador deixa: um `<style>` INJETADO e
    recusado mesmo assim; sobra so o atributo."""
    d = _diretivas(client.get("/").headers["content-security-policy"])
    assert "unsafe-inline" not in d["style-src-elem"]
    assert "sha256-" in d["style-src-elem"], "o bloco legitimo da 404 perdeu o hash"


def test_hash_vem_da_pagina_servida():
    """Derivar da MESMA string que e servida e o ponto: hash escrito a mao vira
    mentira no dia em que alguem editar o CSS da pagina de erro, e o sintoma seria
    uma 404 sem estilo que ninguem ligaria ao CSP."""
    esperado = hash_de_estilo(_PAGINA_404)
    assert esperado.startswith("'sha256-")
    d = _diretivas(client.get("/").headers["content-security-policy"])
    assert esperado in d["style-src-elem"]


def test_hash_acompanha_edicao_do_css():
    a = hash_de_estilo(_PAGINA_404)
    b = hash_de_estilo(_PAGINA_404.replace("font-size:1.4rem", "font-size:1.5rem"))
    assert a != b, "o hash nao acompanha o conteudo; sincronia so aparente"


def test_html_sem_style_nao_gera_hash_vazio_no_csp():
    assert hash_de_estilo("<html><body>nada</body></html>") == ""
    csp = montar_csp(("",))
    assert "style-src-elem 'self';" in csp + ";", "hash vazio sujou a diretiva"


# ---------------------------------------------------------------------------
# o middleware
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nao_sobrescreve_cabecalho_que_a_rota_declarou():
    enviados = []

    async def app_falso(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/html"),
                                (b"x-frame-options", b"SAMEORIGIN")]})
        await send({"type": "http.response.body", "body": b"x", "more_body": False})

    async def guarda(m):
        enviados.append(m)

    await SegurancaHeadersMiddleware(app_falso)(
        {"type": "http", "path": "/", "headers": []}, None, guarda)
    valores = [v for n, v in enviados[0]["headers"] if n == b"x-frame-options"]
    assert valores == [b"SAMEORIGIN"], "o middleware pisou na rota"


@pytest.mark.asyncio
async def test_nao_segura_o_stream():
    """Mesmo cuidado dos dois middlewares vizinhos: cabecalho entra no start e o
    corpo passa pedaco a pedaco. Segurar o stream devolveria o atraso que
    compressao.py existe para evitar."""
    enviados = []

    async def app_falso(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        for i in range(3):
            await send({"type": "http.response.body",
                        "body": f"data: {i}\n\n".encode(), "more_body": True})

    async def guarda(m):
        enviados.append(m)

    await SegurancaHeadersMiddleware(app_falso)(
        {"type": "http", "path": "/api/events", "headers": []}, None, guarda)
    corpos = [m for m in enviados if m["type"] == "http.response.body"]
    assert len(corpos) == 3
    assert corpos[0]["more_body"] is True


@pytest.mark.asyncio
async def test_websocket_passa_intacto():
    chamou = {"sim": False}

    async def app_falso(scope, receive, send):
        chamou["sim"] = True

    await SegurancaHeadersMiddleware(app_falso)({"type": "websocket"}, None, None)
    assert chamou["sim"]
