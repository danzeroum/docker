"""2b-B10 — barreira ENABLE_ACTIONS, prune e auditoria-antes (v12).

Único código do cockpit com privilégio de escrita. Os testes cobrem os três
limites de autorização em camadas: a rota existe? a sessão está destravada? o
`dry_run` é o padrão?

Os dois primeiros testes são a bissecção do git em forma de asserção: nenhum
commit pode existir onde produção perde ações OU instalação nova nasce aberta.
"""

import importlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GB = 1024 ** 3


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


ROTAS_DE_ACAO = (
    ("/api/containers/{container_id}/start", "POST"),
    ("/api/containers/{container_id}/stop", "POST"),
    ("/api/containers/{container_id}/restart", "POST"),
    ("/api/containers/{container_id}", "DELETE"),
    ("/api/projects/{name}/start", "POST"),
    ("/api/projects/{name}/stop", "POST"),
    ("/api/prune", "POST"),
)

_SONDA = """
import json, os, sys
os.environ["ENABLE_ACTIONS"] = %r
os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")
sys.path.insert(0, %r)
from app import app
print(json.dumps(sorted(
    [r.path, m] for r in app.routes if hasattr(r, "path")
    for m in (getattr(r, "methods", None) or [])
)))
"""


def _rotas_com(flag: str) -> set:
    """Importa o app num SUBPROCESSO e devolve as rotas registradas.

    A barreira decide no import: trocar a env depois nao muda nada — e essa e
    justamente a propriedade sob teste. Recarregar modulos no processo do pytest
    resolveria, mas vaza estado para os arquivos seguintes (e deixa threads do
    aiosqlite vivas, impedindo o processo de sair). Subprocesso e hermetico.
    """
    r = subprocess.run(
        [sys.executable, "-c", _SONDA % (flag, os.path.join(RAIZ, "app"))],
        capture_output=True, text=True, timeout=90, cwd=RAIZ,
    )
    assert r.returncode == 0, f"o app nao subiu com ENABLE_ACTIONS={flag}:\n{r.stderr}"
    return {tuple(x) for x in json.loads(r.stdout)}


def _client_ligado():
    """TestClient do app do proprio processo — a suite roda com a flag ligada."""
    from fastapi.testclient import TestClient
    from app import app as app_mod
    return TestClient(app_mod), app_mod


# --- a bissecção em forma de teste ----------------------------------------

def test_instalacao_limpa_sem_env_nao_registra_rota_de_escrita():
    """Aceite: sem ENABLE_ACTIONS, POST restart é 404 — a rota não existe."""
    rotas = _rotas_com("0")
    for caminho, metodo in ROTAS_DE_ACAO:
        assert (caminho, metodo) not in rotas, f"{metodo} {caminho} registrada com a flag desligada"
    # e as leituras continuam de pe: a barreira nao derruba o painel
    assert ("/api/containers", "GET") in rotas
    assert ("/api/overview", "GET") in rotas


def test_producao_com_pin_mantem_o_fluxo_de_acoes():
    """Aceite: com a flag ligada, as 7 rotas existem (e exigem unlock)."""
    rotas = _rotas_com("1")
    for caminho, metodo in ROTAS_DE_ACAO:
        assert (caminho, metodo) in rotas, f"{metodo} {caminho} sumiu com a flag ligada"

    # existe, mas continua fail-closed sem unlock
    client, _ = _client_ligado()
    assert client.post("/api/containers/abc/restart").status_code == 403


def test_o_compose_de_producao_fixa_a_flag():
    """O pin e a inversão do padrão são o mesmo commit — este teste liga os dois.

    Sem o pin, o deploy deste commit derrubaria unlock→reiniciar em produção.
    """
    compose = open(os.path.join(RAIZ, "docker-compose.yml")).read()
    assert re.search(r'ENABLE_ACTIONS:\s*"?1"?', compose), (
        "o compose de produção não fixa ENABLE_ACTIONS=1 — a inversão do padrão "
        "deixaria produção sem ações"
    )


def test_o_padrao_do_codigo_e_desligado():
    import actions
    importlib.reload(actions)
    anterior = os.environ.pop("ENABLE_ACTIONS", None)
    try:
        importlib.reload(actions)
        assert actions.habilitadas() is False, "instalação nova nasceria com escrita aberta"
    finally:
        if anterior is not None:
            os.environ["ENABLE_ACTIONS"] = anterior


