"""B2 — migracao v10, rollup horario, retencao em dois niveis e /history.

A regra do repo (00-decisoes-de-revisao.md) e explicita: toda migracao de
esquema tem teste com banco POPULADO antes do deploy. A v3 perdeu `first_seen`
em producao justamente por nao ter isso.
"""

import importlib
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _agora():
    return datetime.now(timezone.utc)


def _popula_v9(path, amostras):
    """Cria o esquema ate a v9 e insere amostras raw, como um banco em producao."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE container_samples ("
        "sampled_at TEXT NOT NULL,"
        "container_id TEXT NOT NULL,"
        "name TEXT NOT NULL,"
        "cpu_pct REAL NOT NULL DEFAULT 0,"
        "mem_usage INTEGER NOT NULL DEFAULT 0,"
        "mem_limit INTEGER,"
        "PRIMARY KEY (sampled_at, container_id)"
        ")"
    )
    conn.execute(
        "CREATE TABLE host_samples ("
        "sampled_at TEXT PRIMARY KEY,"
        "cpu_pct REAL NOT NULL,"
        "mem_pct REAL NOT NULL,"
        "mem_used INTEGER NOT NULL,"
        "mem_total INTEGER NOT NULL,"
        "disk_pct REAL NOT NULL,"
        "swap_pct REAL NOT NULL DEFAULT 0"
        ")"
    )
    for ver in range(1, 10):
        conn.execute("INSERT INTO schema_version VALUES (?, ?)", (ver, _iso(_agora())))
    conn.executemany(
        "INSERT INTO container_samples (sampled_at, container_id, name, cpu_pct, mem_usage, mem_limit)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        amostras,
    )
    conn.commit()
    conn.close()


@pytest.fixture
def db_mod(tmp_path):
    """Modulo db recarregado apontando para um banco descartavel."""
    caminho = str(tmp_path / "cockpit.db")
    anterior = os.environ.get("COCKPIT_DB")
    os.environ["COCKPIT_DB"] = caminho
    import db as mod
    importlib.reload(mod)
    mod._caminho_teste = caminho
    yield mod
    try:
        import asyncio
        asyncio.get_event_loop()
    except RuntimeError:
        pass
    if anterior is None:
        os.environ.pop("COCKPIT_DB", None)
    else:
        os.environ["COCKPIT_DB"] = anterior


async def _insere(mod, cid, quando, cpu, mem, limite=512 * 1024 * 1024, nome="svc"):
    db = await mod.get_db()
    await db.execute(
        "INSERT OR IGNORE INTO container_samples (sampled_at, container_id, name, cpu_pct, mem_usage, mem_limit)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (_iso(quando), cid, nome, cpu, mem, limite),
    )
    await db.commit()


# --- migracao --------------------------------------------------------------

async def test_v10_preserva_amostras_existentes(tmp_path):
    """Banco populado atravessa a v10 sem perder linha nem embaralhar coluna."""
    caminho = str(tmp_path / "prod.db")
    agora = _agora()
    amostras = [
        (_iso(agora - timedelta(minutes=i)), "cafe1", "nginx", 10.0 + i, 1000 + i, 512)
        for i in range(5)
    ]
    _popula_v9(caminho, amostras)

    anterior = os.environ.get("COCKPIT_DB")
    os.environ["COCKPIT_DB"] = caminho
    try:
        import db as mod
        importlib.reload(mod)
        await mod.init_db()

        db = await mod.get_db()
        cur = await db.execute(
            "SELECT sampled_at, container_id, name, cpu_pct, mem_usage, mem_limit"
            " FROM container_samples ORDER BY sampled_at"
        )
        linhas = await cur.fetchall()
        assert len(linhas) == 5, "a v10 perdeu linhas de container_samples"
        # colunas continuam nos lugares certos (a v3 falhou exatamente aqui)
        for linha in linhas:
            assert linha[1] == "cafe1"
            assert linha[2] == "nginx"
            assert linha[3] >= 10.0

        cur = await db.execute("SELECT MAX(version) FROM schema_version")
        # Contra SCHEMA_VERSION, nao contra 10: este teste valida que a v10 nao
        # perde dado, e `init_db` aplica TODAS as migrations pendentes. Escrever
        # o numero aqui faz o teste quebrar a cada migration nova — foi
        # exatamente o que a v9 fez com quatro testes de uma vez.
        assert (await cur.fetchone())[0] == mod.SCHEMA_VERSION >= 10

        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='container_samples_hourly'"
        )
        assert await cur.fetchone(), "container_samples_hourly nao foi criada"

        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_container_samples_cid'"
        )
        assert await cur.fetchone(), "indice (container_id, sampled_at) ausente"

        await mod.close_db()
    finally:
        if anterior is None:
            os.environ.pop("COCKPIT_DB", None)
        else:
            os.environ["COCKPIT_DB"] = anterior


async def test_v10_e_idempotente(db_mod):
    await db_mod.init_db()
    await db_mod.init_db()
    db = await db_mod.get_db()
    cur = await db.execute("SELECT COUNT(*) FROM schema_version WHERE version = 10")
    assert (await cur.fetchone())[0] == 1
    await db_mod.close_db()


async def test_leitura_no_mesmo_segundo_nao_viola_chave(db_mod):
    """Duas escritas no mesmo instante para o mesmo container: sem exception."""
    await db_mod.init_db()
    quando = _agora()
    await _insere(db_mod, "cafe1", quando, 10.0, 1000)
    await _insere(db_mod, "cafe1", quando, 99.0, 9999)

    db = await db_mod.get_db()
    cur = await db.execute("SELECT COUNT(*) FROM container_samples WHERE container_id='cafe1'")
    assert (await cur.fetchone())[0] == 1, "PK composta deixou duplicar"
    await db_mod.close_db()


# --- rollup e retencao ----------------------------------------------------

async def test_rollup_agrega_por_hora(db_mod):
    await db_mod.init_db()
    base = _agora().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    for i in range(4):
        await _insere(db_mod, "cafe1", base + timedelta(minutes=i * 10), 10.0 * (i + 1), 1000 * (i + 1))

    await db_mod.rollup_container_samples(window_hours=6)

    db = await db_mod.get_db()
    cur = await db.execute(
        "SELECT hour, cpu_pct_avg, cpu_pct_max, mem_usage_avg, mem_usage_max, samples"
        " FROM container_samples_hourly WHERE container_id='cafe1'"
    )
    linhas = await cur.fetchall()
    assert len(linhas) == 1, f"esperava 1 hora agregada, veio {len(linhas)}"
    hora, cpu_avg, cpu_max, mem_avg, mem_max, n = linhas[0]
    assert hora.endswith(":00:00Z")
    assert n == 4
    assert cpu_avg == pytest.approx(25.0)
    assert cpu_max == pytest.approx(40.0)
    assert mem_avg == 2500
    assert mem_max == 4000
    await db_mod.close_db()


async def test_rollup_reescreve_a_hora_em_curso(db_mod):
    """A hora corrente ainda recebe amostras; o agregado dela nao pode congelar."""
    await db_mod.init_db()
    base = _agora().replace(minute=5, second=0, microsecond=0)
    await _insere(db_mod, "cafe1", base, 10.0, 1000)
    await db_mod.rollup_container_samples(window_hours=6)

    await _insere(db_mod, "cafe1", base + timedelta(minutes=10), 30.0, 3000)
    await db_mod.rollup_container_samples(window_hours=6)

    db = await db_mod.get_db()
    cur = await db.execute(
        "SELECT samples, cpu_pct_avg FROM container_samples_hourly WHERE container_id='cafe1'"
    )
    linhas = await cur.fetchall()
    assert len(linhas) == 1
    assert linhas[0][0] == 2, "a segunda amostra da hora nao entrou no agregado"
    assert linhas[0][1] == pytest.approx(20.0)
    await db_mod.close_db()


async def test_purge_corta_raw_em_24h_e_preserva_o_agregado(db_mod):
    await db_mod.init_db()
    agora = _agora()
    antigo = agora - timedelta(hours=30)
    recente = agora - timedelta(hours=2)
    await _insere(db_mod, "cafe1", antigo, 50.0, 5000)
    await _insere(db_mod, "cafe1", recente, 20.0, 2000)

    await db_mod.rollup_container_samples(window_hours=48)
    await db_mod.purge_samples()

    db = await db_mod.get_db()
    cur = await db.execute("SELECT COUNT(*) FROM container_samples")
    assert (await cur.fetchone())[0] == 1, "raw de 30 h deveria ter sido expurgado"

    cur = await db.execute("SELECT COUNT(*) FROM container_samples_hourly")
    assert (await cur.fetchone())[0] == 2, (
        "o agregado das duas horas tinha de sobreviver ao purge do raw"
    )
    await db_mod.close_db()


async def test_purge_nao_toca_host_samples_de_30_dias(db_mod):
    """host_samples e a fonte da projecao da F4 — cortar em 24 h mataria a tela."""
    await db_mod.init_db()
    db = await db_mod.get_db()
    for dias in (0, 5, 20):
        await db.execute(
            "INSERT INTO host_samples (sampled_at, cpu_pct, mem_pct, mem_used, mem_total, disk_pct, swap_pct)"
            " VALUES (?, 10, 20, 100, 1000, 30, 0)",
            (_iso(_agora() - timedelta(days=dias)),),
        )
    await db.commit()

    await db_mod.purge_samples()

    cur = await db.execute("SELECT COUNT(*) FROM host_samples")
    assert (await cur.fetchone())[0] == 3, "purge derrubou a serie da projecao de disco"
    await db_mod.close_db()


# --- leitura --------------------------------------------------------------

async def test_history_devolve_cpu_e_mem_em_raw(db_mod):
    await db_mod.init_db()
    agora = _agora()
    for i in range(3):
        await _insere(db_mod, "cafe1", agora - timedelta(minutes=i), 10.0 + i, 1000 + i)

    r = await db_mod.get_container_history("cafe1", hours=24)

    assert r["resolution"] == "raw"
    assert len(r["points"]) >= 3
    for p in r["points"]:
        assert "cpu_pct" in p and "mem_bytes" in p
        assert p["ts"]
    await db_mod.close_db()


async def test_history_de_7d_vem_agregado_por_hora(db_mod):
    await db_mod.init_db()
    base = _agora().replace(minute=0, second=0, microsecond=0)
    for h in range(1, 6):
        for m in (0, 20, 40):
            await _insere(db_mod, "cafe1", base - timedelta(hours=h, minutes=-m), 10.0, 1000)
    await db_mod.rollup_container_samples(window_hours=48)

    r = await db_mod.get_container_history("cafe1", hours=7 * 24)

    assert r["resolution"] == "hourly"
    assert r["points"], "serie horaria vazia"
    for p in r["points"]:
        assert "samples" in p and "mem_bytes_max" in p
        assert p["ts"].endswith(":00:00Z")
    await db_mod.close_db()


async def test_history_respeita_teto_de_500_pontos(db_mod):
    await db_mod.init_db()
    agora = _agora()
    for i in range(700):
        await _insere(db_mod, "cafe1", agora - timedelta(seconds=i * 30), float(i % 100), 1000 + i)

    r = await db_mod.get_container_history("cafe1", hours=24)

    assert len(r["points"]) == 500, f"veio {len(r['points'])} pontos"
    assert r["downsampled_from"] == 700
    # o ultimo ponto tem de ser a leitura real mais recente, nao uma media
    db = await db_mod.get_db()
    cur = await db.execute(
        "SELECT sampled_at FROM container_samples WHERE container_id='cafe1'"
        " ORDER BY sampled_at DESC LIMIT 1"
    )
    assert r["points"][-1]["ts"] == (await cur.fetchone())[0]
    await db_mod.close_db()


async def test_history_de_container_sem_amostra_vem_vazio(db_mod):
    await db_mod.init_db()
    r = await db_mod.get_container_history("nunca_existiu", hours=24)
    assert r["points"] == []
    assert r["point_count"] == 0
    assert r["downsampled_from"] is None
    await db_mod.close_db()


async def test_history_isola_por_container(db_mod):
    await db_mod.init_db()
    agora = _agora()
    await _insere(db_mod, "cafe1", agora, 11.0, 1111, nome="um")
    await _insere(db_mod, "beef2", agora, 22.0, 2222, nome="dois")

    r = await db_mod.get_container_history("cafe1", hours=24)
    assert len(r["points"]) == 1
    assert r["points"][0]["cpu_pct"] == pytest.approx(11.0)
    await db_mod.close_db()
