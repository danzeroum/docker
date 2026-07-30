"""5-B8 — drift: compose declarado x runtime.

Este bloco e quase todo sobre o que NAO e drift. A versao ingenua — comparar
tudo o que o compose diz com tudo o que o container tem — acusa divergencia em
100% dos servicos no primeiro segundo, porque todo container carrega dezenas de
variaveis que vieram da imagem e nunca estiveram no YAML. Um relatorio que
sempre acusa e um relatorio que ninguem le.

Os tres falsos positivos que os testes fecham:

- **env da imagem** (`PATH`, `LANG`): so chave declarada entra na comparacao;
- **`${VAR}` sem o `.env` do projeto**: vira "nao avaliada", nunca divergencia —
  o cockpit le o YAML cru e nao tem como saber o valor final;
- **compose ilegivel**: aviso no projeto, nunca exception nem drift fantasma.

E o aceite do contrato de tres estados: projeto integro da `count=0`, e `0` e
uma afirmacao. `null` era ausencia de fonte, e o chip vivia nela desde a 2a.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

import drift as drf  # noqa: E402


def inspect(nome="api", imagem="nginx:1.25", projeto="btv", servico="api",
            arquivos="/opt/btv/x/docker-compose.yml", env=None, portas=None):
    rotulos = {}
    if projeto:
        rotulos[drf.LABEL_PROJETO] = projeto
        rotulos[drf.LABEL_SERVICO] = servico
        if arquivos:
            rotulos[drf.LABEL_ARQUIVOS] = arquivos
    ligacoes = {}
    for pub, alvo, proto in portas or []:
        ligacoes.setdefault(f"{alvo}/{proto}", []).append({"HostIp": "", "HostPort": pub})
    return {
        "Id": "cafe" * 8,
        "Name": f"/{nome}",
        "Config": {
            "Image": imagem,
            "Labels": rotulos,
            # Toda imagem traz env que nunca esteve no compose. E a fonte do
            # falso positivo que este bloco existe para nao gerar.
            "Env": ["PATH=/usr/local/sbin:/usr/bin", "LANG=C.UTF-8"] + (env or []),
        },
        "HostConfig": {"PortBindings": ligacoes},
    }


def pendencia(lista, campo):
    """Pendencia daquele campo. Por campo e nao por indice: um decl sem `image`
    ja produz a pendencia de imagem na frente, e indexar [0] testaria ela."""
    return next((p for p in lista if p["campo"] == campo), None)


def compose(tmp_path, texto, nome="docker-compose.yml"):
    caminho = tmp_path / nome
    caminho.write_text(texto, encoding="utf-8")
    return str(caminho)


# --- interpolacao ---------------------------------------------------------

def test_reconhece_as_tres_formas_de_interpolacao():
    for texto in ("${TAG}", "${TAG:-1.0}", "$TAG", "nginx:${TAG}"):
        assert drf.interpola(texto) is True, texto
    for texto in ("nginx:1.25", "", "8080:80", None):
        assert drf.interpola(texto) is False, texto


# --- imagem ---------------------------------------------------------------

def test_tag_divergente_e_drift_com_esperado_e_atual():
    d, _ = drf.compara_servico("api", {"image": "nginx:1.24"}, inspect(imagem="nginx:1.25"))
    assert len(d) == 1
    assert d[0]["campo"] == "imagem"
    assert d[0]["esperado"] == "nginx:1.24"
    assert d[0]["atual"] == "nginx:1.25"


def test_tag_igual_nao_e_drift():
    d, _ = drf.compara_servico("api", {"image": "nginx:1.25"}, inspect(imagem="nginx:1.25"))
    assert d == []


def test_imagem_interpolada_nao_vira_falso_positivo():
    """Sem o `.env` do projeto nao da para resolver `${TAG}`. Afirmar drift ali
    seria acusar o operador de um erro que e nosso."""
    d, np = drf.compara_servico("api", {"image": "nginx:${TAG}"}, inspect(imagem="nginx:1.25"))
    assert d == []
    assert len(np) == 1
    assert np[0]["motivo"] == "interpolacao nao resolvida"


def test_servico_construido_localmente_nao_vira_falso_positivo():
    """`build:` sem `image:`: o nome final e derivado pelo compose."""
    d, np = drf.compara_servico("api", {"build": "./app"}, inspect(imagem="btv-api:latest"))
    assert d == []
    assert np[0]["campo"] == "imagem"


# --- ambiente -------------------------------------------------------------

def test_env_da_imagem_nao_conta_como_drift():
    """PATH e LANG existem em todo container e nunca estiveram no compose."""
    d, _ = drf.compara_servico("api", {"environment": {"TZ": "UTC"}},
                               inspect(env=["TZ=UTC"]))
    assert d == []


def test_env_declarada_com_valor_diferente_e_drift():
    d, _ = drf.compara_servico("api", {"environment": {"TZ": "UTC"}},
                               inspect(env=["TZ=America/Sao_Paulo"]))
    assert len(d) == 1
    assert d[0]["campo"] == "env" and d[0]["chave"] == "TZ"


def test_env_declarada_e_ausente_no_runtime_e_drift():
    d, _ = drf.compara_servico("api", {"environment": {"TZ": "UTC"}}, inspect(env=[]))
    assert d[0]["atual"] == "ausente"


def test_env_em_lista_sem_valor_e_nao_avaliada():
    """`- CHAVE` sem `=` significa herdar do host: nao ha valor declarado, e
    tratar isso como string vazia acusaria drift em toda chave que o operador
    deliberadamente deixou vir de fora."""
    d, np = drf.compara_servico("api", {"environment": ["HERDADA"]},
                                inspect(env=["HERDADA=algo"]))
    assert d == []
    assert pendencia(np, "env")["chave"] == "HERDADA"


def test_env_interpolada_e_nao_avaliada():
    d, np = drf.compara_servico("api", {"environment": {"SENHA": "${DB_PASS}"}},
                                inspect(env=["SENHA=abc"]))
    assert d == []
    assert pendencia(np, "env")["motivo"] == "interpolacao nao resolvida"


def test_valor_de_env_sensivel_sai_mascarado():
    """O drift precisa dizer que a chave divergiu, nao qual e a senha nova."""
    d, _ = drf.compara_servico("api", {"environment": {"DB_PASSWORD": "declarada-abc"}},
                               inspect(env=["DB_PASSWORD=trocada-em-marco"]))
    assert len(d) == 1
    assert "declarada-abc" not in str(d[0])
    assert "trocada-em-marco" not in str(d[0])


# --- portas ---------------------------------------------------------------

def test_porta_declarada_e_nao_publicada_e_drift():
    d, _ = drf.compara_servico("api", {"ports": ["8080:80"]}, inspect(portas=[]))
    assert d[0]["campo"] == "porta" and d[0]["atual"] == "ausente"


def test_porta_publicada_e_nao_declarada_e_drift():
    d, _ = drf.compara_servico("api", {"ports": []}, inspect(portas=[("8080", "80", "tcp")]))
    assert d[0]["campo"] == "porta" and d[0]["esperado"] == "nao declarada"


def test_porta_igual_nao_e_drift():
    d, _ = drf.compara_servico("api", {"ports": ["8080:80"]},
                               inspect(portas=[("8080", "80", "tcp")]))
    assert d == []


def test_porta_com_ip_de_bind_casa_pelo_par_publicado_alvo():
    d, _ = drf.compara_servico("api", {"ports": ["127.0.0.1:8080:80"]},
                               inspect(portas=[("8080", "80", "tcp")]))
    assert d == []


def test_forma_longa_de_porta():
    d, _ = drf.compara_servico("api", {"ports": [{"published": 8080, "target": 80}]},
                               inspect(portas=[("8080", "80", "tcp")]))
    assert d == []


def test_faixa_de_portas_e_nao_avaliada():
    """Expandir acertaria o caso simples e erraria o com offset, e drift
    inventado numa faixa e o alarme que ninguem consegue verificar rapido."""
    d, np = drf.compara_servico("api", {"ports": ["8000-8005:8000-8005"]}, inspect(portas=[]))
    assert d == []
    assert pendencia(np, "porta")["motivo"] == "faixa de portas"


def test_porta_efemera_e_nao_avaliada_nos_DOIS_sentidos():
    """O falso positivo entrava pela outra ponta: `- "80"` sai como nao avaliada
    do lado declarado, e a porta 49153 que o daemon escolheu apareceria como
    "publicada, nao declarada" no mesmo servico que acabamos de marcar como nao
    avaliado. Marcar de um lado so nao resolve nada."""
    d, np = drf.compara_servico("api", {"ports": ["80"]},
                                inspect(portas=[("49153", "80", "tcp")]))
    assert d == [], "a porta efemera voltou como drift pela checagem inversa"
    assert pendencia(np, "porta")["motivo"] == "porta publicada efemera"


def test_faixa_declarada_nao_acusa_as_portas_da_faixa_pela_inversa():
    d, _ = drf.compara_servico("api", {"ports": ["8000-8002:8000-8002"]},
                               inspect(portas=[("8001", "8001", "tcp")]))
    assert d == []


def test_porta_publicada_fora_da_faixa_declarada_ainda_e_drift():
    """Cegar a inversa nao pode virar cegar tudo: o que esta fora do que o
    operador declarou continua sendo achado."""
    d, _ = drf.compara_servico("api", {"ports": ["8000-8002:8000-8002"]},
                               inspect(portas=[("9999", "9999", "tcp")]))
    assert len(d) == 1 and d[0]["esperado"] == "nao declarada"


def test_alvo_interpolado_cala_a_checagem_inversa_do_servico():
    """`${PUB}:${ALVO}`: qualquer porta publicada pode ser a que nao lemos."""
    d, _ = drf.compara_servico("api", {"ports": ["${PUB}:${ALVO}"]},
                               inspect(portas=[("9999", "9999", "tcp")]))
    assert d == []


def test_protocolo_diferente_e_drift():
    d, _ = drf.compara_servico("api", {"ports": ["53:53/udp"]},
                               inspect(portas=[("53", "53", "tcp")]))
    assert len(d) == 2, "udp declarada ausente e tcp publicada nao declarada"


# --- carga do compose -----------------------------------------------------

def test_compose_ausente_vira_aviso_e_nao_exception():
    servicos, aviso = drf.carrega_compose(["/nao/existe/docker-compose.yml"])
    assert servicos == {}
    assert "nao encontrado" in aviso


def test_yaml_quebrado_vira_aviso(tmp_path):
    caminho = compose(tmp_path, "services:\n  api:\n   image: [aberto\n")
    servicos, aviso = drf.carrega_compose([caminho])
    assert servicos == {}
    assert "ilegivel" in aviso


def test_override_sobrepoe_a_base(tmp_path):
    base = compose(tmp_path, "services:\n  api:\n    image: nginx:1.24\n")
    over = compose(tmp_path, "services:\n  api:\n    image: nginx:1.25\n",
                   nome="docker-compose.override.yml")
    servicos, aviso = drf.carrega_compose([base, over])
    assert aviso == ""
    assert servicos["api"]["image"] == "nginx:1.25"


# --- montagem -------------------------------------------------------------

def test_container_sem_label_de_projeto_sai_como_fora_de_projeto():
    """Container antigo ou `docker run` a mao. Nao e erro — e o achado."""
    r = drf.montar({"a": inspect(nome="avulso", projeto=None)})
    assert r["projects"] == []
    assert [c["name"] for c in r["fora_de_projeto"]] == ["avulso"]
    assert r["count"] == 1


def test_projeto_integro_da_count_zero_e_nao_none(tmp_path):
    """Aceite do contrato de tres estados: `0` e a fonte dizendo que esta limpo.
    `null` era ausencia de fonte, e o chip vivia nela desde a 2a."""
    caminho = compose(tmp_path, "services:\n  api:\n    image: nginx:1.25\n")
    r = drf.montar({"a": inspect(arquivos=caminho)})
    assert r["count"] == 0
    assert r["count"] is not None
    assert r["projects"][0]["drift"] == []
    assert r["projects"][0]["aviso"] == ""


def test_tag_divergente_aparece_com_servico_esperado_e_atual(tmp_path):
    caminho = compose(tmp_path, "services:\n  api:\n    image: nginx:1.24\n")
    r = drf.montar({"a": inspect(arquivos=caminho, imagem="nginx:1.25")})
    d = r["projects"][0]["drift"]
    assert len(d) == 1
    assert (d[0]["servico"], d[0]["esperado"], d[0]["atual"]) == ("api", "nginx:1.24", "nginx:1.25")
    assert r["count"] == 1


def test_servico_declarado_sem_container(tmp_path):
    caminho = compose(tmp_path, "services:\n  api:\n    image: nginx:1.25\n"
                                "  worker:\n    image: redis:7\n")
    r = drf.montar({"a": inspect(arquivos=caminho)})
    d = r["projects"][0]["drift"]
    assert [x["chave"] for x in d] == ["worker"]
    assert d[0]["atual"] == "declarado, sem container"


def test_container_em_execucao_ausente_do_compose(tmp_path):
    caminho = compose(tmp_path, "services:\n  api:\n    image: nginx:1.25\n")
    r = drf.montar({
        "a": inspect(arquivos=caminho),
        "b": inspect(nome="extra", servico="extra", arquivos=caminho, imagem="redis:7"),
    })
    d = [x for x in r["projects"][0]["drift"] if x["campo"] == "servico"]
    assert d[0]["chave"] == "extra"
    assert "ausente do compose" in d[0]["atual"]


def test_compose_inacessivel_vira_aviso_no_projeto_sem_drift_fantasma():
    """Projeto que some da resposta por causa de um open() e pior que projeto
    com aviso: some sem dizer que sumiu."""
    r = drf.montar({"a": inspect(arquivos="/nao/existe/compose.yml")})
    p = r["projects"][0]
    assert p["drift"] == []
    assert "nao encontrado" in p["aviso"]
    assert r["count"] == 0, "arquivo ilegivel nao pode inventar divergencia"


def test_container_sem_o_rotulo_config_files_vira_aviso():
    """Compose antigo nao gravava o rotulo; o projeto aparece dizendo isso."""
    r = drf.montar({"a": inspect(arquivos="")})
    assert "config_files" in r["projects"][0]["aviso"]
    assert r["projects"][0]["drift"] == []


def test_nao_avaliadas_nao_entram_na_contagem(tmp_path):
    """Misturar as duas contagens transformaria uma limitacao conhecida da
    comparacao em alarme sobre a infraestrutura."""
    caminho = compose(tmp_path, "services:\n  api:\n    image: nginx:${TAG}\n"
                                "    ports: ['8000-8005:8000-8005']\n")
    r = drf.montar({"a": inspect(arquivos=caminho)})
    assert r["count"] == 0
    assert len(r["projects"][0]["nao_avaliadas"]) == 2


def test_dois_projetos_ficam_separados(tmp_path):
    um = compose(tmp_path, "services:\n  api:\n    image: nginx:1.24\n")
    dois = compose(tmp_path, "services:\n  db:\n    image: postgres:16\n", nome="outro.yml")
    r = drf.montar({
        "a": inspect(projeto="btv", servico="api", arquivos=um, imagem="nginx:1.25"),
        "b": inspect(projeto="loja", servico="db", arquivos=dois, imagem="postgres:16"),
    })
    por_nome = {p["name"]: p for p in r["projects"]}
    assert len(por_nome["btv"]["drift"]) == 1
    assert por_nome["loja"]["drift"] == []


def test_inspect_invalido_nao_derruba_a_montagem():
    r = drf.montar({"a": None, "b": "lixo", "c": inspect(projeto=None)})
    assert r["count"] == 1


def test_sem_containers_da_estrutura_vazia_e_nao_erro():
    r = drf.montar({})
    assert r["count"] == 0 and r["projects"] == [] and r["fora_de_projeto"] == []


# --- integracao com o summary ---------------------------------------------

def test_summary_drift_e_null_sem_fonte():
    import summary
    assert summary._drift(None) == {"count": None}


def test_summary_drift_conta_zero_quando_a_fonte_rodou_limpa():
    import summary
    r = summary._drift({"projects": [], "fora_de_projeto": [], "count": 0})
    assert r["count"] == 0


def test_summary_drift_separa_nao_avaliadas_da_contagem():
    import summary
    r = summary._drift({
        "count": 2,
        "fora_de_projeto": [{"name": "avulso"}],
        "projects": [{"name": "btv", "drift": [{}], "nao_avaliadas": [{}, {}, {}]}],
    })
    assert r["count"] == 2
    assert r["nao_avaliadas"] == 3
    assert r["fora_de_projeto"] == 1


def test_o_calculo_nao_chama_o_daemon():
    """O drift entra no aquecimento da regua; uma varredura de containers por
    poll seria o oposto do que o summary existe para evitar."""
    import inspect as _inspect
    fonte = _inspect.getsource(drf)
    assert "proxy_get" not in fonte
    assert "httpx" not in fonte
