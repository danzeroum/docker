"""Regressao do furo do UNLOCK_TOKEN estatico (migration v8).

Dois grupos:
  1. o token estatico de env nao pode ser aceito em X-Cockpit-Unlock;
  2. a v8 sobe sobre banco POPULADO sem levar dado junto — a regra que as
     migrations v3 e v5 quebraram, ambas perdendo first_seen.
"""
import importlib
import os
import aiosqlite
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


async def _fecha(db_mod):
    """Fecha a conexao mesmo quando o assert falha.

    Sem isto a thread da aiosqlite sobrevive e o pytest trava no fim da
    suite, sem mensagem de erro — o sintoma parece hang, nao falha."""
    try:
        await db_mod.close_db()
    except Exception:
        pass


STATIC_ENV_TOKEN = "token-estatico-do-env-antigo"


async def _fresh_db(tmp_path, name="cockpit.db"):
    db_path = str(tmp_path / name)
    os.environ["COCKPIT_DB"] = db_path
    import db as db_mod
    importlib.reload(db_mod)
    return db_mod, db_path


# ---------------------------------------------------------------------------
# 1. O token estatico nao abre nada
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_estatico_nao_vale_como_sessao(tmp_path):
    """O valor cru do env nao casa com hash nenhum → sem sessao."""
    db_mod, _ = await _fresh_db(tmp_path)
    try:
        await db_mod.init_db()
        os.environ["UNLOCK_TOKEN"] = STATIC_ENV_TOKEN  # simula o env de producao
        assert await db_mod.get_valid_unlock_session(STATIC_ENV_TOKEN) is None
        # mesmo com uma sessao legitima aberta, o estatico continua nao valendo
        token, _exp = await db_mod.create_unlock_session("admin", "172.19.0.9", "janela")
        assert await db_mod.get_valid_unlock_session(token) is not None
        assert await db_mod.get_valid_unlock_session(STATIC_ENV_TOKEN) is None
    finally:
        await _fecha(db_mod)
        os.environ.pop("UNLOCK_TOKEN", None)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_banco_guarda_hash_e_nao_o_token(tmp_path):
    """Vazar o arquivo do banco nao pode devolver token usavel."""
    db_mod, db_path = await _fresh_db(tmp_path)
    try:
        await db_mod.init_db()
        token, _ = await db_mod.create_unlock_session("admin", "172.19.0.9", "janela")
        await db_mod.close_db()

        conn = await aiosqlite.connect(db_path)
        cur = await conn.execute("SELECT token_hash FROM unlock_state")
        rows = [r[0] for r in await cur.fetchall()]
        cur = await conn.execute("PRAGMA table_info(unlock_state)")
        cols = {r[1] for r in await cur.fetchall()}
        await conn.close()

        assert "token" not in cols, "coluna de token em texto claro ainda existe"
        assert "token_hash" in cols and "expires_at" in cols
        assert token not in rows
        assert len(rows) == 1 and len(rows[0]) == 64
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_token_e_diferente_a_cada_unlock(tmp_path):
    """Dois unlocks → dois tokens distintos. Nenhum valor derivado de config."""
    db_mod, _ = await _fresh_db(tmp_path)
    try:
        await db_mod.init_db()
        t1, _ = await db_mod.create_unlock_session("admin", "172.19.0.9", "a")
        t2, _ = await db_mod.create_unlock_session("admin", "172.19.0.9", "b")
        assert t1 != t2
        assert len(t1) >= 32
        # as duas sessoes convivem — unlock de um operador nao derruba o do outro
        assert await db_mod.get_valid_unlock_session(t1) is not None
        assert await db_mod.get_valid_unlock_session(t2) is not None
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_sessao_expirada_nao_valida(tmp_path):
    db_mod, _ = await _fresh_db(tmp_path)
    try:
        await db_mod.init_db()
        token, _ = await db_mod.create_unlock_session("admin", "172.19.0.9", "x", ttl_seconds=-1)
        assert await db_mod.get_valid_unlock_session(token) is None
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_revoke_encerra_a_sessao(tmp_path):
    db_mod, _ = await _fresh_db(tmp_path)
    try:
        await db_mod.init_db()
        token, _ = await db_mod.create_unlock_session("admin", "172.19.0.9", "x")
        assert await db_mod.get_valid_unlock_session(token) is not None
        await db_mod.revoke_unlock_session(token)
        assert await db_mod.get_valid_unlock_session(token) is None
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


