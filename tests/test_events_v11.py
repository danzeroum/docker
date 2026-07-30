"""2b-B3 — timeline de eventos: migration v11, ring, filtros e histórico.

A regra dura do doc 00 vale em dobro aqui: a v10 já carrega dado de produção
(séries de container), então a v11 tem teste sobre banco POPULADO como aceite,
não como lembrete. A v3 perdeu `first_seen` em produção por não ter isso.
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


def evento(action="die", nome="api", stack="web", exit_code="137", tipo="container", quando=None):
    """Evento no formato que o daemon emite."""
    return {
        "Type": tipo,
        "Action": action,
        "time": quando if quando is not None else int(_agora().timestamp()),
        "Actor": {
            "ID": "sha256:abc123",
            "Attributes": {
                "name": nome,
                "com.docker.compose.project": stack,
                "exitCode": exit_code,
            },
        },
    }


@pytest.fixture
def db_mod(tmp_path):
    caminho = str(tmp_path / "cockpit.db")
    anterior = os.environ.get("COCKPIT_DB")
    os.environ["COCKPIT_DB"] = caminho
    import db as mod
    importlib.reload(mod)
    yield mod
    if anterior is None:
        os.environ.pop("COCKPIT_DB", None)
    else:
        os.environ["COCKPIT_DB"] = anterior


# --- migração v10 → v11 sobre banco populado ------------------------------

def _popula_v10(path):
    """Banco no estado da v10, com dado nas tabelas que a Sprint 1 criou."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE container_samples ("
        "sampled_at TEXT NOT NULL, container_id TEXT NOT NULL, name TEXT NOT NULL,"
        "cpu_pct REAL NOT NULL DEFAULT 0, mem_usage INTEGER NOT NULL DEFAULT 0, mem_limit INTEGER,"
        "PRIMARY KEY (sampled_at, container_id))"
    )
    conn.execute(
        "CREATE TABLE container_samples_hourly ("
        "hour TEXT NOT NULL, container_id TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',"
        "cpu_pct_avg REAL NOT NULL DEFAULT 0, cpu_pct_max REAL NOT NULL DEFAULT 0,"
        "mem_usage_avg INTEGER NOT NULL DEFAULT 0, mem_usage_max INTEGER NOT NULL DEFAULT 0,"
        "mem_limit INTEGER, samples INTEGER NOT NULL DEFAULT 0,"
        "PRIMARY KEY (hour, container_id))"
    )
    conn.execute(
        "CREATE TABLE host_samples ("
        "sampled_at TEXT PRIMARY KEY, cpu_pct REAL NOT NULL, mem_pct REAL NOT NULL,"
        "mem_used INTEGER NOT NULL, mem_total INTEGER NOT NULL, disk_pct REAL NOT NULL,"
        "swap_pct REAL NOT NULL DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE audit_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, project TEXT NOT NULL,"
        "result TEXT NOT NULL, token_label TEXT NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT '',"
        "created_at TEXT NOT NULL)"
    )
    for v in range(1, 11):
        conn.execute("INSERT INTO schema_version VALUES (?, ?)", (v, _iso(_agora())))

    base = _agora()
    conn.executemany(
        "INSERT INTO container_samples (sampled_at, container_id, name, cpu_pct, mem_usage, mem_limit)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [(_iso(base - timedelta(minutes=i)), "cafe1", "api", 10.0 + i, 1000 + i, 512) for i in range(6)],
    )
    conn.execute(
        "INSERT INTO container_samples_hourly (hour, container_id, name, cpu_pct_avg, cpu_pct_max,"
        " mem_usage_avg, mem_usage_max, mem_limit, samples) VALUES (?,?,?,?,?,?,?,?,?)",
        (_iso(base - timedelta(hours=3))[:13] + ":00:00Z", "cafe1", "api", 12.5, 20.0, 1500, 2000, 512, 60),
    )
    conn.execute(
        "INSERT INTO host_samples VALUES (?, 10, 20, 100, 1000, 30, 0)", (_iso(base),)
    )
    conn.execute(
        "INSERT INTO audit_log (action, project, result, token_label, ip, created_at)"
        " VALUES ('container_stop', 'api', 'success', 'dz', '10.0.0.1', ?)", (_iso(base),)
    )
    conn.commit()
    conn.close()


