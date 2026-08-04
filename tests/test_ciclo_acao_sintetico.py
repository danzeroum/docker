"""O ciclo inteiro sobre dados sintéticos: estado → regra → achado → cartão → ack.

O QUE FALTAVA. As peças deste caminho já tinham teste cada uma por si:
`test_ack_audit.py` semeia um achado PRONTO e o reconhece; `test_findings.py`
avalia regras com contexto montado à mão; `test_tasks.py` cobre o board. Nenhum
liga as três — e é na emenda que mora o que ninguém viu.

A diferença é o ponto de partida. Aqui nada de achado pré-fabricado: o teste
semeia o ESTADO que uma regra observaria no daemon (um container reiniciando),
roda o motor de verdade, e a partir daí só age pela API. Se a regra parar de
disparar, se o cartão parar de nascer, se o ack parar de fechar o ciclo — este
arquivo cai, e os outros três continuam verdes.

POR QUE SINTÉTICO, e não esperar o real: `restart_loop` precisa que o
`RestartCount` CRESÇA entre dois ciclos. Esperar isso acontecer num container de
verdade é esperar um incidente. Fabricar o estado é a única forma de exercitar o
caminho antes de precisar dele.

O que NÃO está aqui: as ações que tocam o daemon (`stop`, `restart`, `DELETE`,
`prune`). Elas exigem `ENABLE_ACTIONS=1` e um socket-proxy com escrita liberada —
ambiente separado, com sua própria trava. Este arquivo cobre a metade do caminho
de escrita que existe INDEPENDENTE daquela flag, e que por isso vive em qualquer
instalação, inclusive na homologação.
"""
import importlib
import json
import os

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


IP_CONFIAVEL = "10.9.0.7"
CIDR = "10.9.0.0/24"
OPERADOR = "qa-sintetico"


async def _fecha(db_mod):
    """Fecha a conexao mesmo com assert falhando.

    Sem isto a thread da aiosqlite sobrevive e o pytest trava no fim da suite,
    sem mensagem — o sintoma parece hang, nao falha. Copiado de
    test_ack_audit.py de proposito: o modo de errar e o mesmo.
    """
    try:
        await db_mod.close_db()
    except Exception:
        pass


def _inspect_sintetico(nome: str, restart_count: int) -> dict:
    """Um inspect de container como o daemon devolveria.

    Os campos sao os que `restart_loop` le, e nada alem: fabricar um inspect
    completo daria a impressao de fidelidade que este teste nao tem nem precisa.
    `Health` vem PRESENTE valendo None de proposito — e assim que o daemon
    responde para container sem healthcheck, e foi essa forma que ja derrubou o
    ciclo de avaliacao inteiro uma vez (ver o comentario em restart_loop.py).
    """
    return {
        "Id": f"sintetico-{nome}",
        "Name": f"/{nome}",
        "Config": {"Image": "alpine:3", "Labels": {"cockpit.teste.sintetico": "1"}},
        "State": {
            "Status": "running",
            "RestartCount": restart_count,
            "OOMKilled": False,
            "ExitCode": 0,
            "Health": None,
        },
        "HostConfig": {"RestartPolicy": {"Name": "always"}},
        "Mounts": [],
    }


async def _bancada(tmp_path):
    """Banco limpo, motor religado a ele, sem daemon nenhum.

    O `reload` do motor NAO e zelo: `findings/engine.py` faz
    `from db import (upsert_finding, ...)`, o que amarra as funcoes no import.
    Recarregar so o `db` deixa o motor chamando as funcoes ANTIGAS, ligadas a
    conexao que o teste anterior fechou — e o sintoma e cruel: o primeiro teste
    do arquivo passa (o motor ainda aponta para o banco certo) e os seguintes
    falham com "achado nao encontrado", como se a regra tivesse parado de valer.

    Recarregar os dois na ordem reata a ligacao, e de quebra zera `_rules`,
    `_debounce_state` e `_last_run`, que sao estado de processo.
    """
    os.environ["COCKPIT_DB"] = str(tmp_path / "ciclo.db")
    os.environ["TRUSTED_GATEWAY_CIDR"] = CIDR
    import db as db_mod
    importlib.reload(db_mod)
    from findings import engine
    importlib.reload(engine)
    await db_mod.init_db()
    return db_mod


