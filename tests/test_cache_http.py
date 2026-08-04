"""Politica de cache e alcance da compressao.

Dois achados da regua contra a homologacao, na mesma familia — tráfego que o app
manda para o navegador sem dizer o que fazer com ele:

  `test_politica_de_cache_declarada`  reprovava: `/` saia SEM `Cache-Control`
      nenhum, e sem ele cada navegador e cada proxy inventa a propria heuristica
      a partir do Last-Modified. "No meu nao atualizou" vira comportamento
      legitimo, e nao ha o que depurar porque nao ha decisao escrita.

  `test_resposta_comprimida`  reprovava: a lista de content-type do gzip tinha
      so `application/json` e `text/plain`. A API vinha comprimida; o HTML, o
      CSS e o JS — a metade do peso de uma carga fria — nao.

E um terceiro achado que apareceu ao medir os dois: as fontes saiam como
`text/plain`, porque o `mimetypes` do Python nao conhece `.woff2`. Alem do tipo
errado, isso as fazia casar com a lista de compressao — gzip sobre WOFF2, que ja
e Brotli por dentro, economizou 7 bytes em 48 256 e cobrou CPU dos dois lados.

Os testes de middleware sao diretos sobre o ASGI, no mesmo estilo dos de
compressao em test_hardening_b11.py: e o unico jeito de cobrar o comportamento
de STREAM sem subir um servidor.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")


def _guarda(lista, mensagem):
    lista.append(mensagem)

    async def _nada():
        return None
    return _nada()


async def _roda(middleware_app, scope, cabecalhos_resposta, corpo=b"x", stream=False):
    async def app_falso(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": cabecalhos_resposta})
        if stream:
            for i in range(3):
                await send({"type": "http.response.body",
                            "body": f"data: {i}\n\n".encode(), "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        else:
            await send({"type": "http.response.body", "body": corpo, "more_body": False})

    enviados = []
    await middleware_app(app_falso)(scope, None, lambda m: _guarda(enviados, m))
    return enviados


# ---------------------------------------------------------------------------
# as tres faixas da politica
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caminho,esperado", [
    ("/static/assets/fonts/inter-latin.woff2", b"public, max-age=2592000"),
    ("/static/assets/fonts/jetbrains-mono-latin.woff2", b"public, max-age=2592000"),
    ("/static/js/main.bundle.js", b"no-cache"),
    ("/static/css/base.css", b"no-cache"),
    ("/static/index.html", b"no-cache"),
    # A casca e o icone sao conteudo fixo servido por rota: revalidam, nao somem.
    ("/", b"no-cache"),
    ("/favicon.ico", b"no-cache"),
    # A pagina 404 responde por caminho ARBITRARIO — um proxy guardando aquele
    # corpo sob a URL errada e pior do que nao guardar nada.
    ("/caminho/que/nao/existe", b"no-store"),
    ("/api/overview", b"no-store"),
    ("/api/events/stream", b"no-store"),
    ("/health", b"no-store"),
])
def test_regra_por_caminho(caminho, esperado):
    from cache_http import regra_para
    assert regra_para(caminho) == esperado


def test_estatico_sem_hash_nao_ganha_max_age():
    """A trava que impede a 'otimizacao' obvia e errada.

    `main.bundle.js` NAO tem hash no nome. Com `max-age` longo, um deploy nao
    muda a URL e o cliente segue rodando o JS velho junto com o HTML novo — tela
    quebrada sem erro nenhum no servidor. `no-cache` revalida e o StaticFiles
    devolve 304, que ja emite ETag.
    """
    from cache_http import regra_para
    for caminho in ("/static/js/main.bundle.js", "/static/css/components.css"):
        assert b"max-age" not in regra_para(caminho), (
            f"{caminho} ganhou max-age sem ter hash no nome")


def test_dado_ao_vivo_e_no_store_nao_no_cache():
    """`no-cache` guarda e revalida; `no-store` nao guarda.

    A API devolve nome de container, porta, dominio e achado de seguranca. Isso
    nao deveria encostar em cache de proxy compartilhado nem sobrar em disco
    depois que a aba fecha.
    """
    from cache_http import regra_para
    assert regra_para("/api/containers") == b"no-store"


# ---------------------------------------------------------------------------
# o middleware
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_middleware_declara_o_cabecalho():
    from cache_http import CacheControlMiddleware
    enviados = await _roda(
        CacheControlMiddleware,
        {"type": "http", "path": "/api/overview", "headers": []},
        [(b"content-type", b"application/json")],
    )
    assert dict(enviados[0]["headers"])[b"cache-control"] == b"no-store"


@pytest.mark.asyncio
async def test_middleware_nao_sobrescreve_decisao_da_rota():
    """Preenche ausencia, nao revoga escolha: uma rota que precise de politica
    propria (um relatorio gerado, um download) continua mandando."""
    from cache_http import CacheControlMiddleware
    enviados = await _roda(
        CacheControlMiddleware,
        {"type": "http", "path": "/api/qualquer", "headers": []},
        [(b"content-type", b"application/json"),
         (b"cache-control", b"private, max-age=60")],
    )
    valores = [v for n, v in enviados[0]["headers"] if n == b"cache-control"]
    assert valores == [b"private, max-age=60"], "o middleware pisou na rota"


@pytest.mark.asyncio
async def test_middleware_nao_segura_o_stream():
    """Mesmo cuidado do de compressao: o cabeçalho entra no start e o corpo
    passa chunk a chunk. Segurar o stream para mexer em header devolveria o
    atraso que `compressao.py` existe para evitar."""
    from cache_http import CacheControlMiddleware
    enviados = await _roda(
        CacheControlMiddleware,
        {"type": "http", "path": "/api/events/stream", "headers": []},
        [(b"content-type", b"text/event-stream")],
        stream=True,
    )
    corpos = [m for m in enviados if m["type"] == "http.response.body"]
    assert len(corpos) == 4, "o stream foi juntado num corpo so"
    assert corpos[0]["body"] == b"data: 0\n\n"
    assert corpos[0]["more_body"] is True


@pytest.mark.asyncio
async def test_websocket_passa_intacto():
    from cache_http import CacheControlMiddleware

    chamou = {"sim": False}

    async def app_falso(scope, receive, send):
        chamou["sim"] = True

    await CacheControlMiddleware(app_falso)({"type": "websocket"}, None, None)
    assert chamou["sim"]


# ---------------------------------------------------------------------------
# alcance da compressao
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tipo", [
    "text/html; charset=utf-8",
    "text/css; charset=utf-8",
    "text/javascript; charset=utf-8",
    "application/javascript",
    "image/svg+xml",
    "application/json",
    "application/manifest+json",
    "text/plain; charset=utf-8",
])
def test_tipos_que_comprimem(tipo):
    from compressao import _COMPRESSIVEL
    assert any(t in tipo for t in _COMPRESSIVEL), f"{tipo} ficou de fora do gzip"


@pytest.mark.parametrize("tipo", [
    "font/woff2",
    "font/woff",
    "image/png",
    "image/jpeg",
    "image/webp",
    "text/event-stream",
])
def test_tipos_que_nao_comprimem(tipo):
    """WOFF2 ja e Brotli por dentro; PNG/JPEG/WebP idem. Gzip por cima gasta CPU
    nos dois lados para nao economizar nada — medido: 7 bytes em 48 256.
    `text/event-stream` e o motivo de compressao.py nao usar o GZipMiddleware."""
    from compressao import _COMPRESSIVEL
    assert not any(t in tipo for t in _COMPRESSIVEL), f"{tipo} entrou no gzip"


@pytest.mark.asyncio
async def test_html_grande_sai_comprimido():
    import gzip as _gzip
    from compressao import GzipJsonMiddleware

    corpo = ("<!DOCTYPE html><html><body>" + "<p>conteudo</p>" * 400 + "</body></html>").encode()
    enviados = await _roda(
        GzipJsonMiddleware,
        {"type": "http", "headers": [(b"accept-encoding", b"gzip")]},
        [(b"content-type", b"text/html; charset=utf-8")],
        corpo=corpo,
    )
    cabecalhos = dict(enviados[0]["headers"])
    assert cabecalhos[b"content-encoding"] == b"gzip"
    assert cabecalhos[b"vary"] == b"Accept-Encoding"
    assert _gzip.decompress(enviados[1]["body"]) == corpo


@pytest.mark.asyncio
async def test_fonte_passa_sem_ser_comprimida():
    from compressao import GzipJsonMiddleware

    corpo = os.urandom(40_000)  # bytes ja comprimidos nao tem redundancia
    enviados = await _roda(
        GzipJsonMiddleware,
        {"type": "http", "headers": [(b"accept-encoding", b"gzip")]},
        [(b"content-type", b"font/woff2")],
        corpo=corpo,
    )
    assert not any(n == b"content-encoding" for n, _ in enviados[0]["headers"])
    assert enviados[1]["body"] == corpo


# ---------------------------------------------------------------------------
# o tipo MIME das fontes
# ---------------------------------------------------------------------------

def test_woff2_tem_tipo_registrado():
    """Sem isto o StaticFiles cai no default e serve a fonte como `text/plain` —
    tipo errado, e de quebra ela passa a casar com a lista de compressao."""
    import mimetypes
    import app as _app  # noqa: F401  (o registro acontece no import)
    assert mimetypes.guess_type("inter-latin.woff2")[0] == "font/woff2"
    assert mimetypes.guess_type("x.woff")[0] == "font/woff"
