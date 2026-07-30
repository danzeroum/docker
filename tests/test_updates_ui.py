"""4-B6 na interface — o selo "imagem desatualizada · verificado hh:mm".

Tres propriedades que so a execucao prova, e nenhuma delas aparece lendo o
fonte:

- **`summary=null` apaga o selo.** O contrato diz que job que nunca rodou nao
  informa nada. Uma UI que lesse so `images: []` mostraria a mesma tela para
  "nada desatualizado" e para "nunca verifiquei" — e a segunda e a que engana.
- **Uma chamada, nao uma por repintura.** O kernel remonta os modulos a cada
  15s; sem cache, um dado que muda uma vez por dia seria buscado 5.760.
- **Selo so em `desatualizada`.** Selo "em dia" em 20 linhas e ruido que informa
  zero, e empurra o unico selo que importa para fora do campo de visao.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
HARNESS = pathlib.Path(__file__).resolve().parent / "fixtures" / "exercita_updates.mjs"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node ausente; o selo precisa executar os modulos ES",
)

# hh:mm e formatado no fuso de quem olha, entao a hora exata depende do TZ da
# maquina que roda o teste. O que o contrato pede e o formato.
FORMATO = re.compile(r"^imagem desatualizada · verificado \d{2}:\d{2}$")


@pytest.fixture(scope="module")
def u():
    r = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, timeout=90, cwd=RAIZ)
    assert r.returncode == 0, f"o harness levantou:\n{r.stderr}"
    return json.loads(r.stdout)


# --- o texto do selo ------------------------------------------------------

def test_imagem_desatualizada_ganha_selo_com_hora_da_verificacao(u):
    selo = u["desatualizada"]
    assert selo is not None
    assert FORMATO.match(selo["texto"]), selo["texto"]


def test_o_titulo_leva_a_data_da_tag_remota(u):
    """A hora diz quando o cockpit olhou; a data diz o que ele viu. Sem a
    segunda o operador nao sabe se a atualizacao e de ontem ou de 2023."""
    assert "2026-07-29" in u["desatualizada"]["titulo"]


def test_imagem_em_dia_nao_ganha_selo(u):
    assert u["atualizadaNaoTemSelo"] is None


def test_imagem_fora_da_listagem_nao_ganha_selo(u):
    """Construida localmente ou de registry privado nao entra na tabela — e a
    tela nao inventa estado para ela."""
    assert u["foraDaListagemNaoTemSelo"] is None


def test_docker_io_explicito_casa_com_a_forma_curta(u):
    """`docker.io/library/postgres:16` no banco e `library/postgres:16` no
    compose sao a mesma imagem; qual forma aparece e escolha de quem escreveu o
    compose, nao um estado diferente."""
    assert u["prefixoDockerIo"] is not None


# --- ausencia de dado nao vira afirmacao ----------------------------------

def test_job_que_nunca_rodou_nao_desenha_selo(u):
    """summary=null (padrao do certs_expiring): a tela cala, nao afirma."""
    assert u["semJobSelo"] is None


def test_rota_que_falhou_nao_afirma_em_dia(u):
    assert u["comFalhaSelo"] is None


# --- custo ----------------------------------------------------------------

def test_repinturas_do_kernel_nao_viram_uma_chamada_cada(u):
    assert u["chamadasComCache"] == 1


def test_lista_e_subtela_pedindo_juntas_fazem_uma_chamada_so(u):
    """Sem coalescencia, abrir a subtela dispararia a segunda chamada antes de a
    primeira responder — e o cache nunca chegaria a valer."""
    assert u["chamadasConcorrentes"] == 1


# --- render do modulo -----------------------------------------------------

def test_a_lista_aparece_antes_do_selo(u):
    """O selo vem de outra rota. Esperar por ele para desenhar 15 containers
    seria atrasar o dado de 15s pelo dado de 24h."""
    assert u["listaPintaAntesDoSelo"] is True


def test_o_selo_entra_so_na_linha_da_imagem_desatualizada(u):
    por_imagem = {l["imagem"]: l["selos"] for l in u["selosNaLista"]}
    assert len(por_imagem["nginx:1.25"]) == 1
    assert por_imagem["nginx:1.25"][0]["classe"] == "selo-update"
    assert FORMATO.match(por_imagem["nginx:1.25"][0]["texto"])
    assert por_imagem["redis:7"] == []


def test_modulo_desmontado_nao_recebe_selo(u):
    """Navegar para outro escopo antes de a resposta chegar pintaria num corpo
    que ja nao esta na tela — e o proximo render duplicaria o selo."""
    assert u["aposDisposeSemSelo"] is True


# --- doc 13: a leitura nao reconstroi a lista ------------------------------

def test_leitura_com_payload_identico_nao_recria_no_nenhum(u):
    """O aceite central do doc 13, medido por IDENTIDADE de no.

    Comparar o HTML final nao serve: um `innerHTML =` idempotente produz string
    identica e mesmo assim matou toda a arvore no caminho. A pergunta e se o
    elemento e o MESMO objeto — porque e nele que vivem `:hover`, foco e scroll.
    """
    assert u["mesmosNosAposLeitura"] is True


def test_selo_sobrevive_a_leitura(u):
    """O selo vem de uma rota de cadencia diaria; a lista relê a cada 15s.

    Com rebuild, cada leitura apagava o selo e ele so voltava na proxima
    resposta de `/api/updates` — que pode estar a 5 minutos de distancia por
    causa do cache. Na pratica o selo piscava e sumia."""
    por_imagem = {l["imagem"]: l["selos"] for l in u["selosAposLeitura"]}
    assert len(por_imagem["nginx:1.25"]) == 1
    assert FORMATO.match(por_imagem["nginx:1.25"][0]["texto"])
    assert por_imagem["redis:7"] == []