def test_governanca_do_cockpit_nao_e_barrada():
    """ack e tarefas mutam o banco do cockpit, não a infraestrutura."""
    rotas = _rotas_com("0")
    assert ("/api/findings/{finding_id}/ack", "POST") in rotas
    assert ("/api/tasks", "POST") in rotas
    assert ("/api/session/unlock", "POST") in rotas


# --- prune ----------------------------------------------------------------

STORAGE = {
    "images": {"count": 3, "size_bytes": 6 * GB, "dangling_count": 2, "dangling_bytes": 4 * GB},
    "containers": {"count": 2, "size_bytes": 200},
    "volumes": {"count": 1, "size_bytes": 2 * GB, "orphan_count": 1},
    "build_cache": {"count": 1, "size_bytes": GB, "reclaimable_bytes": GB},
    "reclaimable_bytes": 6 * GB,
    "orphans": [
        {"type": "image", "id": "sha256:aaa", "name": "<none>:<none>", "size_bytes": 3 * GB, "reason": "dangling"},
        {"type": "image", "id": "sha256:bbb", "name": "<none>:<none>", "size_bytes": GB, "reason": "dangling"},
        {"type": "volume", "id": "dados_do_banco", "name": "dados_do_banco", "size_bytes": 2 * GB, "reason": "órfão"},
        {"type": "container", "id": "c9", "name": "zumbi", "size_bytes": 200, "reason": "parado há 40 dias"},
    ],
}

SESSAO = {"remote_user": "dz", "ip": "10.0.0.9", "motivo": "limpeza"}


@pytest.fixture(autouse=True)
def _limpa_overrides():
    """Desfaz `dependency_overrides` depois de CADA teste.

    O objeto `app` e compartilhado por toda a suite. Sem esta limpeza, o
    override de `require_unlock` feito aqui vale para os arquivos seguintes — e
    o efeito e o pior possivel num teste de seguranca: rotas protegidas passam a
    responder 200 sem sessao, e os testes que cobram 403 falham em outro arquivo,
    longe da causa.
    """
    yield
    from app import app as app_mod
    app_mod.dependency_overrides.clear()


def _client_destravado():
    client, app = _client_ligado()
    from auth import require_unlock
    app.dependency_overrides[require_unlock] = lambda: SESSAO
    return client, app


def test_dry_run_e_o_padrao_e_nao_remove_nada():
    client, _ = _client_destravado()
    proxy = AsyncMock()
    with patch("routers.prune.get_storage", AsyncMock(return_value=STORAGE)), \
         patch("routers.prune.proxy_post", proxy), \
         patch("routers.prune.audit_iniciar", AsyncMock(return_value=1)), \
         patch("routers.prune.audit_concluir", AsyncMock()):
        r = client.post("/api/prune")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True, "o padrão deixou de ser dry_run"
    assert body["removed_bytes"] == 0
    proxy.assert_not_awaited(), "dry_run chamou o daemon"


def test_dry_run_lista_bytes_por_item():
    client, _ = _client_destravado()
    with patch("routers.prune.get_storage", AsyncMock(return_value=STORAGE)), \
         patch("routers.prune.audit_iniciar", AsyncMock(return_value=1)), \
         patch("routers.prune.audit_concluir", AsyncMock()):
        body = client.post("/api/prune?dry_run=true").json()

    assert body["count"] == 2
    assert body["reclaimable_bytes"] == 4 * GB
    for c in body["candidates"]:
        assert c["size_bytes"] > 0 and c["name"]


def test_prune_nao_toca_volume_nem_container():
    """Volume órfão guarda DADO; container parado pode ser religado na segunda."""
    client, _ = _client_destravado()
    with patch("routers.prune.get_storage", AsyncMock(return_value=STORAGE)), \
         patch("routers.prune.audit_iniciar", AsyncMock(return_value=1)), \
         patch("routers.prune.audit_concluir", AsyncMock()):
        body = client.post("/api/prune").json()

    tipos = {c["type"] for c in body["candidates"]}
    assert tipos == {"image"}, f"prune ofereceu remover {tipos - {'image'}}"
    nomes = {c["name"] for c in body["candidates"]}
    assert "dados_do_banco" not in nomes
    assert "zumbi" not in nomes


