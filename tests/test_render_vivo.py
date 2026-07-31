"""Doc 13 — a interface nao reconstroi a arvore por leitura.

O diagnostico do doc 13 e que a sensacao de "interface travada" nao vem de
lentidao: vem de `alvo.innerHTML =` a cada poll. Recriar o no mata o `:hover` no
meio do movimento, perde foco, selecao e scroll interno, e impede qualquer
`transition` de rodar — o no novo NASCE no valor final, entao barra e numero
saltam em vez de andar.

A medida aqui e IDENTIDADE DE NO, e nao igualdade de HTML. As duas divergem
exatamente no caso que importa: um `innerHTML =` idempotente produz string final
identica e mesmo assim matou toda a arvore no caminho.

Tres niveis, como o doc 13 pede:

- unidade      `lista()` e `texto()` do patch.js;
- integracao   um modulo real sob 20 leituras seguidas;
- aceitacao    o roteiro do doc 12 sem perder foco nem scroll, e o relogio
               compartilhado com a aba oculta.

O harness roda no node com `dom_min.mjs` — uma arvore de verdade, com
`MutationObserver`. O `dom_stub.mjs` nao serve para isto: ele responde ao que os
modulos chamam sem ter nos, e patch sobre no de mentira nao e observavel.

O que precisa de navegador continua precisando: `:hover` real, contraste e
reflow medido sao o roteiro manual do doc 12. O que se afirma aqui e o que
sustenta os tres: se o no sobrevive, o resto e CSS.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
HARNESS = pathlib.Path(__file__).resolve().parent / "fixtures" / "exercita_render_vivo.mjs"
JS = RAIZ / "app" / "static" / "js"
CSS = RAIZ / "app" / "static" / "css"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node ausente; o render precisa executar os modulos ES",
)


@pytest.fixture(scope="module")
def v():
    r = subprocess.run(
        ["node", str(HARNESS)], capture_output=True, text=True, timeout=90, cwd=RAIZ
    )
    assert r.returncode == 0, f"o render levantou:\n{r.stderr}"
    return json.loads(r.stdout)


# --- unidade: a linha que sobrevive ---------------------------------------

def test_leitura_identica_nao_toca_em_no_nenhum(v):
    """Aceite do doc 13: poll com payload identico -> zero nos recriados."""
    assert v["unidade_identico"]["criados"] == 0
    assert v["unidade_identico"]["removidos"] == 0
    assert v["unidade_identico"]["movidos"] == 0
    assert v["unidade_identico"]["mesmosNos"] is True


def test_valor_que_muda_escreve_no_mesmo_no(v):
    """E o que permite a `transition` rodar: ha um estado anterior de onde sair."""
    u = v["unidade_valor"]
    assert u["criados"] == 0 and u["removidos"] == 0
    assert u["mesmoNo"] is True
    assert u["valor"] == "9", "o valor nao chegou a trocar"
    assert u["piscou"].startswith("flash-"), "o valor mudou sem se anunciar"


def test_item_removido_leva_so_a_propria_linha(v):
    """Aceite: `item removido do payload -> so a linha correspondente sai`."""
    u = v["unidade_remocao"]
    assert u["removidos"] == 1, "saiu mais gente do que a linha removida"
    assert u["criados"] == 0
    assert u["restantes"] == ["api", "worker"]
    assert u["vizinhasIntactas"] is True, "as vizinhas foram recriadas junto"


def test_remover_do_meio_nao_empurra_as_seguintes(v):
    """Nenhum no recriado ja passava; o que faltava era nao MOVER 7 vizinhas.

    Com os orfaos saindo depois do posicionamento, remover um container do meio
    de quinze produzia quatorze `insertBefore` — DOM mexido a toa numa lista que
    so precisava perder uma linha.
    """
    assert v["unidade_remocao"]["movidos"] == 0
    assert v["integracao_remocao"]["movidos"] == 0


def test_reordenar_reaproveita_os_nos(v):
    u = v["unidade_reordem"]
    assert u["criados"] == 0 and u["removidos"] == 0
    assert u["ordem"] == ["worker", "api"]
    assert u["reaproveitou"] is True


def test_item_novo_e_o_unico_que_nasce(v):
    assert v["unidade_insercao"]["criados"] == 1
    assert v["unidade_insercao"]["removidos"] == 0


def test_texto_nao_reescreve_o_que_ja_esta_escrito(v):
    """Escrever o mesmo valor invalida selecao dentro do no sem mudar nada."""
    u = v["unidade_texto"]
    assert u["primeira"] is True
    assert u["repetida"] is False
    assert u["diferente"] is True


def test_flash_nao_dispara_na_chegada_do_dado(v):
    """Primeira escrita e chegada de dado, nao mudanca de valor.

    Piscar na carga inicial faria a tela inteira piscar de uma vez — ruido, e
    ruido que ensina o operador a ignorar o sinal.
    """
    assert v["flash_primeira"] == ""


def test_flash_reinicia_alternando_a_classe(v):
    """Duas classes em vez de uma: reiniciar animacao pelo caminho classico
    exige ler `offsetWidth`, que e um reflow sincrono POR ITEM alterado."""
    assert v["flash_mudanca"] != v["flash_realterna"]
    assert v["flash_mudanca"].startswith("flash-")
    assert v["flash_realterna"].startswith("flash-")


# --- integracao: um modulo real sob polls repetidos ------------------------

def test_15_containers_e_20_polls_nao_criam_nem_destroem_no(v):
    """Aceite do doc 13, literal: sem crescimento de nos e sem churn por item."""
    assert v["integracao_20_polls"] == {"criados": 0, "removidos": 0, "movidos": 0}
    assert v["integracao_nos_apos_20"] == 15, "a lista cresceu ou encolheu sozinha"


def test_scroll_interno_e_foco_sobrevivem_a_tres_polls(v):
    """O aceite escrito no doc 13 §aceite, ponto por ponto."""
    assert v["integracao_scroll"] == 120, "o scroll interno voltou ao topo"
    assert v["integracao_foco"] is True, "o foco saiu da linha"


def test_barra_de_cpu_anima_no_mesmo_no(v):
    """Sem no estavel nao ha animacao: o no novo nasce no valor final.

    A largura vai por propriedade customizada — a `transition` de .7s mora no
    components.css e o modulo entrega so o numero.
    """
    b = v["integracao_barra"]
    assert b["mesmoNo"] is True, "a barra foi recriada; a transicao nao roda"
    assert b["antes"] != b["depois"], "a largura nao mudou"
    assert b["depois"].endswith("%")


def test_vizinhas_do_removido_mantem_o_no(v):
    assert v["integracao_remocao"]["criados"] == 0
    assert v["integracao_remocao"]["removidos"] == 1
    assert v["integracao_remocao_vizinha"] is True
    assert v["integracao_remocao_restantes"] == 14


# --- aceitacao: o roteiro do doc 12 ---------------------------------------

def test_digitar_na_busca_de_logs_nao_e_interrompido(v):
    """`logs.js` reconstruia o proprio `input` a cada ciclo.

    Cenario do doc 12: buscar `oom` nos logs. Com o campo recriado, o segundo
    caractere caia num elemento novo, sem foco e sem o texto anterior.
    """
    a = v["aceite_logs"]
    assert a["mesmoCampo"] is True, "o campo de busca foi recriado"
    assert a["textoDigitado"] == "oo", "o que estava digitado se perdeu"
    assert a["focoMantido"] is True, "o foco saiu do campo"
    assert a["criados"] == 0 and a["removidos"] == 0


def test_scroll_do_tail_nao_e_roubado_de_quem_parou_para_ler(v):
    """`scrollTop = scrollHeight` incondicional jogava de volta ao rodape quem
    tinha subido para ler a linha do erro."""
    assert v["aceite_logs"]["scrollMantido"] == 40


# --- aceitacao: relogio compartilhado -------------------------------------

def test_periodo_e_multiplo_do_tick(v):
    """Um relogio, periodos declarados em ticks: os piscas ficam em fase."""
    assert v["relogio_periodos"]["rapido"] == 3
    assert v["relogio_periodos"]["lento"] == 1


def test_aba_oculta_nao_tica(v):
    assert v["relogio_oculto"] == 0


def test_ao_voltar_uma_unica_atualizacao_por_assinante(v):
    """Sem rajada acumulada: repor os ticks perdidos entregaria doze requisicoes
    no instante em que a aba volta, que e quando o operador esta olhando."""
    assert v["relogio_retorno"] == {"rapido": 1, "lento": 1}


def test_sem_assinante_o_relogio_para(v):
    """Relogio batendo para ninguem acorda a aba de graca."""
    assert v["relogio_sem_assinantes"] == 0


# --- aceitacao: regua e pilula "ao vivo" ----------------------------------

def test_regua_repinta_sem_recriar_vital_nem_chip(v):
    r = v["regua"]
    assert r["identica"] == {"criados": 0, "removidos": 0, "movidos": 0}
    assert r["aposMudanca"]["criados"] == 0, "mudar de valor recriou o chip"
    assert r["mesmosVitais"] is True
    assert r["mesmoChip"] is True


def test_vital_troca_de_tom_e_o_chip_pisca(v):
    r = v["regua"]
    assert r["cpuTexto"] == "81%"
    assert "rg-warn" in r["cpuTom"], "81% de CPU tem de sair do tom normal"
    assert r["chipValor"] == "2"
    assert r["chipPiscou"] is True


def test_varredura_reinicia_a_cada_leitura(v):
    """A pilula so informa se a varredura RECOMECA quando o dado chega; um
    trilho animando sozinho diz o mesmo com dado de dez minutos atras."""
    assert v["vivo"]["varreduraAlterna"] is True


def test_pilula_vira_pausado_e_volta(v):
    """`ao vivo` enquanto nada e lido e a unica coisa pior que nao ter
    indicador nenhum."""
    assert "rg-pausado" in v["vivo"]["pausada"]["classe"]
    assert v["vivo"]["pausada"]["rotulo"] == "pausado"
    assert v["vivo"]["retomada"] == "ao vivo"


# --- guardas de fonte ------------------------------------------------------

MODULOS = sorted((JS / "modulos").glob("*.js")) + sorted((JS / "screens").glob("*.js"))


def _sem_comentarios(fonte: str) -> str:
    """Comentario pode DESCREVER o padrao que morreu — e aqui eles descrevem.

    Sem isto o guarda acusaria o proprio texto que explica por que o `style`
    com cor de severidade saiu do JS.
    """
    fonte = re.sub(r"/\*.*?\*/", "", fonte, flags=re.S)
    return re.sub(r"^\s*//.*$", "", fonte, flags=re.M)


# `innerHTML` legitimo: desenho inicial da casca, estado vazio e estado de erro.
# Nenhum dos tres acontece por leitura. O teto por arquivo e um numero, e nao uma
# regra semantica, de proposito: contar e verificavel, e uma atribuicao a mais
# obriga quem a escreveu a passar por aqui e justificar. Um guarda que tenta
# adivinhar a intencao do codigo acaba aceitando qualquer coisa.
ATRIBUICOES_PERMITIDAS = {
    # --- convertidos para patch por linha ---------------------------------
    "armazenamento.js": 6,   # casca + prune (dry-run, confirmacao, resultado) + vazio + erro
    "capacidade.js": 2,      # casca + erro da tela inteira
    "config.js": 3,          # skeleton + casca + erro
    "containers.js": 1,      # casca
    "drift.js": 3,           # skeleton + casca + erro
    "eventos.js": 2,         # casca + erro
    "ingress.js": 1,         # casca
    "logs.js": 3,            # casca + dois estados de erro do tail
    "metricas.js": 3,        # casca do host/stack + casca do container + erro
    "stacks.js": 1,          # casca
    "attention.js": 1,       # casca
    "auditoria.js": 1,       # casca
    "projects.js": 1,        # casca
    "tarefas.js": 1,         # casca
    # --- PENDENCIA declarada (doc 13 §pendencias) -------------------------
    # Estas quatro ainda redesenham por `innerHTML` quando o dado muda. Ficam
    # fora de todo preset padrao (decisao do doc 14), entao so aparecem se o
    # operador as acrescentar pelo Personalizar — e por isso a conversao para
    # patch por linha foi adiada em vez de feita pela metade.
    #
    # O que ja vale para elas: `redesenharSeMudou` compara a assinatura do
    # payload, entao a leitura de 30s so toca no DOM quando o dado mudou de
    # fato. Numa tela de leitura isso e o caso raro.
    "backend.js": 4,
    "executivo.js": 3,
    "plantao.js": 6,
    "topologia.js": 3,
}

# As quatro acima nao podem ganhar mais. Baixar estes numeros e o trabalho
# pendente; subi-los e regressao.
PENDENTES = {"backend.js", "executivo.js", "plantao.js", "topologia.js"}


@pytest.mark.parametrize("arquivo", MODULOS, ids=lambda p: p.name)
def test_innerHTML_so_no_desenho_inicial_e_nos_estados_vazio_e_erro(arquivo):
    """Aceite do doc 13: `grep` por innerHTML nos modulos so encontra desenho
    inicial e estados vazio/erro."""
    fonte = _sem_comentarios(arquivo.read_text())
    n = len([l for l in fonte.splitlines() if ".innerHTML =" in l or ".innerHTML=" in l])
    teto = ATRIBUICOES_PERMITIDAS.get(arquivo.name, 0)
    assert n <= teto, (
        f"{arquivo.name} tem {n} atribuicoes de innerHTML, teto {teto} — "
        "leitura tem de virar patch, nao redesenho"
    )


@pytest.mark.parametrize("nome", sorted(PENDENTES))
def test_telas_pendentes_redesenham_so_quando_o_dado_muda(nome):
    """Enquanto nao viram patch, pelo menos nao repintam por nada."""
    fonte = _sem_comentarios((JS / "screens" / nome).read_text())
    assert "redesenharSeMudou" in fonte or "assinatura" in fonte, (
        f"{nome} redesenha a cada leitura mesmo com o payload igual"
    )


def test_nenhum_modulo_cria_setInterval_proprio():
    """Um relogio so (doc 13 §4). Seis relogios independentes deixam os piscas
    desalinhados e cada um tem de lembrar de pausar com a aba oculta."""
    alvos = MODULOS + [JS / "main.js", JS / "commands.js", JS / "kernel" / "app.js"]
    for arquivo in alvos:
        fonte = _sem_comentarios(arquivo.read_text())
        assert "setInterval" not in fonte, (
            f"{arquivo.name} criou um setInterval proprio; assine o relogio "
            "compartilhado com um periodo multiplo de TICK_MS"
        )


def test_o_relogio_e_o_unico_dono_de_setInterval():
    fonte = _sem_comentarios((JS / "kernel" / "relogio.js").read_text())
    assert fonte.count("setInterval") == 1


def test_css_desliga_movimento_com_prefers_reduced_motion():
    """Movimento periferico e gatilho documentado de enxaqueca vestibular, e um
    cockpit fica aberto o dia inteiro."""
    fonte = (CSS / "components.css").read_text()
    assert "@media (prefers-reduced-motion: reduce)" in fonte
    bloco = fonte.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    assert "animation-duration:.001ms !important" in bloco
    assert "transition-duration:.001ms !important" in bloco


def test_css_traz_o_contrato_visual_do_prototipo():
    """Os numeros sao do `Cockpit Vivo Completo.dc.html`, nao escolhidos aqui."""
    fonte = (CSS / "components.css").read_text()
    assert "--t-hover:140ms" in fonte, "hover fora do contrato de 140ms"
    assert "--t-valor:700ms" in fonte, "barra fora do contrato de .7s"
    assert "--t-flash:900ms" in fonte, "flash fora do contrato de 0,9s"
    assert "--t-vivo:2200ms" in fonte, "pulso/varredura fora do contrato de 2,2s"
    assert "cubic-bezier(.22,1,.36,1)" in (CSS / "themes.css").read_text()


def test_hidden_esconde_de_verdade():
    """O JS esconde e revela por `hidden` — sempre o mesmo no, nunca um no novo.

    A regra do navegador para `[hidden]` e `display:block`, entao qualquer
    classe com `display:flex` a vence em silencio: o no fica marcado como
    escondido e continua na tela.
    """
    assert "[hidden]{display:none !important}" in (CSS / "base.css").read_text()


def test_nenhuma_cor_de_severidade_montada_no_js():
    """A paleta vivia em `style=background:${color}` nos cartoes de achado e nao
    acompanhava a troca de tema. Cor e sinal, e sinal mora no CSS."""
    convertidos = [a for a in MODULOS if a.name not in PENDENTES]
    for arquivo in convertidos:
        fonte = _sem_comentarios(arquivo.read_text())
        assert "border-left:3px solid" not in fonte, f"{arquivo.name} pinta severidade no JS"
        assert 'style="background:' not in fonte, f"{arquivo.name} monta cor inline"
