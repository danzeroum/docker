"""Guarda: doc de registro nao cita rota nem arquivo que nao existe.

Nasceu de um script rodado a mao antes de commitar a PR #31, que na PRIMEIRA
execucao achou duas afirmacoes falsas: o `busca_router` do B5 nao morava num
`app/routers/logs_busca.py`, e o screen map citava esse arquivo inexistente.

Documento de registro que mente sobre onde o codigo esta e pior que registro
nenhum, e era o unico artefato do ciclo sem nada que o conferisse. Um script que
alguem lembra de rodar nao e guarda; guarda e o que falha no CI.

## O que conta como citacao

- **rota**: `/api/...` ou `/metrics` em qualquer lugar da linha;
- **caminho**: `app/...`, `tests/...`, `docs/...`, `scripts/...` com extensao ou
  terminando em `*`.

Referencias como "doc 09 §C" nao casam de proposito — nao tem extensao, e nao
sao caminho de arquivo.

## Escopo: os quatro docs de REGISTRO

Os docs 01 e 08 a 13 sao propostas e contratos: falam de endpoints que ainda nao
existiam quando foram escritos, e alguns que nunca vao existir porque a ideia foi
recusada. Varre-los produziria dezenas de achados corretos e inuteis — e a licao
da Sprint 3 e que guarda barulhento e guarda desligado.

## Allowlist — VISIVEL na renderizacao

Uma linha propria, em codigo inline ou blockquote:

    `guard-docs-ok: /api/capabilities — desenho recusado na 2a, a rota nunca existiu`

Ate a PR #31 o marcador era comentario HTML. Funcionava para o guarda, que le o
fonte — e falhava para o leitor, que e quem o motivo existe para servir: o
GitHub OCULTA comentario HTML tanto no .md do repo quanto no corpo de PR. A
pessoa lia a citacao de uma rota inexistente sem nada explicando por que ela
esta ali. O marcador so cumpre a funcao se aparecer onde a citacao aparece.

Comentario HTML na sintaxe antiga **nao conta como allowlist** — e denunciado,
com a forma nova na mensagem.

Duas propriedades que o formato novo permite e o antigo nao permitia:

**O marcador nomeia o ALVO.** Isenta aquele alvo, e nao a linha inteira: uma
linha com duas citacoes, uma marcada, continua reportando a outra.

**Marcador orfao e falha.** Se o alvo nomeado nao e citado em ate %d linhas de
distancia, o marcador esta morto — sobrou de uma edicao anterior. Allowlist
morta acumula, e uma allowlist que ninguem poda vira a lista de tudo o que o
guarda nao olha mais.

Nunca por arquivo inteiro, e nunca implicitamente. Em particular, **bloco de
codigo nao e excecao**: um prompt XML colado no doc citando uma rota futura
precisa de marcador como qualquer outra linha. Isentar ``` por ser ``` abriria o
buraco exato pelo qual a proxima mentira entraria — colada de outro lugar,
dentro de uma cerca.
"""

import difflib
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PACOTE = RAIZ / "docs" / "handoff_cockpit_completo"

DOCS_DE_REGISTRO = [
    PACOTE / "docs" / "00-decisoes-de-revisao.md",
    PACOTE / "docs" / "14-plano-consolidado.md",
    PACOTE / "github.md",
    PACOTE / "LEIA-ME.md",
]

RE_ROTA = re.compile(r"(?<![\w/])(/api/[A-Za-z0-9_\-{}/]*|/metrics)\b")
# A crase NAO entra no lookbehind: `app/db.py` entre crases e a forma MAIS comum
# de citar arquivo em prosa, e exclui-la deixava justamente o caso mais frequente
# sem cobertura. O guarda descobriu isso em si mesmo — a secao do doc 00 que
# explica este teste cita `app/routers/logs_busca.py` como exemplo do bug, e a
# primeira versao passou batido por ela.
RE_CAMINHO = re.compile(
    r"(?<![\w./])((?:app|tests|docs|scripts)/[A-Za-z0-9_\-./]*(?:\.[A-Za-z0-9]+|/\*|\*))"
)

# Distancia maxima entre o marcador e a citacao que ele isenta. Tres linhas
# cobrem "logo antes" e "logo depois" com uma linha em branco no meio — o que
# uma tabela ou um paragrafo produzem naturalmente — sem deixar um marcador
# isentar algo do outro lado da secao.
JANELA = 3

