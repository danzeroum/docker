import asyncio
from datetime import datetime, timezone
import logging
import time
import platform
import os
import psutil
from stats_util import calc_cpu_percent

_last_sample = None
_container_stats = {}
_container_stats_as_of = None
_last_container_collection = 0.0
_last_persist = 0.0
_rollup_inicial_feito = False

# Duracao MEDIDA da ultima coleta completa. E ela, e nao o intervalo
# configurado, que determina a idade dos numeros na tela — ver
# `_fetch_all_container_stats`. Publicada em /api/overview para a interface
# poder dizer a verdade em vez de "ao vivo" o tempo todo.
_ultimo_ciclo_s = None
_avisou_intervalo = False

# Quantas chamadas ao daemon em paralelo. O semaforo ja existia com o valor 4
# cravado; virou configuravel porque e ELE, e nao `SAMPLER_CONTAINER_INTERVAL`,
# que governa de fato a frequencia de amostragem acima de um punhado de
# containers. O padrao 4 mantem o comportamento anterior — quem quiser encurtar
# o ciclo paga com mais carga simultanea no daemon, e agora essa e uma escolha
# explicita em vez de uma constante escondida.
_CONCORRENCIA_STATS = max(1, int(os.getenv("SAMPLER_STATS_CONCURRENCY", "4")))
_SEM_STATS = asyncio.Semaphore(_CONCORRENCIA_STATS)


def _sample():
    cpu_percent = psutil.cpu_percent(interval=0.0)
    cpu_count = psutil.cpu_count(logical=True)
    load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": round(usage.percent, 1),
            })
        except PermissionError:
            continue

    net_io = psutil.net_io_counters()
    net_if = psutil.net_if_addrs()
    boot_time = psutil.boot_time()
    uptime_seconds = time.time() - boot_time

    warnings = []
    if cpu_percent > 80:
        warnings.append({"level": "warn", "message": f"CPU alta: {cpu_percent:.1f}%"})
    if mem.percent > 85:
        warnings.append({"level": "warn", "message": f"Memoria alta: {mem.percent:.1f}%"})
    if swap.percent > 80:
        warnings.append({"level": "warn", "message": f"Swap alta: {swap.percent:.1f}%"})
    for d in disks:
        if d["percent"] > 90:
            warnings.append({"level": "crit", "message": f"Disco cheio: {d['mountpoint']} ({d['percent']:.1f}%)"})
    if load_avg[0] > cpu_count * 2:
        warnings.append({"level": "warn", "message": f"Load average alto: {load_avg[0]:.2f} (CPUs: {cpu_count})"})

    return {
        "sampled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "cpu": {
            "percent": round(cpu_percent, 1),
            "count": cpu_count,
            "load_1m": round(load_avg[0], 2),
            "load_5m": round(load_avg[1], 2),
            "load_15m": round(load_avg[2], 2),
        },
        "memory": {
            "total": mem.total,
            "used": mem.used,
            "free": mem.available,
            "percent": round(mem.percent, 1),
        },
        "swap": {
            "total": swap.total,
            "used": swap.used,
            "free": swap.free,
            "percent": round(swap.percent, 1),
        },
        "disks": disks,
        "network": {
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv,
            "packets_sent": net_io.packets_sent,
            "packets_recv": net_io.packets_recv,
            "interfaces": {
                name: [addr.address for addr in addrs if addr.family == 2]
                for name, addrs in net_if.items()
            },
        },
        "uptime_seconds": round(uptime_seconds),
        "platform": platform.system(),
        "platform_version": platform.version(),
        "warnings": warnings,
    }


def get_last_sample():
    global _last_sample
    return _last_sample


def get_container_stats():
    return _container_stats, _container_stats_as_of


def get_ciclo_de_stats():
    """Quanto durou a ULTIMA coleta completa, em segundos, e o alvo configurado.

    Acessor proprio em vez de uma terceira posicao em `get_container_stats`: sao
    cinco chamadores desempacotando dois valores, e mexer na aridade quebraria
    todos por uma informacao que so um deles usa.

    A interface precisa dos DOIS numeros para dizer a verdade sem cravar limiar
    no front: a idade so e "atraso" contra o que o servidor de fato consegue
    entregar, e quem sabe isso e o servidor.
    """
    alvo = float(os.getenv("SAMPLER_CONTAINER_INTERVAL", "10"))
    return _ultimo_ciclo_s, alvo

def get_container_inspects():
    return {
        cid: data.get("inspect")
        for cid, data in _container_stats.items()
        if data.get("inspect")
    }


async def take_sample():
    global _last_sample
    _last_sample = await asyncio.to_thread(_sample)
    return _last_sample


async def _fetch_one_container(c):
    from routers._proxy import proxy_get
    c_id = c["Id"]
    try:
        async with _SEM_STATS:
            stats_raw = await proxy_get(f"/containers/{c_id}/stats?stream=false")
        if not isinstance(stats_raw, dict):
            return c_id, None
        cpu_pct = calc_cpu_percent(stats_raw)
        ms = stats_raw.get("memory_stats", {})
        mem_usage = ms.get("usage", 0)
        async with _SEM_STATS:
            insp = await proxy_get(f"/containers/{c_id}/json")
        mem_limit = None
        if isinstance(insp, dict):
            ml = insp.get("HostConfig", {}).get("Memory", 0)
            mem_limit = ml if ml and ml > 0 else None
        return c_id, {
            "cpu_pct": cpu_pct,
            "mem_usage": mem_usage,
            "mem_limit": mem_limit,
            "inspect": insp if isinstance(insp, dict) else None,
        }
    except Exception:
        return c_id, None


