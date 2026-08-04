"""Contraste do selo de severidade — a aritmetica da WCAG, sobre os tokens reais.

Por que este arquivo existe separado do axe:

O axe so ve o que esta na tela, e `.atn-sev` so entra no DOM quando HA achado
critico. A bancada que mediu contraste antes nao tinha nenhum — media um painel
saudavel — e por isso o selo critico atravessou aquela auditoria inteira sem ser
olhado. Ele reprovava desde sempre: branco sobre `--bad` dava 3.76:1 no tema
cockpit, e o minimo para texto pequeno e 4.5:1.

Apareceu na primeira execucao contra a homologacao, que le o nginx.conf real e
emite dois achados `http_plain` criticos. O mecanismo do par `--sev`/`--sev-fg`
estava certo o tempo todo; errado era o VALOR.

Aqui a conta e feita sobre os tokens do CSS, sem navegador e sem depender de o
alvo estar num estado especifico. E o tipo de trava que nao some quando o
ambiente esta saudavel.
"""
import pathlib
import re

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CSS = RAIZ / "app" / "static" / "css"

BRANCO = (255, 255, 255)

# Fundo da faixa critica. Cravado em components.css e NAO `var(--bad-soft)` — ver o
# comentario de `.faixa-critica`: trocar pelo token derruba dois contrastes que passam.
FAIXA = ((239, 68, 68), 0.10)

# Superficie de cartao por tema, para a faixa lateral de 3px (WCAG 1.4.11).
SURFACE = {"cockpit": "#141f3a", "claro": "#ffffff", "escritorio": "#ffffff"}
BG = {"cockpit": "#0a1020", "claro": "#f1f5f9", "escritorio": "#f8f9fa"}

AA_TEXTO_PEQUENO = 4.5
AA_NAO_TEXTUAL = 3.0


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _luminancia(rgb):
    c = [x / 255 for x in rgb]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def razao(a, b):
    la, lb = _luminancia(a), _luminancia(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _sobre(frente, alfa, fundo):
    return tuple(round(frente[i] * alfa + fundo[i] * (1 - alfa)) for i in range(3))


def _tokens(tema):
    """Le --bad, --bad-strong e --bad-text do bloco daquele tema em themes.css."""
    fonte = (CSS / "themes.css").read_text()
    bloco = re.search(rf'html\[data-tema="{tema}"\]\s*\{{(.*?)\n\}}', fonte, re.S)
    assert bloco, f"bloco do tema {tema} nao encontrado em themes.css"
    corpo = bloco.group(1)
    fora = {}
    for nome in ("bad", "bad-strong", "bad-text"):
        m = re.search(rf"--{nome}\s*:\s*(#[0-9a-fA-F]{{6}})", corpo)
        assert m, f"--{nome} ausente no tema {tema}"
        fora[nome] = m.group(1)
    return fora


TEMAS = ["cockpit", "claro", "escritorio"]


@pytest.mark.parametrize("tema", TEMAS)
def test_selo_critico_carrega_texto_branco(tema):
    """`.atn-sev` em cartao critico: fundo `--bad-strong`, texto #fff.

    Este e o caso que reprovava. Texto de 0.6rem em negrito continua sendo texto
    PEQUENO para a WCAG — 4.5:1, sem a folga de 3:1 do texto grande.
    """
    forte = _hex(_tokens(tema)["bad-strong"])
    r = razao(BRANCO, forte)
    assert r >= AA_TEXTO_PEQUENO, (
        f"tema {tema}: branco sobre --bad-strong da {r:.2f}:1, abaixo de "
        f"{AA_TEXTO_PEQUENO}:1. O selo 'Crítico' fica ilegivel.")


@pytest.mark.parametrize("tema", TEMAS)
def test_rotulo_da_faixa_critica_e_legivel(tema):
    """`.fc-sev`: `--bad-text` sobre o fundo composto da faixa critica."""
    tk = _tokens(tema)
    fundo = _sobre(FAIXA[0], FAIXA[1], _hex(BG[tema]))
    r = razao(_hex(tk["bad-text"]), fundo)
    assert r >= AA_TEXTO_PEQUENO, (
        f"tema {tema}: --bad-text sobre a faixa da {r:.2f}:1, abaixo de "
        f"{AA_TEXTO_PEQUENO}:1.")


@pytest.mark.parametrize("tema", TEMAS)
def test_faixa_lateral_do_cartao_critico_permanece_visivel(tema):
    """`--sev-marca` existe por causa DESTE caso.

    A faixa de 3px do cartao usava `--sev`. Escurecer `--sev` para o texto branco
    caber no selo derrubava a faixa de 4.34:1 para 2.84:1 no tema cockpit — abaixo
    do 3:1 que a WCAG 1.4.11 pede de componente nao textual. Dois papeis com
    exigencias OPOSTAS no mesmo tema: um token so nao serve aos dois.
    """
    marca = _hex(_tokens(tema)["bad"])
    r = razao(marca, _hex(SURFACE[tema]))
    assert r >= AA_NAO_TEXTUAL, (
        f"tema {tema}: --bad sobre --surface da {r:.2f}:1, abaixo de "
        f"{AA_NAO_TEXTUAL}:1. A faixa de severidade some do cartao.")


def test_selo_usa_bad_strong_e_faixa_usa_bad():
    """A separacao dos dois papeis esta no CSS, nao so nesta conta."""
    css = (CSS / "components.css").read_text().replace(" ", "")
    assert "--sev:var(--bad-strong)" in css, (
        "o selo critico voltou a usar --bad como fundo")
    assert "--sev-marca:var(--bad)" in css, (
        "a faixa lateral do cartao critico perdeu o proprio token")
    assert "border-left:3pxsolidvar(--sev-marca," in css, (
        "a faixa lateral voltou a herdar --sev e regride para 2.84:1 no cockpit")
    assert "color:var(--bad-text)" in css, (
        "o rotulo da faixa critica voltou a usar --bad")