# Linha PROPRIA, em codigo inline ou blockquote. `^...$` e o que garante o
# "linha propria": marcador no fim de uma frase nao vale, porque ali ele volta a
# competir com o texto em vez de anunciar-se.
RE_MARCADOR = re.compile(
    # `motivo` aceita vazio de proposito: um marcador pela metade tem de ser
    # DENUNCIADO como marcador sem motivo, e nao virar prosa em silencio.
    r"^\s*>?\s*`?\s*guard-docs-ok:\s*(?P<alvo>\S+)\s*(?:—|–|--)\s*(?P<motivo>.*?)\s*`?\s*$"
)

# A sintaxe antiga, so para DENUNCIAR: invisivel na renderizacao.
RE_MARCADOR_ANTIGO = re.compile(r"<!--\s*/?docs-ref-ok(?:-bloco)?\s*:?[^>]*-->")


# --- inventario de rotas: do app MONTADO, nao de grep -----------------------

_SONDA = """
import json, os, sys
sys.path.insert(0, %r)
os.environ["ENABLE_ACTIONS"] = "1"
os.environ["ENABLE_TERMINAL"] = "1"
os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")
from app import app
print(json.dumps(sorted({r.path for r in app.routes if getattr(r, "path", None)})))
"""


def _normaliza(rota: str) -> str:
    """`/api/containers/{container_id}/history` e `/api/containers/{id}/history`
    sao a mesma rota. O nome do parametro e escolha do autor da funcao; o doc nao
    tem por que segui-lo."""
    return re.sub(r"\{[^}]*\}", "{}", rota.rstrip("/")) or "/"


def rotas_montadas() -> set:
    """Rotas do app REAL, com as duas flags de feature LIGADAS.

    Ligadas porque a barreira do B10 decide no import: com `ENABLE_ACTIONS=0` as
    rotas de mutacao nao sao registradas, e o guarda acusaria `POST /api/prune`
    como inexistente — falso positivo, e do tipo pior, porque a rota existe em
    producao. A suite roda com a flag desligada por padrao, entao o inventario
    vem de um SUBPROCESSO hermetico: recarregar modulos no processo do pytest
    vaza estado e deixa threads do aiosqlite vivas.

    Do app montado e nao de grep no codigo: um `@router.get` comentado, ou um
    router que ninguem incluiu no `app.py`, some daqui — como tem de sumir. A
    fonte da verdade e o que o FastAPI serve.
    """
    r = subprocess.run(
        [sys.executable, "-c", _SONDA % str(RAIZ / "app")],
        capture_output=True, text=True, timeout=120, cwd=str(RAIZ),
    )
    assert r.returncode == 0, f"o app nao subiu para inventariar rotas:\n{r.stderr}"
    return {_normaliza(p) for p in json.loads(r.stdout)}


# --- leitura dos docs ------------------------------------------------------

def _alvo_verificavel(alvo: str) -> bool:
    """O alvo tem de ser algo que o guarda saiba conferir: uma rota ou um caminho.

    E o que separa marcador de PROSA SOBRE marcador. A propria secao do doc 00
    que documenta esta sintaxe mostra `guard-docs-ok: <alvo> — <motivo>`, e sem
    esta regra o `<alvo>` literal virava um marcador vivo, orfao por construcao —
    o guarda acusava a documentacao de si mesmo.

    Alvo que nao casa fica INERTE, e nao isenta nada: se alguem errar o alvo por
    typo, a citacao que ele queria proteger volta a falhar, e o erro aparece.
    """
    return bool(RE_ROTA.fullmatch(alvo) or RE_CAMINHO.fullmatch(alvo))


def marcadores(texto: str):
    """(linha, alvo, motivo) de cada marcador visivel e verificavel."""
    achados = []
    for i, linha in enumerate(texto.splitlines(), 1):
        m = RE_MARCADOR.match(linha)
        if not m:
            continue
        alvo = m.group("alvo")
        if not _alvo_verificavel(alvo):
            continue
        if alvo.startswith("/"):
            alvo = _normaliza(alvo)
        achados.append((i, alvo, m.group("motivo").strip()))
    return achados


def marcadores_antigos(texto: str):
    """Linhas com a sintaxe de comentario HTML — invisivel, logo invalida."""
    return [i for i, linha in enumerate(texto.splitlines(), 1)
            if RE_MARCADOR_ANTIGO.search(linha)]


