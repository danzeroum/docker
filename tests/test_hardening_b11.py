"""5-B11 — rate-limit, backup e gzip. A ultima passada no perimetro do app.

O teste que carrega o bloco e o do **IP contado**. Todo request chega do
ingress: um limitador que contasse `request.client.host` daria uma chave so para
o mundo inteiro, e o primeiro atacante trancaria todos os operadores junto com
ele. Um limitador que vira negacao de servico contra quem deveria proteger e
pior que limitador nenhum, porque parece protecao.

O simetrico tambem tem teste: aceitar `X-Forwarded-For` de QUALQUER peer deixa o
atacante escolher a propria chave de contagem, e o limite vira enfeite. O
cabecalho so vale vindo de dentro do `TRUSTED_GATEWAY_CIDR` — mesmo padrao que o
unlock ja usava.

E o backup: a copia roda DURANTE escrita do coletor, e o arquivo tem de abrir
integro. E o motivo de a API de backup do SQLite existir, e de `cp` de arquivo
quente ser o modo errado — o arquivo copiado abre normalmente e falha de forma
arbitraria depois, que e a pior propriedade possivel num backup.
"""

import asyncio
import gzip
import os
import sqlite3
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import backup as bkp  # noqa: E402
import hardening as hrd  # noqa: E402

CIDR = "172.20.0.0/16"
GATEWAY = "172.20.0.5"
CLIENTE = "203.0.113.9"


class Req:
    """Request mínimo: só o que `origem()` toca."""

    def __init__(self, peer=GATEWAY, xff=None):
        self.client = type("C", (), {"host": peer})()
        self.headers = {"x-forwarded-for": xff} if xff else {}


@pytest.fixture(autouse=True)
def _limpo():
    hrd._reset()
    hrd._avisou_sem_xff = False
    antes = os.environ.get("TRUSTED_GATEWAY_CIDR")
    os.environ["TRUSTED_GATEWAY_CIDR"] = CIDR
    yield
    hrd._reset()
    if antes is None:
        os.environ.pop("TRUSTED_GATEWAY_CIDR", None)
    else:
        os.environ["TRUSTED_GATEWAY_CIDR"] = antes


# --- de quem e o IP -------------------------------------------------------

def test_origem_vem_do_forwarded_for_quando_o_peer_e_o_gateway():
    assert hrd.origem(Req(peer=GATEWAY, xff=CLIENTE)) == CLIENTE


def test_pega_a_ultima_entrada_do_forwarded_for():
    """O nginx ANEXA o peer real ao que o cliente mandou: tudo a esquerda e
    texto escrito pelo cliente, e pegar o primeiro e o erro classico."""
    assert hrd.origem(Req(peer=GATEWAY, xff="1.2.3.4, 5.6.7.8, " + CLIENTE)) == CLIENTE


def test_forwarded_for_de_peer_nao_confiavel_e_ignorado():
    """Aceitar o cabecalho de qualquer peer deixa o atacante escolher a propria
    chave de contagem, e o limite vira enfeite."""
    assert hrd.origem(Req(peer="10.9.9.9", xff="1.1.1.1")) == "10.9.9.9"


def test_sem_forwarded_for_o_gateway_nao_vira_a_chave():
    """Contar o IP do ingress daria uma chave so para o mundo inteiro."""
    assert hrd.origem(Req(peer=GATEWAY, xff=None)) == ""


def test_origem_indeterminada_nao_conta_e_nao_bloqueia():
    for _ in range(hrd.LIMITE * 3):
        assert hrd.registra_falha("") is False
    assert hrd.bloqueado("") is False


