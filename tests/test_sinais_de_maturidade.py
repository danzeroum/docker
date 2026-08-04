"""Os seis `xfail` da regua — divida declarada, agora paga.

`xfail` na regua nao e reprovacao: e "isto falta, e sabemos". Os seis eram sinais
de maturidade, cada um de uma linha, todos acumulados porque nenhum quebrava
nada. Divida que ninguem cobra e divida que cresce.

    correlacao de requisicoes .... x-request-id
    Referrer-Policy .............. cabecalho
    Permissions-Policy ........... cabecalho
    /.well-known/security.txt .... RFC 9116
    /robots.txt .................. encontrabilidade
    meta description ............. previa do link

Duas escolhas aqui NAO seguem a recomendacao da regua ao pe da letra, e as duas
sao deliberadas — estao documentadas nos casos correspondentes.
"""
import os
import re
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "app"))
os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")

from fastapi.testclient import TestClient  # noqa: E402

import app as modulo_app  # noqa: E402

client = TestClient(modulo_app.app)


# ---------------------------------------------------------------------------
# 1. correlacao de requisicoes
# ---------------------------------------------------------------------------

def test_toda_resposta_carrega_id_de_correlacao():
    """Sem ele, rastrear um incidente entre nginx, app e daemon e arqueologia:
    tres logs sem nada em comum alem do relogio."""
    for caminho in ("/", "/health", "/robots.txt", "/nao-existe"):
        r = client.get(caminho)
        assert r.headers.get("x-request-id"), f"{caminho} saiu sem id de correlacao"


def test_o_id_da_borda_e_reaproveitado():
    """Gerar um id novo cortaria a corrente exatamente onde ela serve: o operador
    ficaria com dois identificadores para o mesmo evento e nenhum ligando os
    lados."""
    r = client.get("/health", headers={"x-request-id": "vindo-do-ingress-123"})
    assert r.headers["x-request-id"] == "vindo-do-ingress-123"


def test_traceparent_tem_precedencia():
    """E o padrao W3C Trace Context — o que um coletor de tracing procura."""
    r = client.get("/health", headers={
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        "x-request-id": "menos-padronizado",
    })
    assert r.headers["x-request-id"].startswith("00-4bf92f35")


def test_ids_sao_distintos_entre_requisicoes():
    a = client.get("/health").headers["x-request-id"]
    b = client.get("/health").headers["x-request-id"]
    assert a != b, "o id gerado repetiu — nao correlaciona nada"


@pytest.mark.parametrize("hostil,motivo", [
    (b"abc\r\nX-Injetado: sim", "CR/LF permitiria injecao de cabecalho na resposta"),
    (b"x" * 5000, "sem teto, um proxy mal configurado devolve kilobytes a todo cliente"),
    ("idção".encode("latin-1"), "byte alto quebraria o encode latin-1 do ASGI"),
    (b"\x00\x07id", "controles nao imprimiveis nao tem lugar num cabecalho"),
])
def test_id_herdado_e_saneado(hostil, motivo):
    """O id vem de FORA e e ecoado na resposta — e eco de entrada do usuario.

    Exercitado direto sobre `_sanear` e nao por HTTP: o proprio cliente de teste
    recusa cabecalho hostil antes de ele chegar na app, o que provaria a defesa
    do httpx em vez da nossa. Um proxy na frente NAO tem essa cortesia.
    """
    from telemetry import _sanear
    limpo = _sanear(hostil)
    assert "\r" not in limpo and "\n" not in limpo, motivo
    assert len(limpo) <= 200, motivo
    assert all(32 <= ord(c) < 127 for c in limpo), motivo


def test_id_hostil_no_scope_nao_vaza_para_a_resposta():
    """O mesmo, no caminho de verdade: um scope ASGI montado a mao, como um proxy
    mal-intencionado entregaria."""
    from telemetry import id_de_correlacao
    scope = {"headers": [(b"x-request-id", b"ok\r\nX-Injetado: sim")]}
    assert "\n" not in id_de_correlacao(scope)


def test_id_vazio_da_borda_nao_vira_id_vazio():
    """Proxy que carimba o cabecalho sem valor e comum; herdar o vazio deixaria a
    resposta sem correlacao nenhuma, em silencio."""
    from telemetry import id_de_correlacao
    assert id_de_correlacao({"headers": [(b"x-request-id", b"   ")]})


# ---------------------------------------------------------------------------
# 2 e 3. os dois cabecalhos de politica
# ---------------------------------------------------------------------------

def test_referrer_policy_e_no_referrer():
    """`no-referrer`, e nao o `strict-origin-when-cross-origin` de praxe.

    ESCOLHA DELIBERADA: este painel nao carrega NADA de terceiro — as fontes
    foram auto-hospedadas justamente para isso —, entao nao ha destino legitimo
    para um referrer. E a URL que vazaria e indiscreta: o caminho e o host dizem
    qual infraestrutura a pessoa administra.
    """
    assert client.get("/").headers["referrer-policy"] == "no-referrer"