def citacoes(texto: str):
    """(linha, tipo, alvo) de cada citacao.

    A linha do MARCADOR nao conta como citacao — se contasse, um marcador com
    alvo inventado se auto-satisfaria e nunca seria denunciado como orfao. Foi a
    primeira coisa que quebrou ao trocar o formato.
    """
    linhas_de_marcador = {i for i, _, _ in marcadores(texto)}
    achadas = []
    for i, linha in enumerate(texto.splitlines(), 1):
        if i in linhas_de_marcador:
            continue
        for m in RE_ROTA.finditer(linha):
            achadas.append((i, "rota", _normaliza(m.group(1))))
        for m in RE_CAMINHO.finditer(linha):
            achadas.append((i, "caminho", m.group(1).rstrip(".,;:)")))
    return achadas


def _caminho_existe(alvo: str) -> bool:
    if "*" in alvo:
        # `app/routers/*` e `app/findings/rules/*`: vale se o diretorio existe e
        # tem conteudo. Glob vazio e tao mentira quanto caminho inexistente.
        base = RAIZ / alvo.split("*")[0]
        return base.is_dir() and any(base.iterdir())
    return (RAIZ / alvo).exists()


def problemas(texto: str, rotas: set, rotulo: str = "doc"):
    """Lista de achados, cada um com doc:linha, alvo e sugestao."""
    saida = []
    todas = citacoes(texto)

    for linha in marcadores_antigos(texto):
        saida.append({
            "onde": f"{rotulo}:{linha}",
            "tipo": "marcador-antigo",
            "alvo": "comentario HTML nao vale como allowlist — o GitHub o oculta",
            "sugestao": "`guard-docs-ok: <alvo> — <motivo>` numa linha propria",
        })

    # Um marcador isenta o ALVO que nomeia, nas linhas vizinhas — nao a linha
    # inteira, e nao o arquivo.
    isentos = set()
    for linha_marcador, alvo, motivo in marcadores(texto):
        if not motivo:
            saida.append({
                "onde": f"{rotulo}:{linha_marcador}",
                "tipo": "marcador-sem-motivo",
                "alvo": alvo,
                "sugestao": "`guard-docs-ok: <alvo> — <motivo>`",
            })
            continue
        vizinhas = [(l, a) for (l, _t, a) in todas
                    if a == alvo and abs(l - linha_marcador) <= JANELA]
        if not vizinhas:
            # Aponta o MARCADOR, e nao uma citacao: o problema e a allowlist
            # morta, e a citacao que a justificava ja nao esta la.
            saida.append({
                "onde": f"{rotulo}:{linha_marcador}",
                "tipo": "marcador-orfao",
                "alvo": f"{alvo} (nao citado em {JANELA} linhas)",
                "sugestao": "remova o marcador ou aproxime-o da citacao",
            })
            continue
        isentos |= set(vizinhas)

    caminhos_conhecidos = None
    for linha, tipo, alvo in todas:
        if (linha, alvo) in isentos:
            continue
        if tipo == "rota":
            if alvo in rotas:
                continue
            perto = difflib.get_close_matches(alvo, sorted(rotas), n=1, cutoff=0.6)
        else:
            if _caminho_existe(alvo):
                continue
            if caminhos_conhecidos is None:
                caminhos_conhecidos = _inventario_de_caminhos()
            perto = difflib.get_close_matches(alvo, caminhos_conhecidos, n=1, cutoff=0.6)
        saida.append({
            "onde": f"{rotulo}:{linha}",
            "tipo": tipo,
            "alvo": alvo,
            "sugestao": perto[0] if perto else "",
        })
    return saida


def _inventario_de_caminhos():
    achados = []
    for base in ("app", "tests", "scripts"):
        raiz = RAIZ / base
        if not raiz.is_dir():
            continue
        for p in raiz.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                achados.append(str(p.relative_to(RAIZ)))
    return achados


def _mensagem(achados):
    linhas = []
    for a in achados:
        rotulo = {
            "rota": "rota inexistente",
            "caminho": "caminho inexistente",
            "marcador-orfao": "ALLOWLIST MORTA",
            "marcador-antigo": "marcador em sintaxe antiga",
            "marcador-sem-motivo": "marcador sem motivo",
        }.get(a["tipo"], a["tipo"])
        sug = f"  — {a['sugestao']}" if a["sugestao"] else ""
        linhas.append(f"{a['onde']}  {rotulo}: {a['alvo']}{sug}")
    return (
        "\n\nDoc de registro citando alvo que nao existe:\n\n"
        + "\n".join(linhas)
        + "\n\nCorrija a citacao, ou marque-a numa linha propria e VISIVEL:\n"
        "  `guard-docs-ok: <alvo> — <motivo>`\n"
    )


