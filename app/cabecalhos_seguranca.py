"""Cabeçalhos de segurança da resposta — derivados do que a app REALMENTE usa.

Três achados da régua, os últimos que sobravam do perímetro:
`X-Content-Type-Options`, proteção contra clickjacking e `Content-Security-Policy`.

POR QUE AQUI E NÃO NO NGINX
---------------------------
A régua atribuiu os três ao ingress, e para os dois primeiros tanto faz. Para o
CSP, não: a política é uma DESCRIÇÃO dos recursos que este front carrega, e o
nginx não tem como saber quais são. Três razões concretas:

* O que decide cada diretiva está neste repositório — 117 atributos `style="…"`
  gerados pelos moldes JS, um único `<script src>` externo, fontes
  auto-hospedadas, zero `data:` URI, zero `eval`. Trocar qualquer uma dessas
  coisas muda o CSP.
* CSP errado NÃO devolve erro de servidor: o navegador recusa o recurso e a tela
  fica pela metade, calada. Aqui a política viaja no mesmo commit que o front que
  a determina, e o teste quebra junto no CI.
* O ingress serve 15 domínios. Uma política por app dentro de um nginx
  compartilhado é armadilha de manutenção — e o arquivo dele não está sob CI.

Se além disto quiserem proteção de borda para os OUTROS 14 domínios, é mudança
no bloco `http` do ingress, não aqui. Só não devem duplicar o CSP: dois
cabeçalhos fazem o navegador aplicar a INTERSEÇÃO das duas políticas, e a
depuração disso é sofrida.

AS ESCOLHAS, UMA A UMA
----------------------
`script-src 'self'` sem `'unsafe-inline'` — a casca tem um `<script src>` e mais
nada. É a diretiva que importa de verdade, e ela fica fechada.

`style-src 'self' 'unsafe-inline'` é a única concessão, e é forçada: os 117
`style="…"` nascem em runtime dos moldes, e hash só cobre conteúdo estático —
nonce nem se aplica a atributo. Fechá-la exigiria reescrever os 117 pontos.

Mas a concessão é ESTREITADA onde o navegador deixa: o CSP nível 3 separa
`style-src-elem` (blocos `<style>` e `<link>`) de `style-src-attr` (o atributo).
Declarando os dois, um `<style>` injetado é recusado mesmo assim — sobra apenas
o atributo. O único `<style>` legítimo é o da página 404, e o hash dele é
CALCULADO da mesma string que é servida (ver `hash_de_estilo`), então não há como
os dois saírem de sincronia. Firefox ainda não implementa elem/attr e cai no
`style-src` acima, que continua declarado por isso.

`frame-ancestors 'none'` é a proteção real contra clickjacking; o
`X-Frame-Options` vai junto para navegador que ainda não lê a diretiva. Os dois
dizem a mesma coisa de propósito.

`connect-src 'self'` cobre `fetch` e o `EventSource` das duas rotas que
transmitem — um `connect-src` errado mataria a timeline ao vivo sem um erro
sequer no servidor. Medido: 25 chamadas de API, o stream SSE e o service worker
sobem com zero violação.

Sem `report-uri`/`report-to`: não há coletor. Declarar um endpoint que não
existe é ruído no console do visitante, não observabilidade.
"""

import base64
import hashlib
import re

CSP_BASE = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "img-src 'self'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "manifest-src 'self'; "
    "worker-src 'self'"
)

_ESTILO = re.compile(r"<style>(.*?)</style>", re.S)


def hash_de_estilo(html: str) -> str:
    """`'sha256-…'` do primeiro bloco `<style>` do HTML, no formato do CSP.

    Derivar da string SERVIDA é o ponto: um hash escrito à mão vira mentira no dia
    em que alguém editar o CSS da página de erro, e o sintoma seria uma 404 sem
    estilo que ninguém liga ao CSP.
    """
    achado = _ESTILO.search(html)
    if not achado:
        return ""
    digesto = hashlib.sha256(achado.group(1).encode("utf-8")).digest()
    return f"'sha256-{base64.b64encode(digesto).decode('ascii')}'"


def montar_csp(hashes_de_estilo: tuple[str, ...] = ()) -> str:
    elementos = " ".join(("'self'",) + tuple(h for h in hashes_de_estilo if h))
    return (
        f"{CSP_BASE}; "
        # Fallback para quem não implementa elem/attr (Firefox). Precisa ser
        # permissivo o bastante para os atributos, senão a tela some lá.
        "style-src 'self' 'unsafe-inline'; "
        f"style-src-elem {elementos}; "
        "style-src-attr 'unsafe-inline'"
    )


class SegurancaHeadersMiddleware:
    """ASGI puro, como os dois vizinhos: escreve no `http.response.start`.

    `BaseHTTPMiddleware` embrulharia a resposta e seguraria as rotas que
    transmitem — o defeito que `compressao.py` existe para evitar.

    Não sobrescreve cabeçalho que a resposta já traga: uma rota que precise de
    política própria continua mandando.
    """

    def __init__(self, app, csp: str | None = None):
        self.app = app
        self._cabecalhos = (
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"content-security-policy", (csp or montar_csp()).encode("latin-1")),
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def envia(mensagem):
            if mensagem["type"] == "http.response.start":
                atuais = list(mensagem.get("headers") or [])
                presentes = {n.lower() for n, _ in atuais}
                for nome, valor in self._cabecalhos:
                    if nome not in presentes:
                        atuais.append((nome, valor))
                mensagem["headers"] = atuais
            await send(mensagem)

        await self.app(scope, receive, envia)
