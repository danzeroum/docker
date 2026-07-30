"""4-B7 — motor de notificações (v15).

O teste central é o `die` com exit 0. `docker stop` emite exatamente isso, e uma
notificação a cada parada pedida por alguém treina o operador a ignorar o canal
— depois do que o alerta que importa chega no mesmo silêncio dos outros. A
decisão está registrada no doc 00; aqui ela é executável.

Os outros dois que só um teste pega:

- **dedup sobrevive ao restart.** É o restart que reavalia tudo de uma vez: o
  cockpit reconecta ao stream, o sampler colhe a primeira amostra e o job de
  imagens roda. Dedup em memória notificaria de novo tudo o que já tinha sido
  notificado antes de o processo cair.
- **segredo não vaza para o log nem para o banco.** A URL do webhook do Discord
  *é* a credencial, e `str(exc)` do httpx a imprime. O motivo gravado é curto e
  sem URL — e o teste passa a URL inteira por um erro para conferir.
"""

import asyncio
import importlib
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import notify as ntf  # noqa: E402


def _agora():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


SEGREDO = "https://discord.com/api/webhooks/998877/uMsEgReDoQuEnInGuEmPoDeVer"


@pytest.fixture
def db_mod(tmp_path):
    caminho = str(tmp_path / "cockpit.db")
    anterior = os.environ.get("COCKPIT_DB")
    os.environ["COCKPIT_DB"] = caminho
    import db as mod
    importlib.reload(mod)
    yield mod
    try:
        asyncio.get_event_loop().run_until_complete(mod.close_db())
    except Exception:
        pass
    if anterior is None:
        os.environ.pop("COCKPIT_DB", None)
    else:
        os.environ["COCKPIT_DB"] = anterior


@pytest.fixture(autouse=True)
def _fila_limpa():
    """Fila nova por teste: item vazado de um caso vira falha no seguinte."""
    ntf._fila = None
    ntf._descartadas = 0
    yield
    ntf._fila = None


@pytest.fixture
def canais():
    antes = {k: os.environ.get(k) for k in
             ("NOTIFY_TELEGRAM_TOKEN", "NOTIFY_TELEGRAM_CHAT_ID",
              "NOTIFY_DISCORD_WEBHOOK", "NOTIFY_SLACK_WEBHOOK")}
    os.environ["NOTIFY_TELEGRAM_TOKEN"] = "111:AAtoken"
    os.environ["NOTIFY_TELEGRAM_CHAT_ID"] = "-100"
    os.environ["NOTIFY_DISCORD_WEBHOOK"] = SEGREDO
    os.environ.pop("NOTIFY_SLACK_WEBHOOK", None)
    yield
    for k, v in antes.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def evento(action="die", exit_code="1", nome="api"):
    return {"ts": _iso(_agora()), "type": "container", "action": action,
            "actor_id": "cafe", "actor_name": nome, "stack": "web",
            "exit_code": exit_code, "severity": "critical"}


def _drena():
    itens = []
    q = ntf.fila()
    while not q.empty():
        itens.append(q.get_nowait())
    return itens


# --- a regra do die -------------------------------------------------------

@pytest.mark.asyncio
async def test_die_com_exit_zero_nao_notifica():
    """`docker stop` emite `die` com exit 0. Parada limpa é informação."""
    assert ntf.avaliar_evento(evento(exit_code="0")) == []
    assert _drena() == []


@pytest.mark.asyncio
async def test_die_com_exit_vazio_nao_notifica():
    """Exit vazio é o daemon não tendo informado — não dá para afirmar falha."""
    assert ntf.avaliar_evento(evento(exit_code="")) == []
    assert _drena() == []


@pytest.mark.asyncio
async def test_die_com_exit_diferente_de_zero_notifica():
    achados = ntf.avaliar_evento(evento(exit_code="137"))
    assert [a["regra"] for a in achados] == ["container_die"]
    fila = _drena()
    assert len(fila) == 1
    assert fila[0]["alvo"] == "api"
    assert "137" in fila[0]["detalhe"]


@pytest.mark.asyncio
async def test_unhealthy_notifica():
    achados = ntf.avaliar_evento(evento(action="health_status", exit_code="unhealthy"))
    assert [a["regra"] for a in achados] == ["unhealthy"]


