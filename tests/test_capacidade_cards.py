"""Os cartoes novos da Capacidade pintam, inclusive com payload torto (B1/B4).

Complementa test_storage.py e test_security.py: aqueles conferem o JSON que o
backend produz, este confere que o template sobrevive a ele — inclusive quando
o storage responde 503 e quando o payload chega sem secao.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
HARNESS = pathlib.Path(__file__).resolve().parent / "fixtures" / "renderiza_capacidade.mjs"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node ausente; os cartoes precisam executar os modulos ES",
)


@pytest.fixture(scope="module")
def pintado():
    r = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, timeout=60, cwd=RAIZ)
    assert r.returncode == 0, f"pintar os cartoes levantou:\n{r.stderr}"
    return json.loads(r.stdout)


# --- B1: storage -----------------------------------------------------------

def test_storage_mostra_o_total_recuperavel(pintado):
    html = pintado["cheio_storage"]
    assert html, "o cartao de storage nao pintou nada"
    assert "skeleton" not in html, "ficou no esqueleto de carregamento"
    assert "6.0 GB" in html, "o total recuperavel nao apareceu formatado"
    # O texto vai por `textContent` desde o doc 13, entao chega ja decodificado:
    # o que se confere e a palavra que o operador le, nao a entidade HTML.
    assert "recuperáveis" in html


def test_storage_lista_os_tres_tipos_de_orfao(pintado):
    html = pintado["cheio_storage"]
    for rotulo in ("imagem", "volume", "container"):
        assert rotulo in html, f"tipo de orfao {rotulo} ausente na lista"
    assert "zumbi" in html
    assert "sobra_v" in html


def test_storage_marca_a_contagem_de_sobra_por_secao(pintado):
    html = pintado["cheio_storage"]
    assert "(2 sobra)" in html, "as 2 imagens dangling nao foram sinalizadas"
    assert "(1 sobra)" in html


def test_storage_explica_o_criterio_de_container_zumbi(pintado):
    """O operador precisa saber que o corte e 7 dias, nao adivinhar."""
    assert "7 dias parado" in pintado["cheio_storage"]


def test_storage_diz_que_build_cache_esta_fora_do_total(pintado):
    assert "Build cache" in pintado["cheio_storage"]
    assert "fora do total" in pintado["cheio_storage"]


def test_storage_limpo_afirma_que_nao_ha_nada(pintado):
    html = pintado["limpo_storage"]
    assert "Nenhum recurso" in html
    assert "0 B" in html
    assert "zumbi" not in html


def test_storage_caido_nao_apaga_a_tela_de_capacidade(pintado):
    """503 no storage e um cartao com aviso, nao a Capacidade inteira em erro."""
    assert "indispon" in pintado["storage_caido_storage"].lower()
    corpo = pintado["storage_caido_body"]
    assert "Postura de seguran" in corpo, "a tela ao redor sumiu junto com o cartao"
    # o cartao de score, que respondeu, continua pintado
    assert pintado["storage_caido_security"]
    assert "skeleton" not in pintado["storage_caido_security"]


def test_payload_truncado_nao_levanta_no_template(pintado):
    """Secao ausente e dado que falta, nao excecao — o sintoma seria skeleton eterno."""
    assert pintado["truncado_storage"]
    assert "skeleton" not in pintado["truncado_storage"]
    assert pintado["truncado_security"]
    assert "skeleton" not in pintado["truncado_security"]


# --- B4: score -------------------------------------------------------------

def test_score_mostra_medio_e_pior(pintado):
    html = pintado["cheio_security"]
    assert html and "skeleton" not in html
    assert "83.3" in html, "score medio ausente"
    assert "pior 55" in html, "o pior score nao apareceu"


def test_score_lista_os_containers_com_violacao_e_omite_o_conforme(pintado):
    html = pintado["cheio_security"]
    assert "com_socket" in html
    assert "sem_limite" in html
    # ">conforme</span>" e o nome na lista; "1/3 conformes" e o resumo, que fica.
    assert ">conforme</span>" not in html, "container sem violacao nao deve ocupar a lista"


def test_score_rotula_a_pior_severidade_de_cada_container(pintado):
    html = pintado["cheio_security"]
    assert "Cr&iacute;tico" in html or "Crítico" in html
    assert "M&eacute;dio" in html or "Médio" in html


def test_score_resume_violacoes_por_severidade(pintado):
    html = pintado["cheio_security"]
    assert "1/3 conformes" in html
    assert "crít" in html


def test_score_explica_a_ponderacao(pintado):
    """A aritmetica fica na tela: senao 55 e um numero sem procedencia."""
    html = pintado["cheio_security"]
    assert "30" in html and "15" in html and "5" in html
    assert "1 sem healthcheck" in html


def test_score_conforme_afirma_conformidade(pintado):
    html = pintado["limpo_security"]
    assert "Todos os containers conformes" in html
    assert "100" in html


# --- B4: a regra do selo de saude -----------------------------------------

def test_saude_prefere_o_campo_explicito(pintado):
    s = pintado["saude"]
    assert s["explicito_unhealthy"] == "unhealthy"
    # Health explicito vence o texto do daemon, que pode estar defasado
    assert s["explicito_healthy"] == "healthy"


def test_sem_healthcheck_nao_ganha_selo(pintado):
    """Ausencia de healthcheck e ausencia de medida, nao saude confirmada."""
    s = pintado["saude"]
    assert s["sem_healthcheck"] is None
    assert s["vazio"] is None
    assert s["nulo"] is None


def test_fallback_do_status_continua_valendo_no_boot(pintado):
    """Antes do coletor preencher o inspect, o sniff do Status e o que ha."""
    s = pintado["saude"]
    assert s["fallback_status"] == "unhealthy"
    assert s["fallback_state"] == "unhealthy"


def test_starting_e_reportado_como_estado_proprio(pintado):
    assert pintado["saude"]["starting"] == "starting"
