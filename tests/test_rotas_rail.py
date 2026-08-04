"""O rail navega — e o que ele oferece existe.

O defeito de origem: o `hashchange` do kernel roteava só por `deHash`, que
conhece `#/stack/<id>` e `#/container/<id>` e devolve o escopo host para todo o
resto. Os 13 itens do rail caíam nesse resto. Clicar em "Auditoria" trocava a
URL e mais nada: mesma tela, sem erro de console, sem 404, sem exceção.

Nenhum teste falhava, e nenhuma auditoria automática apontava — o verificador de
links pula `href` que comeca com `#` (fragmento nao e requisicao), a checagem de
rotulos de navegacao passava (os links ERAM bem rotulados), e a camada BDD faz um
GET na home e nada mais. Todos mediam VERIFICACAO: o que esta na tela esta certo?
Falta va VALIDACAO: acionar isto faz o que promete?

E o oraculo da validacao, aqui, nao precisa saber nada de Docker:

    item de navegacao que nao muda nada observavel nao navegou.

Os casos abaixo sao esse oraculo em duas camadas — a estrutural, que le o HTML
contra o registro de modulos, e a de execucao, que roda o roteador de verdade.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
JS = RAIZ / "app" / "static" / "js"
HTML = RAIZ / "app" / "static" / "index.html"
FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "exercita_rotas.mjs"


def _modulos() -> dict[str, list[str]]:
    """id -> escopos, lidos dos proprios modulos. Sem lista escrita a mao aqui:
    uma lista neste arquivo divergiria do registro exatamente como o rail
    divergiu, e o teste passaria a vigiar a si mesmo."""
    fora = {}
    for arq in sorted((JS / "modulos").glob("*.js")):
        if arq.name == "index.js":
            continue
        fonte = arq.read_text()
        mid = re.search(r"^\s*id:\s*'([^']+)'", fonte, re.M)
        esc = re.search(r"^\s*escopos:\s*\[([^\]]*)\]", fonte, re.M)
        if not mid:
            continue
        crus = re.findall(r"'([^']+)'", esc.group(1)) if esc else ["host"]
        fora[mid.group(1)] = crus
    return fora


def _rail() -> list[str]:
    return re.findall(r'<a href="(#[^"]*)" class="rail-item"', HTML.read_text())


# ---------------------------------------------------------------------------
# camada estrutural: o rail nao pode oferecer o que nao existe
# ---------------------------------------------------------------------------

def test_rail_tem_itens():
    assert len(_rail()) >= 5, "o rail sumiu ou deixou de usar <a href> — sem navegacao"


def test_todo_link_do_rail_leva_a_algum_lugar():
    """O fiscal que faltava.

    `#/` e o cockpit do host. Qualquer outro item tem de nomear um modulo do
    registro QUE DECLARE o escopo host — modulo que so vive em stack ou em
    container nao tem caixa na grade do host, e o link seria mais um clique que
    nao faz nada. Foi assim que "Logs" apareceu: id valido, escopo errado.
    """
    modulos = _modulos()
    mortos = []
    for href in _rail():
        rota = href.replace("#/", "", 1).split("?")[0]
        if not rota:
            continue  # `#/` = host
        escopos = modulos.get(rota)
        if escopos is None:
            mortos.append(f"{href} — nao existe modulo com id {rota!r}")
        elif "host" not in escopos:
            mortos.append(f"{href} — modulo {rota!r} so vive em {escopos}")
    assert not mortos, "itens do rail sem destino:\n  " + "\n  ".join(mortos)


def test_marca_de_pagina_atual_nao_e_estatica():
    """`aria-current` fixo no HTML afirma uma posicao que nunca muda.

    Era o estado anterior: o primeiro item nascia marcado e ninguem o movia. Para
    leitor de tela, isso anuncia "Visao Geral, pagina atual" dentro de qualquer
    outro modulo — pior que a ausencia do atributo, porque afirma o errado.
    """
    marcados = re.findall(r'<a\s[^>]*\baria-current=[^>]*class="rail-item"', HTML.read_text())
    marcados += re.findall(r'<a\s[^>]*class="rail-item"[^>]*\baria-current=', HTML.read_text())
    assert not marcados, (
        "voltou marca estatica de pagina atual no rail; quem marca e marcarRail()")
    fonte = (JS / "main.js").read_text()
    assert "function marcarRail" in fonte
    assert "'hashchange', marcarRail" in fonte, "a marca nao acompanha a navegacao"


def test_hashchange_passa_pelo_roteador():
    """A ponte ligada — e o `deHash` sozinho fora do tratador de hashchange."""
    fonte = (JS / "kernel" / "app.js").read_text()
    tratador = re.search(r"addEventListener\('hashchange',\s*\(\)\s*=>\s*\{(.*?)\}\)",
                         fonte, re.S)
    assert tratador, "o kernel deixou de tratar hashchange"
    corpo = tratador.group(1)
    assert "rotear(" in corpo, "hashchange voltou a nao passar pelo roteador"
    assert "deHash" not in corpo, (
        "hashchange voltou a rotear so por deHash — e o defeito de origem")


# ---------------------------------------------------------------------------
# camada de execucao: o roteador roda de verdade sob node
# ---------------------------------------------------------------------------

pytestmark_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node ausente; o roteador precisa executar os modulos ES",
)


@pytest.fixture(scope="module")
def r():
    p = subprocess.run(["node", str(FIXTURE)], capture_output=True, text=True,
                       timeout=90, cwd=RAIZ)
    assert p.returncode == 0, f"o roteador levantou:\n{p.stderr}"
    return json.loads(p.stdout)


@pytestmark_node
def test_rota_de_modulo_oculto_o_reexibe(r):
    """Invariante 3 do doc 10, aplicado a navegacao: enderecar um modulo oculto
    o traz de volta. Ocultar nao pode significar tornar inalcancavel — e o preset
    padrao do host ja nasce com modulos ocultos."""
    assert r["oculto_id"], "o preset do host deixou de ter modulo oculto; caso vazio"
    assert r["oculto_na_grade_antes"] is False
    assert r["oculto_ainda_oculto_depois"] is False, "a rota nao reexibiu o modulo"
    assert r["oculto_na_grade_depois"] is True, "reexibido no estado, ausente na grade"


@pytestmark_node
def test_rota_de_modulo_visivel_nao_troca_o_escopo(r):
    assert r["visivel_continua_na_grade"] is True
    assert r["visivel_escopo"] == "host", "rota de modulo nao pode mudar de cockpit"


@pytestmark_node
def test_rotas_de_escopo_continuam_funcionando(r):
    """A gramatica que ja funcionava. Este caso existe porque o conserto mexeu no
    mesmo tratador: consertar a navegacao por modulo sem quebrar a por escopo e
    metade do trabalho."""
    assert r["escopo_container"] == {"t": "container", "id": "criptotrade-app"}
    assert r["escopo_stack"] == {"t": "stack", "id": "web"}
    assert r["escopo_host"] == {"t": "host"}


@pytestmark_node
def test_hash_desconhecida_cai_no_host(r):
    assert r["desconhecida_escopo"] == {"t": "host"}


@pytestmark_node
def test_modulo_sem_escopo_host_nao_finge_que_navegou(r):
    """Modulo que so vive em stack/container nao tem onde ser revelado no host.

    O roteador diz `false` e o chamador cai no host — em vez de repintar a mesma
    tela e devolver ao visitante a sensacao de que o clique nao fez nada, que e
    exatamente o defeito que este conserto elimina."""
    assert r["sem_host_id"], "todo modulo declara host; caso vazio"
    assert r["sem_host_alcancavel"] is False
    assert r["sem_host_na_grade"] is False


@pytestmark_node
def test_alcancavel_no_host_e_o_criterio_do_rail(r):
    """A mesma pergunta que `podarRail()` faz antes de exibir um item."""
    a = r["alcancavel"]
    assert a["host"] is True and a["vazia"] is True
    assert a["modulo_host"] is True
    assert a["inexistente"] is False
    assert a["container"] is True and a["stack"] is True


@pytestmark_node
def test_query_string_nao_atrapalha(r):
    """`attention.js` navega com `#/ingress?host=exemplo.com`. O `?` e do corpo
    da tela, nao do roteador — mas ele tem de sobreviver a passagem."""
    assert r["com_query_na_grade"] is True
    assert r["com_query_escopo"] == "host"
