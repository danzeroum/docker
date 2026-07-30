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

## Allowlist

Por MARCADOR com motivo no proprio documento, no padrao do
`# schema-literal-ok:` do guarda de schema:

    <!-- docs-ref-ok: motivo -->                     (mesma linha ou a de cima)
    <!-- docs-ref-ok-bloco: motivo --> ... <!-- /docs-ref-ok-bloco -->

Nunca por arquivo inteiro, e nunca implicitamente. Em particular, **bloco de
codigo nao e excecao**: um prompt XML colado no doc citando uma rota futura
precisa do marcador como qualquer outra linha. Isentar ``` por ser ``` abriria o
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

RE_MARCADOR = re.compile(r"<!--\s*docs-ref-ok:\s*(?P<motivo>[^>]*?)\s*-->")
RE_BLOCO_ABRE = re.compile(r"<!--\s*docs-ref-ok-bloco:\s*(?P<motivo>[^>]*?)\s*-->")
RE_BLOCO_FECHA = re.compile(r"<!--\s*/docs-ref-ok-bloco\s*-->")


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

def _linhas_isentas(texto: str):
    """`(isentas, aberto_em)` — linhas cobertas por marcador com motivo.

    Marcador sem motivo nao isenta nada: a proxima pessoa precisa saber POR QUE
    aquela citacao pode apontar para o vazio, e "ok" nao conta como resposta.

    `aberto_em` denuncia bloco que abriu e nunca fechou. Sem isso, um
    `<!-- docs-ref-ok-bloco: ... -->` sem o fechamento — um typo, uma edicao pela
    metade — desligaria o guarda do resto do arquivo em silencio, que e o modo
    como um guarda morre sem ninguem notar.
    """
    isentas = set()
    dentro_de_bloco = False
    aberto_em = 0
    for i, linha in enumerate(texto.splitlines(), 1):
        if RE_BLOCO_FECHA.search(linha):
            dentro_de_bloco = False
            isentas.add(i)
            continue
        abre = RE_BLOCO_ABRE.search(linha)
        if abre:
            dentro_de_bloco = bool(abre.group("motivo"))
            if dentro_de_bloco:
                aberto_em = i
            isentas.add(i)
            continue
        if dentro_de_bloco:
            isentas.add(i)
            continue
        m = RE_MARCADOR.search(linha)
        if m and m.group("motivo"):
            isentas.add(i)
            # A linha de baixo tambem: numa celula de tabela ou numa linha
            # longa, o comentario no fim fica ilegivel, e por-lo em cima e a
            # forma que nao estraga o texto.
            isentas.add(i + 1)
    return isentas, (aberto_em if dentro_de_bloco else 0)


def citacoes(texto: str):
    """(linha, tipo, alvo) de cada citacao NAO isenta."""
    isentas, _ = _linhas_isentas(texto)
    achadas = []
    for i, linha in enumerate(texto.splitlines(), 1):
        if i in isentas:
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
    _, aberto_em = _linhas_isentas(texto)
    if aberto_em:
        saida.append({
            "onde": f"{rotulo}:{aberto_em}",
            "tipo": "bloco",
            "alvo": "docs-ref-ok-bloco sem fechamento — isentaria o resto do arquivo",
            "sugestao": "<!-- /docs-ref-ok-bloco -->",
        })
    caminhos_conhecidos = None
    for linha, tipo, alvo in citacoes(texto):
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
        sug = f"  — mais proximo existente: {a['sugestao']}" if a["sugestao"] else ""
        linhas.append(f"{a['onde']}  {a['tipo']} inexistente: {a['alvo']}{sug}")
    return (
        "\n\nDoc de registro citando alvo que nao existe:\n\n"
        + "\n".join(linhas)
        + "\n\nCorrija a citacao, ou marque a linha com o motivo:\n"
        "  <!-- docs-ref-ok: <motivo> -->\n"
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


# --- allowlist -------------------------------------------------------------

def test_marcador_na_mesma_linha_isenta():
    texto = "um endpoint `/api/capabilities` custaria um fetch <!-- docs-ref-ok: desenho recusado -->\n"
    assert problemas(texto, ROTAS_FALSAS, rotulo="fake.md") == []


def test_marcador_na_linha_de_cima_isenta():
    texto = ("<!-- docs-ref-ok: rota historica, removida na F5 -->\n"
             "| `GET /api/antiga` | tabela longa demais para comentario no fim |\n")
    assert problemas(texto, ROTAS_FALSAS, rotulo="fake.md") == []


def test_marcador_sem_motivo_nao_isenta():
    """`<!-- docs-ref-ok: -->` e o mesmo que nao explicar nada, e a proxima
    pessoa fica sem saber por que aquilo aponta para o vazio."""
    texto = "`/api/inventada` <!-- docs-ref-ok: -->\n"
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert len(achados) == 1


def test_bloco_isenta_o_intervalo_e_so_ele():
    texto = (
        "`/api/fora_de_cima`\n"
        "<!-- docs-ref-ok-bloco: prompt XML de bloco futuro -->\n"
        "```xml\n"
        "<task>GET `/api/futura` faz X</task>\n"
        "```\n"
        "<!-- /docs-ref-ok-bloco -->\n"
        "`/api/fora_de_baixo`\n"
    )
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert [a["alvo"] for a in achados] == ["/api/fora_de_cima", "/api/fora_de_baixo"]


def test_bloco_aberto_e_nunca_fechado_e_denunciado():
    """Um typo no fechamento desligaria o guarda do resto do arquivo em
    silencio, que e o modo como um guarda morre sem ninguem notar."""
    texto = ("<!-- docs-ref-ok-bloco: prompt futuro -->\n"
             "`/api/futura`\n"
             "`/api/tambem_inventada`\n")
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert achados[0]["tipo"] == "bloco"
    assert achados[0]["onde"] == "fake.md:1"


def test_bloco_de_codigo_sozinho_nao_isenta():
    """Cerca de codigo NAO e excecao implicita: um prompt colado de outro lugar,
    citando rota que nunca existiu, entraria exatamente por ai."""
    texto = "```xml\n<task>GET `/api/inventada` faz X</task>\n```\n"
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert [a["alvo"] for a in achados] == ["/api/inventada"]


def test_allowlist_e_por_linha_e_nunca_por_arquivo():
    """Um marcador nao pode calar o documento inteiro — foi a regra do guarda de
    schema, e vale igual aqui."""
    texto = ("<!-- docs-ref-ok: motivo bom -->\n"
             "`/api/isenta`\n"
             "`/api/nao_isenta`\n")
    achados = problemas(texto, ROTAS_FALSAS, rotulo="fake.md")
    assert [a["alvo"] for a in achados] == ["/api/nao_isenta"]


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
