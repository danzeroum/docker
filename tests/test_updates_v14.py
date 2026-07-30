"""4-B6 — imagem desatualizada via Docker Hub (v14).

Comparação por **digest**, nunca por nome de tag: `nginx:1.25` local e remoto
têm o mesmo nome sempre, inclusive depois de a tag ser republicada — que é
justamente o caso que a verificação existe para pegar.

O 429 é o teste central: uma VPS com 20 imagens estoura o rate limit anônimo do
Hub com facilidade, e a resposta certa é tentar amanhã, não perder o resultado
bom que já estava no banco.
"""

import importlib
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import updates as upd  # noqa: E402


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _agora():
    return datetime.now(timezone.utc)


@pytest.fixture
def db_mod(tmp_path):
    caminho = str(tmp_path / "cockpit.db")
    anterior = os.environ.get("COCKPIT_DB")
    os.environ["COCKPIT_DB"] = caminho
    import db as mod
    importlib.reload(mod)
    yield mod
    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(mod.close_db())
    except Exception:
        pass
    if anterior is None:
        os.environ.pop("COCKPIT_DB", None)
    else:
        os.environ["COCKPIT_DB"] = anterior


def imagem(repo_tag="nginx:1.25", digest="sha256:local", repo=None):
    caminho = repo or repo_tag.rpartition(":")[0]
    return {
        "Id": "sha256:abc",
        "RepoTags": [repo_tag],
        "RepoDigests": [f"{caminho}@{digest}"] if digest else [],
    }


# --- parsing --------------------------------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    ("nginx:1.25", ("library", "nginx", "1.25")),
    ("redis:latest", ("library", "redis", "latest")),
    ("danzeroum/app:v2", ("danzeroum", "app", "v2")),
])
def test_imagem_do_hub_e_reconhecida(entrada, esperado):
    assert upd.parse_repo_tag(entrada) == esperado


@pytest.mark.parametrize("entrada", [
    "ghcr.io/org/app:1",
    "registry.local:5000/app:1",
    "localhost:5000/app:1",
    "<none>:<none>",
    "sem-tag",
    "",
    None,
])
def test_fora_do_hub_nao_e_candidata(entrada):
    """Registry privado não é erro: é imagem sobre a qual não há o que dizer."""
    assert upd.parse_repo_tag(entrada) is None


def test_digest_local_casa_o_repo_certo():
    """Uma imagem pode ter vários RepoDigests; pegar o primeiro compararia o
    digest de um repo com a tag de outro."""
    img = {
        "RepoTags": ["nginx:1.25"],
        "RepoDigests": ["outro/repo@sha256:errado", "nginx@sha256:certo"],
    }
    assert upd.digest_local(img, "nginx:1.25") == "sha256:certo"


def test_imagem_construida_localmente_nao_tem_digest():
    """É assim que ela se identifica: sem RepoDigest."""
    img = {"RepoTags": ["meuapp:latest"], "RepoDigests": []}
    assert upd.digest_local(img, "meuapp:latest") == ""


# --- consulta ao Hub ------------------------------------------------------

def _resposta(status=200, corpo=None):
    class R:
        status_code = status

        def json(self):
            if corpo is None:
                raise ValueError("sem json")
            return corpo
    return R()


@pytest.mark.asyncio
async def test_hub_ok_devolve_digest_e_data():
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resposta(
        200, {"digest": "sha256:remoto", "last_updated": "2026-07-20T10:00:00Z"}
    ))):
        r = await upd.consulta_hub("library", "nginx", "1.25")
    assert r["status"] == "ok"
    assert r["digest"] == "sha256:remoto"
    assert r["remoto_em"] == "2026-07-20T10:00:00Z"


@pytest.mark.asyncio
async def test_429_vira_pendente_e_nao_erro():
    """O job não pode abortar nem marcar tudo como desconhecido."""
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resposta(429))):
        r = await upd.consulta_hub("library", "nginx", "1.25")
    assert r["status"] == "pendente"
    assert "429" in r["erro"]


@pytest.mark.asyncio
async def test_404_e_desconhecido():
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resposta(404))):
        assert (await upd.consulta_hub("x", "y", "z"))["status"] == "desconhecido"


@pytest.mark.asyncio
async def test_rede_fora_do_ar_e_desconhecido_nao_excecao():
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=httpx.ConnectError("sem rede"))):
        r = await upd.consulta_hub("x", "y", "z")
    assert r["status"] == "desconhecido"
    assert "rede" in r["erro"]


# --- avaliação por imagem -------------------------------------------------

