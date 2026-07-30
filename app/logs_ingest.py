"""Ingestão incremental de logs para o índice FTS5 (B5).

Roda no loop de fundo, nunca no caminho de um request: montar o índice custa uma
chamada por container ao daemon, e fazer isso quando alguém busca transformaria
a busca numa espera de vários segundos.

**O follow NÃO passa por aqui.** Ele continua direto do daemon, como portado na
Sprint 2a (`modulos/logs.js` → `/containers/{id}/logs/stream`). Gravar o follow
no banco dobraria o I/O para entregar o mesmo que o stream já entrega ao vivo —
a decisão é do bloco B5 original e continua valendo. Este módulo alimenta só a
busca histórica.

A marca d'água por container (`logs_ingest.last_ts`) é o que torna a ingestão
incremental: cada ciclo pede ao daemon apenas o que chegou depois da última
linha vista. Sem ela, cada passada reingeriria o tail inteiro e o índice
encheria de duplicata.
"""

import asyncio
import os
import re
from datetime import datetime, timezone

INTERVALO_S = float(os.getenv("LOGS_INGEST_INTERVAL", "30") or 30)

# Teto por container por ciclo. Um container em crash loop cospe milhares de
# linhas por minuto; sem teto, um único container atrasaria a ingestão de todos
# os outros e o índice viraria o log dele.
TETO_LINHAS = int(os.getenv("LOGS_INGEST_MAX_LINES", "2000") or 2000)

# `docker logs --timestamps` prefixa cada linha com RFC3339Nano + espaço.
_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T[\d:.]+Z?(?:[+-]\d{2}:\d{2})?)\s(.*)$", re.S)

_semaforo = asyncio.Semaphore(3)


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_linhas(texto: str, ts_padrao: str) -> list:
    """Texto do daemon -> [(ts, linha)].

    Linha sem timestamp reconhecível herda o ts da anterior. É o caso do stack
    trace: o daemon carimba a primeira linha do traceback e as continuações
    chegam sem prefixo. Herdar mantém as 40 linhas do traceback com o MESMO ts
    base, que é o que faz `oom` no meio dele ser encontrável e ordenável junto
    com o resto do incidente.
    """
    linhas = []
    ultimo_ts = ts_padrao
    for bruta in (texto or "").split("\n"):
        if not bruta.strip():
            continue
        m = _TS.match(bruta)
        if m:
            ultimo_ts = m.group(1)
            conteudo = m.group(2)
        else:
            conteudo = bruta
        if conteudo.strip():
            linhas.append((ultimo_ts, conteudo.rstrip("\r")))
    return linhas


async def _ingere_um(nome: str) -> int:
    from db import get_log_watermark, insert_log_lines
    from routers._proxy import SOCKET_PROXY

    import httpx

    marca = await get_log_watermark(nome)
    params = {"stdout": 1, "stderr": 1, "timestamps": 1, "tail": TETO_LINHAS}
    if marca:
        # `since` do daemon é exclusivo no segundo, então a última linha do ciclo
        # anterior pode voltar. O filtro por ts abaixo descarta o que já entrou.
        params["since"] = marca

    async with _semaforo:
        async with httpx.AsyncClient(base_url=SOCKET_PROXY, timeout=20) as client:
            r = await client.get(f"/containers/{nome}/logs", params=params)
            if r.status_code >= 400:
                return 0
            bruto = r.content

    # Demux do frame de 8 bytes, igual ao tail que já existe em containers.py.
    partes = []
    idx = 0
    while idx + 8 <= len(bruto):
        tamanho = int.from_bytes(bruto[idx + 4: idx + 8], "big")
        partes.append(bruto[idx + 8: idx + 8 + tamanho].decode("utf-8", errors="replace"))
        idx += 8 + tamanho
    texto = "".join(partes) if partes else bruto.decode("utf-8", errors="replace")

    linhas = parse_linhas(texto, _agora_iso())
    if marca:
        linhas = [(ts, l) for ts, l in linhas if ts > marca]
    if len(linhas) > TETO_LINHAS:
        linhas = linhas[-TETO_LINHAS:]
    return await insert_log_lines(nome, linhas)


async def ciclo() -> dict:
    """Uma passada por todos os containers. Falha em um não para os demais."""
    from routers._proxy import proxy_get

    try:
        lista = await proxy_get("/containers/json?all=1")
    except Exception:
        return {"containers": 0, "linhas": 0}

    total = 0
    vistos = 0
    for c in lista if isinstance(lista, list) else []:
        nomes = c.get("Names") if isinstance(c, dict) else None
        nome = (nomes[0].lstrip("/") if nomes else "") or (c.get("Id") or "")[:12]
        if not nome:
            continue
        vistos += 1
        try:
            total += await _ingere_um(nome)
        except Exception:
            # Mesmo padrão do sampler: container removido no meio do ciclo, ou
            # sem log, não pode interromper a ingestão dos outros.
            continue
    return {"containers": vistos, "linhas": total}


async def ingest_loop(intervalo: float = None):
    espera = intervalo or INTERVALO_S
    while True:
        try:
            await ciclo()
            await asyncio.sleep(espera)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(espera)
