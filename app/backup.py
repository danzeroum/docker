"""Backup diário do SQLite pela API de backup do próprio SQLite (B11).

`cp` de um arquivo quente é o modo errado, e não por teoria: o sampler escreve
continuamente, e uma cópia byte a byte pega o arquivo no meio de uma transação —
o WAL num ponto, o `.db` em outro. O resultado abre normalmente e falha de forma
arbitrária depois, que é a pior propriedade possível num backup: ele parece
existir até a hora em que alguém precisa dele.

`sqlite3.Connection.backup()` é a API de backup online. Ela copia página a
página segurando o bloqueio certo, e o destino é sempre um banco consistente,
mesmo com escrita acontecendo durante a cópia inteira.

Rotação por CONTAGEM, 7 cópias. Sete porque o problema que este backup resolve é
"alguém apagou/corrompeu algo e ninguém percebeu no mesmo dia" — uma semana é a
janela em que isso costuma aparecer, e mais do que isso consome disco de VPS
para proteger de um cenário que o backup diário nunca cobriu de verdade.
"""

import asyncio
import glob
import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DIR_BACKUP = os.getenv("BACKUP_DIR", "/data/backups")
MANTER = int(os.getenv("BACKUP_KEEP", "7") or 7)
INTERVALO_S = float(os.getenv("BACKUP_INTERVAL", str(24 * 3600)) or 24 * 3600)

_PREFIXO = "cockpit-"
_SUFIXO = ".db"


def _origem() -> str:
    return os.getenv("COCKPIT_DB", "/data/cockpit.db")


def _carimbo() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def rotaciona(diretorio: str = None, manter: int = None) -> list[str]:
    """Apaga os mais antigos além do teto. Devolve o que foi apagado.

    Por nome e não por mtime: o nome carrega o instante em que o backup foi
    FEITO, e o mtime muda se alguém copiar os arquivos para outro lugar — o que
    é exatamente o que se faz com backup.
    """
    raiz = diretorio or DIR_BACKUP
    teto = MANTER if manter is None else manter
    arquivos = sorted(glob.glob(os.path.join(raiz, f"{_PREFIXO}*{_SUFIXO}")))
    excedente = arquivos[:-teto] if teto > 0 else arquivos
    apagados = []
    for caminho in excedente:
        try:
            os.remove(caminho)
            apagados.append(caminho)
        except OSError as exc:
            logger.warning("backup: nao removi %s (%s)", os.path.basename(caminho),
                           type(exc).__name__)
    return apagados


def _copia(origem: str, destino: str):
    """A cópia em si. Síncrona de propósito — quem chama põe numa thread."""
    origem_conn = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    try:
        destino_conn = sqlite3.connect(destino)
        try:
            origem_conn.backup(destino_conn)
        finally:
            destino_conn.close()
    finally:
        origem_conn.close()


def fazer_backup_sync(diretorio: str = None, origem: str = None, manter: int = None) -> dict:
    raiz = diretorio or DIR_BACKUP
    fonte = origem or _origem()
    if not os.path.exists(fonte):
        return {"ok": False, "erro": "banco de origem ausente", "arquivo": ""}

    try:
        os.makedirs(raiz, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "erro": f"diretorio ({type(exc).__name__})", "arquivo": ""}

    destino = os.path.join(raiz, f"{_PREFIXO}{_carimbo()}{_SUFIXO}")
    try:
        _copia(fonte, destino)
    except (sqlite3.Error, OSError) as exc:
        # Parcial é pior que ausente: um arquivo truncado com nome de backup é
        # o que faz alguém achar que tem cópia.
        try:
            os.remove(destino)
        except OSError:
            pass
        return {"ok": False, "erro": f"{type(exc).__name__}", "arquivo": ""}

    apagados = rotaciona(raiz, manter)
    return {"ok": True, "erro": "", "arquivo": destino, "rotacionados": len(apagados)}


async def fazer_backup(diretorio: str = None, origem: str = None, manter: int = None) -> dict:
    return await asyncio.to_thread(fazer_backup_sync, diretorio, origem, manter)


async def backup_loop(intervalo: float = None):
    espera = intervalo or INTERVALO_S
    while True:
        try:
            r = await fazer_backup()
            if not r["ok"]:
                logger.warning("backup diario falhou: %s", r["erro"])
            await asyncio.sleep(espera)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(espera)
