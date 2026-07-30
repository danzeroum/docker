"""Guarda: versão de schema não se escreve como número literal em teste.

O mesmo erro apareceu três vezes em duas sprints — a terceira num teste escrito
por quem já o tinha corrigido nas outras duas. Quando um erro sobrevive a quem
já o consertou, o problema não é atenção; é a falta de um guarda executável.

O sintoma é sempre igual: `assert versao == 9` passa hoje e quebra na próxima
migration, num arquivo que não tem nada a ver com a mudança. E a intenção quase
nunca é "a versão é exatamente 9" — é "o banco está totalmente migrado", que se
escreve `== db.SCHEMA_VERSION`.

Fixture de migração que cria banco numa versão antiga de propósito é legítima e
tem escape: o marcador `# schema-literal-ok: <motivo>` na mesma linha. Por
marcador e não por caminho de arquivo, de propósito — a próxima fixture nasce
documentando por que pode, em vez de herdar isenção por morar na pasta certa.
"""

import pathlib
import re

TESTES = pathlib.Path(__file__).resolve().parent
MARCADOR = "schema-literal-ok:"

# A forma que aconteceu de verdade nao tem "version" do lado esquerdo:
#
#     cur = await db.execute("SELECT MAX(version) FROM schema_version")
#     assert (await cur.fetchone())[0] == 9
#
# O que faz aquela linha ser sobre schema e o SQL acima. Por isso a deteccao e
# por CONTEXTO: uma linha que fala de schema_version abre uma janela curta, e
# comparacao com literal dentro dela e ofensa.
# So `MAX(version)` abre janela: e a pergunta "em que versao o banco esta". Um
# `COUNT(*) FROM schema_version WHERE version = 11` e outra pergunta — conta
# linhas, e comparar o resultado com 1 e legitimo e estavel.
_CONTEXTO = re.compile(r"(?i)MAX\(\s*version\s*\)")
JANELA = 3

# Só IGUALDADE com literal. `>= 10` e piso, nao equivalencia: ele continua
# valendo quando a v13 chegar, e o que este guarda existe para impedir e a
# comparacao que QUEBRA a cada migration.
_COMPARACAO = re.compile(r"(?:==|!=)\s*(\d+)\b")

# E as formas diretas, que valem mesmo fora de janela.
_DIRETA = re.compile(
    r"""(?ix)
    (?: \bversion\b | \bversao\b )
    [^\n=<>!]{0,80}?
    (?:==|!=)
    \s* (\d+)
    """
)

# Qualquer consulta nova encerra a janela do contexto anterior.
_NOVA_QUERY = re.compile(r"\bexecute\s*\(")

# `version=9` como argumento nomeado ou chave nao e comparacao.
_FALSO_POSITIVO = re.compile(r"""(?ix) (version|versao) \s* = \s* \d+ \s* [,)\]}] """)

# Strings completas na propria linha: o literal dentro delas e texto, nao codigo.
_STRING_INLINE = re.compile(r"""('''.*?'''|\"\"\".*?\"\"\"|'[^']*'|\"[^\"]*\")""")


def _linhas_de_codigo(texto: str):
    """Itera (n, codigo, bruta) sem comentarios nem conteudo de string.

    Sem isto o proprio guarda acusaria os exemplos que ele documenta — e um
    guarda que falha sobre a explicacao dele mesmo nao sobrevive a uma semana.
    """
    dentro = False
    delim = None
    for n, bruta in enumerate(texto.splitlines(), 1):
        linha = bruta
        if dentro:
            if delim in linha:
                dentro = False
                linha = linha.split(delim, 1)[1]
            else:
                continue
        # remove strings que abrem E fecham na mesma linha
        linha = _STRING_INLINE.sub('""', linha)
        # sobrou delimitador triplo impar? entao abriu e nao fechou
        for d in ('"""', "'''"):
            if linha.count(d) % 2 == 1:
                dentro = True
                delim = d
                linha = linha.split(d, 1)[0]
                break
        codigo = linha.split("#", 1)[0]
        if codigo.strip():
            yield n, codigo, bruta


_CONSOME = re.compile(r"\bfetchone\b|\bfetchall\b")
_ATRIBUICAO = re.compile(r"^\s*(\w+)\s*=\s*.*fetchone")


