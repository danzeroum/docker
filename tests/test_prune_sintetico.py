"""Fase 4: prune validado sobre um daemon sintético — sem remover nada.

O QUE FALTAVA. `test_prune_v12.py` cobre bem a barreira e o fluxo, mas com um
ponto cego estrutural: ele mocka `get_storage` com um dicionário escrito à mão.
A afirmação central do módulo — *"a lista que o `dry_run` devolve é a mesma que
`/api/storage` mostra, e não uma segunda opinião que poderia divergir"* — fica
verificada contra uma ficção. Os dois lados leem o MESMO literal, então
concordam por construção. Se o classificador de `/api/storage` mudasse de
critério amanhã, aquele arquivo continuaria verde.

Aqui o ponto de partida é outro: o sintético é o payload do DAEMON
(`/system/df` + `/containers/json?all=1`), e daí para cima roda tudo de
verdade — o classificador do B1, o filtro do B10, a rota, a auditoria. As duas
listas são então comparadas item a item. Divergir aqui é a tela prometer espaço
que o endpoint não entrega, que é o defeito que este módulo existe para não ter.

Por que dá para fazer isto sem `ENABLE_ACTIONS` de verdade e sem socket-proxy
com escrita: `dry_run=true` é o padrão e RETORNA antes de qualquer `proxy_post`.
Esta é a metade do valor pela fração do risco — e para que ela não seja uma
suposição, a escrita aqui é uma ARMADILHA (`_armadilha_de_escrita`), não um
mock complacente: qualquer chamada explode, e um teste prova que ela explodiria.

Fidelidade do sintético, porque é o que separa isto de teatro:

  * a lista `/containers/json?all=1` vem SEM `SizeRw` — é assim que o daemon
    responde sem `size=1`, e a app não pede `size=1` (custaria uma varredura de
    camadas a cada 2 s). Foi essa fidelidade que revelou o zumbi valendo zero;
  * `RepoTags` aparece nas DUAS formas que significam dangling (`null` e
    `["<none>:<none>"]`), porque a versão do daemon decide qual;
  * `UsageData.Size = -1` é o "não calculado" do daemon, não um volume negativo;
  * seções nulas (host limpo) em vez de listas vazias.
"""

import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

GB = 1024 ** 3
MB = 1024 ** 2

SESSAO = {"remote_user": "qa-sintetico", "ip": "10.9.0.7", "motivo": "fase 4"}


def _epoch_dias_atras(dias: float) -> float:
    return datetime.now(timezone.utc).timestamp() - dias * 86400


# ---------------------------------------------------------------------------
# o daemon sintético
# ---------------------------------------------------------------------------

def _df_sintetico() -> dict:
    """`/system/df` com um caso de cada categoria, incluindo os que NÃO contam."""
    return {
        "Images": [
            # dois órfãos de verdade, nas duas formas de "sem tag"
            {"Id": "sha256:orfa1", "RepoTags": None, "Size": 3 * GB, "Containers": 0},
            {"Id": "sha256:orfa2", "RepoTags": ["<none>:<none>"], "Size": 1 * GB, "Containers": 0},
            # SEM TAG MAS EM USO: `docker image prune` recusaria, e oferecê-la na
            # lista seria prometer 2 GB que não vêm. É a armadilha do critério.
            {"Id": "sha256:emuso", "RepoTags": None, "Size": 2 * GB, "Containers": 2},
            # taggeada: some da conversa
            {"Id": "sha256:nginx", "RepoTags": ["nginx:1.27"], "Size": 500 * MB, "Containers": 1},
        ],
        "Volumes": [
            # preso a um container PARADO — não é órfão (ver `_volumes_referenciados`)
            {"Name": "dados-do-banco", "UsageData": {"Size": 2 * GB, "RefCount": 0}},
            # ninguém referencia: órfão para a TELA, nunca candidato do prune
            {"Name": "sobra-de-teste", "UsageData": {"Size": 512 * MB, "RefCount": 0}},
            # -1 é "não calculado" do daemon; não pode virar tamanho negativo
            {"Name": "sem-medida", "UsageData": {"Size": -1, "RefCount": 0}},
        ],
        "Containers": [
            {"Id": "c-app", "SizeRw": 12 * MB},
            {"Id": "c-banco", "SizeRw": 300 * MB},
        ],
        "BuildCache": [
            # 7 GB recuperáveis que NENHUM dos dois lados pode prometer:
            # `builder prune` é outro comando, com outro risco. O valor é
            # deliberadamente diferente de qualquer soma do arquivo — número
            # repetido faria uma asserção passar por coincidência.
            {"Id": "bc1", "Size": 7 * GB, "InUse": False},
        ],
    }


