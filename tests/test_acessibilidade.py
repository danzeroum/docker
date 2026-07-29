"""Fatia 4 — acessibilidade dos controles.

Testes de ESTRUTURA. Ordem de foco e contraste real precisam de navegador; o
que da para travar aqui e a regressao: alvo clicavel voltando a ser <div>,
contorno de foco suprimido, ou interativo aninhado dentro de interativo.
"""
import pathlib
import re
import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
JS = RAIZ / "app" / "static" / "js"
CSS = RAIZ / "app" / "static" / "css"
HTML = RAIZ / "app" / "static" / "index.html"

ARQUIVOS_JS = sorted(JS.rglob("*.js"))

# Classes que nasceram como <div onClick> e foram convertidas. Se alguma voltar
# a ser div, o teste abaixo pega.
CLASSES_CONVERTIDAS = [
    "filter-pill", "list-item", "stack-header", "container-card",
    "stack-contr", "ig-row", "palette-item",
]

# Cartoes que tem interativo dentro e por isso usam o botao esticado.
CARTOES_ESTICADOS = ["atn-card", "atn-mini", "ig-finding"]


def _todo_o_js():
    return "\n".join(f.read_text() for f in ARQUIVOS_JS)


# ---------------------------------------------------------------------------
# nenhum handler de clique em elemento nao focavel
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("classe", CLASSES_CONVERTIDAS)
def test_classe_convertida_nao_volta_a_ser_div(classe):
    fontes = _todo_o_js() + HTML.read_text()
    padrao = re.compile(r'<(div|span)[^>]*class="[^"]*\b' + re.escape(classe) + r'\b')
    achado = padrao.search(fontes)
    assert achado is None, f'{classe} voltou a ser <{achado.group(1)}>: {achado.group(0)[:80]}'


@pytest.mark.parametrize("classe", CLASSES_CONVERTIDAS)
def test_classe_convertida_e_button(classe):
    fontes = _todo_o_js() + HTML.read_text()
    padrao = re.compile(r'<button[^>]*class="[^"]*\b' + re.escape(classe) + r'\b')
    assert padrao.search(fontes), f"{classe} nao aparece como <button> em lugar nenhum"


def test_sem_onclick_inline_em_elemento_nao_focavel():
    fontes = _todo_o_js() + HTML.read_text()
    achados = re.findall(r'<(?:div|span|li|td|tr)[^>]*\bonclick\b[^>]*>', fontes)
    assert not achados, f"onclick inline em elemento nao focavel: {achados[:3]}"


def test_cartoes_com_interativo_dentro_usam_botao_esticado():
    """Interativo dentro de interativo e HTML invalido e quebra o teclado."""
    fontes = _todo_o_js()
    for classe in CARTOES_ESTICADOS:
        assert re.search(r'<div class="' + re.escape(classe), fontes), \
            f"{classe} deveria seguir <div> (tem link/botao dentro)"
    assert fontes.count('class="card-open"') >= len(CARTOES_ESTICADOS), \
        "algum cartao esticado ficou sem o botao que o torna acionavel"


def test_botao_esticado_tem_nome_acessivel():
    """Botao vazio nao tem nome — leitor de tela anuncia 'botao' e mais nada."""
    fontes = _todo_o_js()
    for trecho in re.findall(r'<button[^>]*class="card-open"[^>]*>(.*?)</button>', fontes, re.S):
        assert "sr-only" in trecho or "aria-label" in trecho, \
            f"card-open sem nome acessivel: {trecho[:60]}"


def test_botoes_declaram_type():
    """Sem type, <button> dentro de <form> submete. Barato de garantir."""
    fontes = _todo_o_js() + HTML.read_text()
    sem_type = re.findall(r'<button(?![^>]*\btype=)[^>]*>', fontes)
    assert not sem_type, f"<button> sem type: {sem_type[:3]}"


