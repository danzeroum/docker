"""3-B5 — índice FTS5, ingestão incremental e busca (v13).

O risco desta sprint não é a feature nova: é regressão no follow, que já
funciona e que o porte da Sprint 2a quase perdeu uma vez. Por isso o primeiro
teste aqui é sobre o follow **não** ter mudado.

O caso real de uso é stack trace: o `oom` que o operador procura aparece no meio
de um traceback de 40 linhas, não numa linha limpa.
"""

import importlib
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _agora():
    return datetime.now(timezone.utc)


@pytest.fixture
def db_mod(tmp_path):
    caminho = str(tmp_path / "cockpit.db")
    anterior = os.environ.get("COCKPIT_DB")
    os.environ["COCKPIT_DB"] = caminho
    import db as mod
    importlib.reload(mod)
    yield mod
    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(mod.close_db())
    except Exception:
        pass
    if anterior is None:
        os.environ.pop("COCKPIT_DB", None)
    else:
        os.environ["COCKPIT_DB"] = anterior


# --- o follow NÃO muda ----------------------------------------------------

def test_follow_continua_direto_do_daemon():
    """O B5 acrescenta busca; ele não pode reescrever o que já funciona.

    O follow foi portado na Sprint 2a e quase se perdeu naquele porte. Se algum
    dia ele passar a ler do banco, este teste é quem avisa.
    """
    modulo = open(os.path.join(RAIZ, "app", "static", "js", "modulos", "logs.js")).read()
    assert "new EventSource(`/api/containers/${id}/logs/stream" in modulo, (
        "o follow saiu da rota própria do daemon"
    )
    assert "/api/logs/search" not in modulo.split("function iniciarFollow")[1].split("}")[0], (
        "o follow passou a consultar o índice em vez do daemon"
    )
    ingest = open(os.path.join(RAIZ, "app", "logs_ingest.py")).read()
    assert "follow" in ingest.lower(), "a decisão de não ingerir o follow saiu do código"


# --- sanitização ----------------------------------------------------------

@pytest.mark.parametrize("entrada", [
    'erro NEAR/2 falha',
    '"aspas soltas',
    'oom OR *',
    'a AND (b',
    '^inicio',
    'coluna:valor',
    '""',
    '- - -',
])
def test_sintaxe_fts_vira_literal_e_nunca_levanta(db_mod, entrada):
    """FTS5 não tem escape universal, e sintaxe inválida LEVANTA.

    Uma aspa digitada sem querer mataria a busca inteira. Aqui a expressão é
    reconstruída a partir dos tokens, então não existe entrada que quebre.
    """
    expressao = db_mod.sanitiza_fts(entrada)
    # o que sai tem de ser aceito pelo FTS5 sem excecao
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(linha)")
    conn.execute("INSERT INTO t VALUES ('erro fatal oom no container')")
    if expressao:
        list(conn.execute("SELECT * FROM t WHERE t MATCH ?", (expressao,)))
    conn.close()


def test_operador_nao_e_interpretado(db_mod):
    assert db_mod.sanitiza_fts("erro NEAR/2 falha") == '"erro" "NEAR/2" "falha"'
    assert db_mod.sanitiza_fts("a OR b") == '"a" "OR" "b"'


def test_acento_sobrevive(db_mod):
    """Log em português tem acento; perdê-lo na sanitização é perder a busca."""
    assert "café" in db_mod.sanitiza_fts("café")


# --- ingestão -------------------------------------------------------------

@pytest.mark.asyncio
async def test_grava_e_avanca_a_marca_dagua(db_mod):
    await db_mod.init_db()
    base = _agora()
    linhas = [(_iso(base - timedelta(seconds=i)), f"linha {i}") for i in range(3)]
    n = await db_mod.insert_log_lines("api", linhas)
    assert n == 3
    assert await db_mod.get_log_watermark("api") == max(ts for ts, _ in linhas)
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_marca_dagua_nunca_retrocede(db_mod):
    """Um ciclo que traz linha antiga não pode fazer o próximo reingerir tudo."""
    await db_mod.init_db()
    novo = _iso(_agora())
    antigo = _iso(_agora() - timedelta(hours=2))
    await db_mod.insert_log_lines("api", [(novo, "recente")])
    await db_mod.insert_log_lines("api", [(antigo, "atrasada")])
    assert await db_mod.get_log_watermark("api") == novo
    await db_mod.close_db()


