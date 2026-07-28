import os
import aiosqlite
from datetime import datetime, timezone

_DB_PATH = os.getenv("COCKPIT_DB", "/data/cockpit.db")
_connection = None

def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _parse_row(row, desc):
    if row is None:
        return None
    cols = [d[0] for d in desc]
    return dict(zip(cols, row))

def _parse_rows(rows, desc):
    cols = [d[0] for d in desc]
    return [dict(zip(cols, r)) for r in rows]

async def get_db():
    global _connection
    if _connection is None:
        _connection = await aiosqlite.connect(_DB_PATH)
        _connection.row_factory = aiosqlite.Row
        await _connection.execute("PRAGMA journal_mode=WAL")
        await _connection.execute("PRAGMA foreign_keys=ON")
    return _connection

async def init_db():
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    cur = await db.execute("SELECT MAX(version) FROM schema_version")
    row = await cur.fetchone()
    current = row[0] if row and row[0] else 0
    migrations = [
        (1, [
            "CREATE TABLE IF NOT EXISTS findings ("
            "id TEXT PRIMARY KEY,"
            "rule TEXT NOT NULL,"
            "target TEXT NOT NULL,"
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
            ")",
            "CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status, score DESC)",
        ]),
        (2, [
            "ALTER TABLE findings ADD COLUMN targets TEXT",
        ]),
        (3, [
            "CREATE TABLE IF NOT EXISTS findings_v3 ("
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
            ")",
            "INSERT OR IGNORE INTO findings_v3 SELECT * FROM findings",
            "DROP TABLE findings",
            "ALTER TABLE findings_v3 RENAME TO findings",
            "CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status, score DESC)",
        ]),
    ]
    for ver, stmts in migrations:
        if ver > current:
            for stmt in stmts:
                await db.execute(stmt)
            await db.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (ver, _now()),
            )
    await db.commit()

async def close_db():
    global _connection
    if _connection:
        await _connection.close()
        _connection = None

async def upsert_finding(finding: dict) -> bool:
    db = await get_db()
    cur = await db.execute("SELECT * FROM findings WHERE id = ?", (finding["id"],))
    existing = await cur.fetchone()
    now = _now()
    targets_json = finding.get("targets")
    target_val = finding.get("target")
    if existing:
        existing = dict(existing)
        if existing["status"] == "resolved":
            resolved_at = existing.get("resolved_at")
            if resolved_at:
                try:
                    resolved_dt = datetime.fromisoformat(resolved_at.replace("Z", "+00:00"))
                    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
                    delta = (now_dt - resolved_dt).total_seconds()
                except Exception:
                    delta = 9999
                if delta < 1800:
                    await db.execute("""
                        UPDATE findings SET
                            last_seen = ?, status = 'open', resolved_at = NULL,
                            targets = ?, target = ?
                        WHERE id = ?
                    """, (now, targets_json, target_val, finding["id"]))
                    await db.commit()
                    return False
        await db.execute("""
            UPDATE findings SET
                last_seen = ?, occurrences = occurrences + 1, payload = ?,
                targets = ?, target = ?
            WHERE id = ?
        """, (now, finding.get("payload", "{}"), targets_json, target_val, finding["id"]))
        await db.commit()
        return False
    else:
        await db.execute("""
            INSERT INTO findings (id, rule, target, targets, scope, severity, score,
                caused_by, status, first_seen, last_seen, occurrences, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, 1, ?)
        """, (
            finding["id"], finding["rule"], target_val, targets_json,
            finding["scope"], finding["severity"], finding.get("score", 0),
            finding.get("caused_by"), now, now, finding.get("payload", "{}"),
        ))
        await db.commit()
        return True

async def resolve_finding(finding_id: str):
    db = await get_db()
    now = _now()
    await db.execute("""
        UPDATE findings SET status = 'resolved', resolved_at = ?
        WHERE id = ? AND status != 'resolved'
    """, (now, finding_id))
    await db.commit()

async def get_findings(status=None, scope=None):
    db = await get_db()
    parts = ["SELECT * FROM findings WHERE 1=1"]
    params = []
    if status:
        parts.append("AND status = ?")
        params.append(status)
    if scope:
        parts.append("AND scope = ?")
        params.append(scope)
    parts.append("ORDER BY score DESC, last_seen DESC")
    cur = await db.execute(" ".join(parts), params)
    rows = await cur.fetchall()
    return _parse_rows(rows, cur.description)

async def get_finding(finding_id: str):
    db = await get_db()
    cur = await db.execute("SELECT * FROM findings WHERE id = ?", (finding_id,))
    row = await cur.fetchone()
    return _parse_row(row, cur.description)