# --- o guarda sobre os docs reais ------------------------------------------

@pytest.fixture(scope="module")
def rotas():
    return rotas_montadas()


@pytest.mark.parametrize("doc", DOCS_DE_REGISTRO, ids=lambda p: p.name)
def test_doc_de_registro_nao_cita_alvo_inexistente(doc, rotas):
    assert doc.exists(), f"doc de registro sumiu: {doc}"
    achados = problemas(doc.read_text(), rotas, rotulo=str(doc.relative_to(RAIZ)))
    assert not achados, _mensagem(achados)


def test_o_inventario_vem_do_app_montado_e_nao_esta_vazio(rotas):
    """Inventario vazio faria o guarda passar sempre — e passar sempre e o modo
    mais silencioso de um guarda morrer."""
    assert len(rotas) > 20, f"so {len(rotas)} rotas: a sonda provavelmente falhou"
    assert "/api/overview" in rotas


def test_a_barreira_do_b10_nao_gera_falso_positivo(rotas):
    """A suite roda com `ENABLE_ACTIONS=0`, e nesse estado as rotas de mutacao
    nem sao registradas. Sem a sonda com a flag LIGADA, o guarda acusaria
    `POST /api/prune` — que existe em producao. Foi o segundo achado da primeira
    execucao, e era bug do guarda, nao do doc."""
    assert "/api/prune" in rotas


# --- o guarda sobre si mesmo ----------------------------------------------

ROTAS_FALSAS = {"/api/overview", "/api/storage", "/api/drift", "/api/prune"}


def test_acusa_rota_inexistente_com_doc_linha_e_sugestao():
    texto = "linha um\n| `GET /api/stor` | B1 | tabela |\n"
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert len(achados) == 1
    assert achados[0]["onde"] == "fake.md:2"
    assert achados[0]["alvo"] == "/api/stor"
    assert achados[0]["sugestao"] == "/api/storage", "sem sugestao o achado custa uma busca"


def test_acusa_caminho_inexistente():
    texto = "veja app/routers/logs_busca.py para a busca\n"
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert [a["alvo"] for a in achados] == ["app/routers/logs_busca.py"]
    assert achados[0]["sugestao"], "havia arquivo parecido e nao foi sugerido"


def test_caminho_entre_crases_tambem_e_conferido():
    """Buraco da primeira versao: a crase estava no lookbehind, e citar arquivo
    entre crases — a forma mais comum em prosa — nao era conferido. O guarda
    achou isso em si mesmo, na secao do doc 00 que o documenta."""
    texto = "o `busca_router` vive em `app/routers/logs_busca.py`\n"
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert [a["alvo"] for a in achados] == ["app/routers/logs_busca.py"]


def test_router_renomeado_de_lugar_e_acusado_no_mesmo_pr(tmp_path):
    """Aceite do bloco. Simula o renomeio: o doc aponta para onde o arquivo
    ESTAVA, e o guarda acusa antes de o PR fechar."""
    doc = "| Logs | app/routers/containers.py (`busca_router`) |\n"
    assert problemas(doc, ROTAS_FALSAS, rotulo="d.md") == []
    doc_apos_renomeio = "| Logs | app/routers/logs_busca.py (`busca_router`) |\n"
    achados = problemas(doc_apos_renomeio, ROTAS_FALSAS, rotulo="d.md")
    assert len(achados) == 1 and achados[0]["tipo"] == "caminho"


def test_rota_valida_e_caminho_valido_passam():
    texto = ("`GET /api/overview` e `GET /api/drift`, em app/drift.py\n"
             "e o glob app/routers/* tambem\n")
    assert problemas(texto, ROTAS_FALSAS, rotulo="fake.md") == []


def test_parametro_de_rota_casa_por_forma_e_nao_por_nome():
    texto = "`GET /api/containers/{id}/history`\n"
    rotas = {_normaliza("/api/containers/{container_id}/history")}
    assert problemas(texto, rotas, rotulo="fake.md") == []


# --- allowlist visivel ------------------------------------------------------