def _ofensas(caminho: pathlib.Path):
    """Acha comparacao de versao de schema com literal.

    Rastreia a VARIAVEL em vez de usar janela de linhas. Proximidade era
    imprecisa demais: um `assert findings_before == 12` tres linhas depois da
    consulta de versao virava falso positivo, e falso positivo e o que faz um
    guarda ser desligado.

    O sinal exato e a cadeia: `MAX(version)` -> quem consome aquele cursor ->
    comparacao com aquele valor.
    """
    texto = caminho.read_text(encoding="utf-8")
    achados = []
    pendente = False          # a consulta de versao esta aberta
    de_versao = set()         # variaveis que guardam versao de schema

    for n, codigo, bruta in _linhas_de_codigo(texto):
        if MARCADOR in bruta:
            motivo = bruta.split(MARCADOR, 1)[1].strip()
            if not motivo:
                achados.append((n, bruta.strip(), "marcador sem motivo"))
            continue

        if _CONTEXTO.search(bruta):
            pendente = True
            continue

        if pendente:
            atrib = _ATRIBUICAO.search(codigo)
            if atrib:
                de_versao.add(atrib.group(1))
                pendente = False
            elif _CONSOME.search(codigo):
                # Forma inline: `assert (await cur.fetchone())[0] == 9`
                pendente = False
                m = _COMPARACAO.search(codigo)
                if m:
                    achados.append((n, codigo.strip(), f"comparacao com o literal {m.group(1)}"))
                continue
            elif _NOVA_QUERY.search(codigo):
                pendente = False

        if _FALSO_POSITIVO.search(codigo):
            continue

        # variavel rastreada comparada com literal
        for var in de_versao:
            m = re.search(rf"\b{re.escape(var)}\b[^\n=<>!]{{0,40}}?(?:==|!=)\s*(\d+)\b", codigo)
            if m:
                achados.append((n, codigo.strip(), f"comparacao com o literal {m.group(1)}"))
                break
        else:
            m = _DIRETA.search(codigo)
            if m:
                achados.append((n, codigo.strip(), f"comparacao com o literal {m.group(1)}"))
    return achados


def _varre(arquivos):
    problemas = []
    for arquivo in arquivos:
        for n, trecho, motivo in _ofensas(arquivo):
            problemas.append(f"  {arquivo.name}:{n} — {motivo}\n      {trecho}")
    return problemas


def test_nenhum_teste_compara_schema_com_literal():
    arquivos = sorted(p for p in TESTES.glob("test_*.py") if p.name != pathlib.Path(__file__).name)
    problemas = _varre(arquivos)
    assert not problemas, (
        "versão de schema comparada com número literal:\n"
        + "\n".join(problemas)
        + "\n\n  Use `db.SCHEMA_VERSION` — ele é derivado de `_MIGRATIONS[-1][0]`, então\n"
          "  não precisa ser atualizado a cada migration. A intenção quase sempre é\n"
          '  "banco totalmente migrado", e é isso que SCHEMA_VERSION expressa:\n'
          "\n"
          "      assert (await cur.fetchone())[0] == mod.SCHEMA_VERSION\n"
          "\n"
          "  Se a comparação com o número é MESMO o que você quer (fixture que monta\n"
          "  um banco numa versão antiga de propósito), marque a linha e diga por quê:\n"
          "\n"
          "      conn.execute(...)  # schema-literal-ok: fixture nasce na v9\n"
    )


# --- o guarda também se testa ---------------------------------------------

def _escreve(tmp_path, corpo: str) -> pathlib.Path:
    alvo = tmp_path / "test_amostra.py"
    alvo.write_text(corpo, encoding="utf-8")
    return alvo


def test_guarda_pega_comparacao_direta(tmp_path):
    alvo = _escreve(tmp_path, "def t():\n    assert version == 12\n")
    assert _ofensas(alvo), "o guarda deixou passar a forma mais óbvia"


def test_guarda_pega_a_forma_que_aconteceu_de_verdade(tmp_path):
    """A forma real vem SEMPRE com a consulta acima — é ela que dá o contexto."""
    alvo = _escreve(tmp_path, (
        'async def t():\n'
        '    cur = await db.execute("SELECT MAX(version) FROM schema_version")\n'
        '    assert (await cur.fetchone())[0] == 9\n'
    ))
    ofensas = _ofensas(alvo)
    assert ofensas, "a forma que quebrou quatro testes na v9 não é pega"
    assert "9" in ofensas[0][2]


