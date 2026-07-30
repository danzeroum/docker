"""Drift: o que o compose declara contra o que está em execução (B8).

A pergunta que este módulo responde é a que ninguém consegue responder de
cabeça numa VPS com 15 containers: *o que está rodando ainda é o que está
escrito no arquivo?* Alguém subiu uma tag nova à mão em março, o compose no git
continua apontando para a antiga, e o próximo `docker compose up` — daqui a seis
meses, feito por outra pessoa — vai silenciosamente derrubar a versão boa.

Três regras que separam drift de ruído, e as três existem porque a versão sem
elas gera falso positivo em todo container real:

1. **Só chave declarada no YAML entra na comparação.** Um container tem dezenas
   de variáveis de ambiente que vieram da imagem (`PATH`, `LANG`, o que o
   Dockerfile pôs) e nunca estiveram no compose. Compará-las acusaria drift em
   100% dos serviços, no primeiro segundo, para sempre.

2. **`${VAR}` não resolvida vira "não avaliada", nunca divergência.** O cockpit
   lê o YAML cru, sem o `.env` que o compose usaria para interpolar; afirmar
   divergência entre `${TAG}` e `1.25` seria acusar o operador de um erro que é
   nosso. A chave sai sinalizada, com o motivo — que é informação útil por si:
   diz onde a comparação não alcança.

3. **Compose inacessível vira aviso no projeto, nunca exception nem drift
   fantasma.** Arquivo fora do mount read-only, permissão negada, YAML quebrado:
   em todos, o projeto aparece com aviso e drift vazio. Um projeto que some da
   resposta por causa de um `open()` seria pior que um projeto com aviso — some
   sem dizer que sumiu.

Valores de ambiente passam pela mesma máscara do inspect antes de sair daqui.
Drift de env precisa dizer *que a chave divergiu*, e não qual é a senha nova.
"""

import os
import re
from datetime import datetime, timezone

import yaml

from masking import mask_value

LABEL_PROJETO = "com.docker.compose.project"
LABEL_SERVICO = "com.docker.compose.service"
LABEL_ARQUIVOS = "com.docker.compose.project.config_files"

# `${VAR}`, `${VAR:-default}` e `$VAR`. Qualquer um deles marca a chave como
# não avaliada: sem o `.env` do projeto não dá para saber o valor final.
_INTERPOLACAO = re.compile(r"\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*")


def _agora():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def interpola(texto) -> bool:
    return bool(_INTERPOLACAO.search(str(texto or "")))


# --- leitura do compose ---------------------------------------------------

def carrega_compose(caminhos):
    """Funde os arquivos na ordem dada (override depois da base, como o compose).

    Devolve `(servicos, aviso)`. Nunca levanta: erro vira aviso, e o projeto
    continua na resposta dizendo que não deu para comparar.
    """
    servicos = {}
    avisos = []
    for caminho in caminhos:
        try:
            with open(caminho, "r", encoding="utf-8") as fh:
                # safe_load: o YAML vem do disco do host, e full_load
                # construiria objetos Python a partir dele.
                dados = yaml.safe_load(fh)
        except FileNotFoundError:
            avisos.append(f"nao encontrado: {os.path.basename(caminho)}")
            continue
        except PermissionError:
            avisos.append(f"sem permissao: {os.path.basename(caminho)}")
            continue
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
            avisos.append(f"ilegivel ({type(exc).__name__}): {os.path.basename(caminho)}")
            continue
        if not isinstance(dados, dict):
            avisos.append(f"sem mapa de servicos: {os.path.basename(caminho)}")
            continue
        bloco = dados.get("services")
        if not isinstance(bloco, dict):
            avisos.append(f"sem 'services': {os.path.basename(caminho)}")
            continue
        for nome, decl in bloco.items():
            if isinstance(decl, dict):
                servicos.setdefault(str(nome), {}).update(decl)
    return servicos, "; ".join(avisos)