@pytest.mark.asyncio
async def test_health_status_saudavel_nao_notifica():
    assert ntf.avaliar_evento(evento(action="health_status", exit_code="healthy")) == []


@pytest.mark.asyncio
async def test_start_e_stop_nao_notificam():
    for acao in ("start", "stop", "create", "destroy"):
        assert ntf.avaliar_evento(evento(action=acao, exit_code="")) == [], acao


# --- disco ----------------------------------------------------------------

def test_disco_abaixo_do_limite_nao_notifica():
    assert ntf.avaliar_disco({"disks": [{"mountpoint": "/", "percent": 61.0}]}) == []


def test_disco_acima_do_limite_notifica_por_ponto_de_montagem():
    """`/` cheio e `/mnt/dados` cheio são dois problemas, com donos diferentes."""
    achados = ntf.avaliar_disco({"disks": [
        {"mountpoint": "/", "percent": 91.2},
        {"mountpoint": "/mnt/dados", "percent": 83.0},
        {"mountpoint": "/boot", "percent": 40.0},
    ]})
    assert {a["alvo"] for a in achados} == {"/", "/mnt/dados"}
    assert all(a["regra"] == "disk_high" for a in achados)


def test_amostra_ausente_nao_quebra():
    assert ntf.avaliar_disco(None) == []
    assert ntf.avaliar_disco({}) == []


# --- imagens (consome o B6) ----------------------------------------------

@pytest.mark.asyncio
async def test_imagem_desatualizada_notifica_e_a_atualizada_nao(db_mod):
    await db_mod.init_db()
    await db_mod.upsert_image_update("nginx:1.25", "library", "nginx", "1.25", "sha256:a",
                                     digest_remoto="sha256:b", status="desatualizada",
                                     remoto_em="2026-07-29T10:00:00Z", erro="")
    await db_mod.upsert_image_update("redis:7", "library", "redis", "7", "sha256:c",
                                     digest_remoto="sha256:c", status="atualizada",
                                     remoto_em="", erro="")
    achados = await ntf.avaliar_imagens()
    assert [a["alvo"] for a in achados] == ["nginx:1.25"]


# --- dedup ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_primeira_vez_sempre_notifica(db_mod):
    await db_mod.init_db()
    assert await ntf.deve_notificar("container_die", "api") is True


@pytest.mark.asyncio
async def test_dentro_da_janela_nao_repete(db_mod):
    await db_mod.init_db()
    await db_mod.registrar_notificacao("container_die", "api", _iso(_agora()),
                                       ["telegram"], "", "exit 1")
    assert await ntf.deve_notificar("container_die", "api") is False


@pytest.mark.asyncio
async def test_passada_a_janela_notifica_de_novo(db_mod):
    await db_mod.init_db()
    db = await db_mod.get_db()
    antigo = _iso(_agora() - timedelta(minutes=ntf.DEDUP_MIN + 5))
    await db.execute(
        "INSERT INTO notificacoes (regra, alvo, ts, enviado_em, canais) VALUES (?,?,?,?,?)",
        ("container_die", "api", antigo, antigo, "telegram"))
    await db.commit()
    assert await ntf.deve_notificar("container_die", "api") is True


@pytest.mark.asyncio
async def test_dedup_e_por_par_regra_alvo(db_mod):
    """Dois containers em crash loop são dois incidentes; silenciar o segundo
    porque o primeiro notificou esconderia metade do problema."""
    await db_mod.init_db()
    await db_mod.registrar_notificacao("container_die", "api", _iso(_agora()),
                                       ["telegram"], "", "")
    assert await ntf.deve_notificar("container_die", "api") is False
    assert await ntf.deve_notificar("container_die", "worker") is True
    assert await ntf.deve_notificar("unhealthy", "api") is True


@pytest.mark.asyncio
async def test_dedup_sobrevive_ao_restart(db_mod):
    """O restart é justamente quando tudo reavalia junto. Dedup em memória
    notificaria de novo o que já tinha sido notificado antes da queda."""
    await db_mod.init_db()
    await db_mod.registrar_notificacao("disk_high", "/", _iso(_agora()),
                                       ["telegram"], "", "91%")
    await db_mod.close_db()

    # mesmo arquivo, processo "novo": a conexão é refeita do zero
    importlib.reload(db_mod)
    await db_mod.init_db()
    assert await ntf.deve_notificar("disk_high", "/") is False


