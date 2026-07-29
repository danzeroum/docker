"""A tela de Logs lia texto como se fosse JSON.

Sintoma em producao: "Unexpected non-whitespace character after JSON at
position 244" no lugar das linhas de log. A tela chamava `apiGet`, que faz
`res.json()`, contra /api/containers/{id}/logs — rota que devolve
`text/plain`, porque o demux das molduras de 8 bytes do Docker acontece no
servidor e o que sai e log cru.

Nao era um bug de sorte: a primeira linha de log ja quebrava o parse. A tela
nunca funcionou para nenhum container.

O stream (SSE) sempre esteve certo — e outra rota, lida por EventSource. Estes
testes fixam o contrato dos dois lados: a rota continua text/plain, e o
frontend le rota de texto com .text().
"""
import pathlib
import re

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
JS = RAIZ / "app" / "static" / "js"


# ---------------------------------------------------------------------------
# Lado do servidor: a rota e de texto, e continua sendo
# ---------------------------------------------------------------------------

def test_rota_de_logs_devolve_texto_puro():
    fonte = (RAIZ / "app" / "routers" / "containers.py").read_text()
    trecho = fonte[fonte.index("async def container_logs"):]
    trecho = trecho[: trecho.index("@router") if "@router" in trecho else len(trecho)]
    assert 'media_type="text/plain"' in trecho, (
        "se esta rota passar a devolver JSON, a tela precisa mudar junto — "
        "o contrato e o que liga os dois"
    )


def test_demux_das_molduras_e_do_servidor():
    """O cliente recebe log limpo; quem tira os 8 bytes de moldura e o backend."""
    fonte = (RAIZ / "app" / "routers" / "containers.py").read_text()
    assert "_demux_frame" in fonte
    for arquivo in JS.rglob("*.js"):
        # comentario pode CITAR o demux; codigo nao pode fazer
        texto = re.sub(r"/\*.*?\*/", "", arquivo.read_text(), flags=re.S)
        texto = re.sub(r"^\s*//.*$", "", texto, flags=re.M)
        assert "demux" not in texto.lower(), \
            f"{arquivo.name} tenta demultiplexar no navegador; isso e do servidor"


# ---------------------------------------------------------------------------
# Lado do cliente: rota de texto le com .text()
# ---------------------------------------------------------------------------

def test_existe_leitor_de_texto_separado_do_de_json():
    fonte = (JS / "data.js").read_text()
    assert "export async function apiGetText" in fonte, \
        "rota de texto precisa de leitor proprio; so JSON passa por apiGet"
    corpo = fonte[fonte.index("export async function apiGetText"):]
    corpo = corpo[: corpo.index("\n}\n") + 3]
    assert "res.text()" in corpo
    assert "res.json()" not in corpo.split("if (!res.ok)")[0], \
        "o caminho de sucesso nao pode chamar json()"


def test_apiget_continua_sendo_so_para_json():
    """apiGet e o leitor de JSON. Se ele virar generico, o bug volta calado."""
    fonte = (JS / "data.js").read_text()
    corpo = fonte[fonte.index("export async function apiGet("):]
    corpo = corpo[: corpo.index("\n}\n") + 3]
    assert "res.json()" in corpo
    assert "res.text()" not in corpo


def test_a_tela_de_logs_usa_o_leitor_de_texto():
    fonte = (JS / "main.js").read_text()
    m = re.search(r"async function fetchLines\(.*?\n  \}", fonte, re.S)
    assert m, "fetchLines saiu do main.js"
    corpo = m.group(0)
    assert "apiGetText(" in corpo, "a tela de Logs voltou a ler texto como JSON"
    assert "apiGet(" not in corpo.replace("apiGetText(", "")


def test_leitor_de_texto_e_importado_onde_e_usado():
    """Usar sem importar mata o modulo inteiro, nao so a tela de Logs."""
    fonte = (JS / "main.js").read_text()
    m = re.search(r"import\s*\{([^}]*)\}\s*from\s*'\./data\.js'", fonte)
    assert m, "main.js nao importa de data.js"
    importados = {n.strip() for n in m.group(1).split(",")}
    assert "apiGetText" in importados


def test_o_stream_continua_em_rota_propria_por_eventsource():
    """O SSE nunca teve o bug; o conserto de uma rota nao pode quebrar a outra."""
    fonte = (JS / "main.js").read_text()
    assert "new EventSource(`/api/containers/${id}/logs/stream" in fonte
    # E o SSE nao pode ser lido por fetch de JSON.
    assert "apiGet('logs_stream'" not in fonte


@pytest.mark.parametrize("rota", ["/api/containers/${id}/logs?tail="])
def test_nenhuma_rota_de_texto_sobrou_em_apiget(rota):
    for arquivo in JS.rglob("*.js"):
        texto = arquivo.read_text()
        for linha in texto.splitlines():
            if rota in linha and "apiGet(" in linha and "apiGetText(" not in linha:
                pytest.fail(f"{arquivo.name}: rota de texto lida por apiGet — {linha.strip()}")