def test_prune_real_filtra_por_dangling_no_daemon():
    """Sem o filtro, /images/prune remove toda imagem sem container usando."""
    client, _ = _client_destravado()
    proxy = AsyncMock(return_value={"ImagesDeleted": [{"Deleted": "sha256:aaa"}], "SpaceReclaimed": 3 * GB})
    with patch("routers.prune.get_storage", AsyncMock(return_value=STORAGE)), \
         patch("routers.prune.proxy_post", proxy), \
         patch("routers.prune.audit_iniciar", AsyncMock(return_value=1)), \
         patch("routers.prune.audit_concluir", AsyncMock()):
        body = client.post("/api/prune?dry_run=false").json()

    assert body["dry_run"] is False
    assert body["removed_bytes"] == 3 * GB
    filtros = proxy.await_args.kwargs["params"]["filters"]
    assert "dangling" in filtros, "prune real sem filtro removeria imagem taggeada"


def test_prune_sem_unlock_e_403():
    """A rota existe (flag ligada) mas continua fail-closed.

    `get_valid_unlock_session` mockado porque o teste e de AUTORIZACAO, nao de
    banco: sem o mock ele bate no SQLite e falha por falta de arquivo, mascarando
    o que se quer medir.
    """
    client, _ = _client_ligado()
    with patch("auth.get_valid_unlock_session", AsyncMock(return_value=None)):
        assert client.post("/api/prune").status_code == 403
        assert client.post(
            "/api/prune", headers={"X-Cockpit-Unlock": "token-invalido"}
        ).status_code == 403


def test_prune_com_proxy_fora_do_ar_e_503():
    client, _ = _client_destravado()
    with patch("routers.prune.get_storage", AsyncMock(side_effect=httpx.ConnectError("recusou"))), \
         patch("routers.prune.audit_iniciar", AsyncMock(return_value=1)), \
         patch("routers.prune.audit_concluir", AsyncMock()) as fim:
        r = client.post("/api/prune")

    assert r.status_code == 503
    assert "socket-proxy" in r.json()["detail"]
    assert fim.await_args.kwargs.get("status") == "error", "a tentativa não foi fechada na auditoria"


def test_consulta_de_dry_run_tambem_e_auditada():
    """A consulta precede toda remoção — faz parte do rastro."""
    client, _ = _client_destravado()
    inicio = AsyncMock(return_value=7)
    with patch("routers.prune.get_storage", AsyncMock(return_value=STORAGE)), \
         patch("routers.prune.audit_iniciar", inicio), \
         patch("routers.prune.audit_concluir", AsyncMock()):
        client.post("/api/prune")

    inicio.assert_awaited_once()
    assert inicio.await_args.args[0] == "prune_dry_run"
    assert inicio.await_args.args[2] == "dz", "o ator não foi registrado"


# --- migration v12 sobre audit_log populado -------------------------------