def _semear_estado(nome: str, restart_count: int):
    """Poe o estado sintetico onde o motor o le: o cache do amostrador.

    O motor chama `get_container_inspects()`, que devolve o que o sampler
    guardou. Semear ali e o equivalente honesto de "o daemon reportou isto" —
    sem mockar o motor, que e justamente o que se quer exercitar.
    """
    import sampler
    sampler._container_stats[f"sintetico-{nome}"] = {
        "inspect": _inspect_sintetico(nome, restart_count),
        "cpu_pct": 1.0,
        "mem_usage": 1024,
        "sampled_at": "2026-08-04T12:00:00Z",
    }


def _limpar_estado():
    """Zera TODO o estado que o motor guarda entre ciclos.

    Sao quatro lugares, e esquecer qualquer um faz o teste seguinte herdar o
    anterior — o tipo de acoplamento que so aparece quando alguem roda a suite
    fora de ordem.
    """
    import sampler
    sampler._container_stats.clear()
    from findings.rules import restart_loop
    restart_loop._prev_restart.clear()
    from findings import engine
    engine._debounce_state.clear()
    engine._last_run.clear()


async def _ciclo(nome, contador):
    """UM ciclo do motor, com o estado semeado antes.

    Duas coisas que `_run_cycle()` sozinho nao faz, e que custaram a descobrir:

    `_discover_rules()` — o registro de regras e populado no `findings_loop`, nao
    no import nem no ciclo. Sem a chamada, `_rules` fica VAZIO e o motor roda
    sem avaliar nada: zero achados, zero erros, e a impressao de que a regra
    esta quebrada. Foi exatamente esse o sintoma aqui.

    `_last_run.clear()` — `MIN_INTERVAL = 10` faz o motor pular uma regra
    avaliada ha menos de dez segundos. Ciclos consecutivos num teste pulam TODAS
    as regras menos as do primeiro. Limpar equivale a "passaram-se dez segundos",
    que e o que acontece em producao; a alternativa seria `sleep(10)` quatro
    vezes por teste, e uma suite que leva minutos e uma suite que ninguem roda.
    """
    from findings import engine
    engine._discover_rules()
    _semear_estado(nome, restart_count=contador)
    engine._last_run.clear()
    await engine._run_cycle()


async def _laco_de_reinicios(nome="app-sintetica"):
    """Tres ciclos com o contador subindo — o minimo para a regra EMITIR.

    Contrato de verdade da regra, e o motivo de nao bastar um reinicio:
    `restart_loop` declara `DEBOUNCE = {"window_min": 30, "count": 3}`, entao sao
    TRES avaliacoes positivas dentro de trinta minutos. E cada avaliacao so e
    positiva se o `RestartCount` CRESCEU desde a anterior.

    E isso que separa "reiniciou" de "esta em laco". Um container que reinicia
    uma vez e volta ao normal nao vira achado critico — e o teste que exigisse
    achado no primeiro ciclo estaria cobrando um falso positivo.
    """
    for contador in (1, 2, 3):
        await _ciclo(nome, contador)


# ---------------------------------------------------------------------------
# o ciclo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_estado_sintetico_faz_a_regra_disparar(tmp_path):
    """Primeiro elo: o motor le o estado e cria o achado.

    `restart_loop` exige que o contador CRESCA entre ciclos — um container que
    reiniciou uma vez e parou nao e um laco. Por isso sao dois ciclos, e o
    primeiro nao pode gerar nada.
    """
    db_mod = await _bancada(tmp_path)
    try:
        _limpar_estado()

        async def abertos():
            return [f["rule"] for f in await db_mod.get_findings(status="open")]

        await _ciclo("app-sintetica", 1)
        assert "restart_loop" not in await abertos(), (
            "achado no primeiro reinicio e falso positivo — nao ha laco ainda")

        await _ciclo("app-sintetica", 2)
        assert "restart_loop" not in await abertos(), (
            "DOIS reinicios ainda nao sao laco; o debounce exige tres na janela")

        await _ciclo("app-sintetica", 3)
        depois = await db_mod.get_findings(status="open")
        achados = [f for f in depois if f["rule"] == "restart_loop"]
        assert achados, "tres reinicios crescentes e a regra nao emitiu"
        assert achados[0]["target"] == "app-sintetica"
        assert achados[0]["severity"] == "critical"
    finally:
        _limpar_estado()
        await _fecha(db_mod)


