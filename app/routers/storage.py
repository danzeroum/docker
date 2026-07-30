"""Storage e recursos orfaos (B1).

Agrega `/system/df` do socket-proxy e classifica o que da para recuperar:
imagem dangling, volume que ninguem referencia e container parado ha muito
tempo. `/system/df` e a chamada mais cara do daemon (varre imagens, volumes e
build cache em disco), por isso a rota inteira vive atras de um cache de 30 s —
a UI faz polling e nao pode transformar um clique em uma varredura de disco.

O proxy ja concede `SYSTEM: 1` e `VOLUMES: 1` no docker-compose.yml, portanto
este modulo nao pede mudanca nenhuma no socket-proxy.
"""

import asyncio
import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException

from cache import cached_or_fetch
from routers._proxy import proxy_get

router = APIRouter(prefix="/api", tags=["storage"])

# Um container parado ha mais de uma semana nao e "acabei de derrubar para
# testar" — e sobra. Uma semana e o piso a partir do qual a chance de alguem
# ainda estar contando com aquele container fica baixa o suficiente.
DIAS_CONTAINER_ZUMBI = int(os.getenv("ORPHAN_EXITED_DAYS", "7") or 7)

CACHE_TTL_S = 30.0


def _parse_iso(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _idade_em_dias(iso_ts) -> float | None:
    dt = _parse_iso(iso_ts)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def _secao(df: dict, chave: str) -> list:
    """Secao do /system/df como lista, mesmo quando o daemon devolve null.

    O daemon manda `null` (nao `[]`) para secoes vazias — build cache num host
    que nunca construiu imagem, por exemplo. Sem esta normalizacao o `for`
    seguinte estoura com TypeError num host limpo, que e exatamente o caso de
    borda que o aceite cobra.
    """
    valor = df.get(chave)
    return valor if isinstance(valor, list) else []


def _nome_da_imagem(img: dict) -> str:
    tags = img.get("RepoTags")
    if isinstance(tags, list):
        reais = [t for t in tags if t and t != "<none>:<none>"]
        if reais:
            return reais[0]
    return (img.get("Id") or "")[:19]


def _imagem_dangling(img: dict) -> bool:
    """Dangling = sem tag utilizavel.

    RepoTags vem como `null` ou `["<none>:<none>"]` dependendo da versao do
    daemon; as duas formas significam a mesma coisa.
    """
    tags = img.get("RepoTags")
    if not tags:
        return True
    return all((not t) or t == "<none>:<none>" for t in tags)


def _volumes_referenciados(containers: list) -> set:
    """Nomes de volume citados por QUALQUER container, inclusive parados.

    A fonte e `Mounts` de `/containers/json?all=1`, nao o `RefCount` que o
    /system/df devolve: o RefCount do daemon conta referencia viva, e um volume
    preso a um container parado apareceria como orfao — apagar seria perder o
    dado do servico que o operador so desligou.
    """
    referenciados = set()
    for c in containers:
        if not isinstance(c, dict):
            continue
        for m in c.get("Mounts") or []:
            if not isinstance(m, dict):
                continue
            if m.get("Type") == "volume" and m.get("Name"):
                referenciados.add(m["Name"])
    return referenciados


def _monta_payload(df: dict, containers: list) -> dict:
    imagens = _secao(df, "Images")
    volumes = _secao(df, "Volumes")
    build_cache = _secao(df, "BuildCache")
    containers_df = _secao(df, "Containers")

    orphans = []

    # --- imagens dangling ------------------------------------------------
    imagens_bytes = 0
    dangling_bytes = 0
    for img in imagens:
        if not isinstance(img, dict):
            continue
        tamanho = img.get("Size") or 0
        imagens_bytes += tamanho
        if _imagem_dangling(img) and not (img.get("Containers") or 0) > 0:
            dangling_bytes += tamanho
            orphans.append({
                "type": "image",
                "id": img.get("Id") or "",
                "name": _nome_da_imagem(img),
                "size_bytes": tamanho,
                "reason": "imagem sem tag e sem container usando",
                "reason_plain": "Camada de build antiga que nenhuma imagem nomeada aproveita",
            })

    # --- volumes orfaos --------------------------------------------------
    referenciados = _volumes_referenciados(containers)
    volumes_bytes = 0
    volumes_orfaos_bytes = 0
    for vol in volumes:
        if not isinstance(vol, dict):
            continue
        uso = vol.get("UsageData") if isinstance(vol.get("UsageData"), dict) else {}
        tamanho = uso.get("Size") or 0
        # -1 e o "nao calculado" do daemon, nao um volume de tamanho negativo.
        if tamanho < 0:
            tamanho = 0
        volumes_bytes += tamanho
        nome = vol.get("Name") or ""
        if nome and nome not in referenciados:
            volumes_orfaos_bytes += tamanho
            orphans.append({
                "type": "volume",
                "id": nome,
                "name": nome,
                "size_bytes": tamanho,
                "reason": "nenhum container, nem parado, referencia este volume",
                "reason_plain": "Dado guardado que nenhum servico usa mais",
            })

    # --- containers zumbis ----------------------------------------------
    containers_bytes = 0
    for c in containers_df:
        if isinstance(c, dict):
            containers_bytes += c.get("SizeRw") or 0

    zumbis_bytes = 0
    for c in containers:
        if not isinstance(c, dict):
            continue
        if (c.get("State") or "").lower() != "exited":
            continue
        idade = _idade_em_dias(_created_iso(c))
        if idade is None or idade < DIAS_CONTAINER_ZUMBI:
            continue
        tamanho = c.get("SizeRw") or 0
        zumbis_bytes += tamanho
        nomes = c.get("Names") or []
        orphans.append({
            "type": "container",
            "id": c.get("Id") or "",
            "name": (nomes[0].lstrip("/") if nomes else (c.get("Id") or "")[:12]),
            "size_bytes": tamanho,
            "reason": f"parado ha {int(idade)} dias",
            "reason_plain": f"Container desligado ha {int(idade)} dias e nunca religado",
            "days_stopped": int(idade),
        })

    reclaimable = dangling_bytes + volumes_orfaos_bytes + zumbis_bytes
    build_cache_bytes = sum(
        (b.get("Size") or 0) for b in build_cache if isinstance(b, dict)
    )
    build_cache_reclaimable = sum(
        (b.get("Size") or 0)
        for b in build_cache
        if isinstance(b, dict) and not b.get("InUse")
    )

    return {
        "images": {
            "count": len(imagens),
            "size_bytes": imagens_bytes,
            "dangling_count": sum(1 for o in orphans if o["type"] == "image"),
            "dangling_bytes": dangling_bytes,
        },
        "containers": {
            "count": len(containers),
            "size_bytes": containers_bytes,
            "stopped_old_count": sum(1 for o in orphans if o["type"] == "container"),
            "stopped_old_bytes": zumbis_bytes,
        },
        "volumes": {
            "count": len(volumes),
            "size_bytes": volumes_bytes,
            "orphan_count": sum(1 for o in orphans if o["type"] == "volume"),
            "orphan_bytes": volumes_orfaos_bytes,
        },
        "build_cache": {
            "count": len(build_cache),
            "size_bytes": build_cache_bytes,
            "reclaimable_bytes": build_cache_reclaimable,
        },
        # Soma dos orfaos que ESTE modulo classificou. Nao inclui o build cache
        # de proposito: `docker builder prune` e outro comando, com outro risco
        # (invalida cache de build), e somar os dois num numero unico faria a
        # tela prometer espaco que um `image prune` nao entrega.
        "reclaimable_bytes": reclaimable,
        "orphans": sorted(orphans, key=lambda o: -o["size_bytes"]),
        "orphan_exited_days": DIAS_CONTAINER_ZUMBI,
        "cache_ttl_s": CACHE_TTL_S,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _created_iso(c: dict) -> str:
    """`Created` de /containers/json e epoch em segundos, nao ISO."""
    bruto = c.get("Created")
    if isinstance(bruto, (int, float)):
        return datetime.fromtimestamp(bruto, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return str(bruto or "")


@router.get("/storage")
async def get_storage():
    async def factory():
        # /system/df e a chamada pesada; o `all=1` vem do cache compartilhado
        # com /api/containers, entao na pratica so o df sai para o daemon.
        df, (lista, _stale) = await asyncio.gather(
            proxy_get("/system/df", timeout=30),
            cached_or_fetch(
                "containers_list", ttl=2.0, factory=lambda: proxy_get("/containers/json?all=1")
            ),
        )
        if not isinstance(df, dict):
            raise HTTPException(status_code=502, detail="/system/df devolveu payload inesperado")
        return _monta_payload(df, lista if isinstance(lista, list) else [])

    try:
        data, _ = await cached_or_fetch("storage", ttl=CACHE_TTL_S, factory=factory, timeout=40.0)
    except HTTPException:
        raise
    except (httpx.HTTPError, OSError) as exc:
        # Proxy fora do ar e 503 com motivo legivel, nao stacktrace de 500: a
        # tela precisa distinguir "nao consegui perguntar" de "perguntei e o
        # host esta vazio".
        raise HTTPException(
            status_code=503,
            detail=(
                "socket-proxy indisponivel — nao foi possivel ler /system/df "
                f"({type(exc).__name__})"
            ),
        ) from None
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=503,
            detail="socket-proxy nao respondeu /system/df no prazo",
        ) from None
    return data