def test_marcador_antes_da_citacao_isenta():
    texto = ("`guard-docs-ok: /api/capabilities — desenho recusado na 2a`\n"
             "um endpoint `/api/capabilities` separado custaria um fetch por poll\n")
    assert problemas(texto, ROTAS_FALSAS, rotulo="fake.md") == []


def test_marcador_depois_da_citacao_isenta():
    texto = ("um endpoint `/api/capabilities` separado custaria um fetch por poll\n"
             "`guard-docs-ok: /api/capabilities — desenho recusado na 2a`\n")
    assert problemas(texto, ROTAS_FALSAS, rotulo="fake.md") == []


def test_marcador_em_blockquote_isenta():
    """Blockquote e a outra forma que RENDERIZA — e que destaca o motivo."""
    texto = ("> guard-docs-ok: /api/capabilities — desenho recusado na 2a\n"
             "`/api/capabilities` nunca existiu\n")
    assert problemas(texto, ROTAS_FALSAS, rotulo="fake.md") == []


def test_marcador_isenta_o_alvo_e_nao_a_linha_inteira():
    """Uma linha com duas citacoes, uma marcada, continua reportando a outra —
    o formato antigo isentava a linha e escondia a segunda."""
    texto = ("`guard-docs-ok: /api/capabilities — desenho recusado`\n"
             "`/api/capabilities` e `/api/tambem_inventada` na mesma linha\n")
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert [a["alvo"] for a in achados] == ["/api/tambem_inventada"]


def test_marcador_de_caminho_tambem_vale():
    texto = ("`guard-docs-ok: app/routers/logs_busca.py — nunca existiu, e o exemplo do bug`\n"
             "o `busca_router` nao morava em `app/routers/logs_busca.py`\n")
    assert problemas(texto, ROTAS_FALSAS, rotulo="fake.md") == []


def test_marcador_sem_motivo_nao_isenta():
    """Sem motivo, a proxima pessoa fica sem saber por que aquilo aponta para o
    vazio — e "ok" nao conta como resposta."""
    texto = ("`guard-docs-ok: /api/inventada —`\n"
             "`/api/inventada`\n")
    tipos = [a["tipo"] for a in problemas(texto, ROTAS_FALSAS, rotulo="fake.md")]
    assert "marcador-sem-motivo" in tipos, "marcador pela metade passou como prosa"
    assert "rota" in tipos, "a citacao ficou isenta sem motivo"


def test_placeholder_da_documentacao_nao_e_marcador_vivo():
    """A secao do doc 00 que documenta esta sintaxe mostra `<alvo>` literal. Sem
    a regra do alvo verificavel, ele virava marcador orfao por construcao — o
    guarda acusava a documentacao de si mesmo, e foi o que aconteceu."""
    texto = "`guard-docs-ok: <alvo> — <motivo>`\n"
    assert problemas(texto, ROTAS_FALSAS, rotulo="fake.md") == []


def test_alvo_com_typo_fica_inerte_e_a_citacao_volta_a_falhar():
    """Inerte nao e perdao: o alvo errado nao isenta, entao a citacao que ele
    queria proteger reaparece no relatorio."""
    texto = ("`guard-docs-ok: api/capabilities — faltou a barra`\n"
             "`/api/capabilities`\n")
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert [a["tipo"] for a in achados] == ["rota"]


# --- allowlist morta --------------------------------------------------------

def test_marcador_orfao_e_falha_apontando_o_marcador():
    """Aceite do delta: o problema e a allowlist morta, e a citacao que a
    justificava ja nao esta la — apontar uma citacao seria apontar o lugar
    errado."""
    texto = ("`guard-docs-ok: /api/inventada — sobrou de uma edicao anterior`\n"
             "linha 2\nlinha 3\nlinha 4\nlinha 5\n"
             "`/api/inventada` longe demais para justificar o marcador\n")
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert achados[0]["tipo"] == "marcador-orfao"
    assert achados[0]["onde"] == "fake.md:1", "apontou a citacao em vez do marcador"


def test_marcador_de_alvo_que_nao_existe_no_doc_e_orfao():
    texto = "`guard-docs-ok: /api/fantasma — motivo qualquer`\ntexto sem citacao nenhuma\n"
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert [a["tipo"] for a in achados] == ["marcador-orfao"]