def test_referrer_policy_nao_e_permissiva():
    """Declarar `unsafe-url` seria decisao de vazar, e a regua reprova isso —
    diferente de simplesmente nao declarar nada."""
    valor = client.get("/").headers["referrer-policy"].lower()
    assert "unsafe-url" not in valor


@pytest.mark.parametrize("permissao", ["geolocation", "camera", "microphone"])
def test_permissions_policy_nega_os_sensores(permissao):
    """Lista vazia `()` nega para a PROPRIA origem tambem, nao so para iframes."""
    valor = client.get("/").headers["permissions-policy"]
    assert f"{permissao}=()" in valor, f"{permissao} continua disponivel a qualquer script"


def test_permissions_policy_vai_alem_do_minimo_cobrado():
    """A regua cobra tres; a mesma linha custa o mesmo com mais, e a superficie
    de APIs do navegador so cresce com o tempo."""
    valor = client.get("/").headers["permissions-policy"]
    for extra in ("payment", "usb", "display-capture"):
        assert f"{extra}=()" in valor


# ---------------------------------------------------------------------------
# 4. security.txt
# ---------------------------------------------------------------------------

def test_sem_contato_configurado_a_rota_e_404():
    """ESCOLHA DELIBERADA: `Contact:` e o unico campo obrigatorio do RFC 9116, e
    so vale se for alcancavel.

    Um contato inventado transforma o arquivo no oposto do que ele promete —
    quem achar uma falha escreve para um endereco que nao existe e conclui que
    avisou. 404 e a verdade: nao ha canal declarado.
    """
    assert modulo_app.SECURITY_CONTACT == "", (
        "o repositorio nao deve trazer contato de fabrica; e configuracao de deploy")
    assert client.get("/.well-known/security.txt").status_code == 404


def test_com_contato_o_arquivo_atende_o_rfc(monkeypatch):
    monkeypatch.setattr(modulo_app, "SECURITY_CONTACT", "mailto:seguranca@exemplo.test")
    r = client.get("/.well-known/security.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    corpo = r.text
    assert "Contact: mailto:seguranca@exemplo.test" in corpo
    # `Expires` e obrigatorio desde o RFC 9116 §2.5.5: um security.txt sem prazo
    # envelhece em silencio, e um canal que nao existe mais e pior que nenhum.
    assert re.search(r"^Expires: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", corpo, re.M)


# ---------------------------------------------------------------------------
# 5. robots.txt
# ---------------------------------------------------------------------------

def test_robots_pede_para_nao_indexar():
    """ESCOLHA DELIBERADA, contraria a recomendacao da regua.

    Ela lista sitemap OU robots como sinal de "encontrabilidade". Para um painel
    de operacao a resposta certa e o OPOSTO: cada URL indexada e um mapa da
    infraestrutura de alguem entregue a um buscador. Mesmo com autenticacao na
    frente — um 401 tambem entra em indice, com URL e titulo.
    """
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "User-agent: *" in r.text
    assert "Disallow: /" in r.text


def test_nao_ha_sitemap():
    """Sitemap seria o contrario do robots.txt acima — e nao ha o que indexar:
    a navegacao inteira vive em hash, invisivel para qualquer crawler."""
    assert client.get("/sitemap.xml").status_code == 404


# ---------------------------------------------------------------------------
# 6. meta description
# ---------------------------------------------------------------------------

def test_ha_meta_description_com_conteudo():
    html = open(os.path.join(RAIZ, "app", "static", "index.html")).read()
    achado = re.search(r'<meta name="description" content="([^"]+)"', html)
    assert achado, "sem meta description"
    texto = achado.group(1).strip()
    assert len(texto) >= 50, "descricao curta demais para ser util numa previa"
    assert "carregando" not in texto.lower()


def test_a_descricao_diz_o_que_o_painel_faz():
    """Ela serve a previa de link colado num chat, aba restaurada e leitor de
    tela — nao a buscador, que o robots.txt manda embora."""
    html = open(os.path.join(RAIZ, "app", "static", "index.html")).read()
    texto = re.search(r'<meta name="description" content="([^"]+)"', html).group(1).lower()
    assert "docker" in texto or "container" in texto


# ---------------------------------------------------------------------------
# nenhum dos seis pode ter quebrado os anteriores
# ---------------------------------------------------------------------------

def test_os_cabecalhos_anteriores_seguem_de_pe():
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("caminho,esperado", [
    ("/robots.txt", b"no-store"),
    ("/.well-known/security.txt", b"no-store"),
])
def test_as_rotas_novas_caem_na_faixa_certa_de_cache(caminho, esperado):
    """Nao sao `/static/` nem casca: conteudo gerado por rota, sem cache."""
    from cache_http import regra_para
    assert regra_para(caminho) == esperado