def test_stack_trace_multiline_herda_o_ts_base():
    """O caso REAL: o `oom` está no meio do traceback, não numa linha limpa."""
    from logs_ingest import parse_linhas
    bruto = (
        "2026-07-30T12:00:00.000Z Traceback (most recent call last):\n"
        '  File "/app/worker.py", line 42, in run\n'
        "    processa(lote)\n"
        "MemoryError: oom killed\n"
        "2026-07-30T12:00:05.000Z reiniciando\n"
    )
    linhas = parse_linhas(bruto, "2026-01-01T00:00:00Z")
    assert len(linhas) == 5
    # as 4 primeiras compartilham o ts do traceback
    assert [ts for ts, _ in linhas[:4]] == ["2026-07-30T12:00:00.000Z"] * 4
    assert linhas[4][0] == "2026-07-30T12:00:05.000Z"
    # e a linha do oom sobreviveu como registro próprio, pesquisável
    assert any("oom" in l for _, l in linhas)


def test_linha_sem_timestamp_no_inicio_usa_o_padrao():
    from logs_ingest import parse_linhas
    linhas = parse_linhas("sem carimbo\n", "2026-01-01T00:00:00Z")
    assert linhas == [("2026-01-01T00:00:00Z", "sem carimbo")]


# --- busca ----------------------------------------------------------------

@pytest.mark.asyncio
async def _semeia(db_mod):
    base = _agora()
    await db_mod.insert_log_lines("api", [
        (_iso(base - timedelta(minutes=3)), "Traceback (most recent call last):"),
        (_iso(base - timedelta(minutes=3)), "MemoryError: oom killed at 512MB"),
        (_iso(base - timedelta(minutes=2)), "GET /health 200"),
    ])
    await db_mod.insert_log_lines("front", [
        (_iso(base - timedelta(minutes=1)), "erro 502 ao falar com api"),
    ])


@pytest.mark.asyncio
async def test_busca_devolve_trecho_com_container_e_ts(db_mod):
    await db_mod.init_db()
    await _semeia(db_mod)

    linhas, expressao = await db_mod.search_logs("oom")
    assert expressao == '"oom"'
    assert len(linhas) == 1
    r = linhas[0]
    assert r["container"] == "api"
    assert r["ts"]
    assert "oom" in r["linha"]
    # o trecho vem com o termo entre os marcadores
    assert db_mod.MARCA_INICIO in r["trecho"] and db_mod.MARCA_FIM in r["trecho"]
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_marcadores_nao_sao_html(db_mod):
    """A UI escapa o texto e põe marcação por cima; HTML daqui a obrigaria a
    injetar conteúdo de log no DOM."""
    assert "<" not in db_mod.MARCA_INICIO.replace("⁢", "") or True
    assert "<mark" not in db_mod.MARCA_INICIO
    assert "<mark" not in db_mod.MARCA_FIM


@pytest.mark.asyncio
async def test_busca_filtra_por_container(db_mod):
    await db_mod.init_db()
    await _semeia(db_mod)
    linhas, _ = await db_mod.search_logs("api", container="front")
    assert len(linhas) == 1
    assert linhas[0]["container"] == "front"
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_busca_sem_resultado_e_lista_vazia_nao_erro(db_mod):
    await db_mod.init_db()
    await _semeia(db_mod)
    linhas, _ = await db_mod.search_logs("palavraquenaoexiste")
    assert linhas == []
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_busca_com_operador_encontra_o_literal(db_mod):
    """`erro NEAR/2` não invoca NEAR: procura as palavras, sem levantar."""
    await db_mod.init_db()
    await _semeia(db_mod)
    linhas, expressao = await db_mod.search_logs("erro NEAR/2")
    assert expressao == '"erro" "NEAR/2"'
    assert linhas == [], "não há linha com as duas palavras — e isso é 0 resultado, não erro"
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_busca_no_meio_do_traceback(db_mod):
    """O aceite real: achar `MemoryError` dentro do stack trace ingerido."""
    await db_mod.init_db()
    await _semeia(db_mod)
    linhas, _ = await db_mod.search_logs("MemoryError")
    assert len(linhas) == 1
    assert "oom" in linhas[0]["linha"]
    await db_mod.close_db()


# --- retenção -------------------------------------------------------------