def _containers_sinteticos() -> list:
    """`/containers/json?all=1` — sem `SizeRw`, como o daemon responde de fato."""
    return [
        {
            "Id": "c-app",
            "Names": ["/app-sintetica"],
            "State": "running",
            "Created": _epoch_dias_atras(3),
            "Mounts": [],
        },
        {
            "Id": "c-banco",
            "Names": ["/banco-desligado"],
            "State": "exited",
            "Created": _epoch_dias_atras(40),
            # este mount é o que salva `dados-do-banco` de ser listado como órfão
            "Mounts": [{"Type": "volume", "Name": "dados-do-banco"}],
        },
    ]


async def _proxy_get_falso(path: str, timeout: int = 10):
    if path.startswith("/system/df"):
        return _df_sintetico()
    if path.startswith("/containers/json"):
        return _containers_sinteticos()
    raise AssertionError(f"o teste não previu a chamada {path!r} ao daemon")


async def _armadilha_de_escrita(*args, **kwargs):
    """Nenhum caminho exercitado aqui pode escrever no daemon.

    Deliberadamente uma exceção e não um `AsyncMock`: mock complacente devolve
    algo, a rota segue feliz, e a violação só apareceria num `assert_not_awaited`
    DEPOIS — quando já haveria efeito colateral num daemon de verdade. Aqui a
    primeira escrita derruba a requisição.
    """
    raise AssertionError(f"escrita no daemon a partir de um caminho que não deveria escrever: {args}")


# ---------------------------------------------------------------------------
# bancada
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _bancada():
    """Cache zerado e `dependency_overrides` desfeitos — antes e depois.

    O cache é de processo e `/api/storage` tem TTL de 30 s: sem limpar, este
    arquivo herdaria o storage que outro teste deixou, e as asserções mediriam
    dado alheio. E o override de `require_unlock` sobrevive ao arquivo se não for
    desfeito — o pior vazamento possível num teste de autorização.
    """
    import cache
    from app import app as app_mod
    from auth import require_unlock

    cache.invalidate()
    app_mod.dependency_overrides[require_unlock] = lambda: SESSAO
    yield
    app_mod.dependency_overrides.clear()
    cache.invalidate()


def _cliente():
    from fastapi.testclient import TestClient
    from app import app as app_mod
    return TestClient(app_mod)


@contextmanager
def _daemon_sintetico(leitura=None):
    """Daemon sintético na leitura, armadilha na escrita, auditoria de mentira.

    A auditoria fica mockada nos testes de CLASSIFICAÇÃO de propósito: eles
    medem o critério, não o rastro. O rastro tem os dois casos no fim do
    arquivo, com banco de verdade.
    """
    with patch("routers.storage.proxy_get", leitura or _proxy_get_falso), \
         patch("routers.prune.proxy_post", _armadilha_de_escrita), \
         patch("routers.prune.audit_iniciar", AsyncMock(return_value=1)), \
         patch("routers.prune.audit_concluir", AsyncMock()):
        yield


def _storage_e_prune(client):
    """As duas respostas, de duas classificações INDEPENDENTES.

    O `invalidate` no meio não é zelo: sem ele a segunda chamada leria o cache
    de 30 s da primeira, e a igualdade entre as listas seria garantida pelo
    CACHE, não pelo critério — o teste passaria mesmo com os dois lados
    discordando.
    """
    import cache
    a = client.get("/api/storage")
    assert a.status_code == 200, a.text
    cache.invalidate()
    b = client.post("/api/prune")
    assert b.status_code == 200, b.text
    return a.json(), b.json()


