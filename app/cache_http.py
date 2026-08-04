"""Política de cache HTTP — declarada, e não deixada ao acaso (B11).

(Nome `cache_http` para não colidir com `cache.py`, que é o cache EM MEMÓRIA do
servidor. Este arquivo não guarda nada: só diz ao cliente o que ele pode guardar.)

Sem `Cache-Control`, cada navegador e cada proxy inventa a própria heurística a
partir do `Last-Modified`. O comportamento fica indefinido: uma instalação
revalida a cada carga, outra segura o JS por horas, e a diferença aparece só como
"no meu não atualizou".

A política tem TRÊS faixas, e o que decide entre elas são duas perguntas: os
bytes são conteúdo estático, e podem mudar sob a mesma URL?

  /static/assets/fonts/**   `public, max-age=2592000`  (30 dias)
      Fonte é o único estático cujos bytes não mudam na prática — são
      subconjuntos de uma versão publicada, sob nome fixo. São também o maior
      payload estático do painel (172 KB nas quatro), o que faz deste o item de
      melhor retorno. 30 dias e NÃO `immutable`: `immutable` é promessa que só se
      cumpre com nome versionado por hash, e este projeto não tem build de assets
      com hash. Prometer o que não se pode cumprir custa uma fonte velha presa
      por um ano no navegador de alguém.

  /static/**, `/`, /favicon.ico    `no-cache`
      Revalida SEMPRE, e a resposta é 304 quase toda vez porque o `StaticFiles`
      já emite ETag e Last-Modified. `no-cache` não é "não guarde" — é "guarde,
      mas pergunte antes de usar". Custa uma requisição condicional e devolve
      zero byte de corpo.

      `/` e `/favicon.ico` entram aqui embora não sejam servidos pelo mount de
      estáticos: são conteúdo fixo, sem dado de infraestrutura dentro. Deixá-los
      em `no-store` obrigaria a rebaixar a casca inteira por carga para não
      proteger nada. A página de erro 404 NÃO entra — ela responde por caminho
      arbitrário, e um proxy guardando aquele corpo sob a URL errada é ruim.

      A tentação aqui é `max-age` longo. Ela custaria caro: `main.bundle.js` e os
      CSS NÃO têm hash no nome, então um deploy não muda a URL, e um cliente com
      o arquivo em cache seguiria rodando o JS velho junto com o HTML novo. É a
      receita de tela quebrada sem erro nenhum no servidor.

  todo o resto              `no-store`
      `/api/**` e `/health` são estado ao vivo de infraestrutura: nomes de
      container, portas, domínios, achados de segurança. Nada disso deveria
      encostar em cache de proxy compartilhado nem sobrar em disco depois que a
      aba fecha. E cache de dado ao vivo é contradição em termos: o valor dele é
      ser de agora.

Rota que declara `Cache-Control` por conta própria manda — este middleware
preenche ausência, não sobrescreve decisão.
"""

CAMINHO_FONTES = "/static/assets/fonts/"
CAMINHO_ESTATICO = "/static/"
# Conteúdo fixo servido por rota, e não pelo mount de estáticos.
#
# `/sw.js` entra aqui e não em `no-store` por uma razão de operação: o navegador
# compara o script do service worker byte a byte para decidir se há versão nova.
# `no-cache` (guarde, mas pergunte antes) deixa a revalidação barata e mantém o
# ciclo de atualização funcionando; `no-store` obrigaria o download inteiro a
# cada verificação, sem nada em troca.
CAMINHOS_CASCA = ("/", "/favicon.ico", "/sw.js")

TRINTA_DIAS = 30 * 24 * 60 * 60

REGRA_FONTES = f"public, max-age={TRINTA_DIAS}".encode()
REGRA_ESTATICO = b"no-cache"
REGRA_DINAMICO = b"no-store"


def regra_para(caminho: str) -> bytes:
    if caminho.startswith(CAMINHO_FONTES):
        return REGRA_FONTES
    if caminho.startswith(CAMINHO_ESTATICO) or caminho in CAMINHOS_CASCA:
        return REGRA_ESTATICO
    return REGRA_DINAMICO


class CacheControlMiddleware:
    """ASGI puro: o cabeçalho entra no `http.response.start`, sem tocar no corpo.

    Puro de propósito, como o de compressão ao lado: `BaseHTTPMiddleware` embrulha
    a resposta num objeto, e para as duas rotas que TRANSMITEM isso significaria
    segurar o stream — o mesmo defeito que `compressao.py` existe para evitar.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        regra = regra_para(scope.get("path", ""))

        async def envia(mensagem):
            if mensagem["type"] == "http.response.start":
                cabecalhos = mensagem.get("headers") or []
                if not any(n == b"cache-control" for n, _ in cabecalhos):
                    mensagem["headers"] = list(cabecalhos) + [(b"cache-control", regra)]
            await send(mensagem)

        await self.app(scope, receive, envia)
