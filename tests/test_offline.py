"""O painel abre sem rede — e diz que está sem rede.

O DEFEITO DE ORIGEM: o service worker nunca rodou. `sw.js` existia, era servido
com 200, listava 50+ ativos e tinha um teste conferindo a lista — mas
`navigator.serviceWorker.register` não aparecia em lugar nenhum do código.

Codigo morto com teste passando. O teste lia o FONTE e provava que a lista estava
certa; nunca que o navegador a usava. E o mesmo padrao do rail que nao navegava e
do selo de contraste que ninguem renderizava: verificacao sem validacao.

Estes casos sao estruturais — cobram que as PECAS existam e estejam ligadas. O
comportamento de verdade (carregar sem rede) exige navegador e foi medido na
bancada; o que da para travar aqui e a regressao.
"""
import os
import pathlib
import re
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
JS = RAIZ / "app" / "static" / "js"
SW = RAIZ / "app" / "static" / "sw.js"

sys.path.insert(0, str(RAIZ / "app"))
os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")


# ---------------------------------------------------------------------------
# o registro que faltava
# ---------------------------------------------------------------------------

def test_o_service_worker_e_registrado():
    """Sem esta linha, todo o resto do arquivo e enfeite."""
    fonte = (JS / "main.js").read_text()
    assert "navigator.serviceWorker.register" in fonte, (
        "o service worker voltou a nao ser registrado; o sw.js vira codigo morto")


def test_registra_da_raiz_e_nao_de_static():
    """O escopo de um SW e o diretorio de onde ele veio.

    Registrado de `/static/sw.js`, ele controlaria `/static/` e NAO a app, que
    mora em `/` — um service worker ativo, sem erro nenhum, e sem efeito.
    """
    fonte = (JS / "main.js").read_text()
    assert "register('/sw.js')" in fonte, (
        "registro fora da raiz: o SW nao controlaria a app")


def test_a_rota_da_raiz_serve_o_sw():
    from fastapi.testclient import TestClient
    from app import app

    r = TestClient(app).get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert "CACHE_NAME" in r.text, "a rota /sw.js nao esta servindo o service worker"


def test_sw_nao_e_no_store():
    """O navegador compara o script byte a byte para achar versao nova.
    `no-store` obrigaria o download inteiro a cada verificacao, sem ganho."""
    from cache_http import regra_para
    assert regra_para("/sw.js") == b"no-cache"


# ---------------------------------------------------------------------------
# o que o cache precisa ter para a casca abrir
# ---------------------------------------------------------------------------

def test_o_documento_de_navegacao_esta_no_cache():
    """A app e servida em `/`, nao em `/static/index.html`.

    Sem `/` na lista, offline a requisicao de NAVEGACAO nao casa com nada e o
    navegador mostra a propria tela de erro — cachear 50 arquivos e o documento
    errado e o mesmo que nao cachear.
    """
    sw = SW.read_text()
    lista = sw[sw.index("STATIC_ASSETS"):sw.index("];")]
    assert re.search(r"^\s*'/',", lista, re.M), "`/` saiu da lista de ativos"


def test_ha_reserva_de_navegacao():
    """Endereco fora da lista tem de abrir a casca, e o roteador resolve a hash
    do lado de ca. Sem isto, offline so a URL exata cacheada abriria."""
    sw = SW.read_text()
    assert "request.mode === 'navigate'" in sw
    assert "caches.match('/')" in sw


def test_api_fica_fora_do_cache():
    """A regra que nao pode cair NUNCA.

    Painel de monitoracao servindo dado velho e pior que painel que nao abre: o
    operador olha uma tela de quarenta minutos atras e conclui que esta tudo bem.
    A casca abre offline; o dado continua vindo so da rede, e falha a vista.
    """
    sw = SW.read_text()
    assert "startsWith('/api/')" in sw and "return;" in sw
    lista = sw[sw.index("STATIC_ASSETS"):sw.index("];")]
    assert "/api/" not in lista, "rota de dado ao vivo entrou no cache do SW"