def test_ingress_sem_xff_avisa_uma_vez(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        hrd.origem(Req(peer=GATEWAY))
        hrd.origem(Req(peer=GATEWAY))
    avisos = [r for r in caplog.records if "X-Forwarded-For" in r.getMessage()]
    assert len(avisos) == 1, "um aviso por request encheria o log de uma VPS"


# --- a janela deslizante --------------------------------------------------

def test_quinta_falha_estoura_o_limite():
    for i in range(hrd.LIMITE - 1):
        assert hrd.registra_falha(CLIENTE) is False, f"falha {i + 1}"
    assert hrd.registra_falha(CLIENTE) is True
    assert hrd.bloqueado(CLIENTE) is True


def test_o_estouro_e_so_na_transicao():
    """Uma notificacao por tentativa inundaria o canal com o mesmo fato — que e
    exatamente o que um ataque de forca bruta produz em volume."""
    disparos = [hrd.registra_falha(CLIENTE) for _ in range(hrd.LIMITE * 3)]
    assert disparos.count(True) == 1


def test_quatro_falhas_e_um_sucesso_zeram_o_contador():
    """Sem isto, quatro erros de digitacao seguidos de um acerto deixariam o
    operador a uma falha do 429 pelo resto do minuto."""
    for _ in range(hrd.LIMITE - 1):
        hrd.registra_falha(CLIENTE)
    hrd.zera(CLIENTE)
    assert hrd.bloqueado(CLIENTE) is False
    for _ in range(hrd.LIMITE - 1):
        assert hrd.registra_falha(CLIENTE) is False


def test_a_janela_desliza(monkeypatch):
    base = [1000.0]
    monkeypatch.setattr(hrd.time, "monotonic", lambda: base[0])
    for _ in range(hrd.LIMITE):
        hrd.registra_falha(CLIENTE)
    assert hrd.bloqueado(CLIENTE) is True
    base[0] += hrd.JANELA_S + 1
    assert hrd.bloqueado(CLIENTE) is False


def test_ips_diferentes_contam_separado():
    for _ in range(hrd.LIMITE):
        hrd.registra_falha(CLIENTE)
    assert hrd.bloqueado(CLIENTE) is True
    assert hrd.bloqueado("198.51.100.7") is False


def test_consulta_nao_conta_como_tentativa():
    for _ in range(hrd.LIMITE * 2):
        hrd.bloqueado(CLIENTE)
    assert hrd.bloqueado(CLIENTE) is False


# --- a regra brute_force acende -------------------------------------------

def test_o_estouro_enfileira_brute_force():
    import notify
    notify._fila = None
    hrd._reset()
    req = Req(peer=GATEWAY, xff=CLIENTE)
    for _ in range(hrd.LIMITE - 1):
        assert hrd.registra_e_notifica(req, "unlock") is False
    assert hrd.registra_e_notifica(req, "unlock") is True

    itens = []
    q = notify.fila()
    while not q.empty():
        itens.append(q.get_nowait())
    assert len(itens) == 1
    assert itens[0]["regra"] == "brute_force"
    assert itens[0]["alvo"] == CLIENTE
    assert "unlock" in itens[0]["detalhe"]
    notify._fila = None


def test_a_superficie_vai_no_detalhe():
    import notify
    notify._fila = None
    hrd._reset()
    req = Req(peer=GATEWAY, xff=CLIENTE)
    for _ in range(hrd.LIMITE):
        hrd.registra_e_notifica(req, "/metrics")
    item = notify.fila().get_nowait()
    assert "/metrics" in item["detalhe"]
    notify._fila = None


def test_a_regra_saiu_da_reserva():
    """O teste-sentinela que a proibia foi removido no MESMO commit que a liga:
    a bisseccao nunca encontra um estado em que a regra existe e o teste a
    proibe, nem o contrario. Mesma disciplina do pin do ENABLE_ACTIONS."""
    import inspect as _inspect
    import notify
    assert "brute_force" in notify._TITULOS
    assert "brute_force" in _inspect.getsource(hrd.registra_e_notifica)


# --- as duas superficies --------------------------------------------------

def test_as_duas_superficies_de_auth_estao_cobertas():
    import routers.metrics_prom as prom
    import routers.session as ses
    for modulo, nome in ((ses, "unlock"), (prom, "/metrics")):
        import inspect as _inspect
        fonte = _inspect.getsource(modulo)
        assert "bloqueado(" in fonte, f"{nome} nao consulta o limite"
        assert "registra_e_notifica(" in fonte, f"{nome} nao conta a falha"
        assert "zera(" in fonte, f"{nome} nao limpa o contador no acerto"


def test_metrics_devolve_429_apos_o_limite():
    import base64
    from fastapi.testclient import TestClient
    from app import app

    antes = (os.environ.get("BASIC_AUTH_USER"), os.environ.get("BASIC_AUTH_PASS"))
    os.environ["BASIC_AUTH_USER"] = "operador"
    os.environ["BASIC_AUTH_PASS"] = "certa"
    hrd._reset()
    try:
        cliente = TestClient(app)
        errada = {"Authorization": "Basic " + base64.b64encode(b"operador:errada").decode(),
                  "X-Forwarded-For": CLIENTE}
        codigos = []
        for _ in range(hrd.LIMITE + 2):
            # TestClient conecta de "testclient"; o gateway confiavel precisa
            # aceitar esse peer para o XFF valer.
            os.environ["TRUSTED_GATEWAY_CIDR"] = "0.0.0.0/0"
            codigos.append(cliente.get("/metrics", headers=errada).status_code)
        assert codigos[:hrd.LIMITE] == [401] * hrd.LIMITE
        assert codigos[hrd.LIMITE] == 429
        assert set(codigos[hrd.LIMITE:]) == {429}
    finally:
        hrd._reset()
        for chave, valor in zip(("BASIC_AUTH_USER", "BASIC_AUTH_PASS"), antes):
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor


def test_credencial_certa_depois_de_falhas_zera_e_nao_bloqueia():
    import base64
    from fastapi.testclient import TestClient
    from app import app

    antes = (os.environ.get("BASIC_AUTH_USER"), os.environ.get("BASIC_AUTH_PASS"))
    os.environ["BASIC_AUTH_USER"] = "operador"
    os.environ["BASIC_AUTH_PASS"] = "certa"
    os.environ["TRUSTED_GATEWAY_CIDR"] = "0.0.0.0/0"
    hrd._reset()
    try:
        cliente = TestClient(app)
        cabecalho = {"X-Forwarded-For": CLIENTE}
        errada = dict(cabecalho,
                      Authorization="Basic " + base64.b64encode(b"operador:errada").decode())
        certa = dict(cabecalho,
                     Authorization="Basic " + base64.b64encode(b"operador:certa").decode())
        for _ in range(hrd.LIMITE - 1):
            assert cliente.get("/metrics", headers=errada).status_code == 401
        assert cliente.get("/metrics", headers=certa).status_code == 200
        # zerado: cabem de novo LIMITE-1 falhas sem 429
        for _ in range(hrd.LIMITE - 1):
            assert cliente.get("/metrics", headers=errada).status_code == 401
    finally:
        hrd._reset()
        for chave, valor in zip(("BASIC_AUTH_USER", "BASIC_AUTH_PASS"), antes):
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor


def test_503_de_configuracao_faltando_nao_conta_contra_o_ip():
    """Configuracao NOSSA ausente nao e tentativa de acesso."""
    import base64
    from fastapi.testclient import TestClient
    from app import app

    antes = (os.environ.get("BASIC_AUTH_USER"), os.environ.get("BASIC_AUTH_PASS"))
    os.environ.pop("BASIC_AUTH_USER", None)
    os.environ.pop("BASIC_AUTH_PASS", None)
    os.environ["TRUSTED_GATEWAY_CIDR"] = "0.0.0.0/0"
    hrd._reset()
    try:
        cliente = TestClient(app)
        cabecalho = {"X-Forwarded-For": CLIENTE,
                     "Authorization": "Basic " + base64.b64encode(b"a:b").decode()}
        for _ in range(hrd.LIMITE + 3):
            assert cliente.get("/metrics", headers=cabecalho).status_code == 503
        assert hrd.bloqueado(CLIENTE) is False
    finally:
        hrd._reset()
        for chave, valor in zip(("BASIC_AUTH_USER", "BASIC_AUTH_PASS"), antes):
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor


# --- backup ---------------------------------------------------------------

def _banco(caminho, linhas=200):
    conn = sqlite3.connect(caminho)
    conn.execute("CREATE TABLE amostras (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO amostras (v) VALUES (?)", [(f"v{i}",) for i in range(linhas)])
    conn.commit()
    conn.close()


def test_backup_gera_arquivo_datado_que_abre_integro(tmp_path):
    origem = str(tmp_path / "cockpit.db")
    _banco(origem)
    destino = str(tmp_path / "backups")

    r = bkp.fazer_backup_sync(destino, origem)
    assert r["ok"], r["erro"]
    assert os.path.basename(r["arquivo"]).startswith("cockpit-")

    conn = sqlite3.connect(r["arquivo"])
    assert conn.execute("SELECT COUNT(*) FROM amostras").fetchone()[0] == 200
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


def test_backup_durante_escrita_do_coletor_abre_sem_erro(tmp_path):
    """O sampler escreve continuamente. `cp` pegaria o arquivo no meio de uma
    transacao: abre normalmente e falha de forma arbitraria depois."""
    origem = str(tmp_path / "cockpit.db")
    _banco(origem, linhas=50)
    destino = str(tmp_path / "backups")

    parar = threading.Event()

    def escrevendo():
        conn = sqlite3.connect(origem, timeout=30)
        n = 0
        while not parar.is_set():
            conn.execute("INSERT INTO amostras (v) VALUES (?)", (f"quente{n}",))
            conn.commit()
            n += 1
            time.sleep(0.001)
        conn.close()

    t = threading.Thread(target=escrevendo, daemon=True)
    t.start()
    time.sleep(0.05)
    try:
        r = bkp.fazer_backup_sync(destino, origem)
    finally:
        parar.set()
        t.join(timeout=5)

    assert r["ok"], r["erro"]
    conn = sqlite3.connect(r["arquivo"])
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("SELECT COUNT(*) FROM amostras").fetchone()[0] >= 50
    conn.close()


def test_rotacao_mantem_exatamente_sete(tmp_path):
    destino = tmp_path / "backups"
    destino.mkdir()
    for i in range(12):
        (destino / f"cockpit-2026-07-{i + 1:02d}T000000Z.db").write_bytes(b"x")
    bkp.rotaciona(str(destino), manter=7)
    restantes = sorted(p.name for p in destino.iterdir())
    assert len(restantes) == 7
    # os SETE MAIS NOVOS, e nao sete quaisquer
    assert restantes[0] == "cockpit-2026-07-06T000000Z.db"
    assert restantes[-1] == "cockpit-2026-07-12T000000Z.db"


def test_rotacao_ignora_arquivo_que_nao_e_backup(tmp_path):
    destino = tmp_path / "backups"
    destino.mkdir()
    (destino / "cockpit.db").write_bytes(b"o banco vivo, nao um backup")
    (destino / "NOTAS.txt").write_bytes(b"x")
    for i in range(9):
        (destino / f"cockpit-2026-07-{i + 1:02d}T000000Z.db").write_bytes(b"x")
    bkp.rotaciona(str(destino), manter=7)
    nomes = {p.name for p in destino.iterdir()}
    assert "cockpit.db" in nomes, "a rotacao apagou o banco vivo"
    assert "NOTAS.txt" in nomes


def test_banco_ausente_nao_levanta(tmp_path):
    r = bkp.fazer_backup_sync(str(tmp_path / "b"), str(tmp_path / "nao-existe.db"))
    assert r["ok"] is False
    assert r["arquivo"] == ""


def test_backup_usa_a_api_do_sqlite_e_nao_copia_de_arquivo():
    import ast
    import inspect as _inspect
    arvore = ast.parse(_inspect.getsource(bkp))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Expr) and isinstance(no.value, ast.Constant) \
                and isinstance(no.value.value, str):
            no.value.value = ""
    codigo = ast.unparse(arvore)
    assert ".backup(" in codigo
    for proibido in ("shutil.copy", "shutil.copyfile", "subprocess", "os.system"):
        assert proibido not in codigo, f"backup por {proibido} pega o arquivo quente"


