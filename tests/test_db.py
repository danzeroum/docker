import os
import pytest
import aiosqlite

pytestmark = pytest.mark.asyncio


async def test_init_db_cria_esquema(tmp_path):
    db_path = str(tmp_path / "test.db")
    os.environ["COCKPIT_DB"] = db_path

    import importlib
    import db as db_mod
    importlib.reload(db_mod)

    try:
        await db_mod.init_db()

        conn = await aiosqlite.connect(db_path)
        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in await cur.fetchall()]
        await conn.close()

        assert "schema_version" in tables, "schema_version table missing after first init"
        assert "findings" in tables, "findings table missing after first init"

        await db_mod.init_db()

        conn2 = await aiosqlite.connect(db_path)
        cur2 = await conn2.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables2 = [r[0] for r in await cur2.fetchall()]
        await conn2.close()

        assert "schema_version" in tables2
        assert "findings" in tables2

        await db_mod.close_db()
    finally:
        del os.environ["COCKPIT_DB"]
