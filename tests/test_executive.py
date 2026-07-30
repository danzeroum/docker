"""Resumo executivo: a tela que fala para quem nao opera a VPS.

O risco desta fatia nao e calculo — e afirmar coisa sem fonte. Os testes
concentram-se em config ausente, serie curta e vazamento de nome tecnico.
"""
import json
import os
import pathlib
import re
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from routers import executive as ex

RAIZ = pathlib.Path(__file__).resolve().parent.parent
JS = RAIZ / "app" / "static" / "js"


def _finding(fid, rule, severity, payload, target=None, score=50):
    return {
        "id": fid, "rule": rule, "target": target, "targets": None,
        "scope": "host", "severity": severity, "score": score, "status": "open",
        "first_seen": "2026-07-01T00:00:00Z", "last_seen": "2026-07-29T00:00:00Z",
        "occurrences": 5, "ack_reason": None, "ack_note": None, "ack_until": None,
        "payload": json.dumps(payload, ensure_ascii=False),
    }


# ---------------------------------------------------------------------------
# hero
# ---------------------------------------------------------------------------

def test_hero_pega_o_mais_grave_em_texto_plain():
    findings = [
        _finding("a", "no_gzip", "low", {"title_plain": "coisa menor"}),
        _finding("b", "no_backup", "high", {
            "title_plain": "Os dados nao estao sendo copiados",
            "interpretation_plain": "Se o servidor falhar, nao ha copia",
            "impact_plain": "Uma falha apaga tudo",
            "recommendation_plain": "Contratar destino de copia externo",
        }),
    ]
    h = ex.montar_hero(findings)
    assert h["finding_id"] == "b"
    assert h["title"] == "Os dados nao estao sendo copiados"
    assert h["impact"] == "Uma falha apaga tudo"


def test_hero_ignora_achado_sem_plain():
    """Sem _plain o achado nao entra: melhor mostrar menos que jargao."""
    findings = [
        _finding("tecnico", "oom", "critical", {"title": "exit 137 OOMKilled"}),
        _finding("legivel", "no_backup", "medium", {"title_plain": "sem copia dos dados"}),
    ]
    h = ex.montar_hero(findings)
    assert h["finding_id"] == "legivel", "achado critico sem _plain virou hero"


def test_hero_none_sem_achados():
    assert ex.montar_hero([]) is None


def test_hero_nao_faz_fallback_para_texto_tecnico():
    findings = [_finding("x", "oom", "critical", {"title": "exit 137", "impact": "jargao"})]
    assert ex.montar_hero(findings) is None


# ---------------------------------------------------------------------------
# riscos
# ---------------------------------------------------------------------------

def test_riscos_so_com_requires_approval():
    findings = [
        _finding("a", "no_gzip", "low", {"title_plain": "sem aprovacao"}),
        _finding("b", "no_backup", "high", {"title_plain": "com aprovacao", "requires_approval": True}),
    ]
    r = ex.montar_riscos(findings)
    assert [x["finding_id"] for x in r] == ["b"]


def test_riscos_ordenados_por_prazo():
    findings = [
        _finding("longe", "r1", "high", {"title_plain": "a", "requires_approval": True, "horizon_days": 30}),
        _finding("perto", "r2", "high", {"title_plain": "b", "requires_approval": True, "horizon_days": 3}),
        _finding("agora", "r3", "high", {"title_plain": "c", "requires_approval": True}),
    ]
    r = ex.montar_riscos(findings)
    assert [x["finding_id"] for x in r] == ["agora", "perto", "longe"], \
        "sem prazo significa 'e agora', tem de vir primeiro"


def test_risco_usa_nome_de_negocio_e_nunca_o_alvo_tecnico():
    mapa = {"loja.exemplo.com": {"nome": "Loja online"}}
    findings = [
        _finding("a", "http_plain", "critical",
                 {"title_plain": "sem criptografia", "requires_approval": True},
                 target="loja.exemplo.com"),
        _finding("b", "http_plain", "critical",
                 {"title_plain": "sem criptografia", "requires_approval": True},
                 target="naomapeado.exemplo.com"),
    ]
    r = ex.montar_riscos(findings, mapa)
    assert r[0]["service"] == "Loja online"
    assert r[1]["service"] is None, "alvo nao mapeado vazou para a tela"
    for item in r:
        assert "exemplo.com" not in json.dumps(item), "dominio vazou no risco"


