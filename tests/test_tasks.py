"""Fatia 1 — Tarefas: migration v9, ciclo achado->cartao e limite de escrita.

O ciclo e o que tem risco real:
  - supersede NAO pode fechar cartao (o problema continua vivo);
  - reabertura em <30min tem de trazer o cartao de volta, sem duplicar;
  - cartao manual nunca e movido pelo motor.
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


RESTART_ID = "restart_loop.painel-x"
OOM_ID = "oom.painel-x"


async def _fresh_db(tmp_path, nome="tasks.db"):
    os.environ["COCKPIT_DB"] = str(tmp_path / nome)
    import db as db_mod
    importlib.reload(db_mod)
    await db_mod.init_db()
    return db_mod


def _achado(fid, rule, target, payload="{}"):
    return {
        "id": fid, "rule": rule, "target": target, "scope": "container",
        "severity": "critical", "score": 90, "payload": payload,
    }


# ---------------------------------------------------------------------------
# upsert_finding passou a relatar o que aconteceu
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_relata_created_updated_reopened(tmp_path):
    db_mod = await _fresh_db(tmp_path)
    try:
        assert await db_mod.upsert_finding(_achado(RESTART_ID, "restart_loop", "painel-x")) == "created"
        assert await db_mod.upsert_finding(_achado(RESTART_ID, "restart_loop", "painel-x")) == "updated"
        await db_mod.resolve_finding(RESTART_ID)
        # resolvido ha instantes -> dentro da janela de 30 min
        assert await db_mod.upsert_finding(_achado(RESTART_ID, "restart_loop", "painel-x")) == "reopened"
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


# ---------------------------------------------------------------------------
# sincronia achado -> cartao (camada de persistencia)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cartao_auto_e_idempotente(tmp_path):
    """O motor chama a cada 10s — nao pode acumular cartao."""
    db_mod = await _fresh_db(tmp_path)
    try:
        f = {"id": RESTART_ID, "rule": "restart_loop", "target": "painel-x", "title": "t"}
        a = await db_mod.create_task_from_finding(f)
        b = await db_mod.create_task_from_finding(f)
        c = await db_mod.create_task_from_finding(f)
        assert a["id"] == b["id"] == c["id"]
        assert len(await db_mod.get_tasks()) == 1
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_resolver_move_so_o_cartao_vinculado(tmp_path):
    """Aceite: cartao manual do mesmo alvo fica onde esta."""
    db_mod = await _fresh_db(tmp_path)
    try:
        await db_mod.create_task_from_finding(
            {"id": RESTART_ID, "rule": "restart_loop", "target": "painel-x", "title": "auto"})
        manual = await db_mod.create_task(
            title="conferir o painel a mao", origem="manual", target="painel-x", col="doing")
        outro_auto = await db_mod.create_task_from_finding(
            {"id": OOM_ID, "rule": "oom", "target": "painel-x", "title": "outro"})

        await db_mod.resolve_task_for_finding(RESTART_ID)

        cartoes = {t["id"]: t for t in await db_mod.get_tasks()}
        auto = next(t for t in cartoes.values() if t["finding_id"] == RESTART_ID)
        assert auto["col"] == "done"
        assert "nao reincide" in auto["note"]
        assert cartoes[manual["id"]]["col"] == "doing", "cartao manual foi movido pelo sistema"
        assert cartoes[outro_auto["id"]]["col"] == "todo", "cartao de outro achado foi movido"
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_manual_vinculado_a_achado_nao_e_movido(tmp_path):
    """origem e COLUNA: manual com finding_id preenchido continua manual."""
    db_mod = await _fresh_db(tmp_path)
    try:
        manual = await db_mod.create_task(
            title="decidido tratar depois", origem="manual",
            finding_id=RESTART_ID, col="blocked")
        await db_mod.resolve_task_for_finding(RESTART_ID)
        assert (await db_mod.get_task(manual["id"]))["col"] == "blocked"
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_reabertura_traz_de_done_para_doing_sem_duplicar(tmp_path):
    db_mod = await _fresh_db(tmp_path)
    try:
        f = {"id": RESTART_ID, "rule": "restart_loop", "target": "painel-x", "title": "t"}
        await db_mod.create_task_from_finding(f)
        await db_mod.resolve_task_for_finding(RESTART_ID)
        assert (await db_mod.get_auto_task_for_finding(RESTART_ID))["col"] == "done"

        movidos = await db_mod.reopen_task_for_finding(RESTART_ID)
        assert movidos == 1
        cartoes = await db_mod.get_tasks()
        assert len(cartoes) == 1, "reabertura duplicou o cartao"
        assert cartoes[0]["col"] == "doing"
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


# ---------------------------------------------------------------------------
# o gancho no motor: supersedido != resolvido
# ---------------------------------------------------------------------------

def _mod_falso(auto_task=True):
    class M:
        AUTO_TASK = auto_task
    return M()


@pytest.mark.asyncio
async def test_sync_task_cria_so_para_regra_com_auto_task(tmp_path):
    db_mod = await _fresh_db(tmp_path)
    try:
        import findings.engine as eng
        importlib.reload(eng)
        f = _achado(RESTART_ID, "restart_loop", "painel-x")

        await eng._sync_task(_mod_falso(False), f, {"title": "x"}, "created")
        assert await db_mod.get_tasks() == []

        await eng._sync_task(_mod_falso(True), f, {"title": "x"}, "created")
        assert len(await db_mod.get_tasks()) == 1

        # "updated" e so mais uma observacao — nao mexe em nada
        await eng._sync_task(_mod_falso(True), f, {"title": "x"}, "updated")
        assert len(await db_mod.get_tasks()) == 1
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_supersedido_nao_fecha_cartao(tmp_path):
    """Aceite: restart_loop suplantado por oom -> cartao segue aberto.

    Reproduz o final do ciclo do motor: o achado suplantado esta em seen_ids,
    entao passa pelo resolve de supersede e NAO pelo de desaparecimento.
    """
    db_mod = await _fresh_db(tmp_path)
    try:
        import findings.engine as eng
        importlib.reload(eng)

        await db_mod.upsert_finding(_achado(RESTART_ID, "restart_loop", "painel-x"))
        await eng._sync_task(_mod_falso(True), _achado(RESTART_ID, "restart_loop", "painel-x"),
                             {"title": "reinicio em laco"}, "created")
        assert (await db_mod.get_auto_task_for_finding(RESTART_ID))["col"] == "todo"

        # o motor suprime o suplantado
        await db_mod.resolve_finding(RESTART_ID)

        cartao = await db_mod.get_auto_task_for_finding(RESTART_ID)
        assert cartao["col"] != "done", "supersede fechou cartao com o problema vivo"
        assert cartao["col"] == "todo"
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_desaparecimento_fecha_e_reabertura_devolve(tmp_path):
    """resolve -> reopen: um cartao, em doing, sem orfao em done."""
    db_mod = await _fresh_db(tmp_path)
    try:
        import findings.engine as eng
        importlib.reload(eng)
        f = _achado(RESTART_ID, "restart_loop", "painel-x")

        estado = await db_mod.upsert_finding(f)
        await eng._sync_task(_mod_falso(True), f, {"title": "t"}, estado)

        # achado sumiu do ciclo: resolve + fecha o cartao
        await db_mod.resolve_finding(RESTART_ID)
        await db_mod.resolve_task_for_finding(RESTART_ID)
        assert (await db_mod.get_auto_task_for_finding(RESTART_ID))["col"] == "done"

        # voltou dentro dos 30 min
        estado = await db_mod.upsert_finding(f)
        assert estado == "reopened"
        await eng._sync_task(_mod_falso(True), f, {"title": "t"}, estado)

        cartoes = await db_mod.get_tasks()
        assert len(cartoes) == 1, "reabertura duplicou cartao"
        assert cartoes[0]["col"] == "doing", "cartao ficou orfao em done"
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_reabertura_sem_cartao_previo_cria(tmp_path):
    """Regra ganhou AUTO_TASK depois do achado ja existir."""
    db_mod = await _fresh_db(tmp_path)
    try:
        import findings.engine as eng
        importlib.reload(eng)
        f = _achado(RESTART_ID, "restart_loop", "painel-x")
        await eng._sync_task(_mod_falso(True), f, {"title": "t"}, "reopened")
        cartoes = await db_mod.get_tasks()
        assert len(cartoes) == 1
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


# ---------------------------------------------------------------------------
# migration v9 sobre banco POPULADO
# ---------------------------------------------------------------------------

async def _build_v8(db_path):
    """Banco no estado v8, com dado dentro."""
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
        "CREATE TABLE unlock_state (token_hash TEXT PRIMARY KEY, remote_user TEXT NOT NULL DEFAULT '',"
        "ip TEXT NOT NULL DEFAULT '', motivo TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,"
        "expires_at TEXT NOT NULL)"
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
    for v in range(1, 9):
        await conn.execute("INSERT INTO schema_version VALUES (?, ?)", (v, "2026-01-01T00:00:00Z"))

    for i in range(6):
        await conn.execute(
            "INSERT INTO findings (id, rule, target, scope, severity, score, status, first_seen,"
            " last_seen, occurrences, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"regra-{i}.alvo-{i}", f"regra-{i}", f"alvo-{i}", "container", "high", 70 + i,
             "open", f"2026-0{i+1}-02T03:04:05Z", "2026-07-29T10:00:00Z", 100 + i, "{}"),
        )
    for i in range(4):
        await conn.execute(
            "INSERT INTO audit_log (action, project, result, token_label, ip, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (f"acao-{i}", f"proj-{i}", "success", "admin", "172.19.0.4", "2026-07-01T12:00:00Z"),
        )
    await conn.execute(
        "INSERT INTO unlock_state VALUES ('hash-x','admin','172.19.0.4','janela',"
        "'2026-07-29T10:00:00Z','2099-01-01T00:00:00Z')"
    )
    await conn.execute(
        "INSERT INTO host_samples VALUES ('2026-07-29T10:00:00Z', 12.5, 44.0, 100, 200, 60.0, 1.0)"
    )
    await conn.execute(
        "INSERT INTO container_samples VALUES ('2026-07-29T10:00:00Z','c1','painel-x',3.0,50,100)"
    )
    await conn.commit()
    await conn.close()


@pytest.mark.asyncio
async def test_v9_sobre_banco_populado_preserva_tudo(tmp_path):
    db_path = str(tmp_path / "populado_v9.db")
    await _build_v8(db_path)
    os.environ["COCKPIT_DB"] = db_path
    import db as db_mod
    importlib.reload(db_mod)
    try:
        await db_mod.init_db()
        await db_mod.init_db()  # idempotencia
        await db_mod.close_db()

        conn = await aiosqlite.connect(db_path)
        cur = await conn.execute("SELECT MAX(version) FROM schema_version")
        assert (await cur.fetchone())[0] == 9

        cur = await conn.execute("SELECT COUNT(*) FROM findings")
        assert (await cur.fetchone())[0] == 6
        cur = await conn.execute("SELECT id, first_seen FROM findings ORDER BY id")
        for i, (fid, first_seen) in enumerate(await cur.fetchall()):
            assert first_seen == f"2026-0{i+1}-02T03:04:05Z", f"first_seen alterado em {fid}"

        cur = await conn.execute("SELECT COUNT(*) FROM audit_log")
        assert (await cur.fetchone())[0] == 4
        cur = await conn.execute("SELECT COUNT(*) FROM unlock_state")
        assert (await cur.fetchone())[0] == 1, "sessao viva perdida na v9"
        cur = await conn.execute("SELECT COUNT(*) FROM host_samples")
        assert (await cur.fetchone())[0] == 1
        cur = await conn.execute("SELECT COUNT(*) FROM container_samples")
        assert (await cur.fetchone())[0] == 1

        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
        assert await cur.fetchone() is not None
        await conn.close()
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_indice_unico_impede_dois_cartoes_auto(tmp_path):
    db_mod = await _fresh_db(tmp_path)
    try:
        await db_mod.create_task(title="a", origem="auto", finding_id=RESTART_ID)
        with pytest.raises(aiosqlite.IntegrityError):
            await db_mod.create_task(title="b", origem="auto", finding_id=RESTART_ID)
        # manual nao entra no indice parcial: pode conviver com o auto
        await db_mod.create_task(title="c", origem="manual", finding_id=RESTART_ID)
        assert len(await db_mod.get_tasks()) == 2
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


# ---------------------------------------------------------------------------
# reabertura depois dos 30 min — o achado sumia da fila para sempre
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_achado_reabre_mesmo_depois_de_30_min(tmp_path):
    """Encontrado em producao: 22 achados de ingress presos em `resolved`.

    A regra voltou a emitir, last_seen e occurrences avancavam, e o status
    ficava `resolved` — o problema era atual e invisivel na fila.
    """
    db_mod = await _fresh_db(tmp_path)
    try:
        f = _achado("http_plain.exemplo.com", "http_plain", "exemplo.com")
        await db_mod.upsert_finding(f)
        await db_mod.resolve_finding("http_plain.exemplo.com")

        # empurra o resolved_at para duas horas atras
        conn = await db_mod.get_db()
        antigo = "2020-01-01T00:00:00Z"
        await conn.execute(
            "UPDATE findings SET resolved_at = ? WHERE id = ?",
            (antigo, "http_plain.exemplo.com"),
        )
        await conn.commit()

        estado = await db_mod.upsert_finding(f)
        assert estado == "reopened", f"voltou como {estado}, nao reabriu"
        atual = await db_mod.get_finding("http_plain.exemplo.com")
        assert atual["status"] == "open", "achado seguiu resolved com o problema vivo"
        assert atual["resolved_at"] is None
        assert [x["id"] for x in await db_mod.get_findings(status="open")] == ["http_plain.exemplo.com"]
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_reabertura_longe_reinicia_first_seen(tmp_path):
    """Incidente novo: dizer que existe 'desde ha duas semanas' inventa duracao."""
    db_mod = await _fresh_db(tmp_path)
    try:
        f = _achado("oom.painel", "oom", "painel")
        await db_mod.upsert_finding(f)
        primeiro = (await db_mod.get_finding("oom.painel"))["first_seen"]
        await db_mod.resolve_finding("oom.painel")
        conn = await db_mod.get_db()
        await conn.execute("UPDATE findings SET resolved_at = ? WHERE id = ?",
                           ("2020-01-01T00:00:00Z", "oom.painel"))
        await conn.commit()

        await db_mod.upsert_finding(f)
        atual = await db_mod.get_finding("oom.painel")
        assert atual["first_seen"] != primeiro, "first_seen do incidente antigo sobreviveu"
        assert atual["occurrences"] == 1, "contagem do incidente antigo sobreviveu"
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_reabertura_perto_preserva_first_seen(tmp_path):
    """Oscilacao do mesmo problema: a duracao segue contando do inicio."""
    db_mod = await _fresh_db(tmp_path)
    try:
        f = _achado("unhealthy.api", "unhealthy", "api")
        await db_mod.upsert_finding(f)
        primeiro = (await db_mod.get_finding("unhealthy.api"))["first_seen"]
        await db_mod.resolve_finding("unhealthy.api")

        estado = await db_mod.upsert_finding(f)
        assert estado == "reopened"
        atual = await db_mod.get_finding("unhealthy.api")
        assert atual["first_seen"] == primeiro, "oscilacao reiniciou a duracao"
        assert atual["status"] == "open"
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_cartao_volta_quando_o_achado_reabre_tarde(tmp_path):
    """O ciclo da v9 depende de "reopened"; sem ele o cartao ficava orfao."""
    db_mod = await _fresh_db(tmp_path)
    try:
        import findings.engine as eng
        importlib.reload(eng)
        f = _achado(RESTART_ID, "restart_loop", "painel-x")
        estado = await db_mod.upsert_finding(f)
        await eng._sync_task(_mod_falso(True), f, {"title": "t"}, estado)
        await db_mod.resolve_finding(RESTART_ID)
        await db_mod.resolve_task_for_finding(RESTART_ID)

        conn = await db_mod.get_db()
        await conn.execute("UPDATE findings SET resolved_at = ? WHERE id = ?",
                           ("2020-01-01T00:00:00Z", RESTART_ID))
        await conn.commit()

        estado = await db_mod.upsert_finding(f)
        await eng._sync_task(_mod_falso(True), f, {"title": "t"}, estado)
        cartoes = await db_mod.get_tasks()
        assert len(cartoes) == 1
        assert cartoes[0]["col"] == "doing", "cartao ficou em done com o problema vivo"
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)
