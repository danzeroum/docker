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
#
# `container-card` e `stack-contr` sairam da lista na Sprint 2a: eram markup de
# `screens/overview.js`, que foi removida porque seus quatro paineis viraram os
# modulos atencao/containers/stacks/ingress. Nao houve regressao de a11y — as
# classes deixaram de existir. Em lugar delas entraram os elementos interativos
# do kernel, que precisam da mesma garantia.
CLASSES_CONVERTIDAS = [
    "filter-pill", "list-item", "stack-header", "ig-row", "palette-item",
    # kernel do Cockpit Vivo (2a)
    "mod-linha", "rg-chip",
]

# Cartoes que tem interativo dentro e por isso usam o botao esticado.
# `atn-mini` saiu junto com screens/overview.js, pelo mesmo motivo.
CARTOES_ESTICADOS = ["atn-card", "ig-finding", "plt-card"]


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


# ---------------------------------------------------------------------------
# regioes rolaveis alcancaveis por teclado (WCAG 2.1.1)
# ---------------------------------------------------------------------------
# Roda de mouse e barra de rolagem sao gestos de PONTEIRO: uma caixa com
# overflow:auto fora da ordem de tabulacao esconde tudo abaixo da dobra de quem
# navega por teclado. axe apontou 3 regioes assim (#mod-ingress, .ingress-layout,
# [data-stg-lista]). Como diz o cabecalho deste arquivo, ordem de foco real exige
# navegador — o que se trava aqui e a ESTRUTURA da solucao.

def test_utilitario_de_rolagem_existe():
    fonte = (JS / "kernel" / "rolagem.js").read_text()
    assert "export function marcarRolaveis" in fonte
    assert "export function agendarMarcacao" in fonte


def test_marcacao_e_condicional_ao_transbordo():
    """tabindex em caixa que NAO rola e ruido: o teclado para onde nao ha o que fazer."""
    fonte = (JS / "kernel" / "rolagem.js").read_text()
    assert "scrollHeight" in fonte and "clientHeight" in fonte
    assert re.search(r"auto\|scroll", fonte), "nao confere o overflow computado"


def test_marcacao_e_reversivel():
    """Transbordar e estado, nao natureza: a caixa que parou de rolar perde o tabindex."""
    fonte = (JS / "kernel" / "rolagem.js").read_text()
    assert "removeAttribute('tabindex')" in fonte


def test_nao_sobrescreve_tabindex_alheio():
    """tabindex escrito a mao e decisao de quem conhece o componente."""
    fonte = (JS / "kernel" / "rolagem.js").read_text()
    assert "hasAttribute('tabindex')" in fonte


def test_nao_marca_regiao_que_ja_tem_foco_dentro():
    """Lista de botoes ja e alcancavel: o Tab entra nos botoes e a caixa rola atras.

    Marcar essa caixa acrescentaria uma parada ANTES da lista — exatamente o ruido
    que a marcacao condicional existe para evitar. E o que a regra do axe considera.
    """
    fonte = (JS / "kernel" / "rolagem.js").read_text()
    assert "FOCALIZAVEL" in fonte
    assert "querySelector(FOCALIZAVEL) === null" in fonte


def test_observa_o_dom_e_nao_so_o_render():
    """Gancho de render nao basta — descobrir isso custou duas tentativas.

    Cada modulo busca o proprio dado e se preenche por callback proprio, FORA do laco
    que pinta a grade: a caixa passa a transbordar sem que render nenhum seja chamado.
    A grade monta com skeleton (nada transborda), o dado chega, a caixa cresce. Quem
    ve isso e o MutationObserver.
    """
    fonte = (JS / "kernel" / "rolagem.js").read_text()
    assert "MutationObserver" in fonte, "preenchimento assincrono escapa sem observar o DOM"
    assert "childList: true" in fonte and "subtree: true" in fonte


def test_observador_nao_reentra():
    """Observar atributo faria o nosso setAttribute('tabindex') reentrar — laco infinito."""
    fonte = (JS / "kernel" / "rolagem.js").read_text()
    assert "attributes" not in fonte, "observar atributos reentra na propria marcacao"


def test_marcacao_cobre_a_janela_de_carregamento():
    """Rail e lista lateral rolam com skeleton, e skeleton nao e focalizavel.

    Amarrar a instalacao ao primeiro render deixaria todo o carregamento sem acesso
    por teclado — o estado que uma auditoria medindo logo apos `load` enxerga, e que
    o usuario de teclado encontra ao chegar antes dos dados.
    """
    assert "instalarRolagem()" in (JS / "main.js").read_text(), \
        "a marcacao so comecaria depois do primeiro render"
    assert "DOMContentLoaded" in (JS / "kernel" / "rolagem.js").read_text()


def test_caminho_de_mudanca_marca_sincrono():
    """Onde nasce DOM, adiar deixa a caixa na tela e fora do teclado por um quadro."""
    fonte = (JS / "kernel" / "cockpit.js").read_text()
    assert "marcarRolaveis()" in fonte, "a repintura da grade nao marca de imediato"
    assert "agendarMarcacao()" in fonte, "o caminho da leitura nao marca"


# ---------------------------------------------------------------------------
# icone da aba e pagina 404 com saida
# ---------------------------------------------------------------------------

def test_html_declara_o_icone_da_aba():
    """O icone ja existia, declarado so no manifest — que serve para INSTALAR a app,
    nao para pintar a aba. Sem o <link>, o navegador pedia /favicon.ico e levava 404."""
    html_txt = HTML.read_text()
    assert re.search(r'<link rel="icon"[^>]*href="[^"]+"', html_txt), "sem <link rel=icon>"
    icone = RAIZ / "app" / "static" / "assets" / "icon.svg"
    assert icone.exists(), "o icone declarado nao existe no disco"