@pytest.mark.asyncio
async def test_backup_assincrono_nao_bloqueia_o_loop(tmp_path):
    origem = str(tmp_path / "cockpit.db")
    _banco(origem, linhas=2000)
    marcas = []

    async def batendo():
        for _ in range(5):
            marcas.append(1)
            await asyncio.sleep(0.005)

    tarefa = asyncio.create_task(batendo())
    r = await bkp.fazer_backup(str(tmp_path / "backups"), origem)
    await tarefa
    assert r["ok"]
    assert len(marcas) == 5, "o loop ficou parado durante a copia"


# --- gzip -----------------------------------------------------------------

def test_o_middleware_esta_montado_e_e_o_mais_externo():
    """Mais externo porque comprime a resposta FINAL, depois de todo mundo ter
    escrito nela. Montado por dentro do CORS, ele comprimiria antes de os
    cabecalhos de CORS entrarem."""
    from app import app
    from compressao import GzipJsonMiddleware

    classes = [m.cls for m in app.user_middleware]
    assert GzipJsonMiddleware in classes, "o gzip nao esta montado"
    assert classes[0] is GzipJsonMiddleware, "o gzip nao e a camada mais externa"


def test_o_middleware_nao_toca_em_event_stream():
    """Gzip num stream poe buffer entre o evento acontecer e a tela mostra-lo, e
    a timeline ao vivo e justamente o que nao pode chegar atrasada."""
    import inspect as _inspect
    import compressao
    assert "text/event-stream" not in str(compressao._COMPRESSIVEL)
    fonte = _inspect.getsource(compressao)
    # a decisao e por content-type: filtrar por caminho resolveria as duas rotas
    # de hoje e quebraria na terceira
    assert "content-type" in fonte
    assert "scope[\"path\"]" not in fonte