def _popula_v11_com_auditoria(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE audit_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, project TEXT NOT NULL,"
        "result TEXT NOT NULL, token_label TEXT NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT '',"
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE docker_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, type TEXT NOT NULL DEFAULT '',"
        "action TEXT NOT NULL DEFAULT '', actor_id TEXT NOT NULL DEFAULT '',"
        "actor_name TEXT NOT NULL DEFAULT '', stack TEXT NOT NULL DEFAULT '',"
        "exit_code TEXT NOT NULL DEFAULT '', severity TEXT NOT NULL DEFAULT 'info')"
    )
    for v in range(1, 12):
        conn.execute("INSERT INTO schema_version VALUES (?, ?)", (v, _iso(datetime.now(timezone.utc))))
    agora = _iso(datetime.now(timezone.utc))
    conn.executemany(
        "INSERT INTO audit_log (action, project, result, token_label, ip, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("container_stop", "api", "success", "dz", "10.0.0.1", agora),
            ("container_restart", "front", "error: 500 boom", "dz", "10.0.0.1", agora),
            ("unlock", "-", "success", "dz", "10.0.0.1", agora),
        ],
    )
    conn.execute(
        "INSERT INTO docker_events (ts, type, action, actor_name, severity)"
        " VALUES (?, 'container', 'die', 'api', 'critical')", (agora,)
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_v12_sobre_audit_log_populado_preserva_tudo(tmp_path):
    caminho = str(tmp_path / "prod.db")
    _popula_v11_com_auditoria(caminho)

    anterior = os.environ.get("COCKPIT_DB")
    os.environ["COCKPIT_DB"] = caminho
    try:
        import db as mod
        importlib.reload(mod)
        await mod.init_db()
        db = await mod.get_db()

        cur = await db.execute(
            "SELECT action, project, result, token_label, ip, status, started_at, finished_at"
            " FROM audit_log ORDER BY id"
        )
        linhas = await cur.fetchall()
        assert len(linhas) == 3, "a v12 perdeu linhas de auditoria"

        # colunas antigas intactas, nos lugares certos
        assert linhas[0][:5] == ("container_stop", "api", "success", "dz", "10.0.0.1")
        assert linhas[1][2] == "error: 500 boom"

        for l in linhas:
            # Linha antiga nasce 'done': ela só existia se a ação terminou.
            assert l[5] == "done"
            # started_at NULL de propósito — afirmar um início que ninguém mediu
            # seria inventar dado.
            assert l[6] is None, "a v12 inventou started_at para linha antiga"
            assert l[7] is None

        cur = await db.execute("SELECT COUNT(*) FROM docker_events")
        assert (await cur.fetchone())[0] == 1, "a v12 mexeu na tabela de eventos"

        cur = await db.execute("SELECT MAX(version) FROM schema_version")
        assert (await cur.fetchone())[0] == mod.SCHEMA_VERSION == 12
        await mod.close_db()
    finally:
        if anterior is None:
            os.environ.pop("COCKPIT_DB", None)
        else:
            os.environ["COCKPIT_DB"] = anterior


# --- auditoria-antes ------------------------------------------------------

@pytest.fixture
def db_mod(tmp_path):
    caminho = str(tmp_path / "cockpit.db")
    anterior = os.environ.get("COCKPIT_DB")
    os.environ["COCKPIT_DB"] = caminho
    import db as mod
    importlib.reload(mod)
    yield mod
    # Fecha a conexao mesmo se o teste falhou no meio: aiosqlite mantem uma
    # thread por conexao, e conexao vazada impede o processo do pytest de sair.
    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(mod.close_db())
    except Exception:
        pass
    if anterior is None:
        os.environ.pop("COCKPIT_DB", None)
    else:
        os.environ["COCKPIT_DB"] = anterior


@pytest.mark.asyncio
async def test_linha_nasce_antes_da_execucao(db_mod):
    await db_mod.init_db()
    audit_id = await db_mod.audit_iniciar("container_restart", "api", "dz", "10.0.0.9")

    db = await db_mod.get_db()
    cur = await db.execute("SELECT status, started_at, finished_at, result FROM audit_log WHERE id = ?", (audit_id,))
    status, inicio, fim, resultado = await cur.fetchone()
    assert status == "running", "a linha não nasce aberta"
    assert inicio, "sem started_at não dá para saber quando a ação foi autorizada"
    assert fim is None and resultado == ""
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_conclusao_fecha_a_linha(db_mod):
    await db_mod.init_db()
    audit_id = await db_mod.audit_iniciar("prune", "images", "dz", "10.0.0.9")
    await db_mod.audit_concluir(audit_id, "success: 2 removidas")

    db = await db_mod.get_db()
    cur = await db.execute("SELECT status, result, finished_at FROM audit_log WHERE id = ?", (audit_id,))
    status, resultado, fim = await cur.fetchone()
    assert status == "done"
    assert resultado == "success: 2 removidas"
    assert fim
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_acao_que_trava_deixa_linha_orfa_visivel(db_mod):
    """É o cenário que a auditoria-depois perdia inteiro.

    A linha órfã é o rastro do travamento, não sujeira: nada no código a limpa,
    e nenhum housekeeping futuro deve limpá-la.
    """
    await db_mod.init_db()
    await db_mod.audit_iniciar("container_restart", "trava", "dz", "10.0.0.9")
    # simula o processo morrendo aqui: `audit_concluir` nunca é chamado

    db = await db_mod.get_db()
    cur = await db.execute("SELECT COUNT(*) FROM audit_log WHERE status = 'running'")
    assert (await cur.fetchone())[0] == 1, "a ação travada não deixou rastro"

    orfas = await db_mod.get_audit_log(limit=10)
    assert orfas[0]["status"] == "running"
    assert orfas[0]["action"] == "container_restart"
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_falha_ao_concluir_nao_mascara_o_resultado(db_mod):
    """Erro ao gravar o RESULTADO não pode virar erro da ação para quem chamou."""
    await db_mod.init_db()
    # id inexistente: o UPDATE não casa, e mesmo assim não levanta
    await db_mod.audit_concluir(99999, "success")
    await db_mod.audit_concluir(None, "success")
    await db_mod.close_db()