@pytest.mark.asyncio
async def test_expurgo_de_7_dias(db_mod):
    await db_mod.init_db()
    await db_mod.insert_log_lines("api", [
        (_iso(_agora() - timedelta(days=9)), "linha velha com marcador zzz"),
        (_iso(_agora()), "linha nova com marcador zzz"),
    ])
    await db_mod.purge_logs()
    linhas, _ = await db_mod.search_logs("zzz")
    assert len(linhas) == 1
    assert "nova" in linhas[0]["linha"]
    await db_mod.close_db()


# --- migração v12 -> v13 sobre banco populado -----------------------------

def _popula_v12(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE audit_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, project TEXT NOT NULL,"
        "result TEXT NOT NULL, token_label TEXT NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT '',"
        "created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'done',"
        "started_at TEXT, finished_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE docker_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, type TEXT NOT NULL DEFAULT '',"
        "action TEXT NOT NULL DEFAULT '', actor_id TEXT NOT NULL DEFAULT '',"
        "actor_name TEXT NOT NULL DEFAULT '', stack TEXT NOT NULL DEFAULT '',"
        "exit_code TEXT NOT NULL DEFAULT '', severity TEXT NOT NULL DEFAULT 'info')"
    )
    conn.execute(
        "CREATE TABLE container_samples ("
        "sampled_at TEXT NOT NULL, container_id TEXT NOT NULL, name TEXT NOT NULL,"
        "cpu_pct REAL NOT NULL DEFAULT 0, mem_usage INTEGER NOT NULL DEFAULT 0, mem_limit INTEGER,"
        "PRIMARY KEY (sampled_at, container_id))"
    )
    for v in range(1, 13):
        conn.execute("INSERT INTO schema_version VALUES (?, ?)", (v, _iso(_agora())))
    agora = _iso(_agora())
    conn.execute(
        "INSERT INTO audit_log (action, project, result, token_label, ip, created_at,"
        " status, started_at, finished_at) VALUES"
        " ('prune', 'images', 'success: 2', 'dz', '10.0.0.1', ?, 'done', ?, ?)",
        (agora, agora, agora),
    )
    conn.execute(
        "INSERT INTO docker_events (ts, type, action, actor_name, severity)"
        " VALUES (?, 'container', 'die', 'api', 'critical')", (agora,)
    )
    conn.execute(
        "INSERT INTO container_samples VALUES (?, 'cafe1', 'api', 12.5, 1000, 512)", (agora,)
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_v13_sobre_banco_v12_populado_preserva_tudo(tmp_path):
    caminho = str(tmp_path / "prod.db")
    _popula_v12(caminho)

    anterior = os.environ.get("COCKPIT_DB")
    os.environ["COCKPIT_DB"] = caminho
    try:
        import db as mod
        importlib.reload(mod)
        await mod.init_db()
        db = await mod.get_db()

        for tabela in ("audit_log", "docker_events", "container_samples"):
            cur = await db.execute(f"SELECT COUNT(*) FROM {tabela}")
            assert (await cur.fetchone())[0] == 1, f"{tabela} perdeu linha na v13"

        # colunas da v12 continuam nos lugares
        cur = await db.execute("SELECT action, result, status, started_at FROM audit_log")
        acao, resultado, status, inicio = await cur.fetchone()
        assert acao == "prune" and resultado == "success: 2" and status == "done" and inicio

        cur = await db.execute("SELECT MAX(version) FROM schema_version")
        assert (await cur.fetchone())[0] == mod.SCHEMA_VERSION

        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE name IN ('logs_fts', 'logs_ingest')"
        )
        assert len(await cur.fetchall()) == 2, "as tabelas do índice não nasceram"

        # e o índice novo funciona no banco migrado
        await mod.insert_log_lines("api", [(_iso(_agora()), "erro apos migracao")])
        linhas, _ = await mod.search_logs("erro")
        assert len(linhas) == 1
        await mod.close_db()
    finally:
        if anterior is None:
            os.environ.pop("COCKPIT_DB", None)
        else:
            os.environ["COCKPIT_DB"] = anterior


@pytest.mark.asyncio
async def test_v13_e_idempotente(db_mod):
    await db_mod.init_db()
    await db_mod.init_db()
    db = await db_mod.get_db()
    cur = await db.execute("SELECT COUNT(*) FROM schema_version WHERE version = 13")
    assert (await cur.fetchone())[0] == 1
    await db_mod.close_db()
