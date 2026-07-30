"""GET /api/updates — imagens desatualizadas (B6).

Le do banco, nunca do Hub: a consulta externa e do job diario. Uma rota que
consultasse o Hub por request estouraria o rate limit anonimo no primeiro
polling da tela.
"""

from fastapi import APIRouter

from db import get_image_updates, get_updates_resumo

router = APIRouter(prefix="/api", tags=["updates"])


@router.get("/updates")
async def listar_updates():
    linhas = await get_image_updates()
    resumo = await get_updates_resumo()
    return {
        "images": linhas,
        "count": len(linhas),
        # `summary` None significa que o job nunca rodou — a tela usa isso para
        # nao mostrar badge nenhum, em vez de mostrar "0 desatualizadas".
        "summary": resumo,
    }