def test_guarda_pega_row_por_chave(tmp_path):
    alvo = _escreve(tmp_path, (
        'def t():\n'
        '    cur = conn.execute("SELECT MAX(version) as v FROM schema_version")\n'
        '    assert cur.fetchone()["v"] == 11\n'
    ))
    assert _ofensas(alvo)


def test_guarda_rastreia_a_variavel_e_ignora_as_outras(tmp_path):
    """Proximidade dava falso positivo; o sinal é a variável que recebe a versão."""
    alvo = _escreve(tmp_path, (
        'def t():\n'
        '    cur = conn.execute("SELECT COUNT(*) as cnt FROM findings")\n'
        '    findings_before = cur.fetchone()["cnt"]\n'
        '    cur = conn.execute("SELECT MAX(version) as v FROM schema_version")\n'
        '    version_before = cur.fetchone()["v"]\n'
        '    assert findings_before == 12\n'
        '    assert version_before == 5\n'
    ))
    ofensas = _ofensas(alvo)
    assert len(ofensas) == 1, f"esperava so a linha da versao, veio {ofensas}"
    assert "version_before" in ofensas[0][1]


def test_consulta_nova_encerra_o_rastreio(tmp_path):
    alvo = _escreve(tmp_path, (
        'async def t():\n'
        '    cur = await db.execute("SELECT MAX(version) FROM schema_version")\n'
        '    assert (await cur.fetchone())[0] == mod.SCHEMA_VERSION\n'
        '    cur = await db.execute("SELECT COUNT(*) FROM tasks")\n'
        '    assert (await cur.fetchone())[0] == 6\n'
    ))
    assert not _ofensas(alvo), "contagem de outra tabela virou falso positivo"


def test_guarda_aceita_schema_version(tmp_path):
    alvo = _escreve(tmp_path, "def t():\n    assert version == mod.SCHEMA_VERSION\n")
    assert not _ofensas(alvo), "a forma CORRETA foi acusada"


def test_guarda_ignora_literal_em_comentario(tmp_path):
    alvo = _escreve(tmp_path, "def t():\n    # antes isso era: assert version == 9\n    pass\n")
    assert not _ofensas(alvo), "falso positivo em comentário"


def test_guarda_ignora_literal_em_docstring(tmp_path):
    alvo = _escreve(
        tmp_path,
        'def t():\n    """Explica que `assert version == 9` era o erro."""\n    pass\n',
    )
    assert not _ofensas(alvo), "falso positivo em docstring"


def test_guarda_ignora_docstring_de_varias_linhas(tmp_path):
    alvo = _escreve(
        tmp_path,
        'def t():\n    """Primeira linha.\n\n    assert version == 9\n    """\n    pass\n',
    )
    assert not _ofensas(alvo), "falso positivo em docstring multilinha"


def test_guarda_ignora_argumento_nomeado(tmp_path):
    alvo = _escreve(tmp_path, "def t():\n    popular(path, version=9)\n")
    assert not _ofensas(alvo), "argumento nomeado não é comparação"


def test_marcador_com_motivo_libera_a_linha(tmp_path):
    alvo = _escreve(
        tmp_path,
        "def t():\n    assert version == 9  # schema-literal-ok: fixture nasce na v9\n",
    )
    assert not _ofensas(alvo), "o escape documentado não funcionou"


def test_marcador_sem_motivo_nao_libera(tmp_path):
    """Isenção sem justificativa é isenção que ninguém consegue revisar."""
    alvo = _escreve(tmp_path, "def t():\n    assert version == 9  # schema-literal-ok:\n")
    ofensas = _ofensas(alvo)
    assert ofensas and "sem motivo" in ofensas[0][2]


def test_mensagem_de_falha_ensina_a_correcao():
    """Guarda que só acusa vira ruído; guarda que ensina vira ferramenta."""
    import inspect
    fonte = inspect.getsource(test_nenhum_teste_compara_schema_com_literal)
    assert "SCHEMA_VERSION" in fonte
    assert "schema-literal-ok" in fonte
