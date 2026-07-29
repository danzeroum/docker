"""Senha errada era atribuida ao Remote-User.

Aconteceu de verdade: `BASIC_AUTH` foi exportado com um SHA de `git stash` no
lugar da senha. O nginx devolveu 401, e o aceite 2 imprimiu

    401 aqui = Remote-User (passo 2). 403 = CIDR (passo 1).

mandando reeditar um bloco nginx que estava correto. Foi a terceira vez na
janela que o diagnostico apontou para o lugar errado.

A raiz e de ordem, nao de texto: todo aceite via ingress atravessa o basic auth,
mas o script so exercitava o basic auth DE DENTRO de um aceite cujo proposito
era outro. 401 do nginx e 401 do app sao o mesmo numero por caminhos diferentes;
sem separar os dois, qualquer mensagem ali e chute.

Agora o passo 3c prova a credencial primeiro, numa rota de leitura livre, e usa
o desafio WWW-Authenticate para saber de quem veio o 401. Os aceites que
dependem do ingress so rodam depois disso.

Estes testes rodam o script de verdade com `curl` e `docker` stubados — sem VPS,
sem daemon. Foi assim que apareceu o bug do `docker exec` sem `-i`.
"""
import os
import pathlib
import shutil
import stat
import subprocess

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "scripts" / "deploy-cockpit.sh"
STUBS = pathlib.Path(__file__).resolve().parent / "fixtures" / "stub_deploy"

CRED_BOA = "cockpit:senha-certa"