@pytest.mark.asyncio
async def test_digest_igual_e_atualizada(db_mod):
    await db_mod.init_db()
    with patch("updates.consulta_hub", AsyncMock(return_value={
        "status": "ok", "digest": "sha256:mesmo", "remoto_em": "2026-07-20T10:00:00Z"
    })):
        r = await upd._uma(imagem(digest="sha256:mesmo"))
    assert r["status"] == "atualizada"
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_digest_divergente_e_desatualizada_com_data(db_mod):
    """Aceite: divergiu → desatualizada, com a data da tag remota."""
    await db_mod.init_db()
    with patch("updates.consulta_hub", AsyncMock(return_value={
        "status": "ok", "digest": "sha256:novo", "remoto_em": "2026-07-28T09:00:00Z"
    })):
        r = await upd._uma(imagem(digest="sha256:velho"))
    assert r["status"] == "desatualizada"
    assert r["remoto_em"] == "2026-07-28T09:00:00Z"
    assert r["consultado_em"], "sem consultado_em o operador não sabe a idade do dado"
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_imagem_local_fica_fora_da_listagem(db_mod):
    """Aceite: construída localmente → ignorada, não 'desconhecida'."""
    await db_mod.init_db()
    r = await upd._uma({"RepoTags": ["ghcr.io/org/app:1"], "RepoDigests": []})
    assert r is None
    assert await db_mod.get_image_updates() == []
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_429_preserva_o_resultado_anterior(db_mod):
    """O ponto do 'pendente': não perder o que já se sabia."""
    await db_mod.init_db()
    with patch("updates.consulta_hub", AsyncMock(return_value={
        "status": "ok", "digest": "sha256:novo", "remoto_em": "2026-07-28T09:00:00Z"
    })):
        await upd._uma(imagem(digest="sha256:velho"))

    # força reconsulta ignorando o cache de 24h
    with patch("updates.CACHE_H", 0), \
         patch("updates.consulta_hub", AsyncMock(return_value={
             "status": "pendente", "erro": "429 do Hub — rate limit"})):
        r = await upd._uma(imagem(digest="sha256:velho"))

    assert r["status"] == "pendente"
    assert r["digest_remoto"] == "sha256:novo", "o digest conhecido foi apagado pelo 429"
    assert r["remoto_em"] == "2026-07-28T09:00:00Z"
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_cache_de_24h_evita_reconsulta(db_mod):
    await db_mod.init_db()
    hub = AsyncMock(return_value={"status": "ok", "digest": "sha256:x", "remoto_em": ""})
    with patch("updates.consulta_hub", hub):
        await upd._uma(imagem(digest="sha256:x"))
        await upd._uma(imagem(digest="sha256:x"))
    assert hub.await_count == 1, "consultou o Hub duas vezes dentro da janela de cache"
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_sem_digest_local_e_desconhecido_nao_desatualizada(db_mod):
    """Sem os dois lados não dá para afirmar divergência."""
    await db_mod.init_db()
    with patch("updates.consulta_hub", AsyncMock(return_value={
        "status": "ok", "digest": "sha256:remoto", "remoto_em": ""
    })):
        r = await upd._uma(imagem(digest=""))
    assert r["status"] == "desconhecido"
    await db_mod.close_db()


# --- ciclo ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_falha_numa_imagem_nao_para_as_outras(db_mod):
    await db_mod.init_db()
    imagens = [imagem("nginx:1.25", "sha256:a"), imagem("redis:7", "sha256:b")]

    chamadas = {"n": 0}

    async def hub_instavel(ns, repo, tag):
        chamadas["n"] += 1
        if repo == "nginx":
            raise RuntimeError("explodiu")
        return {"status": "ok", "digest": "sha256:b", "remoto_em": ""}

    with patch("routers._proxy.proxy_get", AsyncMock(return_value=imagens)), \
         patch("updates.consulta_hub", hub_instavel):
        r = await upd.ciclo()

    assert chamadas["n"] == 2, "parou na primeira falha"
    assert r["avaliadas"] == 1
    await db_mod.close_db()


# --- resumo para a régua --------------------------------------------------