@pytest.mark.asyncio
async def test_o_achado_gera_cartao_no_board(tmp_path):
    """Segundo elo. `restart_loop` declara `AUTO_TASK = True` porque exige
    trabalho humano — ler log, corrigir a causa — e nao se conserta sozinho."""
    db_mod = await _bancada(tmp_path)
    try:
        _limpar_estado()
        await _laco_de_reinicios()

        tarefas = await db_mod.get_tasks()
        do_achado = [t for t in tarefas if "app-sintetica" in json.dumps(t)]
        assert do_achado, "achado com AUTO_TASK nao virou cartao"
    finally:
        _limpar_estado()
        await _fecha(db_mod)


@pytest.mark.asyncio
async def test_ack_pela_api_fecha_o_ciclo_e_deixa_rastro(tmp_path):
    """Terceiro elo, e o unico que passa pela REDE.

    Do achado em diante o teste so age como o operador agiria: destrava e
    reconhece por HTTP. Chamar a funcao de ack direto pularia justamente o que
    interessa — o guarda de sessao e a auditoria da rota.
    """
    db_mod = await _bancada(tmp_path)
    try:
        _limpar_estado()
        await _laco_de_reinicios()

        abertos = await db_mod.get_findings(status="open")
        alvo = [f for f in abertos if f["rule"] == "restart_loop"][0]

        from app import app
        cliente = TestClient(app)

        # O IP do cliente e remendado porque o TestClient nao tem um: o padrao da
        # casa (test_session.py) e este, e o alvo aqui e o CICLO, nao a checagem
        # de CIDR — que ja tem teste proprio.
        with patch("routers.session._get_client_ip", return_value=IP_CONFIAVEL):
            # destrava como o ingress faria: basic auth vira Remote-User
            r = cliente.post("/api/session/unlock", json={"motivo": "teste sintetico"},
                             headers={"Remote-User": OPERADOR})
        assert r.status_code == 200, r.text
        token = r.json()["token"]

        r = cliente.post(f"/api/findings/{alvo['id']}/ack",
                         json={"reason": "monitorando"},
                         headers={"X-Cockpit-Unlock": token})
        assert r.status_code == 200, r.text

        # o achado saiu da fila
        ainda = await db_mod.get_findings(status="open")
        assert alvo["id"] not in [f["id"] for f in ainda]

        # e o rastro nomeia QUEM, o que e a metade que importa numa auditoria
        linhas = await db_mod.get_audit_log(limit=50)
        do_ack = [x for x in linhas if x.get("action") == "ack"]
        assert do_ack, "ack sem linha de auditoria"
        # `token_label` e onde o ator mora — nome herdado de quando a credencial
        # era um token rotulado, antes de a sessao passar a carregar o usuario do
        # basic auth. O CONTEUDO e o que importa: uma auditoria sem "quem" nao
        # serve para o que auditoria existe.
        assert do_ack[0].get("token_label") == OPERADOR, (
            f"ator gravado foi {do_ack[0].get('token_label')!r}, esperado {OPERADOR!r}")
        assert do_ack[0].get("project") == alvo["id"], "a linha nao aponta o achado"
    finally:
        _limpar_estado()
        await _fecha(db_mod)