# ---------------------------------------------------------------------------
# sem rede, o painel tem de DIZER que esta sem rede
# ---------------------------------------------------------------------------

def test_a_pilula_distingue_sem_rede_de_pausado():
    """Aba oculta volta sozinha ao clicar na aba; falta de rede nao volta.

    Rotular as duas de "pausado" convidaria o operador a esperar por algo que
    nao vem — e o dado na tela pode ter minutos.
    """
    regua = (JS / "kernel" / "regua.js").read_text()
    assert "'sem rede'" in regua
    assert "rg-sem-rede" in regua
    css = (RAIZ / "app" / "static" / "css" / "components.css").read_text()
    assert ".rg-vivo.rg-sem-rede" in css, "o estado existe no JS e nao tem cor"


def test_as_duas_razoes_de_parada_moram_no_mesmo_lugar():
    """Se cada evento chamasse `pausarVivo` por conta propria, voltar para a aba
    ainda sem rede apagaria o aviso e a pilula voltaria a mentir."""
    app_js = (JS / "kernel" / "app.js").read_text()
    assert "function dizerSeEstaLendo" in app_js
    for evento in ("'visibilitychange', dizerSeEstaLendo",
                   "'offline', dizerSeEstaLendo",
                   "'online', dizerSeEstaLendo"):
        assert evento in app_js, f"{evento} nao passa pelo estado unico"


def test_o_resumo_lateral_tambem_avisa():
    """Medido antes de existir: com o SW registrado, a casca abre offline e o
    resumo fica em "carregando..." PARA SEMPRE, porque a busca nunca volta. Um
    painel que parece carregando convida a esperar."""
    fonte = (JS / "main.js").read_text()
    assert "function dizerConexao" in fonte
    assert "sem conexão" in fonte
    assert "window.addEventListener('offline', dizerConexao)" in fonte


def test_o_resumo_nao_sobrescreve_o_aviso_de_offline():
    """O `subscribe` do resumo dispara com o estado guardado e apagaria o aviso."""
    fonte = (JS / "main.js").read_text()
    trecho = fonte[fonte.index("// --- Global summary ---"):]
    trecho = trecho[:trecho.index("function dizerConexao")]
    assert "navigator.onLine === false" in trecho, (
        "o resumo voltou a pintar por cima do aviso de sem-rede")


# ---------------------------------------------------------------------------
# versao do cache
# ---------------------------------------------------------------------------

def test_a_lista_de_ativos_e_a_versao_andam_juntas():
    """Trocar ativo sem virar a versao serve o antigo para sempre. Nao da para
    provar a intencao por regex; da para exigir que o nome exista e seja
    versionado, e que a limpeza do cache velho continue no `activate`."""
    sw = SW.read_text()
    assert re.search(r"CACHE_NAME\s*=\s*'cockpit-v\d+'", sw)
    assert "caches.delete(k)" in sw, "sem limpeza, cache antigo sobrevive ao deploy"


@pytest.mark.parametrize("ativo", [
    "/static/js/main.bundle.js",
    "/static/css/fontes.css",
    "/static/assets/fonts/inter-latin.woff2",
])
def test_ativos_essenciais_no_cache(ativo):
    assert ativo in SW.read_text()


def test_o_aviso_e_consultado_no_boot_e_nao_so_no_evento():
    """`offline`/`online` marcam a TRANSICAO. Numa carga que ja comeca sem rede
    nenhum dos dois dispara — e sem consulta no boot o operador que abre o painel
    desconectado le "carregando..." para sempre. Medido na bancada antes de
    existir: a pilula acertava (o kernel consulta no boot) e o resumo mentia."""
    fonte = (JS / "main.js").read_text()
    assert "if (navigator.onLine === false) dizerConexao();" in fonte, (
        "o aviso voltou a depender so do evento de transicao")
