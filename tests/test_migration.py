import os
import pytest
import tempfile
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _populate_v1_to_v4(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "action TEXT NOT NULL,"
        "project TEXT NOT NULL,"
        "result TEXT NOT NULL,"
        "token_label TEXT NOT NULL DEFAULT '',"
        "ip TEXT NOT NULL DEFAULT '',"
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS findings ("
        "id TEXT PRIMARY KEY,"
        "rule TEXT NOT NULL,"
        "target TEXT,"
        "targets TEXT,"
        "scope TEXT NOT NULL,"
        "severity TEXT NOT NULL,"
        "score INTEGER NOT NULL,"
        "caused_by TEXT,"
        "status TEXT NOT NULL DEFAULT 'open',"
        "ack_reason TEXT,"
        "ack_note TEXT,"
        "ack_until TEXT,"
        "first_seen TEXT NOT NULL,"
        "last_seen TEXT NOT NULL,"
        "resolved_at TEXT,"
        "occurrences INTEGER NOT NULL DEFAULT 1,"
        "payload TEXT NOT NULL"
        ")"
    )
    for v in range(1, 5):
        conn.execute("INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)", (v, _now()))
    for i in range(10):
        conn.execute(
            "INSERT OR IGNORE INTO findings (id, rule, target, scope, severity, score, first_seen, last_seen, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"finding-{i:03d}", f"rule-{i}", f"target-{i}", "container", "high", 50 + i, _now(), _now(), "{}"),
        )
    for i in range(8):
        conn.execute(
            "INSERT INTO audit_log (action, project, result, token_label, ip, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (f"action-{i}", f"proj-{i}", "success", "admin", "10.0.0.1", _now()),
        )
    conn.commit()
    conn.close()


_DB_PATH_BACKUP = None

def _reset_db(path):
    import db as _db
    global _DB_PATH_BACKUP
    if _DB_PATH_BACKUP is None:
        _DB_PATH_BACKUP = _db._DB_PATH
    _db._connection = None
    _db._DB_PATH = path


def _restore_db():
    import db as _db
    if _DB_PATH_BACKUP:
        _db._connection = None
        _db._DB_PATH = _DB_PATH_BACKUP


def test_migration_v5_preserves_data():
    """init_db sobre banco v1-v4 populado preserva 10 findings + 8 audit."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _populate_v1_to_v4(path)
    _reset_db(path)

    try:
        async def run():
            from db import init_db, close_db
            await init_db()

            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row

            cur = conn.execute("SELECT COUNT(*) as cnt FROM findings")
            assert cur.fetchone()["cnt"] == 10

            cur = conn.execute("SELECT COUNT(*) as cnt FROM findings WHERE first_seen IS NULL")
            assert cur.fetchone()["cnt"] == 0

            for i in range(10):
                cur = conn.execute("SELECT id, first_seen FROM findings WHERE id = ?", (f"finding-{i:03d}",))
                row = cur.fetchone()
                assert row is not None
                assert row["first_seen"] is not None

            cur = conn.execute("SELECT COUNT(*) as cnt FROM audit_log")
            assert cur.fetchone()["cnt"] == 8

            cur = conn.execute("SELECT MAX(version) as v FROM schema_version")
            assert cur.fetchone()["v"] >= 5

            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='unlock_state'")
            assert cur.fetchone() is not None

            conn.close()
            await close_db()

        asyncio.run(run())
    finally:
        _restore_db()
        try:
            os.unlink(path)
        except Exception:
            pass


def _populate_v1_to_v5(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "action TEXT NOT NULL,"
        "project TEXT NOT NULL,"
        "result TEXT NOT NULL,"
        "token_label TEXT NOT NULL DEFAULT '',"
        "ip TEXT NOT NULL DEFAULT '',"
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS findings ("
        "id TEXT PRIMARY KEY,"
        "rule TEXT NOT NULL,"
        "target TEXT,"
        "targets TEXT,"
        "scope TEXT NOT NULL,"
        "severity TEXT NOT NULL,"
        "score INTEGER NOT NULL,"
        "caused_by TEXT,"
        "status TEXT NOT NULL DEFAULT 'open',"
        "ack_reason TEXT,"
        "ack_note TEXT,"
        "ack_until TEXT,"
        "first_seen TEXT NOT NULL,"
        "last_seen TEXT NOT NULL,"
        "resolved_at TEXT,"
        "occurrences INTEGER NOT NULL DEFAULT 1,"
        "payload TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS unlock_state ("
        "token TEXT PRIMARY KEY,"
        "remote_user TEXT NOT NULL DEFAULT '',"
        "ip TEXT NOT NULL DEFAULT '',"
        "motivo TEXT NOT NULL DEFAULT '',"
        "created_at TEXT NOT NULL"
        ")"
    )
    for v in range(1, 6):
        conn.execute("INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)", (v, _now()))
    for i in range(12):
        conn.execute(
            "INSERT OR IGNORE INTO findings (id, rule, target, scope, severity, score, first_seen, last_seen, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"finding-{i:03d}", f"rule-{i}", f"target-{i}", "container", "high", 50 + i, _now(), _now(), "{}"),
        )
    for i in range(8):
        conn.execute(
            "INSERT INTO audit_log (action, project, result, token_label, ip, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (f"action-{i}", f"proj-{i}", "success", "admin", "10.0.0.1", _now()),
        )
    conn.execute(
        "INSERT INTO unlock_state (token, remote_user, ip, motivo, created_at) VALUES (?, ?, ?, ?, ?)",
        ("token-001", "admin", "10.0.0.1", "manutencao", _now()),
    )
    conn.commit()
    conn.close()


def test_migration_v7_fresh_db():
    """init_db sobre banco vazio cria todas as tabelas e schema v7."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _reset_db(path)

    try:
        async def run():
            from db import init_db, close_db
            await init_db()

            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row

            cur = conn.execute("SELECT MAX(version) as v FROM schema_version")
            assert cur.fetchone()["v"] == 7

            for tbl in ("findings", "audit_log", "unlock_state", "host_samples", "container_samples", "api_telemetry"):
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,))
                assert cur.fetchone() is not None, f"Tabela {tbl} nao criada"

            conn.close()
            await close_db()

        asyncio.run(run())
    finally:
        _restore_db()
        try:
            os.unlink(path)
        except Exception:
            pass