# ---------------------------------------------------------------------------
# a afirmação central: uma opinião só
# ---------------------------------------------------------------------------

def test_a_lista_do_dry_run_e_a_mesma_que_a_tela_mostra():
    """Duas opiniões aqui seriam a tela prometendo espaço que o endpoint não
    entrega — e ninguém descobriria até o clique."""
    with _daemon_sintetico():
        storage, prune = _storage_e_prune(_cliente())

    imagens_da_tela = [o for o in storage["orphans"] if o["type"] == "image"]
    assert prune["candidates"] == imagens_da_tela, (
        "a lista do dry_run divergiu da que a tela mostra — são dois critérios")
    assert prune["count"] == storage["images"]["dangling_count"] == 2


def test_o_numero_que_o_prune_promete_e_menor_e_a_diferenca_tem_nome():
    """`reclaimable_bytes` significa coisas DIFERENTES nos dois lados, e isso é
    correto: a tela soma tudo que dá para recuperar, o prune só o que ELE
    recupera. O que não pode é a diferença ser um resto sem explicação.
    """
    with _daemon_sintetico():
        storage, prune = _storage_e_prune(_cliente())

    assert prune["reclaimable_bytes"] == 4 * GB
    assert prune["reclaimable_bytes"] <= storage["reclaimable_bytes"], (
        "o prune prometeu mais espaço do que a tela inteira reconhece")

    diferenca = storage["reclaimable_bytes"] - prune["reclaimable_bytes"]
    assert diferenca == (
        storage["volumes"]["orphan_bytes"] + storage["containers"]["stopped_old_bytes"]
    ), "sobrou byte sem dono entre os dois números"


def test_o_zumbi_nao_vale_zero():
    """Regressão do que a FIDELIDADE do sintético revelou.

    `/containers/json?all=1` não traz `SizeRw` — só vem com `size=1`, que a app
    não pede. O classificador lia o tamanho DALI, então todo container parado
    entrava no `reclaimable_bytes` valendo 0: a tela subestimava a limpeza em
    silêncio, e ninguém via porque o número existia e parecia plausível.
    O `/system/df` já calculou esse tamanho; agora ele é cruzado por Id.
    """
    with patch("routers.storage.proxy_get", _proxy_get_falso):
        r = _cliente().get("/api/storage")

    corpo = r.json()
    assert corpo["containers"]["stopped_old_count"] == 1
    assert corpo["containers"]["stopped_old_bytes"] == 300 * MB, (
        "o container parado voltou a valer zero — a tela subestima a limpeza")
    zumbi = [o for o in corpo["orphans"] if o["type"] == "container"][0]
    assert zumbi["name"] == "banco-desligado"
    assert zumbi["size_bytes"] == 300 * MB


def test_o_build_cache_fica_de_fora_dos_dois_lados():
    """4 GB reais e recuperáveis que nem a tela nem o prune podem prometer:
    `builder prune` é outro comando, com outro risco (invalida cache de build).
    Somar os dois num número só é o jeito clássico de a tela mentir para cima."""
    with _daemon_sintetico():
        storage, prune = _storage_e_prune(_cliente())

    assert storage["build_cache"]["reclaimable_bytes"] == 7 * GB

    # Por COMPOSIÇÃO, e não por "o número não aparece": cada total é exatamente
    # a soma das parcelas que ele promete, e o build cache não é uma delas.
    assert storage["reclaimable_bytes"] == (
        storage["images"]["dangling_bytes"]
        + storage["volumes"]["orphan_bytes"]
        + storage["containers"]["stopped_old_bytes"]
    ), "o total da tela deixou de ser a soma do que ela lista"
    assert prune["reclaimable_bytes"] == storage["images"]["dangling_bytes"], (
        "o prune promete algo além das imagens dangling — é a única categoria "
        "que ele remove")


