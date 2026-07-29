"""Regra no_backup: a VPS nao tem stack de backup, e isso e o achado mais grave.

Regra de AUSENCIA, entao os testes negativos importam tanto quanto o positivo:
detectar backup onde existe, e calar-se quando nao ha leitura do daemon.
"""
import importlib
import os
import pytest

from findings.rules import no_backup


class Ctx:
    def __init__(self, containers):
        self.containers = containers
        self.host = None
        self.history = {}
        self.ingress = None


def _container(nome, imagem="nginx:alpine", rotulos=None):
    return {
        "Name": "/" + nome,
        "State": {"Running": True},
        "Config": {"Image": imagem, "Labels": rotulos or {}},
    }


# ---------------------------------------------------------------------------
# dispara
# ---------------------------------------------------------------------------

def test_dispara_sem_nenhuma_solucao_de_backup():
    ctx = Ctx([_container("web"), _container("api", "python:3.12"), _container("db", "postgres:16")])
    r = no_backup.evaluate(ctx)
    assert r is not None
    assert r["target"] == no_backup.ALVO
    assert no_backup.SEVERITY == "high"


def test_achado_tem_recommendation_acionavel():
    r = no_backup.evaluate(Ctx([_container("web")]))
    assert r["recommendation"]
    # o conselho tem de dizer o que fazer, nao so que ha um problema
    assert "fora" in r["recommendation"].lower()
    assert r["actions"]
    assert all(a.get("title") for a in r["actions"])


def test_achado_tem_plain_para_o_resumo_executivo():
    """Chega ao Resumo executivo, entao _plain e obrigatorio (00-decisoes)."""
    r = no_backup.evaluate(Ctx([_container("web")]))
    for campo in ("title_plain", "interpretation_plain", "impact_plain"):
        assert r.get(campo), f"falta {campo}"
        assert r[campo] != r.get(campo.replace("_plain", "")), \
            f"{campo} e copia do texto tecnico, nao outra frase"


def test_plain_nao_usa_jargao():
    r = no_backup.evaluate(Ctx([_container("web")]))
    junto = " ".join([r["title_plain"], r["interpretation_plain"], r["impact_plain"]]).lower()
    for jargao in ("container", "volume", "docker", "stack", "daemon"):
        assert jargao not in junto, f"'{jargao}' no texto para leigo"


# ---------------------------------------------------------------------------
# nao dispara
# ---------------------------------------------------------------------------

def test_nao_dispara_com_imagem_de_backup():
    """Fixture canonica: offen/docker-volume-backup rodando."""
    ctx = Ctx([_container("web"), _container("bkp", "offen/docker-volume-backup:v2.43.0")])
    assert no_backup.evaluate(ctx) is None


@pytest.mark.parametrize("imagem", [
    "restic/restic:latest",
    "ghcr.io/borgmatic-collective/borgmatic",
    "lscr.io/linuxserver/duplicati:latest",
    "kopia/kopia:0.17",
    "offen/docker-volume-backup",
])
def test_nao_dispara_para_ferramentas_conhecidas(imagem):
    assert no_backup.evaluate(Ctx([_container("web"), _container("b", imagem)])) is None


def test_nao_dispara_com_rotulo_de_backup():
    ctx = Ctx([_container("web", rotulos={"com.docker.compose.project": "backup-noturno"})])
    assert no_backup.evaluate(ctx) is None


def test_nao_dispara_com_nome_de_backup():
    ctx = Ctx([_container("web"), _container("btv-backup-diario")])
    assert no_backup.evaluate(ctx) is None


def test_cala_se_sem_leitura_do_daemon():
    """Ausencia de dado nao e evidencia de ausencia de backup."""
    assert no_backup.evaluate(Ctx([])) is None
    assert no_backup.evaluate(Ctx(None)) is None


def test_ignora_entrada_malformada():
    ctx = Ctx(["lixo", None, 42])
    assert no_backup.evaluate(ctx) is None


def test_container_de_backup_parado_ainda_conta_como_configurado():
    """Stack parada e outro problema, com outro dono. Ver docstring da regra."""
    parado = _container("bkp", "restic/restic:latest")
    parado["State"] = {"Running": False}
    assert no_backup.evaluate(Ctx([_container("web"), parado])) is None


# ---------------------------------------------------------------------------
# integracao com o motor: descoberta e ciclo achado -> cartao
# ---------------------------------------------------------------------------