async def test_v11_sobre_banco_v10_populado_nao_perde_nada(tmp_path):
    caminho = str(tmp_path / "prod.db")
    _popula_v10(caminho)

    anterior = os.environ.get("COCKPIT_DB")
    os.environ["COCKPIT_DB"] = caminho
    try:
        import db as mod
        importlib.reload(mod)
        await mod.init_db()
        db = await mod.get_db()

        # As 4 tabelas com dado atravessam intactas, com as colunas nos lugares.
        cur = await db.execute(
            "SELECT sampled_at, container_id, name, cpu_pct FROM container_samples ORDER BY sampled_at"
        )
        linhas = await cur.fetchall()
        assert len(linhas) == 6, "a v11 perdeu linhas de container_samples"
        for l in linhas:
            assert l[1] == "cafe1" and l[2] == "api" and l[3] >= 10.0

        for tabela, esperado in (
            ("container_samples_hourly", 1), ("host_samples", 1), ("audit_log", 1),
        ):
            cur = await db.execute(f"SELECT COUNT(*) FROM {tabela}")
            assert (await cur.fetchone())[0] == esperado, f"{tabela} perdeu linha na v11"

        cur = await db.execute("SELECT samples, cpu_pct_max FROM container_samples_hourly")
        assert tuple(await cur.fetchone()) == (60, 20.0), "colunas do rollup embaralharam"

        cur = await db.execute("SELECT MAX(version) FROM schema_version")
        assert (await cur.fetchone())[0] == mod.SCHEMA_VERSION == 11

        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='docker_events'"
        )
        assert await cur.fetchone(), "docker_events não foi criada"
        await mod.close_db()
    finally:
        if anterior is None:
            os.environ.pop("COCKPIT_DB", None)
        else:
            os.environ["COCKPIT_DB"] = anterior


async def test_v11_e_idempotente(db_mod):
    await db_mod.init_db()
    await db_mod.init_db()
    db = await db_mod.get_db()
    cur = await db.execute("SELECT COUNT(*) FROM schema_version WHERE version = 11")
    assert (await cur.fetchone())[0] == 1
    await db_mod.close_db()


# --- gravação -------------------------------------------------------------

async def test_grava_evento_de_container(db_mod):
    await db_mod.init_db()
    linha = await db_mod.insert_event(evento())
    assert linha is not None
    assert linha["action"] == "die"
    assert linha["actor_name"] == "api"
    assert linha["stack"] == "web"
    assert linha["exit_code"] == "137"
    await db_mod.close_db()


async def test_ruido_do_daemon_nao_entra_no_ring(db_mod):
    """exec_create/exec_start chegam às dezenas por minuto e expulsariam os die."""
    await db_mod.init_db()
    for acao in ("exec_create", "exec_start", "attach", "top"):
        assert await db_mod.insert_event(evento(action=acao)) is None
    # e evento que não é de container também não
    assert await db_mod.insert_event(evento(tipo="network", action="connect")) is None

    db = await db_mod.get_db()
    cur = await db.execute("SELECT COUNT(*) FROM docker_events")
    assert (await cur.fetchone())[0] == 0
    await db_mod.close_db()


async def test_varios_eventos_no_mesmo_segundo_sobrevivem(db_mod):
    """die+stop+start de um restart chegam juntos — é a sequência que importa."""
    await db_mod.init_db()
    t = int(_agora().timestamp())
    for acao in ("die", "stop", "start"):
        await db_mod.insert_event(evento(action=acao, quando=t))

    linhas = await db_mod.get_events()
    assert len(linhas) == 3, "PK temporal descartaria a sequência do restart"
    assert [l["action"] for l in linhas] == ["start", "stop", "die"], "ordem cronológica reversa"
    await db_mod.close_db()


@pytest.mark.parametrize("action,exit_code,esperado", [
    ("oom", "", "critical"),
    ("die", "137", "critical"),
    ("die", "0", "info"),
    ("die", "", "info"),
    ("kill", "", "warn"),
    ("destroy", "", "warn"),
    ("start", "", "info"),
    ("health_status", "unhealthy", "warn"),
])
async def test_severidade_por_acao(db_mod, action, exit_code, esperado):
    """die com exit 0 é parada limpa; com exit != 0 é o que derrubou o serviço."""
    await db_mod.init_db()
    acao_bruta = f"health_status: {exit_code}" if action == "health_status" else action
    linha = await db_mod.insert_event(evento(action=acao_bruta, exit_code=exit_code))
    assert linha["severity"] == esperado
    await db_mod.close_db()


# --- ring -----------------------------------------------------------------