# ---------------------------------------------------------------------------
# servicos e config ausente
# ---------------------------------------------------------------------------

def test_servicos_por_nome_de_negocio():
    mapa = {
        "a.com": {"nome": "Site institucional"},
        "b.com": {"nome": "Painel de vendas", "critico": True},
    }
    servicos, nao_mapeados = ex.montar_servicos(["a.com", "b.com", "c.com"], mapa)
    assert nao_mapeados == 1
    assert [s["name"] for s in servicos] == ["Painel de vendas", "Site institucional"], \
        "essencial primeiro, depois alfabetico"
    assert "c.com" not in json.dumps(servicos)


def test_config_ausente_nao_levanta(tmp_path):
    mapa, faltando = ex.carregar_servicos(str(tmp_path / "nao-existe.json"))
    assert mapa == {}
    assert faltando.endswith("nao-existe.json")


def test_config_invalida_e_tratada_como_ausente(tmp_path):
    ruim = tmp_path / "servicos.json"
    ruim.write_text("{ isto nao e json", encoding="utf-8")
    mapa, faltando = ex.carregar_servicos(str(ruim))
    assert mapa == {}
    assert faltando


def test_config_valida_carrega(tmp_path):
    bom = tmp_path / "servicos.json"
    bom.write_text(json.dumps({"servicos": {"a.com": {"nome": "Site"}}}), encoding="utf-8")
    mapa, faltando = ex.carregar_servicos(str(bom))
    assert faltando is None
    assert mapa["a.com"]["nome"] == "Site"


def test_exemplo_versionado_e_json_valido():
    exemplo = RAIZ / "app" / "config" / "servicos.example.json"
    dados = json.loads(exemplo.read_text(encoding="utf-8"))
    assert "servicos" in dados


# ---------------------------------------------------------------------------
# custo
# ---------------------------------------------------------------------------

def test_custo_ausente_e_none():
    os.environ.pop("COST_MONTHLY", None)
    assert ex._custo_mensal() is None


def test_custo_vazio_e_none_nao_zero():
    os.environ["COST_MONTHLY"] = "   "
    try:
        assert ex._custo_mensal() is None, "custo vazio virou 0"
    finally:
        os.environ.pop("COST_MONTHLY", None)


def test_custo_invalido_e_none():
    os.environ["COST_MONTHLY"] = "de graca"
    try:
        assert ex._custo_mensal() is None
    finally:
        os.environ.pop("COST_MONTHLY", None)


def test_custo_aceita_virgula():
    os.environ["COST_MONTHLY"] = "249,90"
    try:
        assert ex._custo_mensal() == 249.90
    finally:
        os.environ.pop("COST_MONTHLY", None)


# ---------------------------------------------------------------------------
# endpoint
# ---------------------------------------------------------------------------

def _client():
    from app import app
    return TestClient(app)


def test_endpoint_com_config_ausente_renderiza_o_resto(tmp_path):
    findings = [_finding("b", "no_backup", "high", {
        "title_plain": "Os dados nao estao sendo copiados", "requires_approval": True,
    })]
    client = _client()
    with patch("routers.executive.SERVICOS_PATH", str(tmp_path / "ausente.json")):
        with patch("routers.executive.get_findings", new=AsyncMock(return_value=findings)):
            with patch("routers.executive._hosts_publicos", return_value=["a.com"]):
                r = client.get("/api/executive")
    assert r.status_code == 200
    d = r.json()
    assert d["config_missing"], "nao avisou qual arquivo falta"
    assert d["hero"]["title"] == "Os dados nao estao sendo copiados"
    assert d["services"] == []
    assert d["services_unmapped"] == 1
    assert len(d["risks"]) == 1


def test_endpoint_sem_custo_omite_o_campo(tmp_path):
    os.environ.pop("COST_MONTHLY", None)
    client = _client()
    with patch("routers.executive.SERVICOS_PATH", str(tmp_path / "x.json")):
        with patch("routers.executive.get_findings", new=AsyncMock(return_value=[])):
            with patch("routers.executive._hosts_publicos", return_value=[]):
                r = client.get("/api/executive")
    assert r.json()["cost_monthly"] is None


