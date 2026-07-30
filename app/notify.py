"""Motor de notificações (B7).

Duas metades separadas de propósito por uma fila:

    detecção  ──put_nowait──>  fila  ──>  despachante  ──>  Telegram/Discord/Slack

A detecção roda dentro do consumidor de eventos do daemon. Se ela chamasse o
webhook direto, um Telegram lento — e o Telegram *é* lento quando a rede da VPS
oscila — seguraria o `async for` do stream de eventos, e a timeline inteira
pararia esperando uma mensagem de chat. A fila é o que garante que a entrega
nunca segura a detecção; e ela tem teto, porque uma fila sem teto num crash loop
vira consumo de memória sem limite.

Regras vivas:

- `container_die` — `die` com exit ≠ 0. Exit 0 **nunca** notifica: `docker stop`
  emite `die` com exit 0, e um alerta a cada parada pedida por alguém treina o
  operador a ignorar o canal. Parada limpa é informação, não incidente.
- `unhealthy` — healthcheck falhando.
- `disk_high` — uso acima de `NOTIFY_DISCO_PCT` (padrão 80).
- `imagem_desatualizada` — o que o job diário do B6 encontrou.
- `brute_force` — **reservada para o B11**. O nome está aqui e no dedup para que
  a regra entre lá sem migração de banco nem mudança de contrato na tela.

O que a mensagem carrega: host, alvo, regra e instante. Nada de payload bruto —
inspect e log de container passam por variável de ambiente, linha de comando e
cabeçalho de request, e um webhook de chat é o lugar menos controlado por onde
esse conteúdo poderia sair. O canal recebe o suficiente para o operador saber
onde olhar; olhar é no cockpit.
"""

import asyncio
import os
import socket
from datetime import datetime, timedelta, timezone

import httpx

# Janela de silêncio por (regra, alvo). Persistida: ver a v15.
DEDUP_MIN = float(os.getenv("NOTIFY_DEDUP_MIN", "30") or 30)

DISCO_PCT = float(os.getenv("NOTIFY_DISCO_PCT", "80") or 80)

# Intervalo do laço que olha vitais e imagens. O caminho de evento é push e não
# passa por aqui.
INTERVALO_S = float(os.getenv("NOTIFY_INTERVAL", "300") or 300)

# Teto da fila. Cheia, a detecção descarta em vez de bloquear: um crash loop
# gera centenas de `die` por minuto, e travar o stream de eventos para entregar
# todos seria trocar a timeline por notificação — o oposto da prioridade.
FILA_MAX = int(os.getenv("NOTIFY_FILA_MAX", "500") or 500)

HOST = os.getenv("NOTIFY_HOST", "") or socket.gethostname()

_fila: asyncio.Queue | None = None
_descartadas = 0


def _agora():
    return datetime.now(timezone.utc)


def _iso(dt=None):
    return (dt or _agora()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# --- canais ---------------------------------------------------------------
#
# Cada canal é (nome, url, corpo). O segredo mora na URL (Discord, Slack) ou no
# path (Telegram) — e é por isso que NADA aqui devolve a URL para o chamador: o
# que sobe para o log e para o banco é o NOME do canal e um motivo curto.

def canais_configurados() -> list[str]:
    nomes = []
    if os.getenv("NOTIFY_TELEGRAM_TOKEN") and os.getenv("NOTIFY_TELEGRAM_CHAT_ID"):
        nomes.append("telegram")
    if os.getenv("NOTIFY_DISCORD_WEBHOOK"):
        nomes.append("discord")
    if os.getenv("NOTIFY_SLACK_WEBHOOK"):
        nomes.append("slack")
    return nomes


def _destino(nome: str, texto: str):
    if nome == "telegram":
        token = os.getenv("NOTIFY_TELEGRAM_TOKEN", "")
        chat = os.getenv("NOTIFY_TELEGRAM_CHAT_ID", "")
        return f"https://api.telegram.org/bot{token}/sendMessage", {
            "chat_id": chat, "text": texto, "disable_web_page_preview": True,
        }
    if nome == "discord":
        return os.getenv("NOTIFY_DISCORD_WEBHOOK", ""), {"content": texto}
    if nome == "slack":
        return os.getenv("NOTIFY_SLACK_WEBHOOK", ""), {"text": texto}
    return "", {}


async def _entrega(nome: str, texto: str) -> str:
    """Entrega num canal. Devolve "" se entregou, ou um motivo CURTO e sem segredo.

    O motivo nunca é `str(exc)`: httpx põe a URL na representação da exceção, e a
    URL do webhook do Discord *é* a credencial. Um log de erro que a imprime
    publica o segredo no journald e em qualquer coletor de log que o siga.
    """
    url, corpo = _destino(nome, texto)
    if not url:
        return "sem configuracao"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=corpo)
    except (httpx.HTTPError, OSError) as exc:
        return f"rede: {type(exc).__name__}"
    if r.status_code >= 400:
        return f"HTTP {r.status_code}"
    return ""


