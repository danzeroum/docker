import os
import aiosqlite
from datetime import datetime, timedelta, timezone

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
            "INSERT OR IGNORE INTO findings_v3 "
            "(id, rule, target, scope, severity, score, caused_by, status, "
            "ack_reason, ack_note, ack_until, first_seen, last_seen, "
            "resolved_at, occurrences, payload) "
            "SELECT id, rule, target, scope, severity, score, caused_by, "
            "status, ack_reason, ack_note, ack_until, first_seen, last_seen, "
            "resolved_at, occurrences, payload FROM findings",
            "DROP TABLE findings",
            "ALTER TABLE findings_v3 RENAME TO findings",
            "CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status, score DESC)",
        ]),
        (4, [
            "CREATE TABLE IF NOT EXISTS audit_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "action TEXT NOT NULL,"
            "project TEXT NOT NULL,"
            "result TEXT NOT NULL,"
            "token_label TEXT NOT NULL DEFAULT '',"
            "ip TEXT NOT NULL DEFAULT '',"
            "created_at TEXT NOT NULL"
            ")",
        ]),
        (5, [
            "CREATE TABLE IF NOT EXISTS unlock_state ("
            "token TEXT PRIMARY KEY,"
            "remote_user TEXT NOT NULL DEFAULT '',"
            "ip TEXT NOT NULL DEFAULT '',"
            "motivo TEXT NOT NULL DEFAULT '',"
            "created_at TEXT NOT NULL"
            ")",
        ]),
        (6, [
            "CREATE TABLE IF NOT EXISTS host_samples ("
            "sampled_at TEXT PRIMARY KEY,"
            "cpu_pct REAL NOT NULL,"
            "mem_pct REAL NOT NULL,"
            "mem_used INTEGER NOT NULL,"
            "mem_total INTEGER NOT NULL,"
            "disk_pct REAL NOT NULL,"
            "swap_pct REAL NOT NULL DEFAULT 0"
            ")",
            "CREATE TABLE IF NOT EXISTS container_samples ("
            "sampled_at TEXT NOT NULL,"
            "container_id TEXT NOT NULL,"
            "name TEXT NOT NULL,"
            "cpu_pct REAL NOT NULL DEFAULT 0,"
            "mem_usage INTEGER NOT NULL DEFAULT 0,"
            "mem_limit INTEGER,"
            "PRIMARY KEY (sampled_at, container_id)"
            ")",
        ]),
        (7, [
            "CREATE TABLE IF NOT EXISTS api_telemetry ("
            "route TEXT NOT NULL,"
            "hour TEXT NOT NULL,"
            "total INTEGER NOT NULL DEFAULT 0,"
            "errors INTEGER NOT NULL DEFAULT 0,"
            "durations_total REAL NOT NULL DEFAULT 0,"
            "durations_squared REAL NOT NULL DEFAULT 0,"
            "durations_max REAL NOT NULL DEFAULT 0,"
            "PRIMARY KEY (route, hour)"
            ")",
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

async def ack_finding(finding_id: str, reason: str, note: str = "", until: str = ""):
    db = await get_db()
    now = _now()
    ack_until = until or ""
    await db.execute("""
        UPDATE findings SET status = 'acked', ack_reason = ?, ack_note = ?, ack_until = ?, last_seen = ?
        WHERE id = ? AND status != 'resolved'
    """, (reason, note, ack_until, now, finding_id))
    await db.commit()

async def add_audit_entry(action: str, project: str, result: str, token_label: str = "", ip: str = ""):
    db = await get_db()
    now = _now()
    await db.execute(
        "INSERT INTO audit_log (action, project, result, token_label, ip, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (action, project, result, token_label, ip, now),
    )
    await db.commit()

async def get_audit_log(limit: int = 100):
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    rows = await cur.fetchall()
    return _parse_rows(rows, cur.description)

async def cleanup_expired_sessions():
    db = await get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    await db.execute("DELETE FROM unlock_state WHERE created_at < ?", (cutoff,))
    await db.commit()

async def set_unlock_state(token: str, remote_user: str, ip: str, motivo: str):
    db = await get_db()
    now = _now()
    await cleanup_expired_sessions()
    await db.execute(
        "INSERT OR REPLACE INTO unlock_state (token, remote_user, ip, motivo, created_at) VALUES (?, ?, ?, ?, ?)",
        (token, remote_user, ip, motivo, now),
    )
    await db.commit()

async def get_valid_unlock_session(token: str):
    await cleanup_expired_sessions()
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM unlock_state WHERE token = ?",
        (token,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    session = dict(row)
    try:
        created = datetime.fromisoformat(session["created_at"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if (now - created).total_seconds() > 1800:
            return None
    except Exception:
        return None
    return session


async def insert_host_sample(sample: dict):
    db = await get_db()
    cpu = sample.get("cpu", {}) or {}
    mem = sample.get("memory", {}) or {}
    swap = sample.get("swap", {}) or {}
    disks = sample.get("disks", []) or []
    root = next((d for d in disks if d.get("mountpoint") == "/"), None) or (disks[0] if disks else {})
    sampled_at = sample.get("sampled_at", _now())
    await db.execute(
        "INSERT OR IGNORE INTO host_samples (sampled_at, cpu_pct, mem_pct, mem_used, mem_total, disk_pct, swap_pct)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            sampled_at,
            round(cpu.get("percent", 0), 1),
            round(mem.get("percent", 0), 1),
            mem.get("used", 0) or 0,
            mem.get("total", 0) or 0,
            round(root.get("percent", 0), 1),
            round(swap.get("percent", 0), 1),
        ),
    )
    await db.commit()


async def insert_container_samples(stats: dict):
    db = await get_db()
    now = _now()
    for cid, data in stats.items():
        if not isinstance(data, dict):
            continue
        name = data.get("inspect", {}) if isinstance(data.get("inspect"), dict) else {}
        cname = ""
        if isinstance(name, dict):
            cname = ((name.get("Name") or "").lstrip("/") or "")
        mem_limit = data.get("mem_limit")
        await db.execute(
            "INSERT OR IGNORE INTO container_samples (sampled_at, container_id, name, cpu_pct, mem_usage, mem_limit)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                now,
                cid,
                cname,
                round(data.get("cpu_pct", 0), 1),
                data.get("mem_usage", 0) or 0,
                mem_limit if mem_limit and mem_limit > 0 else None,
            ),
        )
    await db.commit()


async def purge_samples():
    db = await get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    await db.execute("DELETE FROM host_samples WHERE sampled_at < ?", (cutoff,))
    await db.execute("DELETE FROM container_samples WHERE sampled_at < ?", (cutoff,))
    await db.commit()


async def get_host_series(metric: str, days: int = 30, step: str = "1d") -> list:
    db = await get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    col = {"cpu_pct": "cpu_pct", "mem_pct": "mem_pct", "disk_pct": "disk_pct", "swap_pct": "swap_pct"}.get(metric, "disk_pct")
    if step == "1d":
        cur = await db.execute(
            f"SELECT DATE(sampled_at) AS ts, ROUND(AVG({col}), 2) AS v"
            " FROM host_samples WHERE sampled_at >= ?"
            " GROUP BY DATE(sampled_at) ORDER BY ts",
            (cutoff,),
        )
    else:
        cur = await db.execute(
            f"SELECT sampled_at AS ts, {col} AS v FROM host_samples WHERE sampled_at >= ? ORDER BY sampled_at",
            (cutoff,),
        )
    rows = await cur.fetchall()
    return [{"ts": r[0], "v": r[1]} for r in rows]


async def get_container_samples_since(hours: int = 24):
    db = await get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    cur = await db.execute(
        "SELECT container_id, name, MAX(cpu_pct) as cpu_pct,"
        " AVG(mem_usage) as mem_usage, MAX(mem_limit) as mem_limit"
        " FROM container_samples WHERE sampled_at >= ?"
        " GROUP BY container_id ORDER BY name",
        (cutoff,),
    )
    rows = await cur.fetchall()
    return _parse_rows(rows, cur.description)


async def get_first_sample_time():
    db = await get_db()
    cur = await db.execute("SELECT MIN(sampled_at) FROM host_samples")
    row = await cur.fetchone()
    return row[0] if row and row[0] else None


async def flush_telemetry(hist: dict):
    """Flush in-memory histogram to api_telemetry table."""
    db = await get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00:00Z")
    for key, vals in hist.items():
        if not vals:
            continue
        n = len(vals)
        errors = sum(1 for v in vals if v[1] >= 400 or v[1] == 0)
        total_dur = sum(v[2] for v in vals)
        sq_dur = sum(v[2] * v[2] for v in vals)
        max_dur = max(v[2] for v in vals)
        route = key
        await db.execute(
            "INSERT INTO api_telemetry (route, hour, total, errors, durations_total, durations_squared, durations_max)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(route, hour) DO UPDATE SET"
            " total = total + ?, errors = errors + ?, durations_total = durations_total + ?,"
            " durations_squared = durations_squared + ?, durations_max = MAX(durations_max, ?)",
            (route, now, n, errors, total_dur, sq_dur, max_dur, n, errors, total_dur, sq_dur, max_dur),
        )
    await db.commit()


async def get_telemetry_summary(hours: int = 1):
    """Return aggregate telemetry per route for recent hours."""
    db = await get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:00:00Z")
    cur = await db.execute(
        "SELECT route, SUM(total) as total, SUM(errors) as errors,"
        " SUM(durations_total) as dur_sum, SUM(durations_squared) as dur_sq, MAX(durations_max) as dur_max"
        " FROM api_telemetry WHERE hour >= ?"
        " GROUP BY route ORDER BY total DESC",
        (cutoff,),
    )
    rows = await cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        n = d["total"] or 0
        dur = d.pop("dur_sum", 0) or 0
        dur_sq = d.pop("dur_sq", 0) or 0
        d["avg_ms"] = round((dur / n) * 1000, 1) if n else 0
        d["p95_ms"] = round(((dur_sq / n) ** 0.5) * 1000, 1) if n else 0
        d["dur_max_ms"] = round((d.pop("dur_max", 0) or 0) * 1000, 1)
        d["error_rate"] = round((d["errors"] / n) * 100, 1) if n else 0
        result.append(d)
    return result
