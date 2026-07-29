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
        # nao ha app para esperar; 30s de espera real por teste estouraria tudo
        env["ESPERA_APP_S"] = "2"
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


# ---------------------------------------------------------------------------
# App fora do ar: aceite inconclusivo nao e aceite reprovado
#
# Encontrado na VPS. Em --validate logo depois de `up -d --build app`, os dois
# primeiros aceites deram:
#
#     [1] token estatico em X-Cockpit-Unlock
#     FALHA esperado 403, veio erro
#     [2] unlock via ingress 200 · direto no app 401
#         direto em localhost:8000 -> erro
#     FALHA esperado 401, veio erro
#
# "erro" era qualquer excecao sem `.code` — ou seja, ninguem respondeu. Mas a
# mensagem lia como gate de escrita falhando, e a versao anterior chegava a
# sugerir "imagem antiga ainda rodando?". Reprovar um aceite de seguranca por
# app fora do ar manda consertar o lugar errado.
# ---------------------------------------------------------------------------

def test_app_fora_do_ar_nao_reprova_o_gate(rodar):
    saida = rodar("ok", CRED_BOA, extra={"STUB_APP": "fora"})
    assert "app nao respondeu em" in saida, saida
    assert "isto NAO e falha do gate de escrita: nada foi exercitado" in saida


def test_app_fora_do_ar_pula_os_aceites_internos(rodar):
    saida = rodar("ok", CRED_BOA, extra={"STUB_APP": "fora"})
    assert "pulei o aceite (nao ha o que concluir)" in saida
    assert "pulei o teste direto em localhost:8000" in saida
    assert "imagem antiga ainda rodando" not in saida, \
        "a mensagem que culpava a imagem por app fora do ar continua viva"


def test_sem_resposta_nunca_vira_erro_generico(rodar):
    """'erro' nao distinguia nada. Agora ha palavra propria."""
    saida = rodar("ok", CRED_BOA, extra={"STUB_APP": "fora"})
    assert "veio erro" not in saida
    assert "sem resposta do app" in saida or "app nao respondeu" in saida


def test_board_sem_resposta_nao_acusa_falta_de_guard(rodar):
    """'o board esta escrevendo sem guard' seria acusacao grave e errada."""
    saida = rodar("ok", CRED_BOA, extra={"STUB_APP": "fora"})
    assert "o board esta escrevendo sem guard" not in saida
    assert "guard nao exercitado, aceite inconclusivo" in saida


# ---------------------------------------------------------------------------
# O aceite 1 nao pode mais reiniciar o cockpit que ele testa
# ---------------------------------------------------------------------------

def test_aceite_1_nao_reinicia_o_proprio_cockpit():
    """No unico caso em que tinha algo a dizer, o teste destruia a evidencia.

    Se o gate ACEITASSE o token, o cockpit reiniciava a si mesmo: a conexao
    morria, o status virava erro de conexao e o aceite seguinte tambem falhava.
    O furo aparecia como "sem resposta" e era atribuido a outra coisa.
    """
    fonte = SCRIPT.read_text()
    corpo = fonte[fonte.index("# --- aceite 1:"):fonte.index("# --- aceite 2:")]
    sem_comentario = "\n".join(
        l for l in corpo.splitlines() if not l.strip().startswith("#")
    )
    assert "/restart" not in sem_comentario, \
        "o aceite 1 voltou a reiniciar o container que esta validando"
    assert "/api/tasks/cartao-que-nao-existe" in sem_comentario


def test_gate_aceitando_token_invalido_dispara_alarme(rodar):
    """404 na rota guardada = require_unlock deixou passar. E o furo da v8."""
    saida = rodar("ok", CRED_BOA, extra={"STUB_APP": "furo"})
    assert "o gate ACEITOU" in saida, saida
    assert "404 = passou e so nao achou o cartao" in saida
    assert "Nao siga com a janela" in saida


def test_gate_recusando_passa_o_aceite(rodar):
    saida = rodar("ok", CRED_BOA)
    assert "token estatico negado pelo gate" in saida or \
           "token arbitrario" in saida, saida
    assert "o gate ACEITOU" not in saida


# ---------------------------------------------------------------------------
# Ordem: app ouvindo, depois credencial, depois aceites
# ---------------------------------------------------------------------------

def test_espera_do_app_vem_antes_da_credencial_e_dos_aceites(rodar):
    saida = rodar("ok", CRED_BOA)
    pos_3d = saida.index("3d · App ouvindo")
    pos_3c = saida.index("3c · Credencial do ingress")
    pos_4 = saida.index("4 · Validacao")
    assert pos_3d < pos_3c < pos_4, \
        "a ordem e app -> credencial -> aceites; cada passo torna o seguinte legivel"


def test_espera_do_app_nao_roda_em_dry_run():
    fonte = SCRIPT.read_text()
    corpo = fonte[fonte.index('if [ "$MODO" = "dry-run" ]; then'):]
    trecho = corpo[: corpo.index('titulo "Resultado"')]
    antes, _, depois = trecho.partition("else")
    assert "espera_app" not in antes
    assert "espera_app" in depois
