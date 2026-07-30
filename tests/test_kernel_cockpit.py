"""Sprint 2a — o registro de módulos, a régua, o layout e a subtela.

O `switch` com um `case` por tela saiu do main.js. Estes testes cobram o que
substituiu: um registro que é o único ponto de extensão, uma régua que vive do
`summary`, e os invariantes do doc 10 que a arquitetura anterior não conseguia
sustentar.

O harness executa os módulos ES de verdade no node — regex sobre o fonte prova
que a função existe, não que o módulo aparece na tela quando registrado.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
JS = RAIZ / "app" / "static" / "js"
HARNESS = pathlib.Path(__file__).resolve().parent / "fixtures" / "exercita_kernel.mjs"

# Os 13 do protótipo completo (doc 12). Lista fixa de propósito: se um sair do
# registro por acidente num refactor, este teste é quem conta.
DO_PROTOTIPO = {
    "armazenamento", "atencao", "auditoria", "capacidade", "config", "containers",
    "drift", "eventos", "ingress", "logs", "metricas", "stacks", "tarefas",
}
# Telas que existiam e não têm contrapartida no protótipo. Decisão de escopo:
# registradas (nada se perde) mas fora de qualquer preset padrão.
EXTRAS = {"backend", "executivo", "plantao", "projetos", "topologia"}

# Arquivos do núcleo. Nenhum pode citar módulo por nome — é o teste de
# aberto/fechado do doc 10 §4.
NUCLEO = [
    JS / "main.js",
    JS / "kernel" / "app.js",
    JS / "kernel" / "cockpit.js",
    JS / "kernel" / "regua.js",
    JS / "kernel" / "personalizar.js",
    JS / "kernel" / "registry.js",
    JS / "kernel" / "layout.js",
]

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node ausente; o kernel precisa executar os módulos ES",
)


@pytest.fixture(scope="module")
def k():
    r = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, timeout=90, cwd=RAIZ)
    assert r.returncode == 0, f"o kernel levantou:\n{r.stderr}"
    return json.loads(r.stdout)


# --- o registro é o único ponto de extensão -------------------------------

def test_todos_os_modulos_estao_registrados(k):
    assert set(k["registrados"]) == DO_PROTOTIPO | EXTRAS


def test_os_13_do_prototipo_e_os_extras_estao_separados(k):
    assert set(k["doPrototipo"]) == DO_PROTOTIPO
    assert set(k["extras"]) == EXTRAS


def test_presets_montam_exatamente_os_13_do_prototipo(k):
    """Aceite da decisão de escopo: nenhum preset padrão referencia os extras."""
    assert set(k["ids_em_presets"]) == DO_PROTOTIPO
    for extra in EXTRAS:
        assert extra not in k["ids_em_presets"], f"{extra} entrou num preset padrão"


def test_nucleo_nao_cita_nenhum_modulo_por_nome():
    """O `switch` antigo nomeava 13 telas. Nenhum arquivo do núcleo pode voltar a isso."""
    nomes = DO_PROTOTIPO | EXTRAS
    for arquivo in NUCLEO:
        fonte = arquivo.read_text()
        for nome in nomes:
            assert f"'{nome}'" not in fonte, f"{arquivo.name} cita o módulo {nome} por nome"
            assert f'"{nome}"' not in fonte, f"{arquivo.name} cita o módulo {nome} por nome"


def _sem_comentarios(fonte: str) -> str:
    """Remove comentários: o núcleo pode DESCREVER o roteador que morreu."""
    fonte = re.sub(r"/\*.*?\*/", "", fonte, flags=re.S)
    return re.sub(r"^\s*//.*$", "", fonte, flags=re.M)


def test_nucleo_nao_tem_roteador_por_tela():
    codigo = _sem_comentarios((JS / "main.js").read_text())
    assert "switch (_route" not in codigo
    assert not re.search(r"case\s*'#/", codigo), "voltou um desvio de rota ao main.js"


def test_apenas_o_indice_enumera_modulos():
    """Acrescentar módulo tem de ser: criar arquivo + importar no índice."""
    indice = (JS / "modulos" / "index.js").read_text()
    for nome in DO_PROTOTIPO | EXTRAS:
        assert f"./{nome}.js" in indice, f"{nome} não está importado no índice"


def test_modulo_registrado_em_runtime_aparece_sem_tocar_o_nucleo(k):
    """Aceite do doc 10 §testes — o teste de aberto/fechado, executado."""
    assert "sonda_de_teste" in k["regua_com_sonda"], "módulo novo não ganhou chip na régua"
    assert "sonda_de_teste" in k["estado_com_sonda"]["ordem"], "não entrou no layout"


def test_modulo_novo_entra_oculto_e_nao_invade_a_grade(k):
    """Grade é escolha do operador: módulo que ele nunca escolheu não brota nela."""
    assert "sonda_de_teste" in k["estado_com_sonda"]["ocultos"]
    assert k["corpo_sonda_oculta"] == "", "módulo oculto renderizou na grade"


def test_exibir_o_modulo_novo_o_faz_renderizar(k):
    assert k["sonda_visivel_no_estado"] is True
    assert "sonda viva" in k["corpo_sonda_visivel"], "exibido, mas não renderizou"


# --- invariantes do kernel (doc 10 §1) ------------------------------------

def test_regua_pinta_os_quatro_vitais(k):
    for rotulo in ("CPU", "RAM", "Disco", "Swap"):
        assert rotulo in k["regua"], f"vital {rotulo} ausente da régua"


def test_regua_vive_do_summary_com_um_chip_por_modulo(k):
    assert k["regua"].count("rg-chip") >= 6, "régua com chips demais de menos"
    # valores vindos do summary, não recalculados na tela
    assert "9.8 GB" in k["regua"], "chip de storage não leu summary.storage"
    assert "~24d" in k["regua"], "chip de capacidade não leu summary.capacity"
    assert "11/13" in k["regua"], "chip de ingress não leu summary.ingress"


def test_chip_de_modulo_oculto_continua_vivo(k):
    """Invariante 3: ocultar não pode significar perder o dado.

    Cenário do doc 12 §5: o preset Executivo esconde 4 módulos e os chips deles
    continuam vivos na régua. O preset padrão não serve para este teste porque
    esconde `drift` e `logs`, os dois que não têm chip.
    """
    ocultos = set(k["estado_executivo"]["ocultos"])
    assert {"containers", "auditoria"} <= ocultos, "o preset Executivo mudou de forma"
    assert "rg-oculto" in k["regua_executivo"], "nenhum chip de módulo oculto na régua"
    # e o dado do módulo escondido continua na régua, não sumiu com ele
    assert "dz" in k["regua_executivo"], "chip de auditoria perdeu o dado ao ser oculto"
    # a grade, essa sim, não mostra o módulo oculto
    assert 'data-modulo="auditoria"' not in k["grade_executivo"]


def test_faixa_critica_aparece_em_todo_escopo(k):
    """Invariante 2: a faixa é do host inteiro, inclusive dentro de um container."""
    assert "faixa-critica" in k["faixa"]
    assert "faixa-critica" in k["faixa_no_stack"]
    assert "faixa-critica" in k["faixa_no_container"]


def test_regua_continua_visivel_na_subtela(k):
    """Invariante 1: o kernel não pode ser coberto pela subtela."""
    assert "rg-vitais" in k["regua_no_container"]


def test_subtela_abre_sobre_a_grade_do_host(k):
    assert "sub-painel" in k["subtela"], "subtela não pintou"
    assert "sub-voltar" in k["subtela"], "sem caminho de volta"
    assert "data-modulo" in k["grade_atras_da_subtela"], (
        "a grade do host desapareceu atrás da subtela — o kernel deixaria de ser invariante"
    )


# --- escopo: 1 registro × N escopos ---------------------------------------

def test_mesmo_modulo_renderiza_em_escopos_diferentes(k):
    """Não existem 3 telas; existe 1 registro × 3 escopos (doc 10 §1)."""
    assert "data-modulo" in k["grade_host"]
    assert "data-modulo" in k["grade_stack"]
    assert k["grade_host"] != k["grade_stack"], "o escopo stack renderizou igual ao host"


# --- layout ---------------------------------------------------------------

def test_layout_corrompido_volta_ao_padrao(k):
    """localStorage é editável pelo usuário e sobrevive a deploy."""
    est = k["layout_corrompido"]
    assert est["v"] == 1
    assert est["preset"] == "operacao"
    assert est["ordem"], "padrão sem ordem"


def test_setas_e_drag_produzem_o_mesmo_estado(k):
    """HTML5 drag não funciona em touch; os ↑↓ têm de ser equivalentes."""
    assert k["setas_igual_drag"] is True


def test_ajuste_manual_vira_personalizado(k):
    assert k["ajuste_vira_personalizado"] is True


def test_restaurar_volta_ao_preset_padrao(k):
    assert k["restaurar_volta_ao_preset"] == "operacao"


# --- ações fail-closed na UI ---------------------------------------------

def test_sem_actions_enabled_nenhum_botao_de_acao_no_dom(k):
    """Aceite do doc 11: ausente, não `display:none`.

    Esconder por CSS deixa a rota alcançável por quem inspeciona o DOM; o
    contrato é o botão não existir.
    """
    dom = k["dom_sem_acoes"]
    for marca in ('data-acao="restart"', 'data-acao="stop"', 'data-acao="prune"'):
        assert marca not in dom, f"botão de ação {marca} existe no DOM com a flag desligada"
    assert "display:none" not in dom.replace("display:none;flex", ""), (
        "há algo escondido por CSS onde o contrato pede ausência"
    )