async def _fetch_all_container_stats():
    """Coleta stats de todos os containers e MEDE quanto isso custou.

    A duracao nao e curiosidade: ela e o teto real da frequencia de amostragem, e
    por muito tempo ninguem a olhou. Medido nesta bancada, `/stats?stream=false`
    custa ~2,0s por container — inerente a API do daemon, que amostra DUAS vezes
    para calcular delta de CPU. Com o semaforo em 4 e duas chamadas por
    container, o lote leva

        n_containers x 2,0s / SAMPLER_STATS_CONCURRENCY

    o que da ~21s para 42 containers (medido: 19s) e ~50s para 100. O ciclo do
    laco e esse lote MAIS `SAMPLER_INTERVAL` — ou seja, `SAMPLER_CONTAINER_INTERVAL`
    deixa de ser respeitado assim que o lote passa dele, o que acontece por volta
    de oito containers. Um botao que nao obedece e pior que botao nenhum: alguem
    o ajusta, nada muda, e a conclusao vira "o painel e lento" em vez de "o teto
    e outro".

    Por isso a duracao passa a ser publicada (`ultimo_ciclo_s`) e o descompasso
    passa a gritar no log, uma vez por transicao.
    """
    global _container_stats, _container_stats_as_of, _ultimo_ciclo_s
    from routers._proxy import proxy_get
    inicio = time.monotonic()
    try:
        containers_raw = await proxy_get("/containers/json?all=1")
    except Exception:
        return
    tasks = [asyncio.create_task(_fetch_one_container(c)) for c in containers_raw]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for c_id, data in results:
        if isinstance(data, dict):
            _container_stats[c_id] = {**data, "sampled_at": now}
    _container_stats_as_of = now
    _ultimo_ciclo_s = round(time.monotonic() - inicio, 1)
    _avisar_se_o_intervalo_nao_cabe(_ultimo_ciclo_s, len(containers_raw))


def _avisar_se_o_intervalo_nao_cabe(duracao: float, quantos: int) -> None:
    """Grita UMA vez por transicao quando o intervalo configurado nao cabe.

    Mesma politica do aviso de nginx ausente em app.py: a falha silenciosa e o
    modo de errar mais caro deste produto. Aqui o silencio fazia o operador
    acreditar que via numeros de cinco segundos atras enquanto via de trinta.

    Uma vez por TRANSICAO, e nao por ciclo: um aviso a cada 20s vira ruido, e
    ruido no log e a forma mais eficiente de esconder um aviso.
    """
    global _avisou_intervalo
    alvo = float(os.getenv("SAMPLER_CONTAINER_INTERVAL", "10"))
    estourou = duracao > alvo
    if estourou and not _avisou_intervalo:
        logging.getLogger(__name__).warning(
            "a coleta de stats levou %.1fs para %d containers, acima do "
            "SAMPLER_CONTAINER_INTERVAL de %.0fs — o intervalo configurado NAO "
            "esta sendo respeitado, e os numeros de CPU/memoria na tela tem essa "
            "idade. O teto e n_containers x ~2s / SAMPLER_STATS_CONCURRENCY "
            "(hoje %d); a API do daemon amostra duas vezes por chamada de stats. "
            "Para encurtar, aumente SAMPLER_STATS_CONCURRENCY — as custas de mais "
            "carga simultanea no daemon.",
            duracao, quantos, alvo, _CONCORRENCIA_STATS,
        )
    elif not estourou and _avisou_intervalo:
        logging.getLogger(__name__).info(
            "a coleta de stats voltou a caber no intervalo (%.1fs para %d containers)",
            duracao, quantos,
        )
    _avisou_intervalo = estourou


async def _persist_samples():
    global _last_persist
    now = time.monotonic()
    if now - _last_persist < 60:
        return
    _last_persist = now
    sample = _last_sample
    if not sample:
        return
    global _rollup_inicial_feito
    try:
        from db import (
            insert_host_sample,
            insert_container_samples,
            purge_samples,
            purge_events,
            purge_logs,
            rollup_container_samples,
            RETENTION_RAW_HOURS,
        )
        await insert_host_sample(sample)
        if _container_stats:
            await insert_container_samples(_container_stats)
        # Agregar SEMPRE antes de expurgar: purge_samples corta o raw em
        # RETENTION_RAW_HOURS, e o que nao virou linha horaria antes disso
        # desaparece. Na primeira passada a janela e a do raw inteiro, para
        # cobrir as horas em que o cockpit esteve fora do ar.
        if _rollup_inicial_feito:
            await rollup_container_samples()
        else:
            await rollup_container_samples(window_hours=RETENTION_RAW_HOURS)
            _rollup_inicial_feito = True
        await purge_samples()
        # O ring de eventos entra no MESMO ciclo de retenção, não num mecanismo
        # próprio: já existe um lugar que roda a cada 60s e sabe expurgar.
        await purge_events()
        await purge_logs()
    except Exception:
        import traceback
        traceback.print_exc()


async def sampler_loop(interval: float = 5.0, container_interval: float = 10.0):
    global _last_container_collection
    await take_sample()
    await _fetch_all_container_stats()
    await _persist_samples()
    _last_container_collection = time.monotonic()
    while True:
        try:
            now = time.monotonic()
            if now - _last_container_collection >= container_interval:
                await _fetch_all_container_stats()
                _last_container_collection = now
            await take_sample()
            await _persist_samples()
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception:
            import traceback
            traceback.print_exc()
            await asyncio.sleep(interval)