# ---------------------------------------------------------------------------
# o que NÃO pode entrar na lista
# ---------------------------------------------------------------------------

def test_imagem_sem_tag_mas_em_uso_nao_entra_na_lista():
    """Dangling não basta: `Containers > 0` significa que alguém está rodando
    aquilo. O daemon recusaria a remoção — mas a lista teria prometido 2 GB, e a
    promessa é o defeito, não a recusa."""
    with _daemon_sintetico():
        corpo = _cliente().post("/api/prune").json()

    ids = {c["id"] for c in corpo["candidates"]}
    assert "sha256:emuso" not in ids, "ofereceu remover imagem que um container usa"
    assert ids == {"sha256:orfa1", "sha256:orfa2"}


def test_volume_preso_a_container_parado_nao_e_orfao_nem_candidato():
    """Duas proteções em camadas, e as duas medidas aqui:

    1. o classificador não o chama de órfão, porque um container PARADO ainda o
       referencia (`RefCount` do daemon diria 0 — por isso a fonte é `Mounts`);
    2. mesmo o volume que É órfão nunca vira candidato do prune: volume guarda
       DADO, e remover exige um pedido próprio que este endpoint não oferece.
    """
    with _daemon_sintetico():
        storage, prune = _storage_e_prune(_cliente())

    orfaos_volume = {o["name"] for o in storage["orphans"] if o["type"] == "volume"}
    assert "dados-do-banco" not in orfaos_volume, (
        "volume de container parado listado como órfão — apagá-lo perderia o dado")
    assert "sobra-de-teste" in orfaos_volume

    tipos = {c["type"] for c in prune["candidates"]}
    assert tipos == {"image"}, f"o prune ofereceu remover {tipos - {'image'}}"


def test_volume_sem_medida_nao_vira_tamanho_negativo():
    """`Size: -1` é o "não calculado" do daemon. Somado cru, encolheria o total
    e a tela prometeria MENOS espaço do que existe — erro silencioso porque o
    número continua parecendo um número."""
    with patch("routers.storage.proxy_get", _proxy_get_falso):
        corpo = _cliente().get("/api/storage").json()

    assert corpo["volumes"]["size_bytes"] >= 0
    assert corpo["volumes"]["orphan_bytes"] == 512 * MB
    sem_medida = [o for o in corpo["orphans"] if o["name"] == "sem-medida"]
    assert sem_medida and sem_medida[0]["size_bytes"] == 0


# ---------------------------------------------------------------------------
# a armadilha: o dry_run não pode alcançar a escrita
# ---------------------------------------------------------------------------

def test_o_padrao_nao_alcanca_a_escrita_no_daemon():
    """Chamada sem parâmetro nenhum: não pode remover nada."""
    with _daemon_sintetico():
        r = _cliente().post("/api/prune")

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["dry_run"] is True, "o padrão deixou de ser dry_run"
    assert corpo["removed_bytes"] == 0
    assert "nada foi removido" in corpo["note"]


def test_a_armadilha_esta_armada():
    """O teste do teste, e o motivo de a armadilha valer mais que um mock.

    Uma armadilha que nunca dispara não prova nada: se `proxy_post` estivesse
    remendado no lugar errado, o teste acima passaria por engano. Aqui a mesma
    armadilha é exercitada pelo caminho que DEVE escrever — e ela explode.
    """
    with _daemon_sintetico():
        with pytest.raises(AssertionError, match="escrita no daemon"):
            _cliente().post("/api/prune?dry_run=false")


# ---------------------------------------------------------------------------
# host limpo
# ---------------------------------------------------------------------------

def test_host_limpo_nao_quebra_o_dry_run():
    """O daemon manda `null`, não `[]`, para seção vazia — num host que nunca
    construiu imagem, por exemplo. É o caso de borda que estoura com TypeError
    onde ninguém testou."""
    async def vazio(path: str, timeout: int = 10):
        if path.startswith("/system/df"):
            return {"Images": None, "Volumes": None, "Containers": None, "BuildCache": None}
        return []

    with _daemon_sintetico(leitura=vazio):
        r = _cliente().post("/api/prune")

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["count"] == 0
    assert corpo["reclaimable_bytes"] == 0
    assert corpo["candidates"] == []


