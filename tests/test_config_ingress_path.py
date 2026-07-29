"""NGINX_CONFIG_PATH tem de casar com onde o compose monta o nginx.conf.

Encontrado em producao: o compose monta /opt/btv/ingress/nginx em
/etc/nginx-ingress, mas o padrao do codigo e /etc/nginx/nginx.conf e a env nao
era declarada em lugar nenhum. Resultado: o parser nao achava o arquivo, as 11
regras de ingress nunca emitiam, a tela Ingress & TLS ficava vazia e o Resumo
executivo listava zero servicos — tudo sem uma linha de erro.

O teste amarra as duas pontas: se alguem mudar a montagem sem mudar a env (ou o
contrario), quebra aqui.
"""
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = (RAIZ / "docker-compose.yml").read_text()


def _destino_do_ingress():
    m = re.search(r'-\s*/opt/btv/ingress/nginx:([^\s:]+):ro', COMPOSE)
    assert m, "montagem do nginx do ingress sumiu do compose"
    return m.group(1)


def _env_declarada():
    m = re.search(r'NGINX_CONFIG_PATH:\s*(\S+)', COMPOSE)
    assert m, "NGINX_CONFIG_PATH nao declarada no compose"
    return m.group(1)


def test_env_aponta_para_dentro_da_montagem():
    destino = _destino_do_ingress()
    env = _env_declarada()
    assert env.startswith(destino + "/"), \
        f"NGINX_CONFIG_PATH={env} nao esta dentro da montagem {destino}"


def test_env_aponta_para_um_nginx_conf():
    assert _env_declarada().endswith("/nginx.conf")


def test_env_mora_no_compose_nao_no_env_file():
    """O caminho e consequencia da montagem; separar os dois deixa o padrao
    do codigo valer em silencio quando alguem esquece o .env."""
    exemplo = (RAIZ / ".env.example").read_text()
    assert "NGINX_CONFIG_PATH" not in exemplo, \
        "declarar no .env.example convida a divergir da montagem do compose"


def test_os_tres_consumidores_usam_a_mesma_env():
    """Router de ingress, motor de achados e Resumo executivo leem o mesmo lugar."""
    for arquivo in ("app/routers/ingress.py", "app/findings/engine.py",
                    "app/routers/executive.py"):
        fonte = (RAIZ / arquivo).read_text()
        assert 'getenv("NGINX_CONFIG_PATH"' in fonte, f"{arquivo} nao le a env"


def test_startup_avisa_quando_o_arquivo_falta(caplog, tmp_path, monkeypatch):
    """Falha silenciosa e o modo de errar mais caro deste produto."""
    import app as app_mod
    monkeypatch.setenv("NGINX_CONFIG_PATH", str(tmp_path / "nao-existe.conf"))
    caplog.set_level("WARNING")
    app_mod._avisa_se_nginx_ausente()
    assert any("nao encontrado" in r.message for r in caplog.records), \
        "startup nao avisa que o nginx.conf sumiu"


def test_startup_calado_quando_o_arquivo_existe(caplog, tmp_path, monkeypatch):
    import app as app_mod
    conf = tmp_path / "nginx.conf"
    conf.write_text("events {}\n")
    monkeypatch.setenv("NGINX_CONFIG_PATH", str(conf))
    caplog.set_level("WARNING")
    app_mod._avisa_se_nginx_ausente()
    assert not [r for r in caplog.records if "nao encontrado" in r.message]
