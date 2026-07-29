"""Topologia e Plantao deixaram de ser promessa de fase.

As duas telas mostravam "Aguarda /api/topology, previsto para F3" e "Aguarda
/api/findings, previsto para F1". A segunda frase era falsa desde a F2:
/api/findings existe e responde. Rotulo de fase em producao e pior que tela
vazia — quem le acha que o dado nao existe, e para de procurar.

Topologia nao ganhou rota nova de proposito. Os dois lados da corrente ja sao
observaveis: /api/ingress da dominio e proxy_pass, /api/overview da o inventario
do daemon. A tela cruza os dois; onde discordam, o no fica marcado.

A logica que da para errar aqui nao e HTML, e decisao: qual upstream esta
quebrado, e em que ordem o plantonista atende. Regex sobre o fonte nao verifica
isso, entao o node importa os modulos de verdade e o pytest confere as respostas.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
JS = RAIZ / "app" / "static" / "js"
HARNESS = pathlib.Path(__file__).resolve().parent / "fixtures" / "exercita_telas.mjs"

precisa_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node ausente; os testes de logica de tela precisam executar os modulos ES",
)


@pytest.fixture(scope="module")
def telas():
    saida = subprocess.run(
        ["node", str(HARNESS)], capture_output=True, text=True, timeout=60, cwd=RAIZ
    )
    assert saida.returncode == 0, f"harness falhou:\n{saida.stderr}"
    return json.loads(saida.stdout)


# ---------------------------------------------------------------------------
# Nenhuma tela promete fase
# ---------------------------------------------------------------------------

def test_nenhum_js_cita_fase_pendente():
    """O critério de pronto: grep 'previsto para F' no JS não acha nada."""
    achados = []
    for arquivo in sorted(JS.rglob("*.js")):
        for n, linha in enumerate(arquivo.read_text().splitlines(), 1):
            if re.search(r"previsto para\s*<?\w*>?\s*F\d", linha) or "previsto para" in linha:
                achados.append(f"{arquivo.relative_to(RAIZ)}:{n}")
    assert not achados, f"promessa de fase ainda na interface: {achados}"


def test_router_nao_tem_mais_placeholder():
    fonte = (JS / "main.js").read_text()
    assert "renderPlaceholder" not in fonte, \
        "o placeholder de fase saiu das duas telas; a funcao nao deve sobreviver sem uso"
    for rota, render in (("#/topologia", "renderTopologia"), ("#/plantao", "renderPlantao")):
        m = re.search(rf"case '{re.escape(rota)}':([^\n]*)", fonte)
        assert m, f"{rota} saiu do router"
        assert render in m.group(1), f"{rota} nao chama {render}: {m.group(1)!r}"


def test_topologia_nao_inventa_rota_nova():
    """A tela se monta de duas rotas que ja existiam."""
    fonte = (JS / "screens" / "topologia.js").read_text()
    rotas = set(re.findall(r"'(/api/[^']+)'", fonte))
    assert rotas == {"/api/ingress", "/api/overview"}, \
        f"topologia deveria usar so ingress e overview, usa {rotas}"


def test_plantao_le_os_achados_abertos():
    fonte = (JS / "screens" / "plantao.js").read_text()
    rotas = set(re.findall(r"'(/api/[^']+)'", fonte))
    assert rotas == {"/api/findings?status=open"}, \
        f"plantao deveria ler so a fila de achados abertos, usa {rotas}"


def test_plantao_nao_escreve():
    """Silenciar e da tela de Atencao, que audita. Aqui so se le e se navega."""
    fonte = (JS / "screens" / "plantao.js").read_text()
    for escrita in ("apiPost", "apiPatch", "apiDelete"):
        assert escrita not in fonte, \
            f"plantao chama {escrita}: mutacao aqui ficaria fora do gate de destravamento"


def test_nenhum_dado_fixo_nas_telas_novas():
    """Nenhum nome de container, dominio ou metrica escrito a mao."""
    for nome in ("topologia.js", "plantao.js"):
        fonte = (JS / "screens" / nome).read_text()
        sem_comentario = re.sub(r"/\*.*?\*/", "", fonte, flags=re.S)
        sem_comentario = re.sub(r"^\s*//.*$", "", sem_comentario, flags=re.M)
        assert not re.search(r"buildtovalue|criptotrade|prompte|srv1351082", sem_comentario, re.I), \
            f"{nome} tem dado de producao escrito no fonte"


# ---------------------------------------------------------------------------
# Topologia: leitura de upstream
# ---------------------------------------------------------------------------

@precisa_node
def test_upstream_com_caminho_e_esquema_resolve_no_nome_do_container(telas):
    a = telas["alvos"]
    assert a[0]["nome"] == "criptotrade-frontend" and a[0]["porta"] == "80"
    # proxy_pass com caminho: o container e o que vem antes da barra
    assert a[1]["nome"] == "btv-squad-dashboard" and a[1]["porta"] == "7878"
    assert a[2]["nome"] == "app" and a[2]["porta"] == "8000"
    assert a[3]["nome"] == "semporta" and a[3]["porta"] is None
    assert a[4] is None and a[5] is None, "entrada vazia ou nula nao pode virar nome de container"


# ---------------------------------------------------------------------------
# Topologia: tres desfechos, tres consertos
# ---------------------------------------------------------------------------

@precisa_node
def test_upstream_sem_container_e_marcado_ausente_nao_e_erro(telas):
    """O critério do enunciado: upstream inexistente vira nó ausente."""
    por_dominio = {s["dominio"]: s for s in telas["situacoes"]}
    assert por_dominio["sumiu.exemplo.com"]["situacao"] == "ausente"
    assert por_dominio["sumiu.exemplo.com"]["alvo"] == "app-que-nao-existe"


@precisa_node
def test_container_parado_nao_e_confundido_com_inexistente(telas):
    """Consertos diferentes: parado se sobe, ausente se corrige o proxy_pass."""
    por_dominio = {s["dominio"]: s for s in telas["situacoes"]}
    assert por_dominio["parado.exemplo.com"]["situacao"] == "parado"
    assert por_dominio["doente.exemplo.com"]["situacao"] == "doente"
    assert por_dominio["no-ar.exemplo.com"]["situacao"] == "no_ar"


@precisa_node
def test_server_name_sem_proxy_pass_nao_conta_como_quebrado(telas):
    por_dominio = {s["dominio"]: s for s in telas["situacoes"]}
    assert por_dominio["so-redirect.exemplo.com"]["situacao"] == "sem_upstream"
    assert por_dominio["so-redirect.exemplo.com"]["alvo"] is None


@precisa_node
def test_sem_inventario_a_tela_nao_acusa_ausencia(telas):
    """A licao da regra upstream_missing, agora na tela.

    Inventario vazio nao e prova de que o upstream sumiu — e prova de que nao
    houve leitura. Chamar isso de "ausente" produziria 13 achados falsos na
    primeira vez que o socket-proxy engasgasse.
    """
    assert set(telas["sem_inventario"]) == {"sem_inventario"}, \
        f"sem leitura do daemon a tela afirmou ausencia: {telas['sem_inventario']}"


@precisa_node
def test_no_de_ingress_e_descoberto_pelas_portas_do_host(telas):
    """Nenhum nome de container escrito na tela: quem publica 80/443 e o ingress."""
    assert telas["ingress_achado"] == "borda"
    assert telas["ingress_sem_candidato"] is None, \
        "sem container publicando 80/443 o no fica ausente, nao chuta um qualquer"
    assert telas["ingress_lista_vazia"] is None


# ---------------------------------------------------------------------------
# Plantao: ordem de atendimento
# ---------------------------------------------------------------------------

@precisa_node
def test_fila_ordena_por_gravidade_e_depois_por_idade(telas):
    """Mais grave primeiro; empatado, o mais antigo — nao o mais recente.

    Fila cronologica faz o plantonista atender sempre o ultimo grito e deixar
    apodrecer o que esta aberto ha 30h.
    """
    ordem = telas["ordem"]
    assert ordem[0] == "critico-mais-pontos", "score maior desempata entre criticos"
    assert ordem.index("critico-antigo") < ordem.index("critico-novo"), \
        "entre dois criticos de score igual, o mais antigo vem primeiro"
    assert ordem.index("alto") < ordem.index("medio-antigo"), \
        "severidade vem antes de idade: alto de 2h passa na frente de medio de 50h"
    assert ordem[-1] == "baixo"


@precisa_node
def test_ordenar_nao_muta_a_lista_recebida(telas):
    """A tela repinta a cada 30s sobre o mesmo array de resposta."""
    assert telas["ordem_nao_mutou_entrada"] == "medio-antigo"


@precisa_node
def test_fila_vazia_ou_ausente_nao_explode(telas):
    assert telas["ordem_lista_vazia"] == 0
    assert telas["ordem_sem_lista"] == 0


@precisa_node
def test_severidade_desconhecida_vai_para_o_fim(telas):
    """Regra nova com SEVERITY inedita nao pode furar a fila."""
    assert telas["ordem_severidade_desconhecida"] == ["baixo", "lixo"]


@precisa_node
def test_tempo_aberto_e_honesto(telas):
    minutos, uma_hora, um_dia, sem_data, futuro = telas["tempos"]
    assert minutos == "agora"
    assert uma_hora == "há 1h"
    assert um_dia == "há 1d"
    assert sem_data == "", "sem first_seen a tela nao inventa idade"
    assert futuro == "", "data no futuro nao vira 'há -1min'"