# ---------------------------------------------------------------------------
# foco visivel
# ---------------------------------------------------------------------------

def test_nenhum_outline_suprimido():
    for arquivo in CSS.glob("*.css"):
        texto = arquivo.read_text()
        achados = re.findall(r'outline\s*:\s*none', texto)
        assert not achados, f"{arquivo.name} suprime o contorno de foco"
        achados0 = re.findall(r'outline\s*:\s*0(?!\w)', texto)
        assert not achados0, f"{arquivo.name} zera o contorno de foco"


def test_focus_visible_existe():
    css = (CSS / "components.css").read_text()
    assert ":focus-visible" in css
    assert re.search(r':focus-visible\s*\{[^}]*outline\s*:', css), \
        ":focus-visible sem outline proprio"


def test_anel_de_foco_tem_cor_por_tema():
    """Fundo muda nos 3 temas; um anel unico nao contrasta nos 3."""
    css = (CSS / "components.css").read_text() + (CSS / "themes.css").read_text()
    for tema in ("cockpit", "escritorio", "claro"):
        assert re.search(r'\[data-tema="' + tema + r'"\][^{]*\{[^}]*--focus-ring', css), \
            f"tema {tema} sem --focus-ring proprio"


def test_reset_de_button_usa_where_para_nao_mudar_layout():
    """:where() tem especificidade zero — o estilo original das classes vence.

    Sem isso o reset apendado no fim do arquivo sobrescreveria fundo e padding
    dos cartoes, e a conversao mudaria o layout.
    """
    css = (CSS / "components.css").read_text()
    assert ":where(button." in css, "reset de button sem :where()"


def test_sr_only_existe():
    css = (CSS / "components.css").read_text()
    assert ".sr-only" in css


# ---------------------------------------------------------------------------
# foco preso no modal
# ---------------------------------------------------------------------------

def test_modal_prende_o_foco():
    fonte = (JS / "notifications.js").read_text()
    assert "prenderFoco" in fonte and "soltarFoco" in fonte
    assert "e.key !== 'Tab'" in fonte, "o trap nao trata Tab"
    assert "shiftKey" in fonte, "o trap nao trata Shift+Tab"


def test_modal_devolve_o_foco_a_quem_abriu():
    fonte = (JS / "notifications.js").read_text()
    trecho = fonte[fonte.index("function prenderFoco"):fonte.index("function soltarFoco")]
    assert "document.activeElement" in trecho, "nao guarda quem tinha o foco"
    assert "anterior.focus()" in trecho, "nao devolve o foco ao fechar"


def test_trap_ligado_em_todos_os_modais():
    """Os tres modais compartilham o overlay; nenhum pode ficar de fora."""
    fonte = (JS / "notifications.js").read_text()
    aberturas = fonte.count("overlay.classList.add('open')")
    prendem = fonte.count("prenderFoco(overlay)") - 1  # menos a definicao
    assert prendem == aberturas, f"{aberturas} aberturas, {prendem} com foco preso"
    fechamentos = fonte.count("overlay.classList.remove('open')")
    soltam = fonte.count("soltarFoco()") - 1  # menos a definicao da funcao
    assert soltam >= fechamentos, f"{fechamentos} fechamentos, {soltam} soltando o foco"


def test_modal_fecha_com_escape():
    """Os tres modais. O de silenciar nao fechava — descoberto por este teste."""
    fonte = (JS / "notifications.js").read_text()
    assert fonte.count("'Escape'") >= 3, "algum modal nao fecha com Escape"


# ---------------------------------------------------------------------------
# o rail ja estava certo — trava para nao regredir
# ---------------------------------------------------------------------------

def test_rail_navegavel_por_teclado():
    html = HTML.read_text()
    assert 'aria-current="page"' in html
    itens = re.findall(r'<a href="#/[^"]*" class="rail-item"', html)
    assert itens, "rail deixou de usar <a href> para navegacao"
