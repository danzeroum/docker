"""As duas telas novas pintam de ponta a ponta, inclusive quando falta dado.

Os testes de logica conferem a decisao (qual upstream esta quebrado, em que
ordem atender). Estes conferem o caminho inteiro: render -> fetch -> template.
Um campo ausente que levanta no template nao aparece em teste de unidade — a
tela simplesmente fica no skeleton, que foi exatamente o sintoma do `let
pollTimer` duplicado.

Tres cenarios, porque os tres acontecem na VPS:
  1. tudo respondendo, com upstream parado E upstream inexistente;
  2. as duas rotas fora (cockpit sem socket-proxy);
  3. nginx.conf lido mas inventario vazio — o caso em que a tela e tentada a
     acusar 13 upstreams de sumidos sem ter olhado para nenhum.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
HARNESS = pathlib.Path(__file__).resolve().parent / "fixtures" / "renderiza_telas.mjs"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node ausente; a renderizacao das telas precisa executar os modulos ES",
)


@pytest.fixture(scope="module")
def pintado():
    r = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, timeout=60, cwd=RAIZ)
    assert r.returncode == 0, f"renderizar as telas levantou:\n{r.stderr}"
    return json.loads(r.stdout)


# ---------------------------------------------------------------------------
# Cenario 1 — tudo respondendo
# ---------------------------------------------------------------------------

def test_topologia_desenha_a_corrente_inteira(pintado):
    html = pintado["topologia"]
    assert html, "a tela nao pintou nada"
    assert "skeleton" not in html, "ficou no esqueleto de carregamento"
    # os cinco elos, cada um vindo de dado: dominios, borda, upstreams, proxy, daemon
    assert "Domínios publicados" in html
    assert "borda" in html, "o no de ingress e descoberto pelas portas publicadas"
    assert "Upstreams de proxy_pass" in html
    assert "Socket-proxy" in html
    assert "srv-de-teste" in html, "o nome do host vem de /api/overview"


def test_topologia_conta_o_que_leu(pintado):
    html = pintado["topologia"]
    assert "4 hosts" in html
    assert "2/4 no ar" in html, "2 dos 4 upstreams alcancaveis"
    assert "2 com TLS" in html and "1 atrás de basic auth" in html


def test_topologia_separa_parado_de_inexistente_com_conserto_diferente(pintado):
    html = pintado["topologia"]
    assert "container existe e está parado — subir a stack" in html
    assert "container não existe no daemon" in html
    assert "corrigir o proxy_pass" in html
    # e cada um citado com o dominio que o alcanca
    assert "b.exemplo.com" in html and "http://parado:8080" in html
    assert "c.exemplo.com" in html and "http://fantasma:3000" in html


def test_topologia_mostra_a_superficie_exposta(pintado):
    html = pintado["topologia"]
    assert "sem TLS" in html, "host em 80 puro tem de aparecer marcado"
    assert "interno" in html, "localhost nao e superficie publica"
    assert "basic auth" in html


def test_topologia_nao_deixa_undefined_nem_nan_na_tela(pintado):
    for chave in ("topologia", "topologia_sem_inventario"):
        html = pintado[chave]
        for lixo in ("undefined", "NaN", "[object Object]"):
            assert lixo not in html, f"{chave} pintou '{lixo}'"


def test_plantao_lista_os_achados_abertos(pintado):
    html = pintado["plantao"]
    assert html and "skeleton" not in html
    assert "3 aberto(s)" in pintado["plantao_resumo"]
    assert "1 crítico" in pintado["plantao_resumo"]
    for titulo in ("aponta para um serviço que não existe", "container morto por falta de memoria", "hosts sem TLS"):
        assert titulo in html


def test_plantao_prefere_a_frase_direta_e_traz_a_acao(pintado):
    html = pintado["plantao"]
    assert "O site c.exemplo.com aponta para um serviço que não existe" in html, \
        "title_plain existe e e o que o plantonista le"
    assert "Corrigir o endereço no nginx ou recriar o serviço" in html, \
        "fila sem a acao e so lista de problema"


def test_plantao_cai_no_titulo_tecnico_quando_nao_ha_plain(pintado):
    """Achado sem title_plain nao pode virar cartao vazio."""
    assert "container morto por falta de memoria" in pintado["plantao"]


def test_plantao_mostra_idade_e_reincidencia(pintado):
    html = pintado["plantao"]
    assert "há 1d" in html and "12×" in html
    assert "2 alvos" in html, "achado agregado mostra a contagem, nao um alvo escolhido a esmo"


def test_plantao_tem_botao_acessivel_por_cartao(pintado):
    html = pintado["plantao"]
    assert html.count('class="card-open"') == 3
    assert html.count('class="sr-only"') == 3, \
        "botao esticado sem nome acessivel e um botao sem rotulo para leitor de tela"


def test_as_duas_telas_devolvem_dispose(pintado):
    """Sem dispose o setInterval sobrevive a troca de tela e vaza requisicao."""
    for k in ("topologia_dispose", "plantao_dispose", "topologia_caida_dispose"):
        assert pintado[k] is True, f"{k} nao devolveu funcao de limpeza"


# ---------------------------------------------------------------------------
# Cenario 2 — rotas fora
# ---------------------------------------------------------------------------

def test_rotas_fora_dizem_o_que_falhou(pintado):
    assert "socket-proxy fora" in pintado["topologia_caida"], \
        "erro de rede tem de citar o motivo que o servidor deu"
    assert "socket-proxy fora" in pintado["plantao_caido"]
    assert "skeleton" not in pintado["topologia_caida"]


# ---------------------------------------------------------------------------
# Cenario 3 — inventario vazio nao autoriza acusar ninguem
# ---------------------------------------------------------------------------

def test_sem_inventario_a_tela_diz_que_nao_confrontou(pintado):
    html = pintado["topologia_sem_inventario"]
    assert "4 sem confronto" in html
    assert "não se afirma que um upstream sumiu" in html
    assert "Lista em branco aqui não significa que está tudo certo" in html, \
        "lista de rompidos vazia por falta de leitura tem de dizer isso"


def test_sem_inventario_nao_acusa_upstream_de_ausente(pintado):
    html = pintado["topologia_sem_inventario"]
    assert "container não existe no daemon" not in html, (
        "acusou ausencia sem ter lido o daemon — o falso positivo que a regra "
        "upstream_missing ja teve de aprender a nao dar"
    )
    assert "subir a stack" not in html


def test_sem_inventario_nao_acusa_falta_de_ingress(pintado):
    html = pintado["topologia_sem_inventario"]
    assert "Nenhum container publica 80 ou 443" not in html, \
        "nao se olhou o inventario; nao da para dizer que ninguem publica as portas"
    assert "Inventário do daemon não chegou nesta leitura" in html


def test_sem_inventario_ainda_mostra_o_que_o_nginx_disse(pintado):
    """Metade da leitura ainda e leitura: os dominios continuam na tela."""
    html = pintado["topologia_sem_inventario"]
    assert "4 hosts" in html
    assert "a.exemplo.com" in html
