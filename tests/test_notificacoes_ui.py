"""4-B7 na interface — o selo "notificado hh:mm · canal".

O caso que so a execucao separa: uma tentativa REGISTRADA mas nao entregue. Ela
existe na resposta da rota justamente para registrar que o alerta nao chegou, e
um mapa que so olhasse (regra, alvo) diria "notificado" a quem nao recebeu nada
— o pior erro possivel neste selo, porque a decisao do operador as 3 da manha
depende exatamente dessa distincao.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
HARNESS = pathlib.Path(__file__).resolve().parent / "fixtures" / "exercita_notificacoes.mjs"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node ausente; o selo precisa executar os modulos ES",
)

# hh:mm sai no fuso de quem olha; o contrato e o formato.
FORMATO = re.compile(r"^notificado \d{2}:\d{2} · .+$")


@pytest.fixture(scope="module")
def n():
    r = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, timeout=90, cwd=RAIZ)
    assert r.returncode == 0, f"o harness levantou:\n{r.stderr}"
    return json.loads(r.stdout)


def test_achado_notificado_ganha_hora_e_canal(n):
    selo = n["entregue"]
    assert selo is not None
    assert FORMATO.match(selo["texto"]), selo["texto"]
    assert "telegram" in selo["texto"] and "discord" in selo["texto"]


def test_tentativa_sem_entrega_nao_vira_selo(n):
    """Canal fora do ar: a linha existe no banco, mas ninguem foi avisado.
    Dizer "notificado" aqui e a mentira que este selo existe para nao contar."""
    assert n["semEntregaNaoTemSelo"] is None


def test_entrega_parcial_e_entrega_e_o_canal_que_falhou_vai_no_titulo(n):
    """Um canal entregou: o operador foi avisado. O que falhou fica no title,
    onde diagnostica sem competir com o fato."""
    selo = n["entregaParcial"]
    assert selo is not None
    assert "telegram" in selo["texto"]
    assert "discord" in selo["titulo"]


def test_achado_nunca_notificado_nao_ganha_selo(n):
    assert n["regraNaoNotificadaNaoTemSelo"] is None


def test_o_selo_nao_vaza_entre_alvos_da_mesma_regra(n):
    """Dois containers unhealthy sao dois incidentes; o aviso de um nao cobre o
    outro — e a chave e a mesma do dedup no servidor."""
    assert n["alvoDiferenteNaoHerdaSelo"] is None


def test_motor_que_nunca_rodou_nao_desenha_selo(n):
    """Sem canal configurado tambem cai aqui, e a ausencia e honesta nos dois
    casos: ninguem foi avisado."""
    assert n["semMotorSelo"] is None


def test_rota_que_falhou_nao_afirma_notificado(n):
    assert n["comFalhaSelo"] is None


def test_repinturas_da_fila_nao_viram_uma_chamada_cada(n):
    assert n["chamadasComCache"] == 1


def test_recarga_forcada_busca_de_novo(n):
    """Cache de 20s e curto de proposito: isto muda no ritmo dos incidentes, e
    um selo que so aparece cinco minutos depois do alerta e pior que nenhum."""
    assert n["chamadasAposForcar"] == 2
    assert n["aposLimparSelo"] is None