def test_favicon_ico_e_servido():
    """O navegador pede /favicon.ico por conta propria, independente do <link>."""
    fonte = (RAIZ / "app" / "app.py").read_text()
    assert '@app.get("/favicon.ico"' in fonte
    assert 'media_type="image/svg+xml"' in fonte, "sem content-type, o navegador ignora"


def test_pagina_404_tem_rota_de_volta():
    """404 sem link de saida e beco: quem digitou errado fica sem caminho."""
    fonte = (RAIZ / "app" / "app.py").read_text()
    assert 'href="/"' in fonte, "a pagina de erro nao oferece volta ao cockpit"
    assert "@app.exception_handler(404)" in fonte


def test_404_de_api_continua_json():
    """HTML so serve para quem NAVEGA. O front le `detail` para mostrar o erro na
    tela — trocar por HTML aqui quebraria o proprio cockpit."""
    fonte = (RAIZ / "app" / "app.py").read_text()
    assert 'startswith("/api/")' in fonte, "o tratador nao ramifica por caminho"
    assert "JSONResponse" in fonte


def test_caminho_ecoado_no_404_e_escapado():
    """O caminho vem do visitante e e impresso na pagina."""
    fonte = (RAIZ / "app" / "app.py").read_text()
    assert "html.escape(request.url.path)" in fonte


# ---------------------------------------------------------------------------
# fontes proprias e bundle de producao
# ---------------------------------------------------------------------------

FONTES = RAIZ / "app" / "static" / "assets" / "fonts"


def test_nenhuma_referencia_a_cdn_de_fonte():
    """Cada visitante entregava IP e User-Agent ao Google, sem escolha (LGPD Art. 5 I).

    E o <link> do CDN e BLOQUEANTE: com o host inacessivel, medimos 13 s ate o
    primeiro pixel. Auto-hospedar resolve privacidade, disponibilidade e velocidade.
    """
    for arquivo in [HTML] + list(CSS.glob("*.css")):
        texto = arquivo.read_text()
        assert "fonts.googleapis.com" not in texto, f"{arquivo.name} volta a chamar o CDN"
        assert "fonts.gstatic.com" not in texto, f"{arquivo.name} volta a chamar o CDN"


def test_fontes_estao_no_disco_com_licenca():
    arquivos = sorted(p.name for p in FONTES.glob("*.woff2"))
    assert arquivos, "as fontes auto-hospedadas sumiram"
    assert (FONTES / "OFL.txt").exists(), "SIL OFL exige distribuir a licenca junto"


def test_fontes_sao_variaveis_e_sem_duplicata():
    """Um arquivo por familia/subconjunto cobre TODOS os pesos.

    O CSS do Google devolvia 18 blocos para os pesos usados, apontando para 4
    arquivos — os mesmos bytes repetidos. Baixar os 18 seriam 907 KB; sao 172.
    """
    import hashlib
    hashes = {hashlib.sha256(p.read_bytes()).hexdigest() for p in FONTES.glob("*.woff2")}
    assert len(hashes) == len(list(FONTES.glob("*.woff2"))), "ha arquivos de fonte duplicados"
    css = (CSS / "fontes.css").read_text()
    # `^@font-face` ancorado: a palavra tambem aparece no comentario do cabecalho.
    blocos = re.findall(r"^@font-face\s*\{", css, re.M)
    assert len(blocos) == 4, f"esperado 4 blocos (2 familias x 2 subconjuntos), achei {len(blocos)}"
    assert "font-weight: 300 800" in css, "Inter deve declarar faixa de peso (fonte variavel)"


def test_unicode_range_evita_baixar_o_que_nao_se_usa():
    """Sem unicode-range o navegador baixaria latin-ext sempre, dobrando o peso."""
    assert "unicode-range" in (CSS / "fontes.css").read_text()


def test_imagem_empacota_o_js_e_o_repositorio_nao():
    """49 modulos ES em cascata viram 1 requisicao; 384 KB viram 132 KB.

    O REPOSITORIO segue sem build: index.html aponta para main.js e rodar do
    codigo-fonte funciona. E a IMAGEM que recebe o bundle e o <script> reescrito.
    """
    dockerfile = (RAIZ / "app" / "Dockerfile").read_text()
    assert "esbuild" in dockerfile and "--minify" in dockerfile
    assert "main.bundle.js" in dockerfile
    assert 'src="/static/js/main.js"' in HTML.read_text(), \
        "o repositorio nao deve apontar para o bundle — quem reescreve e o build"


def test_build_falha_alto_se_o_bundle_nao_sair():
    """App servindo <script> para arquivo inexistente sobe EM BRANCO, sem erro no
    servidor. A trava tem de estar no build, nao na primeira visita."""
    dockerfile = (RAIZ / "app" / "Dockerfile").read_text()
    assert "test -s static/js/main.bundle.js" in dockerfile
    assert "grep -q 'main\\.bundle\\.js' static/index.html" in dockerfile


def test_service_worker_conhece_bundle_e_fontes():
    """Sem estar no cache, offline a interface fica em branco — divida ja paga uma vez."""
    sw = (RAIZ / "app" / "static" / "js").parent.joinpath("sw.js").read_text()
    assert "/static/js/main.bundle.js" in sw
    assert "/static/css/fontes.css" in sw
    assert "inter-latin.woff2" in sw
    assert "cockpit-v4" in sw, "trocar assets sem virar a versao do cache serve o antigo"