def test_regra_e_descoberta_por_filesystem():
    import findings.engine as eng
    importlib.reload(eng)
    eng._discover_rules()
    nomes = [
        os.path.basename(m.__file__).replace(".py", "")
        for m in eng._rules if hasattr(m, "__file__")
    ]
    assert "no_backup" in nomes, "auto-discovery nao pegou a regra"


def test_declara_auto_task():
    assert getattr(no_backup, "AUTO_TASK", False) is True


@pytest.mark.asyncio
async def test_dois_ciclos_geram_um_unico_cartao(tmp_path):
    """O motor reavalia a cada ciclo; ausencia de backup persiste. Um cartao."""
    os.environ["COCKPIT_DB"] = str(tmp_path / "nb.db")
    import db as db_mod
    importlib.reload(db_mod)
    import findings.engine as eng
    importlib.reload(eng)
    try:
        await db_mod.init_db()
        achado = no_backup.evaluate(Ctx([_container("web")]))
        finding = {
            "id": f"no_backup.{achado['target']}",
            "rule": "no_backup",
            "target": achado["target"],
            "scope": no_backup.SCOPE,
            "severity": no_backup.SEVERITY,
            "score": 80,
            "payload": "{}",
        }
        for _ in range(2):
            estado = await db_mod.upsert_finding(finding)
            await eng._sync_task(no_backup, finding, achado, estado)

        cartoes = await db_mod.get_tasks()
        assert len(cartoes) == 1, f"dois ciclos geraram {len(cartoes)} cartoes"
        assert cartoes[0]["origem"] == "auto"
        assert cartoes[0]["finding_id"] == "no_backup.vps"
    finally:
        try:
            await db_mod.close_db()
        except Exception:
            pass
        os.environ.pop("COCKPIT_DB", None)


@pytest.mark.asyncio
async def test_backup_sobe_e_o_cartao_fecha(tmp_path):
    """Uma stack de backup no ar -> regra se cala -> achado some -> cartao done."""
    os.environ["COCKPIT_DB"] = str(tmp_path / "nb2.db")
    import db as db_mod
    importlib.reload(db_mod)
    import findings.engine as eng
    importlib.reload(eng)
    try:
        await db_mod.init_db()
        achado = no_backup.evaluate(Ctx([_container("web")]))
        finding = {
            "id": "no_backup.vps", "rule": "no_backup", "target": "vps",
            "scope": "host", "severity": "high", "score": 80, "payload": "{}",
        }
        estado = await db_mod.upsert_finding(finding)
        await eng._sync_task(no_backup, finding, achado, estado)
        assert (await db_mod.get_auto_task_for_finding("no_backup.vps"))["col"] == "todo"

        # sobe a stack de backup: a regra para de emitir
        assert no_backup.evaluate(
            Ctx([_container("web"), _container("bkp", "offen/docker-volume-backup")])
        ) is None

        # o motor resolve o achado que sumiu do ciclo e fecha o cartao
        await db_mod.resolve_finding("no_backup.vps")
        await db_mod.resolve_task_for_finding("no_backup.vps")

        cartao = await db_mod.get_auto_task_for_finding("no_backup.vps")
        assert cartao["col"] == "done"
        assert await db_mod.get_findings(status="open") == []
    finally:
        try:
            await db_mod.close_db()
        except Exception:
            pass
        os.environ.pop("COCKPIT_DB", None)


# ---------------------------------------------------------------------------
# o _plain precisa CHEGAR na API — e o que o Resumo executivo consome
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plain_chega_em_api_findings(tmp_path):
    """Antes desta fatia a API descartava impact_plain e recommendation_plain."""
    import json
    from unittest.mock import patch, AsyncMock
    from fastapi.testclient import TestClient

    achado = no_backup.evaluate(Ctx([_container("web")]))
    payload = {k: v for k, v in achado.items() if k != "target"}
    linha = {
        "id": "no_backup.vps", "rule": "no_backup", "target": "vps",
        "targets": None, "scope": "host", "severity": "high", "score": 80,
        "status": "open", "first_seen": "2026-07-29T00:00:00Z",
        "last_seen": "2026-07-29T00:00:00Z", "occurrences": 3,
        "ack_reason": None, "ack_note": None, "ack_until": None,
        "payload": json.dumps(payload, ensure_ascii=False),
    }
    from app import app
    client = TestClient(app)
    with patch("routers.findings.get_findings", new=AsyncMock(return_value=[linha])):
        r = client.get("/api/findings")
    assert r.status_code == 200
    item = r.json()[0]
    for campo in ("title_plain", "interpretation_plain", "impact_plain", "recommendation_plain"):
        assert item.get(campo), f"{campo} nao chegou na API"