# ---------------------------------------------------------------------------
# a auditoria, no banco de verdade
# ---------------------------------------------------------------------------

async def _banco(tmp_path):
    """Banco real e temporário, com o prune religado a ele.

    O `patch` das duas funções de auditoria NÃO é para fingir: são as funções
    VERDADEIRAS do módulo recarregado. `routers/prune.py` faz
    `from db import audit_iniciar, audit_concluir`, então recarregar o `db`
    deixaria a rota escrevendo na conexão do banco ANTERIOR — já fechada. Mesmo
    mecanismo que fez o motor de achados escrever no banco errado em
    test_ciclo_acao_sintetico.py.
    """
    import importlib
    os.environ["COCKPIT_DB"] = str(tmp_path / "prune.db")
    import db as db_mod
    importlib.reload(db_mod)
    await db_mod.init_db()
    return db_mod


async def _fecha(db_mod):
    try:
        await db_mod.close_db()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_a_consulta_deixa_linha_de_auditoria_fechada(tmp_path):
    """`dry_run` também é auditado: é a consulta que precede toda remoção, e
    saber quem perguntou o que dá para apagar é parte do rastro.

    Diferente do caso equivalente em `test_prune_v12.py`, aqui a linha é lida do
    BANCO — o mock só podia afirmar que a função foi chamada, não que a linha
    nasceu, fechou e guardou o ator.
    """
    db_mod = await _banco(tmp_path)
    try:
        with patch("routers.storage.proxy_get", _proxy_get_falso), \
             patch("routers.prune.proxy_post", _armadilha_de_escrita), \
             patch("routers.prune.audit_iniciar", db_mod.audit_iniciar), \
             patch("routers.prune.audit_concluir", db_mod.audit_concluir):
            r = _cliente().post("/api/prune")
        assert r.status_code == 200, r.text

        linhas = await db_mod.get_audit_log(limit=10)
        do_prune = [x for x in linhas if x["action"].startswith("prune")]
        assert do_prune, "a consulta não deixou rastro nenhum"
        linha = do_prune[0]
        assert linha["action"] == "prune_dry_run", (
            f"a consulta foi registrada como {linha['action']!r} — uma auditoria "
            "que não distingue consulta de remoção não serve para o que existe")
        assert linha["token_label"] == SESSAO["remote_user"], "rastro sem quem"
        assert linha["status"] == "done", "a linha ficou aberta"
        assert "2 imagem(ns)" in linha["result"] and str(4 * GB) in linha["result"]
    finally:
        await _fecha(db_mod)


@pytest.mark.asyncio
async def test_daemon_fora_do_ar_deixa_a_tentativa_registrada(tmp_path):
    """A ordem é a propriedade: `audit_iniciar` roda ANTES de `get_storage`.

    Se a auditoria viesse depois, a tentativa que falhou não existiria em lugar
    nenhum — e é exatamente a tentativa contra um daemon fora do ar que alguém
    vai querer encontrar depois.
    """
    async def recusa(path: str, timeout: int = 10):
        raise httpx.ConnectError("connection refused")

    db_mod = await _banco(tmp_path)
    try:
        with patch("routers.storage.proxy_get", recusa), \
             patch("routers.prune.proxy_post", _armadilha_de_escrita), \
             patch("routers.prune.audit_iniciar", db_mod.audit_iniciar), \
             patch("routers.prune.audit_concluir", db_mod.audit_concluir):
            r = _cliente().post("/api/prune")

        assert r.status_code == 503
        assert "socket-proxy" in r.json()["detail"]

        linhas = await db_mod.get_audit_log(limit=10)
        do_prune = [x for x in linhas if x["action"].startswith("prune")]
        assert do_prune, "a tentativa contra um daemon fora do ar não deixou rastro"
        assert do_prune[0]["status"] == "error"
        assert do_prune[0]["result"].startswith("error:")
    finally:
        await _fecha(db_mod)