def test_marcador_nao_se_auto_satisfaz():
    """A linha do marcador CONTEM o alvo. Se ela contasse como citacao, um
    marcador inventado se justificaria sozinho e nunca seria podado — foi a
    primeira coisa que quebrou ao trocar o formato."""
    texto = "`guard-docs-ok: /api/fantasma — motivo`\n"
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert len(achados) == 1 and achados[0]["tipo"] == "marcador-orfao"


def test_marcador_dentro_da_janela_de_tres_linhas_vale():
    texto = ("`guard-docs-ok: /api/inventada — motivo`\n"
             "linha 2\nlinha 3\n"
             "`/api/inventada` a tres linhas\n")
    assert problemas(texto, ROTAS_FALSAS, rotulo="fake.md") == []


# --- a sintaxe antiga nao vale ---------------------------------------------

def test_comentario_html_nao_conta_como_allowlist():
    """Aceite do delta: funcionava para o guarda e falhava para o leitor — o
    GitHub oculta comentario HTML no .md do repo e no corpo de PR."""
    texto = ("<!-- docs-ref-ok: motivo que ninguem ve -->\n"
             "`/api/inventada`\n")
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    tipos = [a["tipo"] for a in achados]
    assert "marcador-antigo" in tipos, "a sintaxe antiga passou em silencio"
    assert "rota" in tipos, "a citacao ficou isenta por um marcador invisivel"


def test_a_denuncia_da_sintaxe_antiga_traz_a_forma_nova():
    texto = "<!-- docs-ref-ok: x -->\n"
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert "guard-docs-ok:" in achados[0]["sugestao"]


def test_bloco_antigo_tambem_e_denunciado():
    texto = "<!-- docs-ref-ok-bloco: motivo -->\n`/api/inventada`\n<!-- /docs-ref-ok-bloco -->\n"
    tipos = [a["tipo"] for a in problemas(texto, ROTAS_FALSAS, rotulo="fake.md")]
    assert tipos.count("marcador-antigo") == 2
    assert "rota" in tipos, "o bloco antigo ainda estava isentando"


def test_bloco_de_codigo_sozinho_nao_isenta():
    """Cerca de codigo NAO e excecao implicita: um prompt colado de outro lugar,
    citando rota que nunca existiu, entraria exatamente por ai."""
    texto = "```xml\n<task>GET `/api/inventada` faz X</task>\n```\n"
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert [a["alvo"] for a in achados] == ["/api/inventada"]


def test_marcador_no_fim_de_uma_frase_nao_vale():
    """"Linha propria" e requisito: no fim de uma frase o marcador volta a
    competir com o texto em vez de anunciar-se."""
    texto = "a rota `/api/inventada` sumiu `guard-docs-ok: /api/inventada — motivo`\n"
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    # Nada isento: a linha nao e marcador, entao ela e varrida como qualquer
    # outra — e a rota aparece nela duas vezes, na prosa e no pseudo-marcador.
    assert achados and all(a["tipo"] == "rota" for a in achados)
    assert all(a["alvo"] == "/api/inventada" for a in achados)


# --- ausencia de ruido -----------------------------------------------------

def test_referencia_a_doc_por_numero_nao_e_caminho():
    """"doc 09 §C" e "docs/12" sao referencias a documento, nao a arquivo."""
    texto = "ver docs 09 §C e o doc 12 para o roteiro; docs/12 tem o passo a passo\n"
    assert problemas(texto, ROTAS_FALSAS, rotulo="fake.md") == []


def test_url_externa_nao_vira_rota():
    texto = ("https://hub.docker.com/v2/repositories/library/nginx/tags/1.25\n"
             "https://outro.servico.com/api/coisa\n")
    assert problemas(texto, ROTAS_FALSAS, rotulo="fake.md") == []


def test_url_do_github_nao_vira_caminho_de_arquivo():
    """O doc 00 ja linka PRs; um link para `blob/main/app/...` viria a seguir, e
    o caminho ali dentro nao e uma citacao ao repo local."""
    texto = "veja https://github.com/danzeroum/docker/blob/main/app/db.py\n"
    assert problemas(texto, ROTAS_FALSAS, rotulo="fake.md") == []


def test_pontuacao_no_fim_da_frase_nao_entra_no_caminho():
    texto = "o calculo vive em app/drift.py, e a rota em app/routers/drift.py.\n"
    assert problemas(texto, ROTAS_FALSAS, rotulo="fake.md") == []