@pytest.fixture
def rodar(tmp_path):
    """Executa o script em --validate com PATH stubado. Devolve o stdout."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for nome in ("curl", "docker"):
        destino = bin_dir / nome
        shutil.copy(STUBS / nome, destino)
        destino.chmod(destino.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    compose = tmp_path / "compose"
    compose.mkdir()
    (compose / ".env").write_text(
        "BASIC_AUTH_USER=cockpit\nTRUSTED_GATEWAY_CIDR=172.19.0.0/16\n"
    )

    def _rodar(cenario, basic_auth, extra=None):
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["STUB_CENARIO"] = cenario
        env["STUB_CRED_BOA"] = CRED_BOA
        env["DOMAIN"] = "cockpit.teste.invalido"
        env.pop("BASIC_AUTH", None)
        if basic_auth is not None:
            env["BASIC_AUTH"] = basic_auth
        if extra:
            env.update(extra)
        r = subprocess.run(
            ["bash", str(SCRIPT), "--validate"],
            cwd=compose, env=env, capture_output=True, text=True, timeout=180,
        )
        return r.stdout + r.stderr

    return _rodar


# ---------------------------------------------------------------------------
# O caso que aconteceu
# ---------------------------------------------------------------------------

def test_senha_errada_acusa_a_credencial(rodar):
    saida = rodar("senha_errada", "cockpit:sha-de-git-stash-por-engano")
    assert "credencial REJEITADA" in saida, saida
    assert "a senha (ou o usuario) esta errada" in saida


def test_senha_errada_nao_culpa_o_remote_user(rodar):
    """O aceite 2 nao pode nem rodar: a credencial nao passou."""
    saida = rodar("senha_errada", "cockpit:errada")
    assert "401 = falta proxy_set_header Remote-User" not in saida, (
        "voltou a mandar consertar o bloco nginx por causa de senha errada:\n" + saida
    )
    assert "NAO e Remote-User e NAO e o CIDR" in saida


def test_senha_errada_diz_onde_consertar(rodar):
    saida = rodar("senha_errada", "cockpit:errada")
    assert ".htpasswd" in saida
    assert "openssl passwd -apr1" in saida, \
        "htpasswd nao existe na VPS; o hash sai do openssl"
    assert ">>" in saida, "o .htpasswd e bind-mount: sobrescrever troca o inode"


def test_senha_errada_pula_os_aceites_de_ingress(rodar):
    saida = rodar("senha_errada", "cockpit:errada")
    assert "pulando os aceites que passam por ela" in saida
    for pulado in ("pulei o teste via ingress", "pulei o teste de SSE"):
        assert pulado in saida, f"faltou pular: {pulado}\n{saida}"


def test_senha_errada_reconhece_o_desafio_do_nginx(rodar):
    """WWW-Authenticate separa 401 do nginx de 401 do app."""
    saida = rodar("senha_errada", "cockpit:errada")
    assert "veio do nginx, nao do cockpit" in saida


def test_a_senha_nunca_aparece_na_saida(rodar):
    segredo = "senha-que-nao-pode-vazar-123"
    saida = rodar("senha_errada", f"cockpit:{segredo}")
    assert segredo not in saida, "o script imprimiu a senha"
    assert "usuario informado em BASIC_AUTH: cockpit" in saida, \
        "o usuario pode e deve aparecer — ja esta no .env"


# ---------------------------------------------------------------------------
# Credencial boa: o 3c passa e os aceites rodam
# ---------------------------------------------------------------------------

def test_credencial_boa_libera_os_aceites(rodar):
    saida = rodar("ok", CRED_BOA)
    assert "credencial aceita pelo ingress" in saida
    assert "basic auth ativo: credencial falsa recusada" in saida
    assert "unlock via ingress autorizado" in saida
    assert "pulando os aceites que passam por ela" not in saida


def test_com_credencial_boa_o_401_do_aceite_2_ainda_aponta_o_cabecalho(rodar):
    """A mensagem nao foi apagada — foi condicionada.

    Se a credencial passou no 3c e o unlock ainda da 401, ai sim o suspeito e o
    Remote-User. O texto novo diz isso explicitamente ("credencial ja validada
    no 3c, logo"), para nao virar chute de novo.
    """
    fonte = SCRIPT.read_text()
    assert "credencial ja validada no 3c, logo:" in fonte
    assert "401 = falta proxy_set_header Remote-User (passo 2)." in fonte
    assert "403 = TRUSTED_GATEWAY_CIDR nao cobre o ip do gateway (passo 1)." in fonte


# ---------------------------------------------------------------------------
# BASIC_AUTH ausente nao e reprovacao
# ---------------------------------------------------------------------------

def test_sem_basic_auth_avisa_e_nao_reprova(rodar):
    saida = rodar("ok", None)
    assert "BASIC_AUTH nao exportado" in saida
    assert "serao pulados, nao reprovados" in saida
    assert "credencial REJEITADA" not in saida


# ---------------------------------------------------------------------------
# O caso que o 3c descobre de graca
# ---------------------------------------------------------------------------

def test_basic_auth_desligado_e_denunciado(rodar):
    """Se qualquer credencial passa, o 200 da credencial boa nao prova nada.

    Uma credencial deliberadamente falsa TEM de ser recusada. Se nao for, o
    cockpit esta aberto a quem alcancar o dominio — mais grave que qualquer
    aceite abaixo.
    """
    saida = rodar("auth_aberto", CRED_BOA)
    assert "basic auth nao protege esta rota" in saida
    assert "o cockpit esta aberto a quem alcancar o dominio" in saida
    assert "pulando os aceites que passam por ela" in saida, \
        "com auth aberto os aceites via ingress nao significam nada"


# ---------------------------------------------------------------------------
# Ordem: o 3c vem antes
# ---------------------------------------------------------------------------

def test_a_checagem_de_credencial_vem_antes_dos_aceites(rodar):
    saida = rodar("ok", CRED_BOA)
    pos_3c = saida.index("3c · Credencial do ingress")
    pos_4 = saida.index("4 · Validacao")
    assert pos_3c < pos_4, "o 3c tem de imprimir antes do 4; era essa a raiz do bug"


def test_o_fluxo_principal_chama_o_3c_antes_de_validar():
    fonte = SCRIPT.read_text()
    corpo = fonte[fonte.index("printf '\\033[1mJanela de deploy"):]
    assert corpo.index("checa_credencial") < corpo.index("\n  validar\n"), \
        "checa_credencial precisa ser chamado antes de validar no fluxo principal"


def test_dry_run_nao_toca_a_rede(rodar, tmp_path):
    """O 3c faz requisicao; em dry-run isso nao pode acontecer."""
    fonte = SCRIPT.read_text()
    corpo = fonte[fonte.index('if [ "$MODO" = "dry-run" ]; then'):]
    trecho = corpo[: corpo.index("titulo \"Resultado\"")]
    antes, _, depois = trecho.partition("else")
    assert "checa_credencial" not in antes, \
        "checa_credencial ficou no ramo de dry-run — faria requisicao autenticada"
    assert "checa_credencial" in depois
