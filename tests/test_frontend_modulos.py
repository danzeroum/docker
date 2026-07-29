"""Os modulos ES do frontend precisam ser carregaveis.

Encontrado em producao: `main.js` declarava `let pollTimer` duas vezes no topo
do modulo — a segunda entrou na F6 (#8). Redeclarar no mesmo escopo e
SyntaxError, entao o main.js inteiro nunca executava e a interface ficava no
"carregando" para sempre, sem pintar nada e sem erro visivel fora do console.

Passou despercebido porque o #8 foi mergeado mas nunca implantado: producao
rodava imagem pre-F5. A primeira janela que publicou a F6 derrubou a tela.

O CI so exercita o backend (pytest + smoke de endpoint). Nada olhava o JS.
Estes testes olham — sem navegador, so pelo que da para afirmar lendo o codigo.
"""
import pathlib
import re
import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
JS = RAIZ / "app" / "static" / "js"
ARQUIVOS = sorted(JS.rglob("*.js"))

# Declaracoes no topo do modulo: coluna zero, sem indentacao.
TOPO = re.compile(r'^(let|const|var|function|class)\s+([A-Za-z_$][\w$]*)', re.M)


def _sem_comentarios(fonte):
    """Tira // e /* */ para nao contar declaracao comentada."""
    fonte = re.sub(r'/\*.*?\*/', '', fonte, flags=re.S)
    return re.sub(r'^\s*//.*$', '', fonte, flags=re.M)


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda p: p.name)
def test_sem_redeclaracao_no_topo_do_modulo(arquivo):
    """`let x` duas vezes no mesmo escopo = SyntaxError = tela morta."""
    fonte = _sem_comentarios(arquivo.read_text())
    vistos = {}
    for tipo, nome in TOPO.findall(fonte):
        if tipo == "function":
            # funcao redeclarada e legal em JS (a ultima vence). Feio, nao fatal.
            continue
        anterior = vistos.get(nome)
        assert anterior is None, (
            f"{arquivo.name}: '{nome}' declarado como {anterior} e de novo como "
            f"{tipo} no topo do modulo — SyntaxError, o modulo nao carrega"
        )
        vistos[nome] = tipo


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda p: p.name)
def test_imports_apontam_para_arquivos_que_existem(arquivo):
    """Import quebrado tambem mata o modulo inteiro, e so aparece no console."""
    fonte = arquivo.read_text()
    for caminho in re.findall(r'''from\s+['"](\.[^'"]+)['"]''', fonte):
        alvo = (arquivo.parent / caminho).resolve()
        assert alvo.is_file(), f"{arquivo.name} importa {caminho}, que nao existe"


def test_imports_dinamicos_tambem_existem():
    for arquivo in ARQUIVOS:
        fonte = arquivo.read_text()
        for caminho in re.findall(r'''import\(\s*['"](\.[^'"]+)['"]\s*\)''', fonte):
            alvo = (arquivo.parent / caminho).resolve()
            assert alvo.is_file(), f"{arquivo.name} importa {caminho} dinamicamente, e nao existe"


def test_main_importa_o_que_o_router_usa():
    """Tela roteada sem import quebra so quando alguem navega ate ela."""
    fonte = (JS / "main.js").read_text()
    importados = set()
    for bloco in re.findall(r'import\s*\{([^}]*)\}', fonte):
        importados.update(n.strip() for n in bloco.split(",") if n.strip())
    # Tela pode vir de import OU ser definida no proprio main.js (renderDossie e).
    locais = set(re.findall(r'^function\s+(\w+)', fonte, re.M))
    usados = set(re.findall(r'dispose\s*=\s*(\w+)\(container\)', fonte))
    faltando = usados - importados - locais
    assert not faltando, f"main.js usa sem importar nem definir: {faltando}"


def test_index_referencia_o_main():
    html = (RAIZ / "app" / "static" / "index.html").read_text()
    m = re.search(r'<script[^>]*type="module"[^>]*src="([^"]+)"', html)
    assert m, "index.html nao carrega nenhum modulo ES"
    # src e "/static/js/main.js"; /static e o mount de app/static.
    rel = m.group(1).removeprefix("/static/").lstrip("/")
    alvo = (RAIZ / "app" / "static" / rel).resolve()
    assert alvo.is_file(), f"index.html aponta para {m.group(1)}, que nao existe"
