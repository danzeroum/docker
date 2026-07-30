"""5-certs — fonte real para `certs_expiring` (a decisao pendente da 2a).

O bloco carrega a decisao nos dois ramos, e os testes cobram os dois:

- **com diretorio montado**, a chave ganha fonte e o chip conta;
- **sem diretorio**, ela sai `null` com `stale_since` — e `null` continua
  significando "nao estou olhando", nunca "nenhum certificado esta para vencer".

`notAfter` vem do X.509, nunca da saida do `certbot certificates`. Parsear a
saida de uma CLI amarra o cockpit ao formato de texto de outro projeto, que muda
entre versoes sem aviso — e a quebra apareceria aqui como "nenhum certificado
expirando", a pior falha possivel nesta medida.

O symlink quebrado em `live/` tem teste proprio porque e rotina do certbot, e
nao incidente: acontece toda vez que alguem apaga um lineage a mao.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import certs as crt  # noqa: E402


def _emite(dias, nome="exemplo.com"):
    """Cert autoassinado com notAfter forjado."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    chave = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    sujeito = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nome)])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(sujeito)
        .issuer_name(sujeito)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=30))
        .not_valid_after(agora + timedelta(days=dias))
        .sign(chave, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


def lineage(raiz, nome, dias, arquivo="fullchain.pem"):
    d = raiz / nome
    d.mkdir(parents=True, exist_ok=True)
    (d / arquivo).write_bytes(_emite(dias, nome))
    return d


# --- leitura do X.509 -----------------------------------------------------

def test_le_not_after_de_um_pem(tmp_path):
    d = lineage(tmp_path, "exemplo.com", 40)
    quando, erro = crt.le_not_after(str(d / "fullchain.pem"))
    assert erro == ""
    assert 39 <= (quando - datetime.now(timezone.utc)).days <= 40


def test_arquivo_que_nao_e_pem_nao_levanta(tmp_path):
    caminho = tmp_path / "lixo.pem"
    caminho.write_bytes(b"isto nao e um certificado")
    quando, erro = crt.le_not_after(str(caminho))
    assert quando is None
    assert "nao e um certificado" in erro


def test_a_leitura_e_do_x509_e_nao_da_saida_do_certbot():
    """Parsear a CLI amarraria o cockpit ao formato de texto de outro projeto.

    Le so o CODIGO: a prosa do modulo cita `certbot` justamente para explicar
    por que nao o invoca, e um grep no fonte inteiro acusaria a explicacao — foi
    o que este teste fez na primeira execucao.
    """
    import ast
    import inspect as _inspect

    arvore = ast.parse(_inspect.getsource(crt))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Expr) and isinstance(no.value, ast.Constant) \
                and isinstance(no.value.value, str):
            no.value.value = ""
    codigo = ast.unparse(arvore)
    for proibido in ("subprocess", "certbot", "os.system", "popen"):
        assert proibido not in codigo, f"o modulo chama {proibido}"


# --- contagem e janela ----------------------------------------------------

def test_conta_e_janela_com_cert_forjado(tmp_path):
    lineage(tmp_path, "vence.com", 10)
    lineage(tmp_path, "tranquilo.com", 60)
    r = crt.coletar(str(tmp_path), janela=14)
    assert r["expiring"] == 1
    assert r["window_days"] == 14
    por_nome = {c["name"]: c for c in r["certs"]}
    assert por_nome["vence.com"]["expiring"] is True
    assert por_nome["tranquilo.com"]["expiring"] is False


def test_dias_arredondam_para_baixo(tmp_path):
    """13,9 dias tem 13, nao 14. A direcao do arredondamento importa quando o
    numero decide se alguem e acordado."""
    lineage(tmp_path, "quase.com", 14)
    r = crt.coletar(str(tmp_path), janela=14)
    assert r["certs"][0]["days"] == 13


def test_ordena_do_mais_urgente_para_o_menos(tmp_path):
    lineage(tmp_path, "c.com", 90)
    lineage(tmp_path, "a.com", 3)
    lineage(tmp_path, "b.com", 30)
    r = crt.coletar(str(tmp_path), janela=14)
    assert [c["name"] for c in r["certs"]] == ["a.com", "b.com", "c.com"]


def test_cert_ja_vencido_conta_como_expirando_com_dias_negativos(tmp_path):
    lineage(tmp_path, "morto.com", -5)
    r = crt.coletar(str(tmp_path), janela=14)
    assert r["expiring"] == 1
    assert r["certs"][0]["days"] < 0


def test_aceita_cert_pem_alem_de_fullchain(tmp_path):
    lineage(tmp_path, "so-cert.com", 20, arquivo="cert.pem")
    r = crt.coletar(str(tmp_path), janela=14)
    assert [c["name"] for c in r["certs"]] == ["so-cert.com"]


# --- ausencia de fonte ----------------------------------------------------

def test_diretorio_ausente_da_none_e_nao_erro():
    """Instalacao sem TLS local e legitima — e a maioria das VPS com ingress
    externo e assim."""
    assert crt.coletar("/nao/existe/live") is None


def test_diretorio_vazio_da_none(tmp_path):
    assert crt.coletar(str(tmp_path)) is None


def test_env_vazia_desliga_a_leitura():
    assert crt.coletar("") is None


def test_none_e_nao_zero():
    """Zero afirma "nenhum certificado esta para vencer"; a verdade pode ser
    "nao estou olhando certificado nenhum"."""
    r = crt.coletar("/nao/existe/live")
    assert r is None
    assert r != {"expiring": 0}


# --- casos do dia a dia do certbot ----------------------------------------

