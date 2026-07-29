"""Limite de escrita de /api/tasks + e2e pelo caminho do navegador.

O ack passou por 125 testes verdes sem guard, sem auditoria e sem e2e — e o
defeito real estava na CHAMADA do frontend (corpo passado como options do
fetch), nao no router. Por isso o e2e daqui monta a requisicao do mesmo jeito
que `data.js` monta, em vez de confiar no TestClient com json=.
"""
import importlib
import json
import os
import re
import pathlib
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


RAIZ = pathlib.Path(__file__).resolve().parent.parent
JS = RAIZ / "app" / "static" / "js"


def _client():
    from app import app
    return TestClient(app)


def _sessao(remote_user="admin"):
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone.utc)
    return {
        "remote_user": remote_user, "ip": "172.19.0.9", "motivo": "",
        "created_at": agora.isoformat().replace("+00:00", "Z"),
        "expires_at": (agora + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
    }


# ---------------------------------------------------------------------------
# guard: escrita sem destravamento
# ---------------------------------------------------------------------------

def test_patch_sem_unlock_403():
    client = _client()
    with patch("auth.get_valid_unlock_session", new=AsyncMock(return_value=None)):
        r = client.patch("/api/tasks/task-x", json={"col": "doing"})
    assert r.status_code == 403


def test_post_sem_unlock_403():
    client = _client()
    with patch("auth.get_valid_unlock_session", new=AsyncMock(return_value=None)):
        r = client.post("/api/tasks", json={"title": "x"})
    assert r.status_code == 403


def test_get_tasks_e_leitura_livre():
    client = _client()
    with patch("routers.tasks.get_tasks", new=AsyncMock(return_value=[])):
        r = client.get("/api/tasks")
    assert r.status_code == 200
    assert [c["key"] for c in r.json()["columns"]] == ["todo", "doing", "blocked", "done"]


@pytest.mark.asyncio
async def test_patch_sem_unlock_nao_muda_o_banco(tmp_path):
    """Aceite: 403 E nada muda no banco."""
    os.environ["COCKPIT_DB"] = str(tmp_path / "guard.db")
    import db as db_mod
    importlib.reload(db_mod)
    try:
        await db_mod.init_db()
        tarefa = await db_mod.create_task(title="nao me mova", col="todo")
        await db_mod.close_db()

        client = _client()
        with patch("auth.get_valid_unlock_session", new=AsyncMock(return_value=None)):
            r = client.patch(f"/api/tasks/{tarefa['id']}", json={"col": "done"})
        assert r.status_code == 403

        importlib.reload(db_mod)
        depois = await db_mod.get_task(tarefa["id"])
        assert depois["col"] == "todo", "banco mudou apesar do 403"
        assert len(await db_mod.get_tasks()) == 1
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


# ---------------------------------------------------------------------------
# auditoria
# ---------------------------------------------------------------------------

def test_patch_audita_movimento_com_operador():
    client = _client()
    audit = AsyncMock()
    with patch("auth.get_valid_unlock_session", new=AsyncMock(return_value=_sessao("danniel"))):
        with patch("routers.tasks.get_task", new=AsyncMock(return_value={"id": "t1", "col": "todo"})):
            with patch("routers.tasks.update_task", new=AsyncMock(return_value={"id": "t1", "col": "doing"})):
                with patch("routers.tasks.add_audit_entry", new=audit):
                    r = client.patch("/api/tasks/t1",
                                     headers={"X-Cockpit-Unlock": "tok"},
                                     json={"col": "doing"})
    assert r.status_code == 200
    args, _ = audit.call_args
    assert args[0] == "task_move"
    assert args[1] == "t1"
    assert args[2] == "todo -> doing"
    assert args[3] == "danniel"


def test_post_audita_criacao():
    client = _client()
    audit = AsyncMock()
    with patch("auth.get_valid_unlock_session", new=AsyncMock(return_value=_sessao("danniel"))):
        with patch("routers.tasks.create_task", new=AsyncMock(return_value={"id": "t9"})):
            with patch("routers.tasks.add_audit_entry", new=audit):
                r = client.post("/api/tasks",
                                headers={"X-Cockpit-Unlock": "tok"},
                                json={"title": "trocar o certificado"})
    assert r.status_code == 200
    args, _ = audit.call_args
    assert args[0] == "task_create"
    assert args[3] == "danniel"


def test_coluna_invalida_400():
    client = _client()
    with patch("auth.get_valid_unlock_session", new=AsyncMock(return_value=_sessao())):
        with patch("routers.tasks.add_audit_entry", new=AsyncMock()):
            r = client.patch("/api/tasks/t1", headers={"X-Cockpit-Unlock": "tok"},
                             json={"col": "arquivada"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# e2e: o caminho do navegador
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_mover_cartao_persiste_e_audita(tmp_path):
    """Board -> PATCH -> banco -> /api/audit, sem mock de persistencia."""
    os.environ["COCKPIT_DB"] = str(tmp_path / "e2e.db")
    import db as db_mod
    importlib.reload(db_mod)
    try:
        await db_mod.init_db()
        tarefa = await db_mod.create_task_from_finding(
            {"id": "restart_loop.painel-x", "rule": "restart_loop",
             "target": "painel-x", "title": "reinicio em laco"})
        await db_mod.close_db()

        client = _client()
        with patch("auth.get_valid_unlock_session", new=AsyncMock(return_value=_sessao("danniel"))):
            board = client.get("/api/tasks").json()
            todo = next(c for c in board["columns"] if c["key"] == "todo")
            assert [t["id"] for t in todo["tasks"]] == [tarefa["id"]]

            # exatamente o que data.js/apiPatch monta
            r = client.patch(
                f"/api/tasks/{tarefa['id']}",
                headers={"X-Cockpit-Unlock": "tok", "Content-Type": "application/json"},
                content=json.dumps({"col": "doing"}),
            )
            assert r.status_code == 200, r.text
            assert r.json()["col"] == "doing"

            board = client.get("/api/tasks").json()
            doing = next(c for c in board["columns"] if c["key"] == "doing")
            assert [t["id"] for t in doing["tasks"]] == [tarefa["id"]]

            linhas = client.get("/api/audit?limit=10").json()
            assert any(l["action"] == "task_move" and l["project"] == tarefa["id"]
                       and l["token_label"] == "danniel" for l in linhas), \
                "movimento nao apareceu em /api/audit"

        importlib.reload(db_mod)
        assert (await db_mod.get_task(tarefa["id"]))["col"] == "doing"
    finally:
        await _fecha(db_mod)
        os.environ.pop("COCKPIT_DB", None)


# ---------------------------------------------------------------------------
# contrato do frontend
# ---------------------------------------------------------------------------

def test_apiPatch_manda_corpo_e_header_de_unlock():
    """A regressao do ack: corpo virando options, header sumindo."""
    fonte = (JS / "data.js").read_text()
    trecho = fonte[fonte.index("export async function apiPatch"):]
    trecho = trecho[:trecho.index("export async function apiDelete")]
    assert "method: 'PATCH'" in trecho
    assert "JSON.stringify(body)" in trecho, "apiPatch nao serializa o corpo"
    assert "...unlockHeader" in trecho, "apiPatch nao manda X-Cockpit-Unlock"


def test_tela_tarefas_nao_tem_dado_fixo():
    """Regra 1: nenhum nome de container, dominio ou frase de diagnostico no JS."""
    fonte = (JS / "screens" / "tarefas.js").read_text()
    for proibido in ("criptotrade", "giva", "buildtovalue", "executagent",
                     "familia-web", "danzeroum", "painel-x"):
        assert proibido not in fonte.lower(), f"dado fixo no JS: {proibido}"


def test_tela_tarefas_usa_button_de_verdade():
    """Fatia 4 vem depois, mas board novo nao entra ja com <div onClick>."""
    fonte = (JS / "screens" / "tarefas.js").read_text()
    assert "<button type=\"button\"" in fonte
    assert re.search(r"<div[^>]*onclick", fonte, re.I) is None


def test_placeholder_de_tarefas_saiu_do_router():
    fonte = (JS / "main.js").read_text()
    assert "renderTarefas(container)" in fonte
    assert "renderPlaceholder(container, 'Tarefas'" not in fonte