@pytest.mark.asyncio
async def test_ack_sem_destravar_nao_passa(tmp_path):
    """O negativo do elo acima. Sem ele, o teste anterior prova que o caminho
    feliz funciona e nada sobre o caminho que importa."""
    db_mod = await _bancada(tmp_path)
    try:
        _limpar_estado()
        await _laco_de_reinicios()
        alvo = [f for f in await db_mod.get_findings(status="open")
                if f["rule"] == "restart_loop"][0]

        from app import app
        cliente = TestClient(app)
        r = cliente.post(f"/api/findings/{alvo['id']}/ack", json={"reason": "monitorando"})
        assert r.status_code == 403

        ainda = await db_mod.get_findings(status="open")
        assert alvo["id"] in [f["id"] for f in ainda], "o achado fechou sem destravamento"
    finally:
        _limpar_estado()
        await _fecha(db_mod)


# ---------------------------------------------------------------------------
# o portao: as duas lacunas que sobraram
# ---------------------------------------------------------------------------
# `test_session.py` (12 casos) e `test_unlock_v8.py` (8) ja cobrem CIDR,
# Remote-User, expiracao, hash do token e recusa de token estatico. O que NAO
# estava coberto sao duas propriedades de ORDEM e de CLASSIFICACAO — as duas
# afirmadas em comentario no codigo, nenhuma verificada.

def test_o_429_vem_antes_de_qualquer_outra_verificacao():
    """Ordem e a propriedade de seguranca aqui, nao o codigo em si.

    Quem ja estourou o limite nao pode aprender SE o problema era o Remote-User
    ausente ou o IP fora do CIDR — responder o motivo exato continuaria
    entregando o oraculo que o limite existe para calar. Por isso a requisicao
    abaixo vai sem Remote-User nenhum: sem a ordem certa, ela devolveria 401.
    """
    import hardening as hrd
    from app import app

    cliente = TestClient(app)
    with patch("routers.session._get_client_ip", return_value=IP_CONFIAVEL):
        os.environ["TRUSTED_GATEWAY_CIDR"] = CIDR
        hrd._reset()
        # `routers.session.bloqueado` e nao `hardening.bloqueado`: a rota faz
        # `from hardening import bloqueado`, o que amarra a funcao no import.
        # Remendar o modulo de origem nao alcanca quem ja copiou a referencia —
        # mesmo mecanismo que fez o motor escrever no banco errado neste arquivo.
        with patch("routers.session.bloqueado", return_value=True):
            r = cliente.post("/api/session/unlock", json={"motivo": "x"})
    assert r.status_code == 429, (
        f"devolveu {r.status_code} — a ordem vazou qual verificacao falhou")
    assert r.headers.get("Retry-After"), "429 sem Retry-After nao diz quando voltar"


def test_ma_configuracao_nossa_nao_conta_contra_o_ip():
    """`TRUSTED_GATEWAY_CIDR` ausente e erro NOSSO, nao tentativa de acesso.

    Conta-lo como falha faria uma configuracao esquecida trancar o operador
    legitimo depois de cinco tentativas — o limitador viraria negacao de servico
    contra quem ele deveria proteger. O simetrico ja tem teste no lado do
    /metrics (503); no unlock (403) nao tinha.
    """
    import hardening as hrd
    from app import app

    antes = os.environ.get("TRUSTED_GATEWAY_CIDR")
    os.environ.pop("TRUSTED_GATEWAY_CIDR", None)
    hrd._reset()
    try:
        cliente = TestClient(app)
        with patch("routers.session._get_client_ip", return_value=IP_CONFIAVEL):
            for _ in range(6):
                r = cliente.post("/api/session/unlock", json={"motivo": "x"},
                                 headers={"Remote-User": OPERADOR})
                assert r.status_code == 403, (
                    f"esperado 403 de configuracao, veio {r.status_code}")
        assert not hrd.bloqueado(IP_CONFIAVEL), (
            "seis erros DE CONFIGURACAO trancaram o operador — o limitador virou "
            "negacao de servico contra quem ele protege")
    finally:
        if antes is not None:
            os.environ["TRUSTED_GATEWAY_CIDR"] = antes
        hrd._reset()