@pytest.mark.asyncio
async def test_stream_passa_chunk_a_chunk_sem_buffer():
    from compressao import GzipJsonMiddleware

    async def app_falso(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        for i in range(3):
            await send({"type": "http.response.body",
                        "body": f"data: {i}\n\n".encode(), "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    enviados = []

    async def send(msg):
        enviados.append(msg)

    scope = {"type": "http", "headers": [(b"accept-encoding", b"gzip")]}
    await GzipJsonMiddleware(app_falso)(scope, None, send)

    corpos = [m for m in enviados if m["type"] == "http.response.body"]
    assert len(corpos) == 4, "o stream foi bufferizado num corpo so"
    inicio = enviados[0]
    assert not any(n == b"content-encoding" for n, _ in inicio["headers"])


@pytest.mark.asyncio
async def test_json_pequeno_nao_ganha_gzip():
    from compressao import GzipJsonMiddleware

    async def app_falso(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"ok":true}', "more_body": False})

    enviados = []
    scope = {"type": "http", "headers": [(b"accept-encoding", b"gzip")]}
    await GzipJsonMiddleware(app_falso)(scope, None, lambda m: _guarda(enviados, m))
    inicio = enviados[0]
    assert not any(n == b"content-encoding" for n, _ in inicio["headers"])


async def _guarda(lista, msg):
    lista.append(msg)


@pytest.mark.asyncio
async def test_json_grande_comprime_e_declara_vary():
    from compressao import GzipJsonMiddleware

    corpo = ('{"x":"' + "a" * 5000 + '"}').encode()

    async def app_falso(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(corpo)).encode())]})
        await send({"type": "http.response.body", "body": corpo, "more_body": False})

    enviados = []
    scope = {"type": "http", "headers": [(b"accept-encoding", b"gzip")]}
    await GzipJsonMiddleware(app_falso)(scope, None, lambda m: _guarda(enviados, m))

    cabecalhos = dict(enviados[0]["headers"])
    assert cabecalhos[b"content-encoding"] == b"gzip"
    # Vary: sem ele, um cache intermediario serve a resposta comprimida a um
    # cliente que nao pediu gzip.
    assert cabecalhos[b"vary"] == b"Accept-Encoding"
    saida = enviados[1]["body"]
    assert int(cabecalhos[b"content-length"]) == len(saida)
    assert gzip.decompress(saida) == corpo


@pytest.mark.asyncio
async def test_cliente_que_nao_pede_gzip_recebe_cru():
    from compressao import GzipJsonMiddleware

    corpo = ('{"x":"' + "a" * 5000 + '"}').encode()

    async def app_falso(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": corpo, "more_body": False})

    enviados = []
    await GzipJsonMiddleware(app_falso)({"type": "http", "headers": []}, None,
                                        lambda m: _guarda(enviados, m))
    assert enviados[1]["body"] == corpo
