"""Rate-limit das superfícies de autenticação (B11).

Duas superfícies, e só elas: `POST /api/session/unlock` e o 401 do `/metrics`.
São os dois pontos em que apresentar uma credencial errada custa nada e pode ser
repetido para sempre — o resto do app ou é leitura autenticada pelo ingress, ou
já exige o token de unlock.

**O IP contado é a origem real, e isso não é detalhe.** Todo request chega do
ingress: contar `request.client.host` daria uma chave só para o mundo inteiro, e
o primeiro atacante trancaria todos os operadores junto com ele — um limitador
que vira negação de serviço contra quem ele deveria proteger. A origem sai do
`X-Forwarded-For`, e **só** quando o peer está dentro de
`TRUSTED_GATEWAY_CIDR`: aceitar o cabeçalho de qualquer peer deixaria o atacante
escolher a própria chave de contagem, e o limite viraria enfeite.

Do `X-Forwarded-For` vale a entrada **mais à direita**, não a primeira. O nginx
usa `$proxy_add_x_forwarded_for`, que ANEXA o peer ao que o cliente mandou: a
primeira entrada é texto que o cliente escreveu, e a última é a única que o
nosso gateway garantiu.

Janela deslizante em memória. O restart zera a contagem — e isso é aceitável
porque a notificação do B7 é persistida: o contador se perde, o fato não. É a
divisão de trabalho entre os dois blocos, e trocar isso por uma tabela nova
custaria uma migração para guardar dado que vale 60 segundos.
"""

import ipaddress
import logging
import os
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

LIMITE = int(os.getenv("AUTH_RATE_LIMIT", "5") or 5)
JANELA_S = float(os.getenv("AUTH_RATE_WINDOW", "60") or 60)

_falhas: dict[str, deque] = defaultdict(deque)
_avisou_sem_xff = False


def _gateway_confiavel(ip: str) -> bool:
    cidr = os.environ.get("TRUSTED_GATEWAY_CIDR", "").strip()
    if not cidr or not ip:
        return False
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


def origem(request) -> str:
    """IP real do cliente, ou `""` quando não dá para determinar.

    `""` desliga a contagem para aquele request em vez de cair no IP do
    ingress. Um limitador que não sabe quem está batendo não deve chutar: a
    alternativa — contar todo mundo junto sob a chave do gateway — transforma
    a proteção na própria negação de serviço.
    """
    global _avisou_sem_xff
    peer = request.client.host if getattr(request, "client", None) else ""
    if not _gateway_confiavel(peer):
        # Peer que não é o gateway: o cabeçalho dele não vale nada, mas o
        # próprio peer vale — é acesso direto, e o IP é o que se vê.
        return peer

    bruto = request.headers.get("x-forwarded-for") or ""
    partes = [p.strip() for p in bruto.split(",") if p.strip()]
    if not partes:
        if not _avisou_sem_xff:
            _avisou_sem_xff = True
            logger.warning(
                "ingress nao envia X-Forwarded-For: o rate-limit de autenticacao "
                "fica inerte, porque contar o IP do gateway trancaria todos os "
                "operadores junto com o atacante"
            )
        return ""
    # A ÚLTIMA: o nginx anexa o peer real ao que o cliente mandou, então tudo à
    # esquerda é texto escrito pelo cliente.
    return partes[-1]


def _limpa(fila: deque, agora: float):
    while fila and agora - fila[0] > JANELA_S:
        fila.popleft()


def bloqueado(ip: str) -> bool:
    """Já estourou a janela? Consulta pura — não conta como tentativa."""
    if not ip:
        return False
    agora = time.monotonic()
    fila = _falhas.get(ip)
    if not fila:
        return False
    _limpa(fila, agora)
    return len(fila) >= LIMITE


def registra_falha(ip: str) -> bool:
    """Conta uma falha. Devolve True quando ESTA falha estourou o limite.

    True só na transição, e não em toda falha depois dela: o disparo do
    `brute_force` está pendurado neste retorno, e uma notificação por tentativa
    inundaria o canal com o mesmo fato — que é justamente o que um ataque de
    força bruta produz em volume.
    """
    if not ip:
        return False
    agora = time.monotonic()
    fila = _falhas[ip]
    _limpa(fila, agora)
    fila.append(agora)
    return len(fila) == LIMITE


def zera(ip: str):
    """Credencial correta limpa o contador daquele IP.

    Sem isto, quatro erros de digitação seguidos de um acerto deixariam o
    operador a uma falha do 429 pelo resto do minuto — punindo quem provou ser
    quem diz ser."""
    if ip:
        _falhas.pop(ip, None)


def _reset():
    """Só para os testes: estado global entre casos."""
    _falhas.clear()


def registra_e_notifica(request, superficie: str) -> bool:
    """Conta a falha e dispara `brute_force` na transição. Devolve se estourou.

    A regra estava reservada no motor do B7 desde a Sprint 4, com um teste que
    proibia o disparo. O teste sai no MESMO commit que liga a regra: a bissecção
    nunca encontra um estado em que a regra existe e o teste a proíbe, nem o
    contrário — mesma disciplina do pin do `ENABLE_ACTIONS`.
    """
    ip = origem(request)
    if not registra_falha(ip):
        return False
    try:
        from notify import enfileirar
        enfileirar("brute_force", ip, detalhe=f"{LIMITE} falhas em {int(JANELA_S)}s · {superficie}")
    except Exception:
        # Notificação que falha não pode derrubar o 429: o bloqueio é a
        # proteção, o aviso é consequência.
        pass
    return True