async def _entrega_em_todos(texto: str):
    """Falha num canal não impede os outros — entregas em paralelo, erros isolados."""
    nomes = canais_configurados()
    if not nomes:
        return [], "sem canal configurado"
    resultados = await asyncio.gather(
        *(_entrega(n, texto) for n in nomes), return_exceptions=True
    )
    entregues, falhas = [], []
    for nome, res in zip(nomes, resultados):
        motivo = res if isinstance(res, str) else f"erro: {type(res).__name__}"
        if motivo:
            falhas.append(f"{nome}: {motivo}")
        else:
            entregues.append(nome)
    return entregues, "; ".join(falhas)


# --- mensagem -------------------------------------------------------------

_TITULOS = {
    "container_die": "container terminou com erro",
    "unhealthy": "healthcheck falhando",
    "disk_high": "disco acima do limite",
    "imagem_desatualizada": "imagem desatualizada",
    "brute_force": "tentativas de acesso",
}


def monta_mensagem(regra: str, alvo: str, ts: str, detalhe: str = "") -> str:
    """host · alvo · regra · ts. Nada além disso.

    `detalhe` é texto que ESTE módulo escreveu (um exit code, um percentual) —
    nunca um trecho de log, de inspect ou de resposta de API.
    """
    titulo = _TITULOS.get(regra, regra)
    linhas = [
        f"[{HOST}] {titulo}",
        f"alvo: {alvo or '—'}",
        f"regra: {regra}",
        f"quando: {ts}",
    ]
    if detalhe:
        linhas.append(detalhe)
    return "\n".join(linhas)


# --- dedup ----------------------------------------------------------------

