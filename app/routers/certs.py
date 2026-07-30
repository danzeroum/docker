"""GET /api/certs — validade dos certificados (5-certs).

`null` no corpo quando nao ha fonte: diretorio nao montado, ausente ou vazio.
Nao e erro — instalacao sem TLS local e legitima, e a maioria das VPS com
ingress externo e assim. A tela le esse `null` como "nao estou olhando", que e
diferente de "nenhum certificado esta para vencer".
"""

from fastapi import APIRouter

from cache import cached_or_fetch
from certs import calcular

router = APIRouter(prefix="/api", tags=["certs"])


@router.get("/certs")
async def get_certs():
    dados, _stale = await cached_or_fetch("certs", ttl=3600.0, factory=calcular)
    if not dados:
        return {"certs": None, "expiring": None, "window_days": None,
                "motivo": "diretorio de certificados nao montado ou vazio"}
    return dados