# --- normalização ---------------------------------------------------------

def _env_declarado(decl: dict) -> tuple[dict, list]:
    """`environment` em dict ou lista. Devolve (declaradas, nao_avaliadas).

    `- CHAVE` sem `=` significa "herda do ambiente do host" — não há valor
    declarado a comparar, e tratar isso como `""` acusaria drift em toda chave
    que o operador deliberadamente deixou vir de fora.
    """
    bruto = decl.get("environment")
    declaradas, pendentes = {}, []
    if isinstance(bruto, dict):
        itens = [(str(k), v) for k, v in bruto.items()]
    elif isinstance(bruto, list):
        itens = []
        for entrada in bruto:
            texto = str(entrada)
            if "=" not in texto:
                pendentes.append((texto, "herdada do host, sem valor declarado"))
                continue
            chave, _, valor = texto.partition("=")
            itens.append((chave, valor))
    else:
        return {}, []

    for chave, valor in itens:
        if valor is None:
            pendentes.append((chave, "herdada do host, sem valor declarado"))
        elif interpola(valor):
            pendentes.append((chave, "interpolacao nao resolvida"))
        else:
            declaradas[chave] = str(valor)
    return declaradas, pendentes


def _env_em_execucao(insp: dict) -> dict:
    saida = {}
    for entrada in (insp.get("Config") or {}).get("Env") or []:
        chave, _, valor = str(entrada).partition("=")
        saida[chave] = valor
    return saida


def _alvos_do_texto(alvo: str) -> set:
    """Portas-alvo cobertas por `80` ou por uma faixa `8000-8005`.

    Só para SUPRIMIR a checagem inversa, nunca para afirmar drift: aqui basta
    saber quais alvos o operador declarou de alguma forma.
    """
    texto = str(alvo)
    if "-" not in texto:
        return {texto}
    inicio, _, fim = texto.partition("-")
    try:
        a, b = int(inicio), int(fim)
    except ValueError:
        return set()
    if b < a or b - a > 1024:
        return set()
    return {str(n) for n in range(a, b + 1)}


def _portas_declaradas(decl: dict) -> dict:
    """Normaliza para `(publicada, alvo, protocolo)`.

    Devolve também `alvos_cegos` e `reverso_cego`, e é por causa deles que este
    retorno é um dicionário e não uma tupla. Uma porta que não deu para avaliar
    do lado declarado — `- "80"` (efêmera), `${PORT}:80`, `8000-8005:8000-8005` —
    **também precisa sair da checagem inversa**. Sem isso, `- "80"` declarada e
    publicada em `49153` pelo daemon apareceria como "publicada, não declarada":
    o falso positivo entraria pela outra ponta, no mesmo serviço que acabamos de
    marcar como não avaliado.

    `reverso_cego` cobre o caso extremo em que nem o alvo é conhecido
    (`${PUB}:${ALVO}`): aí a checagem inversa do serviço inteiro se cala, porque
    qualquer porta publicada pode ser a que não conseguimos ler.
    """
    bruto = decl.get("ports")
    saida = {"pares": set(), "pendentes": [], "alvos_cegos": set(), "reverso_cego": False}
    if not isinstance(bruto, list):
        return saida

    for entrada in bruto:
        if isinstance(entrada, dict):
            pub = entrada.get("published")
            alvo = entrada.get("target")
            proto = str(entrada.get("protocol") or "tcp")
            if pub is None or alvo is None:
                saida["pendentes"].append((str(entrada), "forma longa incompleta"))
                if alvo is None:
                    saida["reverso_cego"] = True
                else:
                    saida["alvos_cegos"] |= _alvos_do_texto(alvo)
                continue
            if interpola(pub) or interpola(alvo):
                saida["pendentes"].append((f"{pub}:{alvo}", "interpolacao nao resolvida"))
                if interpola(alvo):
                    saida["reverso_cego"] = True
                else:
                    saida["alvos_cegos"] |= _alvos_do_texto(alvo)
                continue
            saida["pares"].add((str(pub), str(alvo), proto))
            continue

        texto = str(entrada)
        corpo, _, proto = texto.partition("/")
        proto = proto or "tcp"
        partes = corpo.split(":")
        alvo_bruto = partes[-1]

        if interpola(texto):
            saida["pendentes"].append((texto, "interpolacao nao resolvida"))
            if interpola(alvo_bruto):
                saida["reverso_cego"] = True
            else:
                saida["alvos_cegos"] |= _alvos_do_texto(alvo_bruto)
            continue
        if "-" in corpo:
            # Expandir acertaria o caso simples e erraria o caso com offset, e um
            # drift inventado numa faixa de portas é exatamente o alarme que
            # ninguém consegue verificar rápido.
            saida["pendentes"].append((texto, "faixa de portas"))
            saida["alvos_cegos"] |= _alvos_do_texto(alvo_bruto)
            continue
        if len(partes) == 1:
            # `- "80"` publica numa porta efêmera escolhida pelo daemon: não há
            # o que comparar do lado publicado.
            saida["pendentes"].append((texto, "porta publicada efemera"))
            saida["alvos_cegos"] |= _alvos_do_texto(alvo_bruto)
            continue
        saida["pares"].add((partes[-2], alvo_bruto, proto))
    return saida