async def deve_notificar(regra: str, alvo: str) -> bool:
    """False enquanto a janela de silêncio do par (regra, alvo) estiver aberta.

    Por (regra, alvo) e não por regra: dois containers em crash loop são dois
    incidentes, e silenciar o segundo porque o primeiro notificou esconderia
    metade do problema.
    """
    from db import ultima_entrega

    quando = await ultima_entrega(regra, alvo)
    if not quando:
        return True
    try:
        visto = datetime.fromisoformat(str(quando).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    return _agora() - visto >= timedelta(minutes=DEDUP_MIN)


# --- fila -----------------------------------------------------------------

def fila() -> asyncio.Queue:
    global _fila
    if _fila is None:
        _fila = asyncio.Queue(maxsize=FILA_MAX)
    return _fila


def enfileirar(regra: str, alvo: str, ts: str = "", detalhe: str = "") -> bool:
    """Chamada pela detecção. Nunca bloqueia, nunca levanta, nunca faz I/O.

    Devolve False quando a fila está cheia. Descarte é uma escolha: com o
    despachante travado, a alternativa seria segurar o stream de eventos.
    """
    global _descartadas
    try:
        fila().put_nowait({
            "regra": regra, "alvo": alvo or "", "ts": ts or _iso(), "detalhe": detalhe or "",
        })
        return True
    except asyncio.QueueFull:
        _descartadas += 1
        return False
    except RuntimeError:
        # Sem loop rodando (import em teste síncrono): não é caminho de produção.
        return False


async def despachar(item: dict) -> dict:
    """Dedup, entrega e registro de UM item. Devolve o que foi feito."""
    from db import registrar_notificacao

    regra, alvo = item.get("regra", ""), item.get("alvo", "")
    if not await deve_notificar(regra, alvo):
        return {"regra": regra, "alvo": alvo, "acao": "deduplicado"}

    texto = monta_mensagem(regra, alvo, item.get("ts") or _iso(), item.get("detalhe", ""))
    entregues, falhas = await _entrega_em_todos(texto)
    await registrar_notificacao(regra, alvo, item.get("ts") or _iso(),
                                entregues, falhas, item.get("detalhe", ""))
    return {"regra": regra, "alvo": alvo, "acao": "entregue" if entregues else "sem entrega",
            "canais": entregues, "falhas": falhas}


async def despachante_loop():
    """Consome a fila para sempre. Item que levanta não mata o laço."""
    q = fila()
    while True:
        try:
            item = await q.get()
        except asyncio.CancelledError:
            break
        try:
            await despachar(item)
        except asyncio.CancelledError:
            break
        except Exception:
            pass
        finally:
            q.task_done()


# --- detecção: eventos do daemon -----------------------------------------

def avaliar_evento(linha: dict) -> list[dict]:
    """Chamada pelo consumidor de eventos, com a LINHA já persistida.

    Síncrona e sem I/O: ela roda dentro do `async for` do stream.
    """
    if not isinstance(linha, dict):
        return []
    acao = linha.get("action") or ""
    alvo = linha.get("actor_name") or linha.get("actor_id") or ""
    ts = linha.get("ts") or _iso()
    achados = []

    if acao == "die":
        exit_code = str(linha.get("exit_code") or "")
        # Exit vazio: o daemon não informou, e não dá para afirmar que foi falha.
        # Exit 0: parada pedida. Nenhum dos dois notifica.
        if exit_code not in ("", "0"):
            achados.append({"regra": "container_die", "alvo": alvo, "ts": ts,
                            "detalhe": f"exit {exit_code}"})
    elif acao == "health_status" and "unhealthy" in str(linha.get("exit_code") or ""):
        achados.append({"regra": "unhealthy", "alvo": alvo, "ts": ts, "detalhe": ""})

    for a in achados:
        enfileirar(a["regra"], a["alvo"], a["ts"], a["detalhe"])
    return achados


# --- detecção: vitais e imagens ------------------------------------------

def avaliar_disco(amostra: dict) -> list[dict]:
    """Um alvo por ponto de montagem: `/` cheio e `/mnt/dados` cheio são dois
    problemas, com donos e soluções diferentes."""
    if not isinstance(amostra, dict):
        return []
    achados = []
    for d in amostra.get("disks") or []:
        if not isinstance(d, dict):
            continue
        pct = d.get("percent")
        if isinstance(pct, (int, float)) and pct >= DISCO_PCT:
            ponto = str(d.get("mountpoint") or "?")
            achados.append({"regra": "disk_high", "alvo": ponto, "ts": _iso(),
                            "detalhe": f"{pct:.1f}% em uso"})
    for a in achados:
        enfileirar(a["regra"], a["alvo"], a["ts"], a["detalhe"])
    return achados


async def avaliar_imagens() -> list[dict]:
    """Lê o resultado do job do B6 no banco. Não consulta o Hub."""
    from db import get_image_updates

    achados = []
    for linha in await get_image_updates():
        if linha.get("status") != "desatualizada":
            continue
        achados.append({"regra": "imagem_desatualizada", "alvo": linha.get("image") or "",
                        "ts": linha.get("consultado_em") or _iso(), "detalhe": ""})
    for a in achados:
        enfileirar(a["regra"], a["alvo"], a["ts"], a["detalhe"])
    return achados


async def ciclo() -> dict:
    """Uma varredura do que não chega por evento."""
    from sampler import get_last_sample

    disco = []
    try:
        disco = avaliar_disco(get_last_sample() or {})
    except Exception:
        pass
    imagens = []
    try:
        imagens = await avaliar_imagens()
    except Exception:
        pass
    return {"disco": len(disco), "imagens": len(imagens), "descartadas": _descartadas}


async def notify_loop(intervalo: float = None):
    espera = intervalo or INTERVALO_S
    while True:
        try:
            await ciclo()
            await asyncio.sleep(espera)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(espera)
