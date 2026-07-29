"""ack de um achado: sai da fila, sobrevive ao ciclo do motor e aparece em /api/audit.

Caso canonico do handoff: os dois healthcheck_never_passed do criptotrade.
"""
import importlib
import os
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


FINDING_ID = "healthcheck_never_passed:criptotrade-dashboard"


async def _db_com_achado(tmp_path):
    os.environ["COCKPIT_DB"] = str(tmp_path / "ack.db")
    import db as db_mod
    importlib.reload(db_mod)
    await db_mod.init_db()
    await db_mod.upsert_finding({
        "id": FINDING_ID,
        "rule": "healthcheck_never_passed",
        "target": "criptotrade-dashboard",
        "scope": "container",
        "severity": "medium",
        "score": 50,
        "payload": "{}",
    })
    return db_mod


@pytest.mark.asyncio
async def test_ack_tira_da_fila_e_registra_auditoria(tmp_path):
    db_mod = await _db_com_achado(tmp_path)
    try:
        abertos = await db_mod.get_findings(status="open")
        assert [f["id"] for f in abertos] == [FINDING_ID]

        await db_mod.ack_finding(FINDING_ID, "monitorando", "corrige na proxima janela", "24h")
        await db_mod.add_audit_entry("ack", FINDING_ID, "monitorando · 24h", "admin", "172.19.0.9")

        abertos = await db_mod.get_findings(status="open")
        assert abertos == [], "achado silenciado continua na fila"

        acked = await db_mod.get_findings(status="acked")
        assert [f["id"] for f in acked] == [FINDING_ID]
        assert acked[0]["ack_reason"] == "monitorando"
        assert acked[0]["ack_until"] == "24h"

        linhas = await db_mod.get_audit_log()
        assert any(
            l["action"] == "ack" and l["project"] == FINDING_ID and l["token_label"] == "admin"
            for l in linhas
        ), "ack nao apareceu em /api/audit"
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_ack_sobrevive_ao_ciclo_do_motor(tmp_path):
    """O motor reobserva o achado a cada 10s — nao pode devolve-lo para a fila."""
    db_mod = await _db_com_achado(tmp_path)
    try:
        await db_mod.ack_finding(FINDING_ID, "aceito_estrutural", "", "7d")
        await db_mod.upsert_finding({
            "id": FINDING_ID,
            "rule": "healthcheck_never_passed",
            "target": "criptotrade-dashboard",
            "scope": "container",
            "severity": "medium",
            "score": 50,
            "payload": "{}",
        })
        assert await db_mod.get_findings(status="open") == [], "ack revertido pelo motor"
        atual = await db_mod.get_finding(FINDING_ID)
        assert atual["status"] == "acked"
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


# ---------------------------------------------------------------------------
# camada HTTP
# ---------------------------------------------------------------------------

def _client():
    from app import app
    return TestClient(app)


def _sessao(remote_user="admin"):
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    return {
        "remote_user": remote_user,
        "ip": "172.19.0.9",
        "motivo": "",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
    }


def test_ack_http_exige_destravamento():
    """Silenciar e mutacao: sem sessao valida → 403."""
    client = _client()
    with patch("auth.get_valid_unlock_session", new=AsyncMock(return_value=None)):
        r = client.post(f"/api/findings/{FINDING_ID}/ack", json={"reason": "monitorando"})
    assert r.status_code == 403


def test_ack_http_audita_com_prazo_e_usuario():
    client = _client()
    audit = AsyncMock()
    with patch("auth.get_valid_unlock_session", new=AsyncMock(return_value=_sessao("danniel"))):
        with patch("routers.findings.get_finding", new=AsyncMock(return_value={"id": FINDING_ID, "status": "open"})):
            with patch("routers.findings.ack_finding", new=AsyncMock()):
                with patch("routers.findings.add_audit_entry", new=audit):
                    r = client.post(
                        f"/api/findings/{FINDING_ID}/ack",
                        headers={"X-Cockpit-Unlock": "tok"},
                        json={"reason": "monitorando", "note": "porta errada", "until": "24h"},
                    )
    assert r.status_code == 200
    args, _ = audit.call_args
    assert args[0] == "ack"
    assert args[1] == FINDING_ID
    assert "24h" in args[2] and "monitorando" in args[2]
    assert args[3] == "danniel"


def test_ack_http_rejeita_motivo_fora_do_contrato():
    """O select do modal tem 3 opcoes; texto livre nao entra como motivo."""
    client = _client()
    with patch("auth.get_valid_unlock_session", new=AsyncMock(return_value=_sessao())):
        r = client.post(
            f"/api/findings/{FINDING_ID}/ack",
            headers={"X-Cockpit-Unlock": "tok"},
            json={"reason": "asdf"},
        )
    assert r.status_code == 400