@pytest.mark.asyncio
async def test_resumo_e_none_quando_o_job_nunca_rodou(db_mod):
    """Aceite: chip ausente, não '0 desatualizadas'.

    Zero afirmaria uma conclusão; o job pode simplesmente não ter rodado. Mesmo
    padrão já firmado para `certs_expiring`.
    """
    await db_mod.init_db()
    assert await db_mod.get_updates_resumo() is None
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_resumo_conta_desatualizadas_e_traz_a_idade(db_mod):
    await db_mod.init_db()
    with patch("updates.consulta_hub", AsyncMock(return_value={
        "status": "ok", "digest": "sha256:novo", "remoto_em": "2026-07-28T09:00:00Z"
    })):
        await upd._uma(imagem("nginx:1.25", "sha256:velho"))
        await upd._uma(imagem("redis:7", "sha256:novo"))

    r = await db_mod.get_updates_resumo()
    assert r["outdated_count"] == 1
    assert r["checked"] == 2
    assert r["consultado_em"], "sem a idade do dado o operador não sabe se confiar"
    await db_mod.close_db()


@pytest.mark.asyncio
async def test_desatualizada_vem_primeiro_na_listagem(db_mod):
    """É a única linha sobre a qual há o que fazer."""
    await db_mod.init_db()
    with patch("updates.consulta_hub", AsyncMock(return_value={
        "status": "ok", "digest": "sha256:novo", "remoto_em": ""
    })):
        await upd._uma(imagem("aaa:1", "sha256:novo"))     # atualizada
        await upd._uma(imagem("zzz:1", "sha256:velho"))    # desatualizada

    linhas = await db_mod.get_image_updates()
    assert linhas[0]["status"] == "desatualizada"
    await db_mod.close_db()


# --- migração v13 -> v14 --------------------------------------------------

def _popula_v13(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE audit_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, project TEXT NOT NULL,"
        "result TEXT NOT NULL, token_label TEXT NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT '',"
        "created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'done',"
        "started_at TEXT, finished_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE docker_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, type TEXT NOT NULL DEFAULT '',"
        "action TEXT NOT NULL DEFAULT '', actor_id TEXT NOT NULL DEFAULT '',"
        "actor_name TEXT NOT NULL DEFAULT '', stack TEXT NOT NULL DEFAULT '',"
        "exit_code TEXT NOT NULL DEFAULT '', severity TEXT NOT NULL DEFAULT 'info')"
    )
    conn.execute("CREATE VIRTUAL TABLE logs_fts USING fts5(linha, container UNINDEXED, ts UNINDEXED, stream UNINDEXED)")
    conn.execute(
        "CREATE TABLE logs_ingest (container TEXT PRIMARY KEY, last_ts TEXT NOT NULL DEFAULT '',"
        " last_run TEXT NOT NULL DEFAULT '', linhas INTEGER NOT NULL DEFAULT 0)"
    )
    for v in range(1, 14):
        conn.execute("INSERT INTO schema_version VALUES (?, ?)", (v, _iso(_agora())))
    agora = _iso(_agora())
    conn.execute(
        "INSERT INTO audit_log (action, project, result, token_label, ip, created_at,"
        " status, started_at, finished_at)"
        " VALUES ('prune', 'images', 'success', 'dz', '10.0.0.1', ?, 'done', ?, ?)",
        (agora, agora, agora),
    )
    conn.execute("INSERT INTO docker_events (ts, type, action, actor_name, severity)"
                 " VALUES (?, 'container', 'die', 'api', 'critical')", (agora,))
    conn.execute("INSERT INTO logs_fts (linha, container, ts, stream)"
                 " VALUES ('erro fatal oom', 'api', ?, 'stderr')", (agora,))
    conn.execute("INSERT INTO logs_ingest VALUES ('api', ?, ?, 1)", (agora, agora))
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_v14_sobre_banco_v13_populado_preserva_tudo(tmp_path):
    caminho = str(tmp_path / "prod.db")
    _popula_v13(caminho)

    anterior = os.environ.get("COCKPIT_DB")
    os.environ["COCKPIT_DB"] = caminho
    try:
        import db as mod
        importlib.reload(mod)
        await mod.init_db()
        db = await mod.get_db()

        for tabela in ("audit_log", "docker_events", "logs_ingest"):
            cur = await db.execute(f"SELECT COUNT(*) FROM {tabela}")
            assert (await cur.fetchone())[0] == 1, f"{tabela} perdeu linha na v14"

        # o índice FTS continua pesquisável depois da migração
        linhas, _ = await mod.search_logs("oom")
        assert len(linhas) == 1, "a v14 quebrou o índice de logs"

        cur = await db.execute("SELECT MAX(version) FROM schema_version")
        assert (await cur.fetchone())[0] == mod.SCHEMA_VERSION

        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='image_updates'"
        )
        assert await cur.fetchone(), "image_updates não nasceu"
        await mod.close_db()
    finally:
        if anterior is None:
            os.environ.pop("COCKPIT_DB", None)
        else:
            os.environ["COCKPIT_DB"] = anterior