def test_http_com_token_estatico_e_negado():
    """O aceite literal: curl com o token estatico → 403, nunca 200."""
    os.environ["UNLOCK_TOKEN"] = STATIC_ENV_TOKEN
    try:
        from app import app
        client = TestClient(app)
        with patch("auth.get_valid_unlock_session", new=AsyncMock(return_value=None)):
            for method, url in (
                ("post", "/api/containers/docker-cockpit/restart"),
                ("post", "/api/containers/docker-cockpit/stop"),
                ("post", "/api/projects/meu-app/start"),
                ("post", "/api/findings/algum-achado/ack"),
            ):
                r = getattr(client, method)(
                    url,
                    headers={"X-Cockpit-Unlock": STATIC_ENV_TOKEN},
                    json={"reason": "monitorando"},
                )
                assert r.status_code in (401, 403), f"{url} devolveu {r.status_code}"
            # DELETE dentro do mesmo patch: fora dele a rota chega no banco real
            r = client.delete(
                "/api/containers/docker-cockpit",
                headers={"X-Cockpit-Unlock": STATIC_ENV_TOKEN},
            )
            assert r.status_code in (401, 403)
    finally:
        os.environ.pop("UNLOCK_TOKEN", None)


# ---------------------------------------------------------------------------
# 2. Migration v8 sobre banco POPULADO
# ---------------------------------------------------------------------------

async def _build_v7(db_path):
    """Reconstroi um banco no estado v7, com dado dentro — inclusive uma
    unlock_state chaveada pelo token estatico, como esta em producao."""
    conn = await aiosqlite.connect(db_path)
    await conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    await conn.execute(
        "CREATE TABLE findings (id TEXT PRIMARY KEY, rule TEXT NOT NULL, target TEXT, targets TEXT,"
        "scope TEXT NOT NULL, severity TEXT NOT NULL, score INTEGER NOT NULL, caused_by TEXT,"
        "status TEXT NOT NULL DEFAULT 'open', ack_reason TEXT, ack_note TEXT, ack_until TEXT,"
        "first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, resolved_at TEXT,"
        "occurrences INTEGER NOT NULL DEFAULT 1, payload TEXT NOT NULL)"
    )
    await conn.execute(
        "CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL,"
        "project TEXT NOT NULL, result TEXT NOT NULL, token_label TEXT NOT NULL DEFAULT '',"
        "ip TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)"
    )
    await conn.execute(
        "CREATE TABLE unlock_state (token TEXT PRIMARY KEY, remote_user TEXT NOT NULL DEFAULT '',"
        "ip TEXT NOT NULL DEFAULT '', motivo TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)"
    )
    await conn.execute(
        "CREATE TABLE host_samples (sampled_at TEXT PRIMARY KEY, cpu_pct REAL NOT NULL,"
        "mem_pct REAL NOT NULL, mem_used INTEGER NOT NULL, mem_total INTEGER NOT NULL,"
        "disk_pct REAL NOT NULL, swap_pct REAL NOT NULL DEFAULT 0)"
    )
    await conn.execute(
        "CREATE TABLE container_samples (sampled_at TEXT NOT NULL, container_id TEXT NOT NULL,"
        "name TEXT NOT NULL, cpu_pct REAL NOT NULL DEFAULT 0, mem_usage INTEGER NOT NULL DEFAULT 0,"
        "mem_limit INTEGER, PRIMARY KEY (sampled_at, container_id))"
    )
    await conn.execute(
        "CREATE TABLE api_telemetry (route TEXT NOT NULL, hour TEXT NOT NULL,"
        "total INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,"
        "durations_total REAL NOT NULL DEFAULT 0, durations_squared REAL NOT NULL DEFAULT 0,"
        "durations_max REAL NOT NULL DEFAULT 0, PRIMARY KEY (route, hour))"
    )
    for v in range(1, 8):
        await conn.execute("INSERT INTO schema_version VALUES (?, ?)", (v, "2026-01-01T00:00:00Z"))

    # Dado real de producao: dois healthcheck_never_passed do criptotrade,
    # com first_seen antigo — exatamente o campo que v3 e v5 perderam.
    await conn.execute(
        "INSERT INTO findings (id, rule, target, scope, severity, score, status, first_seen, last_seen, occurrences, payload)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("healthcheck_never_passed:dash", "healthcheck_never_passed", "criptotrade-dashboard",
         "container", "medium", 50, "open", "2026-01-02T03:04:05Z", "2026-07-29T10:00:00Z", 900, "{}"),
    )
    await conn.execute(
        "INSERT INTO findings (id, rule, target, scope, severity, score, status, first_seen, last_seen, occurrences, payload)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("http_plain:x", "http_plain", "executagent", "ingress", "critical", 95, "open",
         "2026-02-10T08:00:00Z", "2026-07-29T10:00:00Z", 120, "{}"),
    )
    await conn.execute(
        "INSERT INTO audit_log (action, project, result, token_label, ip, created_at)"
        " VALUES ('stop','giva','success','unlock','172.19.0.4','2026-07-01T12:00:00Z')"
    )
    await conn.execute(
        "INSERT INTO unlock_state (token, remote_user, ip, motivo, created_at)"
        " VALUES (?,?,?,?,?)",
        (STATIC_ENV_TOKEN, "admin", "172.19.0.4", "janela antiga", "2026-07-29T10:00:00Z"),
    )
    await conn.execute(
        "INSERT INTO host_samples VALUES ('2026-07-29T10:00:00Z', 12.5, 44.0, 100, 200, 60.0, 1.0)"
    )
    await conn.commit()
    await conn.close()


