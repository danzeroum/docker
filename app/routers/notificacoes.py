"""GET /api/notifications — o que o motor de notificacoes (B7) entregou.

Existe para a tela poder dizer "notificado hh:mm · canal" ao lado do achado. A
resposta NAO leva a mensagem enviada nem qualquer payload: leva regra, alvo,
instante e os canais que aceitaram. O que a tela precisa e saber que o alerta
saiu, e nao reler o texto dele.
"""

from fastapi import APIRouter

from db import get_notificacoes, get_notificacoes_resumo

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/notifications")
async def listar_notificacoes(limit: int = 100, regra: str = None):
    linhas = await get_notificacoes(limit=limit, regra=regra)
    return {
        "notifications": [
            {
                "regra": l.get("regra"),
                "alvo": l.get("alvo"),
                "ts": l.get("ts"),
                "enviado_em": l.get("enviado_em") or None,
                # Lista e nao string: a tela mostra "· telegram, discord" sem
                # ter de saber por qual separador o servidor juntou.
                "canais": [c for c in (l.get("canais") or "").split(",") if c],
                "falhas": l.get("falhas") or "",
            }
            for l in linhas
        ],
        "summary": await get_notificacoes_resumo(),
    }