def test_symlink_quebrado_e_ignorado_com_aviso(tmp_path):
    """`live/` e feito de symlinks para `archive/`, e symlink quebrado acontece
    toda vez que alguem apaga um lineage a mao."""
    d = tmp_path / "orfao.com"
    d.mkdir()
    os.symlink(str(tmp_path / "archive" / "sumiu" / "fullchain.pem"),
               str(d / "fullchain.pem"))
    lineage(tmp_path, "vivo.com", 40)

    r = crt.coletar(str(tmp_path), janela=14)
    assert [c["name"] for c in r["certs"]] == ["vivo.com"], "o lineage bom foi perdido"
    assert any("orfao.com" in a for a in r["avisos"])
    assert r["expiring"] == 0


def test_lineage_sem_certificado_vira_aviso(tmp_path):
    (tmp_path / "vazio.com").mkdir()
    lineage(tmp_path, "vivo.com", 40)
    r = crt.coletar(str(tmp_path), janela=14)
    assert len(r["certs"]) == 1
    assert any("vazio.com" in a for a in r["avisos"])


def test_so_avisos_ainda_devolve_estrutura(tmp_path):
    """Diretorio montado com tudo quebrado NAO e ausencia de fonte: ha o que
    contar ao operador, e some se devolvermos None."""
    (tmp_path / "vazio.com").mkdir()
    r = crt.coletar(str(tmp_path), janela=14)
    assert r is not None
    assert r["certs"] == [] and r["avisos"]


def test_arquivo_solto_na_raiz_e_ignorado(tmp_path):
    (tmp_path / "README").write_text("nao sou lineage")
    lineage(tmp_path, "vivo.com", 40)
    r = crt.coletar(str(tmp_path), janela=14)
    assert [c["name"] for c in r["certs"]] == ["vivo.com"]


# --- ponte com o B7 -------------------------------------------------------

def test_achados_so_para_os_que_estao_na_janela(tmp_path):
    lineage(tmp_path, "vence.com", 10)
    lineage(tmp_path, "tranquilo.com", 60)
    achados = crt.achados_de_cert(crt.coletar(str(tmp_path), janela=14))
    assert [a["alvo"] for a in achados] == ["vence.com"]
    assert achados[0]["regra"] == "cert_expirando"
    # 9 e nao 10: o arredondamento e para baixo, e o detalhe carrega o mesmo
    # numero que o operador ve na tela.
    assert "9 dia" in achados[0]["detalhe"]


def test_sem_fonte_nao_gera_achado():
    """Alerta de "nao sei" seria ruido sobre a NOSSA configuracao, e nao sobre a
    infraestrutura do operador."""
    assert crt.achados_de_cert(None) == []


def test_dedup_de_cert_e_diario_e_nao_de_trinta_minutos():
    """Cert expira em dias: repetir o aviso a cada meia hora martelaria o canal
    48 vezes por dia sem informacao nova — o caminho mais curto para o operador
    silenciar o canal inteiro justo antes do aviso que importa."""
    import notify
    assert notify._JANELA_POR_REGRA["cert_expirando"] == 24 * 60
    assert notify._JANELA_POR_REGRA["cert_expirando"] > notify.DEDUP_MIN


@pytest.mark.asyncio
async def test_a_regra_de_cert_respeita_a_janela_diaria(tmp_path, monkeypatch):
    import importlib
    import notify

    caminho = str(tmp_path / "cockpit.db")
    anterior = os.environ.get("COCKPIT_DB")
    os.environ["COCKPIT_DB"] = caminho
    try:
        import db as mod
        importlib.reload(mod)
        await mod.init_db()
        agora = datetime.now(timezone.utc)

        # entregue ha 2h: dentro da janela DIARIA, fora da janela padrao
        recente = (agora - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        conexao = await mod.get_db()
        await conexao.execute(
            "INSERT INTO notificacoes (regra, alvo, ts, enviado_em, canais)"
            " VALUES (?,?,?,?,?)",
            ("cert_expirando", "vence.com", recente, recente, "telegram"))
        await conexao.execute(
            "INSERT INTO notificacoes (regra, alvo, ts, enviado_em, canais)"
            " VALUES (?,?,?,?,?)",
            ("unhealthy", "api", recente, recente, "telegram"))
        await conexao.commit()

        assert await notify.deve_notificar("cert_expirando", "vence.com") is False
        assert await notify.deve_notificar("unhealthy", "api") is True, (
            "a janela diaria vazou para as outras regras")
        await mod.close_db()
    finally:
        if anterior is None:
            os.environ.pop("COCKPIT_DB", None)
        else:
            os.environ["COCKPIT_DB"] = anterior


# --- contrato do summary --------------------------------------------------

def test_summary_sem_fonte_mantem_as_duas_chaves_null():
    import summary
    r = summary._ingress({"hosts": {}, "totals": {"public": 3}}, None)
    assert r["certs_expiring"] is None
    assert r["cert_window_days"] is None


def test_summary_com_fonte_preenche_as_duas_chaves():
    import summary
    r = summary._ingress({"hosts": {}, "totals": {"public": 3}},
                         {"expiring": 1, "window_days": 14, "certs": []})
    assert r["certs_expiring"] == 1
    assert r["cert_window_days"] == 14


def test_summary_com_fonte_limpa_da_zero_e_nao_null():
    """Fonte que rodou e nao achou nada afirma zero — mesmo contrato de tres
    estados do drift."""
    import summary
    r = summary._ingress({"hosts": {}, "totals": {"public": 3}},
                         {"expiring": 0, "window_days": 14, "certs": []})
    assert r["certs_expiring"] == 0
    assert r["certs_expiring"] is not None