@pytest.mark.asyncio
async def test_v8_sobre_banco_populado_preserva_dado(tmp_path):
    """v7 populado → v8: findings, audit e samples intactos; first_seen intacto."""
    db_path = str(tmp_path / "populado.db")
    await _build_v7(db_path)
    os.environ["COCKPIT_DB"] = db_path
    import db as db_mod
    importlib.reload(db_mod)
    try:
        await db_mod.init_db()
        await db_mod.init_db()  # idempotencia: roda duas vezes seguidas
        await db_mod.close_db()

        conn = await aiosqlite.connect(db_path)
        # try/finally: assert falhando aqui deixaria a conexao aberta e o
        # pytest travaria no fim da suite sem mensagem nenhuma.
        try:
            await _checa_v8(conn)
        finally:
            await conn.close()
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


async def _checa_v8(conn):
        import db as db_mod
        cur = await conn.execute("SELECT MAX(version) FROM schema_version")
        # init_db aplica todas as migrations pendentes, nao para na v8
        assert (await cur.fetchone())[0] == db_mod.SCHEMA_VERSION

        cur = await conn.execute(
            "SELECT first_seen, last_seen, occurrences, severity FROM findings WHERE id = ?",
            ("healthcheck_never_passed:dash",),
        )
        row = await cur.fetchone()
        assert row is not None, "achado sumiu na v8"
        assert row[0] == "2026-01-02T03:04:05Z", "first_seen perdido — o defeito de v3/v5"
        assert row[1] == "2026-07-29T10:00:00Z"
        assert row[2] == 900
        assert row[3] == "medium"

        cur = await conn.execute("SELECT COUNT(*) FROM findings")
        assert (await cur.fetchone())[0] == 2

        cur = await conn.execute("SELECT action, project, ip FROM audit_log")
        assert list(await cur.fetchall()) == [("stop", "giva", "172.19.0.4")]

        cur = await conn.execute("SELECT COUNT(*) FROM host_samples")
        assert (await cur.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_v8_descarta_sessoes_do_token_estatico(tmp_path):
    """A sessao antiga NAO e migrada: carrega-la manteria a credencial viva."""
    db_path = str(tmp_path / "populado2.db")
    await _build_v7(db_path)
    os.environ["COCKPIT_DB"] = db_path
    import db as db_mod
    importlib.reload(db_mod)
    try:
        await db_mod.init_db()
        assert await db_mod.get_valid_unlock_session(STATIC_ENV_TOKEN) is None
        await db_mod.close_db()

        conn = await aiosqlite.connect(db_path)
        cur = await conn.execute("SELECT COUNT(*) FROM unlock_state")
        assert (await cur.fetchone())[0] == 0, "sessao do token estatico sobreviveu a v8"
        await conn.close()
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)