def _portas_em_execucao(insp: dict) -> set:
    saida = set()
    ligacoes = (insp.get("HostConfig") or {}).get("PortBindings") or {}
    for chave, destinos in ligacoes.items():
        alvo, _, proto = str(chave).partition("/")
        for d in destinos or []:
            porta = (d or {}).get("HostPort")
            if porta:
                saida.add((str(porta), alvo, proto or "tcp"))
    return saida


def _imagem_em_execucao(insp: dict) -> str:
    return str((insp.get("Config") or {}).get("Image") or "")


# --- comparação -----------------------------------------------------------

def compara_servico(nome: str, decl: dict, insp: dict) -> tuple[list, list]:
    """Devolve `(divergencias, nao_avaliadas)` para um serviço."""
    divergencias, pendentes = [], []

    # imagem
    imagem_decl = decl.get("image")
    if imagem_decl is None:
        # `build:` sem `image:`: o nome final é derivado pelo compose, e
        # compará-lo com o que está rodando acusaria drift em todo serviço
        # construído localmente.
        pendentes.append({"servico": nome, "campo": "imagem", "chave": "image",
                          "motivo": "servico construido localmente (sem 'image')"})
    elif interpola(imagem_decl):
        pendentes.append({"servico": nome, "campo": "imagem", "chave": "image",
                          "motivo": "interpolacao nao resolvida"})
    else:
        atual = _imagem_em_execucao(insp)
        if str(imagem_decl) != atual:
            divergencias.append({"servico": nome, "campo": "imagem", "chave": "image",
                                 "esperado": str(imagem_decl), "atual": atual})

    # portas
    portas = _portas_declaradas(decl)
    for texto, motivo in portas["pendentes"]:
        pendentes.append({"servico": nome, "campo": "porta", "chave": texto, "motivo": motivo})
    atuais = _portas_em_execucao(insp)
    for p in sorted(portas["pares"] - atuais):
        divergencias.append({"servico": nome, "campo": "porta", "chave": f"{p[0]}:{p[1]}/{p[2]}",
                             "esperado": "publicada", "atual": "ausente"})
    if not portas["reverso_cego"]:
        for p in sorted(atuais - portas["pares"]):
            if p[1] in portas["alvos_cegos"]:
                continue
            divergencias.append({"servico": nome, "campo": "porta",
                                 "chave": f"{p[0]}:{p[1]}/{p[2]}",
                                 "esperado": "nao declarada", "atual": "publicada"})

    # ambiente
    decl_env, env_pendentes = _env_declarado(decl)
    for chave, motivo in env_pendentes:
        pendentes.append({"servico": nome, "campo": "env", "chave": chave, "motivo": motivo})
    atual_env = _env_em_execucao(insp)
    for chave, esperado in sorted(decl_env.items()):
        if chave not in atual_env:
            divergencias.append({"servico": nome, "campo": "env", "chave": chave,
                                 "esperado": mask_value(chave, esperado), "atual": "ausente"})
        elif atual_env[chave] != esperado:
            # Mascarado dos dois lados: o drift é o FATO de a chave divergir. O
            # valor novo de uma senha não tem por que passar por aqui.
            divergencias.append({"servico": nome, "campo": "env", "chave": chave,
                                 "esperado": mask_value(chave, esperado),
                                 "atual": mask_value(chave, atual_env[chave])})

    return divergencias, pendentes