async def test_ring_mantem_os_mais_recentes(db_mod):
    """10.050 eventos → tabela fica com os 10.000 mais recentes."""
    await db_mod.init_db()
    db = await db_mod.get_db()
    agora = _iso(_agora())
    await db.executemany(
        "INSERT INTO docker_events (ts, type, action, actor_id, actor_name, stack, exit_code, severity)"
        " VALUES (?, 'container', 'start', '', ?, 'web', '', 'info')",
        [(agora, f"c{i}") for i in range(10050)],
    )
    await db.commit()

    await db_mod.purge_events()

    cur = await db.execute("SELECT COUNT(*) FROM docker_events")
    assert (await cur.fetchone())[0] == 10000

    # os que sobraram são os do FIM da inserção, não os do começo
    cur = await db.execute("SELECT actor_name FROM docker_events ORDER BY id ASC LIMIT 1")
    assert (await cur.fetchone())[0] == "c50", "o ring cortou pela ponta errada"
    cur = await db.execute("SELECT actor_name FROM docker_events ORDER BY id DESC LIMIT 1")
    assert (await cur.fetchone())[0] == "c10049"
    await db_mod.close_db()


async def test_ring_nao_faz_nada_com_tabela_pequena(db_mod):
    await db_mod.init_db()
    for i in range(5):
        await db_mod.insert_event(evento(nome=f"c{i}"))
    await db_mod.purge_events()
    assert len(await db_mod.get_events()) == 5
    await db_mod.close_db()


# --- leitura e filtros ----------------------------------------------------

async def test_filtro_por_container(db_mod):
    await db_mod.init_db()
    await db_mod.insert_event(evento(nome="api", stack="web"))
    await db_mod.insert_event(evento(nome="worker", stack="batch"))
    await db_mod.insert_event(evento(nome="api", stack="web", action="start"))

    linhas = await db_mod.get_events(container="api")
    assert len(linhas) == 2
    assert all(l["actor_name"] == "api" for l in linhas)
    await db_mod.close_db()


async def test_filtro_por_stack_acao_e_severidade(db_mod):
    await db_mod.init_db()
    await db_mod.insert_event(evento(nome="api", stack="web", action="die", exit_code="137"))
    await db_mod.insert_event(evento(nome="front", stack="web", action="start"))
    await db_mod.insert_event(evento(nome="worker", stack="batch", action="oom"))

    assert len(await db_mod.get_events(stack="web")) == 2
    assert len(await db_mod.get_events(action="start")) == 1
    criticos = await db_mod.get_events(severity="critical")
    assert {l["actor_name"] for l in criticos} == {"api", "worker"}
    await db_mod.close_db()


async def test_container_inexistente_devolve_vazio(db_mod):
    await db_mod.init_db()
    await db_mod.insert_event(evento(nome="api"))
    assert await db_mod.get_events(container="nao_existe") == []
    await db_mod.close_db()


async def test_paginacao_keyset_nao_repete_nem_pula(db_mod):
    """OFFSET numa tabela que recebe escrita pela frente repete ou pula linha."""
    await db_mod.init_db()
    for i in range(10):
        await db_mod.insert_event(evento(nome=f"c{i}"))

    p1 = await db_mod.get_events(limit=4)
    assert len(p1) == 4
    # chega evento novo entre as páginas — é o cenário que quebra OFFSET
    await db_mod.insert_event(evento(nome="recem_chegado"))

    p2 = await db_mod.get_events(limit=4, before_id=p1[-1]["id"])
    assert len(p2) == 4
    assert not ({l["id"] for l in p1} & {l["id"] for l in p2}), "página repetiu linha"
    assert "recem_chegado" not in {l["actor_name"] for l in p2}
    await db_mod.close_db()


# --- resumo para a régua --------------------------------------------------

async def test_resumo_traz_total_e_ultimo_critico(db_mod):
    await db_mod.init_db()
    await db_mod.insert_event(evento(nome="api", action="start"))
    await db_mod.insert_event(evento(nome="api", action="die", exit_code="137"))
    await db_mod.insert_event(evento(nome="front", action="start"))

    r = await db_mod.get_events_resumo()
    assert r["total"] == 3
    assert r["last_at"]
    assert r["last_critical"]["container"] == "api"
    assert r["last_critical"]["action"] == "die"
    await db_mod.close_db()


async def test_resumo_sem_critico_nao_inventa(db_mod):
    await db_mod.init_db()
    await db_mod.insert_event(evento(action="start", exit_code=""))
    r = await db_mod.get_events_resumo()
    assert r["total"] == 1
    assert r["last_critical"] is None
    await db_mod.close_db()


async def test_resumo_de_banco_vazio(db_mod):
    await db_mod.init_db()
    r = await db_mod.get_events_resumo()
    assert r == {"total": 0, "last_at": None, "last_critical": None}
    await db_mod.close_db()
