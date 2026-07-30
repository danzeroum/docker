"""POST /api/prune — remoção de recursos órfãos (B10).

Fecha o ciclo do B1: aquele módulo diz "9.8 GB recuperáveis", este é quem
recupera. Por isso o critério de "órfão" é o MESMO dos dois lados — a lista que
o `dry_run` devolve é a mesma que `/api/storage` mostra, e não uma segunda
opinião que poderia divergir dela.

Três guardas, nesta ordem:
  1. a rota só existe com `ENABLE_ACTIONS` ligado (404, não 403);
  2. `require_unlock` (403 sem sessão destravada);
  3. `dry_run=true` é o PADRÃO — remover exige pedir explicitamente.

Build cache fica fora, coerente com o `reclaimable_bytes` do B1: `builder prune`
é outro comando com outro risco (invalida cache de build), e somar os dois num
número só faria a tela prometer espaço que este endpoint não entrega.
"""

import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from actions import habilitadas as acoes_habilitadas
from auth import require_unlock
from cache import invalidate
from db import audit_concluir, audit_iniciar
from routers._proxy import proxy_post
from routers.storage import get_storage

router = APIRouter(prefix="/api", tags=["prune"])


def _candidatos(storage: dict) -> list:
    """Só imagens dangling. Volume órfão e container parado ficam de fora.

    Não é timidez: volume órfão guarda DADO, e um container parado há 8 dias
    pode ser o que alguém vai religar na segunda. Imagem dangling é a única
    categoria em que "recuperar" não pode destruir nada que não se reconstrua.
    Remover volume precisa de um pedido próprio, explícito, que este bloco não
    oferece de propósito.
    """
    orfaos = storage.get("orphans") or []
    return [o for o in orfaos if isinstance(o, dict) and o.get("type") == "image"]


if acoes_habilitadas():

    @router.post("/prune")
    async def prune(
        request: Request,
        session: dict = Depends(require_unlock),
        dry_run: bool = Query(True, description="padrão true: lista sem remover"),
    ):
        ip = request.client.host if request.client else ""
        ator = session.get("remote_user") or "—"
        acao = "prune_dry_run" if dry_run else "prune"

        # Auditar ANTES, inclusive o dry_run: saber quem consultou o que dá para
        # remover é parte do rastro, e é a consulta que precede toda remoção.
        audit_id = await audit_iniciar(acao, "images", ator, ip)

        try:
            storage = await get_storage()
        except HTTPException as exc:
            await audit_concluir(audit_id, f"error: {exc.status_code} {exc.detail}", status="error")
            raise
        except (httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
            await audit_concluir(audit_id, f"error: {type(exc).__name__}", status="error")
            raise HTTPException(
                status_code=503,
                detail="socket-proxy indisponivel — nao foi possivel listar candidatos",
            ) from None

        candidatos = _candidatos(storage)
        total = sum(c.get("size_bytes") or 0 for c in candidatos)

        if dry_run:
            await audit_concluir(audit_id, f"dry_run: {len(candidatos)} imagem(ns), {total} bytes")
            return {
                "dry_run": True,
                "candidates": candidatos,
                "count": len(candidatos),
                "reclaimable_bytes": total,
                "removed_bytes": 0,
                "note": "nada foi removido; repita com dry_run=false para executar",
            }

        try:
            # `dangling=true` no filtro do daemon: mesmo critério da lista acima.
            # Sem ele, `/images/prune` remove TODA imagem sem container usando —
            # inclusive as taggeadas que a stack parada vai precisar ao subir.
            resultado = await proxy_post(
                "/images/prune",
                params={"filters": '{"dangling":{"true":true}}'},
                timeout=120,
            )
        except HTTPException as exc:
            await audit_concluir(audit_id, f"error: {exc.status_code} {exc.detail}", status="error")
            raise
        except Exception as exc:
            await audit_concluir(audit_id, f"error: {exc}", status="error")
            raise

        liberado = 0
        removidas = []
        if isinstance(resultado, dict):
            liberado = resultado.get("SpaceReclaimed") or 0
            for item in resultado.get("ImagesDeleted") or []:
                if isinstance(item, dict):
                    removidas.append(item.get("Deleted") or item.get("Untagged") or "")

        # O storage cacheado ficou desatualizado no instante da remoção.
        invalidate("storage")

        await audit_concluir(audit_id, f"success: {len(removidas)} removida(s), {liberado} bytes")
        return {
            "dry_run": False,
            "candidates": candidatos,
            "count": len(candidatos),
            "reclaimable_bytes": total,
            "removed": removidas,
            "removed_bytes": liberado,
        }
