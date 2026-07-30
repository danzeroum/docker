"""GET /api/drift — compose declarado x runtime (B8).

Cache de 60s pela mesma razao que o resto da regua: o modulo e o chip leem o
MESMO calculo, e sem cache a tela mostraria dois numeros diferentes para a mesma
pergunta enquanto o poll de 15s corresse.
"""

from fastapi import APIRouter

from cache import cached_or_fetch
from drift import calcular

router = APIRouter(prefix="/api", tags=["drift"])


@router.get("/drift")
async def get_drift():
    dados, _stale = await cached_or_fetch("drift", ttl=60.0, factory=calcular)
    return dados