# --- montagem -------------------------------------------------------------

def _rotulos(insp) -> dict:
    if not isinstance(insp, dict):
        return {}
    labels = (insp.get("Config") or {}).get("Labels")
    return labels if isinstance(labels, dict) else {}


def _nome(insp) -> str:
    return str(insp.get("Name") or "").lstrip("/") or str(insp.get("Id") or "")[:12]


def montar(inspects: dict) -> dict:
    """Monta o drift a partir dos inspects que o sampler já tem em memória.

    Zero chamada ao daemon: este cálculo entra no aquecimento da régua, e uma
    varredura de containers por poll seria o oposto do que o `summary` existe
    para evitar.
    """
    projetos = {}
    fora = []

    for insp in (inspects or {}).values():
        if not isinstance(insp, dict):
            continue
        rotulos = _rotulos(insp)
        projeto = str(rotulos.get(LABEL_PROJETO) or "")
        if not projeto:
            # Container antigo ou `docker run` à mão: fora de projeto NÃO é
            # erro, é o achado. Ele existe e ninguém o declarou.
            fora.append({"name": _nome(insp), "image": _imagem_em_execucao(insp)})
            continue
        p = projetos.setdefault(projeto, {
            "name": projeto,
            "compose_files": [c for c in str(rotulos.get(LABEL_ARQUIVOS) or "").split(",") if c],
            "servicos": {},
        })
        servico = str(rotulos.get(LABEL_SERVICO) or _nome(insp))
        p["servicos"][servico] = insp

    saida = []
    total = 0
    for nome in sorted(projetos):
        p = projetos[nome]
        divergencias, pendentes, aviso = [], [], ""
        if not p["compose_files"]:
            aviso = "container sem o rotulo config_files — compose nao localizavel"
            declarados = {}
        else:
            declarados, aviso = carrega_compose(p["compose_files"])

        if declarados:
            for servico, insp in sorted(p["servicos"].items()):
                decl = declarados.get(servico)
                if decl is None:
                    divergencias.append({"servico": servico, "campo": "servico",
                                         "chave": servico, "esperado": "declarado",
                                         "atual": "em execucao, ausente do compose"})
                    continue
                d, np = compara_servico(servico, decl, insp)
                divergencias.extend(d)
                pendentes.extend(np)
            for servico in sorted(set(declarados) - set(p["servicos"])):
                divergencias.append({"servico": servico, "campo": "servico",
                                     "chave": servico, "esperado": "em execucao",
                                     "atual": "declarado, sem container"})

        total += len(divergencias)
        saida.append({
            "name": nome,
            "compose_files": p["compose_files"],
            "aviso": aviso,
            "servicos": len(p["servicos"]),
            "drift": divergencias,
            "nao_avaliadas": pendentes,
        })

    return {
        "projects": saida,
        # Container fora de projeto conta como drift: ele está rodando e não
        # está escrito em lugar nenhum, que é exatamente a pergunta do bloco.
        "fora_de_projeto": fora,
        "count": total + len(fora),
        "generated_at": _agora(),
    }


async def calcular() -> dict:
    from sampler import get_container_inspects
    return montar(get_container_inspects())