def test_endpoint_nao_expoe_disponibilidade(tmp_path):
    """Removida de proposito: cobertura de coleta nao e uptime de servico.

    Dois numeros diferentes com o mesmo rotulo e pior que campo ausente —
    quem le "99,8%" nao vai atras da nota que explica a diferenca. Volta
    quando existir uptime de verdade.
    """
    client = _client()
    with patch("routers.executive.SERVICOS_PATH", str(tmp_path / "x.json")):
        with patch("routers.executive.get_findings", new=AsyncMock(return_value=[])):
            with patch("routers.executive._hosts_publicos", return_value=[]):
                r = client.get("/api/executive")
    assert "availability" not in r.json()


def test_tela_nao_tem_kpi_de_disponibilidade():
    fonte = (JS / "screens" / "executivo.js").read_text()
    assert "Disponibilidade" not in fonte
    assert "availability" not in fonte


def test_endpoint_sem_riscos(tmp_path):
    client = _client()
    with patch("routers.executive.SERVICOS_PATH", str(tmp_path / "x.json")):
        with patch("routers.executive.get_findings", new=AsyncMock(return_value=[])):
            with patch("routers.executive._hosts_publicos", return_value=[]):
                r = client.get("/api/executive")
    d = r.json()
    assert d["risks"] == []
    assert d["hero"] is None


# ---------------------------------------------------------------------------
# regras que alimentam a tela
# ---------------------------------------------------------------------------

def test_regras_de_decisao_declaram_requires_approval():
    from findings.rules import no_backup
    achado = no_backup.evaluate(type("C", (), {
        "containers": [{"Name": "/web", "Config": {"Image": "nginx", "Labels": {}}}],
        "host": None, "history": {}, "ingress": None,
    })())
    assert achado["requires_approval"] is True


@pytest.mark.parametrize("regra", ["http_plain", "default_cert_borrowed", "no_backup"])
def test_plain_das_regras_de_decisao_nao_interpola_alvo(regra):
    """O _plain e a frase do gestor. O texto tecnico pode nomear o host; o _plain nao.

    Checa so as linhas *_plain — a `interpretation` tecnica logo ao lado
    legitimamente interpola {host}, e confundir as duas foi o primeiro erro
    deste teste.
    """
    fonte = (RAIZ / "app" / "findings" / "rules" / f"{regra}.py").read_text()
    linhas_plain = [
        linha for linha in fonte.splitlines()
        if re.search(r'"(title|interpretation|impact|recommendation)_plain"', linha)
    ]
    assert linhas_plain, f"{regra} nao declara nenhum _plain"
    for linha in linhas_plain:
        assert "{host}" not in linha, f"{regra}: _plain interpola o host — {linha.strip()}"
        assert "{name}" not in linha, f"{regra}: _plain interpola o alvo — {linha.strip()}"


# ---------------------------------------------------------------------------
# contrato do frontend
# ---------------------------------------------------------------------------

def test_tela_nao_tem_dado_fixo():
    fonte = (JS / "screens" / "executivo.js").read_text().lower()
    for proibido in ("criptotrade", "giva", "buildtovalue", "executagent",
                     "familia-web", "danzeroum", "prompte", "juridico",
                     "docker-cockpit", "btv-"):
        assert proibido not in fonte, f"dado fixo na tela: {proibido}"


def test_tela_nao_inventa_custo_zero():
    fonte = (JS / "screens" / "executivo.js").read_text()
    assert "cost_monthly !== null" in fonte, "cartao de custo sem guarda de ausencia"


def test_executivo_esta_registrado_e_chama_o_render_real():
    """Antes: `case '#/executivo':` no switch do main.js.

    Na Sprint 2a o switch morreu — era um `case` por tela no nucleo, o oposto da
    regra "zero if no nucleo" do doc 10 §4. A intencao do teste nao muda: a tela
    esta ligada ao render de verdade, nao a um placeholder de fase. O que muda e
    onde isso se verifica — no modulo e no registro.
    """
    modulo = (JS / "modulos" / "executivo.js").read_text()
    assert "renderExecutivo" in modulo, "modulo executivo nao chama o render real"
    assert "renderPlaceholder" not in modulo
    indice = (JS / "modulos" / "index.js").read_text()
    assert "executivo" in indice, "executivo nao esta registrado"