@pytest.mark.asyncio
async def test_falha_total_nao_abre_janela_de_silencio(db_mod):
    """Nenhum canal aceitou: o operador não recebeu nada. Deduplicar aqui seria
    trocar o alerta por silêncio de 30 min."""
    await db_mod.init_db()
    await db_mod.registrar_notificacao("container_die", "api", _iso(_agora()),
                                       [], "discord: HTTP 500", "exit 1")
    assert await ntf.deve_notificar("container_die", "api") is True


# --- entrega --------------------------------------------------------------

@pytest.mark.asyncio
async def test_falha_num_canal_nao_impede_os_outros(db_mod, canais):
    await db_mod.init_db()

    async def post(self, url, **kw):
        if "discord" in url:
            raise httpx.ConnectError(f"nao resolveu {url}")
        return httpx.Response(200, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", post):
        r = await ntf.despachar({"regra": "container_die", "alvo": "api",
                                 "ts": _iso(_agora()), "detalhe": "exit 1"})
    assert r["canais"] == ["telegram"]
    assert "discord" in r["falhas"]

    linhas = await db_mod.get_notificacoes()
    assert linhas[0]["canais"] == "telegram"
    assert linhas[0]["enviado_em"], "entrega parcial ainda é entrega"


@pytest.mark.asyncio
async def test_o_segredo_nunca_chega_ao_banco(db_mod, canais):
    """A URL do webhook do Discord é a credencial, e `str(exc)` do httpx a
    imprime. O motivo gravado é curto e sem URL."""
    await db_mod.init_db()

    async def post(self, url, **kw):
        raise httpx.ConnectError(f"falhou ao chamar {url}")

    with patch.object(httpx.AsyncClient, "post", post):
        r = await ntf.despachar({"regra": "container_die", "alvo": "api",
                                 "ts": _iso(_agora()), "detalhe": "exit 1"})

    linhas = await db_mod.get_notificacoes()
    gravado = " ".join(str(v) for v in linhas[0].values())
    for pedaco in (SEGREDO, "uMsEgReDoQuEnInGuEmPoDeVer", "AAtoken", "discord.com/api"):
        assert pedaco not in gravado, f"segredo vazou para o banco: {pedaco}"
        assert pedaco not in str(r), f"segredo vazou para o retorno: {pedaco}"
    assert "ConnectError" in linhas[0]["falhas"], "sem o tipo do erro não dá para diagnosticar"


@pytest.mark.asyncio
async def test_falha_total_registra_a_linha(db_mod, canais):
    """Canal quebrado e ausência de problema não podem ter a mesma aparência."""
    await db_mod.init_db()

    async def post(self, url, **kw):
        return httpx.Response(500, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", post):
        await ntf.despachar({"regra": "disk_high", "alvo": "/", "ts": _iso(_agora())})

    linhas = await db_mod.get_notificacoes()
    assert len(linhas) == 1
    assert linhas[0]["canais"] == ""
    assert linhas[0]["enviado_em"] == ""
    assert "500" in linhas[0]["falhas"]


@pytest.mark.asyncio
async def test_sem_canal_configurado_registra_e_nao_deduplica(db_mod):
    await db_mod.init_db()
    for k in ("NOTIFY_TELEGRAM_TOKEN", "NOTIFY_DISCORD_WEBHOOK", "NOTIFY_SLACK_WEBHOOK"):
        os.environ.pop(k, None)
    assert ntf.canais_configurados() == []
    await ntf.despachar({"regra": "unhealthy", "alvo": "api", "ts": _iso(_agora())})
    assert await ntf.deve_notificar("unhealthy", "api") is True


@pytest.mark.asyncio
async def test_item_deduplicado_nao_faz_chamada_de_rede(db_mod, canais):
    await db_mod.init_db()
    await db_mod.registrar_notificacao("unhealthy", "api", _iso(_agora()), ["telegram"], "", "")

    chamadas = []

    async def post(self, url, **kw):
        chamadas.append(url)
        return httpx.Response(200, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", post):
        r = await ntf.despachar({"regra": "unhealthy", "alvo": "api", "ts": _iso(_agora())})
    assert r["acao"] == "deduplicado"
    assert chamadas == []


# --- mensagem -------------------------------------------------------------

def test_mensagem_tem_host_alvo_regra_e_instante():
    ts = "2026-07-30T03:14:00Z"
    msg = ntf.monta_mensagem("container_die", "api", ts, "exit 137")
    assert ntf.HOST in msg
    assert "api" in msg and "container_die" in msg and ts in msg


def test_mensagem_nao_leva_payload_bruto():
    """Inspect e log passam por env, cmdline e header; um webhook de chat é o
    lugar menos controlado por onde esse conteúdo poderia sair."""
    import ast
    import inspect as _inspect

    fn = ast.parse(_inspect.getsource(ntf.monta_mensagem).strip()).body[0]
    # Só o CÓDIGO. A prosa da função fala em payload justamente para explicar
    # por que ele não entra, e um grep no fonte inteiro acusaria a explicação —
    # foi o que este teste fez na primeira execução.
    if ast.get_docstring(fn) is not None:
        fn.body = fn.body[1:]
    corpo = ast.unparse(fn)
    for proibido in ("payload", "inspect", "Env", "logs"):
        assert proibido not in corpo, f"a mensagem toca em {proibido}"


# --- fila -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_deteccao_nao_faz_io_de_rede():
    """`avaliar_evento` roda dentro do `async for` do stream do daemon."""
    import inspect as _inspect
    fonte = _inspect.getsource(ntf.avaliar_evento)
    assert "await" not in fonte
    assert "httpx" not in fonte


@pytest.mark.asyncio
async def test_fila_cheia_descarta_em_vez_de_bloquear():
    """Com o despachante travado, bloquear seria segurar o stream de eventos —
    trocar a timeline por notificação."""
    ntf._fila = asyncio.Queue(maxsize=2)
    assert ntf.enfileirar("container_die", "a") is True
    assert ntf.enfileirar("container_die", "b") is True
    assert ntf.enfileirar("container_die", "c") is False
    assert ntf._descartadas == 1


@pytest.mark.asyncio
async def test_o_despachante_consome_a_fila(db_mod, canais):
    await db_mod.init_db()
    enviados = []

    async def post(self, url, **kw):
        enviados.append(kw.get("json"))
        return httpx.Response(200, request=httpx.Request("POST", url))

    ntf.enfileirar("container_die", "api", _iso(_agora()), "exit 1")
    with patch.object(httpx.AsyncClient, "post", post):
        tarefa = asyncio.create_task(ntf.despachante_loop())
        await asyncio.wait_for(ntf.fila().join(), timeout=5)
        tarefa.cancel()
        try:
            await tarefa
        except asyncio.CancelledError:
            pass

    assert enviados, "o despachante não entregou"
    assert (await db_mod.get_notificacoes())[0]["regra"] == "container_die"


@pytest.mark.asyncio
async def test_item_que_levanta_nao_mata_o_despachante(db_mod, canais):
    await db_mod.init_db()
    ntf.enfileirar("container_die", "api")
    ntf.enfileirar("unhealthy", "worker")

    chamadas = []
    real = ntf.despachar

    async def instavel(item):
        chamadas.append(item["regra"])
        if len(chamadas) == 1:
            raise RuntimeError("banco fora")
        return await real(item)

    async def post(self, url, **kw):
        return httpx.Response(200, request=httpx.Request("POST", url))

    with patch.object(ntf, "despachar", instavel), patch.object(httpx.AsyncClient, "post", post):
        tarefa = asyncio.create_task(ntf.despachante_loop())
        await asyncio.wait_for(ntf.fila().join(), timeout=5)
        tarefa.cancel()
        try:
            await tarefa
        except asyncio.CancelledError:
            pass

    assert chamadas == ["container_die", "unhealthy"], "o laço morreu no primeiro erro"


# --- contrato -------------------------------------------------------------

@pytest.mark.asyncio
async def test_resumo_e_none_quando_nada_foi_notificado(db_mod):
    await db_mod.init_db()
    assert await db_mod.get_notificacoes_resumo() is None


@pytest.mark.asyncio
async def test_resumo_separa_entregue_de_sem_entrega(db_mod):
    await db_mod.init_db()
    await db_mod.registrar_notificacao("container_die", "api", _iso(_agora()), ["telegram"], "", "")
    await db_mod.registrar_notificacao("disk_high", "/", _iso(_agora()), [], "slack: HTTP 500", "")
    r = await db_mod.get_notificacoes_resumo()
    assert r["total"] == 2
    assert r["sem_entrega"] == 1
    assert r["ultima_entrega"]


@pytest.mark.asyncio
async def test_brute_force_saiu_da_reserva_no_b11():
    """Este teste SUBSTITUI o sentinela que proibia o disparo, no mesmo commit
    que o B11 liga a regra — a bissecção nunca encontra um estado em que a regra
    existe e o teste a proíbe, nem o contrário. Mesma disciplina do pin do
    `ENABLE_ACTIONS`.

    O disparo mora no `hardening`, e não aqui: quem detecta força bruta é o
    limitador que conta as falhas, e o motor só entrega.
    """
    import hardening
    assert "brute_force" in ntf._TITULOS
    assert "brute_force" in __import__("inspect").getsource(hardening.registra_e_notifica)


@pytest.mark.asyncio
async def test_purga_mantem_o_ring(db_mod):
    await db_mod.init_db()
    for i in range(12):
        await db_mod.registrar_notificacao("container_die", f"c{i}", _iso(_agora()), ["telegram"], "", "")
    await db_mod.purge_notificacoes(teto=5)
    assert len(await db_mod.get_notificacoes(limit=500)) == 5


# --- migração v14 -> v15 sobre banco POPULADO -----------------------------

def _popula_v14(path):
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
    conn.execute(
        "CREATE TABLE image_updates (image TEXT PRIMARY KEY, namespace TEXT NOT NULL DEFAULT '',"
        " repo TEXT NOT NULL DEFAULT '', tag TEXT NOT NULL DEFAULT '',"
        " digest_local TEXT NOT NULL DEFAULT '', digest_remoto TEXT NOT NULL DEFAULT '',"
        " status TEXT NOT NULL DEFAULT 'desconhecido', remoto_em TEXT NOT NULL DEFAULT '',"
        " consultado_em TEXT NOT NULL DEFAULT '', erro TEXT NOT NULL DEFAULT '')"
    )
    for v in range(1, 15):
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
    conn.execute(
        "INSERT INTO image_updates (image, namespace, repo, tag, digest_local, digest_remoto,"
        " status, remoto_em, consultado_em, erro)"
        " VALUES ('nginx:1.25','library','nginx','1.25','sha256:a','sha256:b',"
        " 'desatualizada','2026-07-29T10:00:00Z', ?, '')", (agora,))
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_v15_sobre_banco_v14_populado_preserva_tudo(tmp_path):
    """A v3 perdeu `first_seen` em produção. Toda migração passa por aqui."""
    caminho = str(tmp_path / "prod.db")
    _popula_v14(caminho)

    anterior = os.environ.get("COCKPIT_DB")
    os.environ["COCKPIT_DB"] = caminho
    try:
        import db as mod
        importlib.reload(mod)
        await mod.init_db()
        db = await mod.get_db()

        for tabela in ("audit_log", "docker_events", "logs_ingest", "image_updates"):
            cur = await db.execute(f"SELECT COUNT(*) FROM {tabela}")
            assert (await cur.fetchone())[0] == 1, f"{tabela} perdeu linha na v15"

        # o achado do B6 continua legível: é dele que a regra de imagem vive
        linha = (await mod.get_image_updates())[0]
        assert linha["status"] == "desatualizada"
        assert linha["digest_remoto"] == "sha256:b"

        linhas, _ = await mod.search_logs("oom")
        assert len(linhas) == 1, "a v15 quebrou o índice de logs"

        cur = await db.execute("SELECT MAX(version) FROM schema_version")
        assert (await cur.fetchone())[0] == mod.SCHEMA_VERSION

        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='notificacoes'")
        assert await cur.fetchone(), "notificacoes não nasceu"

        # e a tabela nova serve para o que existe: o dedup
        assert await mod.ultima_entrega("container_die", "api") is None
        await mod.close_db()
    finally:
        if anterior is None:
            os.environ.pop("COCKPIT_DB", None)
        else:
            os.environ["COCKPIT_DB"] = anterior