def test_migration_v6_banco_populado():
    """init_db sobre banco v5 populado preserva 12 findings + 8 audit + 1 unlock."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _populate_v1_to_v5(path)

    # Snapshot counts antes da migracao
    conn_before = sqlite3.connect(path)
    conn_before.row_factory = sqlite3.Row
    cur = conn_before.execute("SELECT COUNT(*) as cnt FROM findings")
    findings_before = cur.fetchone()["cnt"]
    cur = conn_before.execute("SELECT COUNT(*) as cnt FROM audit_log")
    audit_before = cur.fetchone()["cnt"]
    cur = conn_before.execute("SELECT COUNT(*) as cnt FROM unlock_state")
    unlock_before = cur.fetchone()["cnt"]
    cur = conn_before.execute("SELECT id, first_seen FROM findings ORDER BY id")
    first_seens_before = {r["id"]: r["first_seen"] for r in cur.fetchall()}
    cur = conn_before.execute("SELECT MAX(version) as v FROM schema_version")
    version_before = cur.fetchone()["v"]
    conn_before.close()

    assert findings_before == 12
    assert audit_before == 8
    assert unlock_before == 1
    assert version_before == 5

    _reset_db(path)

    try:
        async def run():
            from db import init_db, close_db
            await init_db()

            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row

            # Contagens intactas
            cur = conn.execute("SELECT COUNT(*) as cnt FROM findings")
            assert cur.fetchone()["cnt"] == findings_before, "findings perdidos na migracao"

            cur = conn.execute("SELECT COUNT(*) as cnt FROM audit_log")
            assert cur.fetchone()["cnt"] == audit_before, "audit_log perdido na migracao"

            cur = conn.execute("SELECT COUNT(*) as cnt FROM unlock_state")
            assert cur.fetchone()["cnt"] == unlock_before, "unlock_state perdido na migracao"

            # first_seen preservado
            cur = conn.execute("SELECT id, first_seen FROM findings ORDER BY id")
            for row in cur.fetchall():
                assert row["first_seen"] == first_seens_before[row["id"]], (
                    f"first_seen alterado para {row['id']}: {row['first_seen']} != {first_seens_before[row['id']]}"
                )
                assert row["first_seen"] is not None

            # Schema agora em v7
            cur = conn.execute("SELECT MAX(version) as v FROM schema_version")
            assert cur.fetchone()["v"] == 7

            # Novas tabelas existem
            for tbl in ("host_samples", "container_samples", "api_telemetry"):
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,))
                assert cur.fetchone() is not None, f"Tabela {tbl} nao criada"

            conn.close()
            await close_db()

        asyncio.run(run())
    finally:
        _restore_db()
        try:
            os.unlink(path)
        except Exception:
            pass


def test_cleanup_expired_sessions():
    """cleanup_expired_sessions apaga apenas sessoes vencidas."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _reset_db(path)

    try:
        async def run():
            from db import init_db, close_db, cleanup_expired_sessions, get_db
            await init_db()

            db = await get_db()
            old_ts = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat().replace("+00:00", "Z")
            mid_ts = (datetime.now(timezone.utc) - timedelta(minutes=35)).isoformat().replace("+00:00", "Z")
            fresh_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
            for ts, lbl in [(old_ts, "expired-45"), (mid_ts, "expired-35"), (fresh_ts, "valid")]:
                await db.execute(
                    "INSERT INTO unlock_state (token, remote_user, ip, motivo, created_at) VALUES (?, ?, ?, ?, ?)",
                    (f"token-{lbl}", "admin", "", lbl, ts),
                )
            await db.commit()

            await cleanup_expired_sessions()

            cur = await db.execute("SELECT motivo FROM unlock_state ORDER BY created_at DESC")
            rows = await cur.fetchall()
            motivos = [dict(r)["motivo"] for r in rows]
            assert motivos == ["valid"], f"Expected only 'valid', got {motivos}"

            await close_db()

        asyncio.run(run())
    finally:
        _restore_db()
        try:
            os.unlink(path)
        except Exception:
            pass
