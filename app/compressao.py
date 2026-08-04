"""Gzip por content-type — nunca em stream, nunca no que já vem comprimido (B11).

O `GZipMiddleware` do Starlette comprime tudo o que passa, e é por isso que ele
não serve aqui: o cockpit tem duas rotas que **transmitem** — o SSE de
`/api/events` e o follow de logs. Comprimir um stream em gzip introduz buffer
entre o evento acontecer e o navegador vê-lo, e a timeline ao vivo é justamente
o que não pode chegar atrasada. Um `docker stop` que aparece 40 s depois na tela
não é um cockpit vivo.

Por isso a decisão é pelo **content-type**, e por uma LISTA, nunca por prefixo:
`text/` pegaria `text/event-stream` junto e quebraria exatamente as duas rotas
que motivaram este arquivo. Filtrar por caminho resolveria as rotas de hoje e
quebraria na terceira.

A lista começou só com JSON e text/plain — a API vinha comprimida e o HTML, o CSS
e o JS não, que é a metade do tráfego de uma carga fria. Media-se 384 KB de
estáticos sem compressão nenhuma enquanto `/api/overview` chegava gzipado.

O QUE NÃO ENTRA, e é decisão e não esquecimento:

  `font/woff2`  — WOFF2 já é Brotli por dentro da própria especificação. Medido
                  neste projeto: gzip sobre a fonte economizou 7 bytes em 48 256
                  (0,01%) e cobrou CPU dos dois lados. Só entrava na lista porque
                  o `mimetypes` do Python não conhece a extensão e a servia como
                  `text/plain` — corrigido em `app.py`, onde o tipo é registrado.
  `image/png`, `image/jpeg`, `image/webp` — mesmo motivo: já comprimidos.
  `text/event-stream` — ver acima; é o motivo de este arquivo existir.
"""

import gzip
import io

# Abaixo disto o cabeçalho de gzip custa mais do que economiza, e ainda gasta
# CPU nos dois lados.
MINIMO_BYTES = 1024

_COMPRESSIVEL = (
    "application/json",           # a API, e o manifest não casa com isto — vem abaixo
    "application/manifest+json",
    "text/plain",
    "text/html",                  # a casca e a página de erro
    "text/css",
    "text/javascript",            # é o que o mimetypes do Python devolve para .js
    "application/javascript",     # e é o que outros servidores devolvem
    "image/svg+xml",              # o ícone: é XML, comprime como texto
)


class GzipJsonMiddleware:
    """ASGI puro: precisa decidir no `http.response.start`, antes do corpo."""

    def __init__(self, app, minimo: int = MINIMO_BYTES):
        self.app = app
        self.minimo = minimo

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        aceita = ""
        for nome, valor in scope.get("headers") or []:
            if nome == b"accept-encoding":
                aceita = valor.decode("latin-1")
                break
        if "gzip" not in aceita.lower():
            await self.app(scope, receive, send)
            return

        estado = {"inicio": None, "buffer": None, "passa": False}

        async def envia(mensagem):
            if mensagem["type"] == "http.response.start":
                cabecalhos = mensagem.get("headers") or []
                tipo, ja_codificado = "", False
                for nome, valor in cabecalhos:
                    if nome == b"content-type":
                        tipo = valor.decode("latin-1").lower()
                    elif nome == b"content-encoding":
                        ja_codificado = True
                estado["passa"] = (
                    ja_codificado or not any(t in tipo for t in _COMPRESSIVEL)
                )
                if estado["passa"]:
                    await send(mensagem)
                    return
                # Segura o start: os cabeçalhos só ficam corretos depois de
                # saber o tamanho comprimido.
                estado["inicio"] = mensagem
                estado["buffer"] = io.BytesIO()
                return

            if mensagem["type"] != "http.response.body" or estado["passa"]:
                await send(mensagem)
                return

            estado["buffer"].write(mensagem.get("body") or b"")
            if mensagem.get("more_body"):
                return

            corpo = estado["buffer"].getvalue()
            inicio = estado["inicio"]
            if len(corpo) < self.minimo:
                await send(inicio)
                await send({"type": "http.response.body", "body": corpo, "more_body": False})
                return

            comprimido = gzip.compress(corpo, compresslevel=6)
            cabecalhos = [
                (n, v) for n, v in (inicio.get("headers") or [])
                if n not in (b"content-length", b"content-encoding")
            ]
            cabecalhos.append((b"content-encoding", b"gzip"))
            cabecalhos.append((b"content-length", str(len(comprimido)).encode()))
            # `Vary` porque a MESMA URL devolve bytes diferentes conforme o
            # Accept-Encoding: sem ele, um cache intermediário serve a resposta
            # comprimida a um cliente que não pediu gzip.
            if not any(n == b"vary" for n, _ in cabecalhos):
                cabecalhos.append((b"vary", b"Accept-Encoding"))
            inicio["headers"] = cabecalhos
            await send(inicio)
            await send({"type": "http.response.body", "body": comprimido, "more_body": False})

        await self.app(scope, receive, envia)
