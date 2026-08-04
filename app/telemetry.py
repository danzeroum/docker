import asyncio
import time
import uuid
from datetime import datetime, timezone

_histogram: dict = {}
_last_flush: float = 0

# Cabecalhos de correlacao que um proxy pode ter posto na frente. Lidos NESTA
# ordem, e o primeiro presente vence.
#
# Reaproveitar em vez de gerar e o ponto: quem esta na borda ja carimbou a
# requisicao, e um id novo aqui cortaria a corrente exatamente onde ela serve —
# o operador ficaria com dois identificadores para o mesmo evento e nenhum que
# ligue os dois lados. `traceparent` vem primeiro por ser o padrao (W3C Trace
# Context), que e o que um coletor de tracing vai procurar.
_ENTRADAS_DE_CORRELACAO = (b"traceparent", b"x-request-id", b"x-correlation-id")

# Teto de tamanho do id herdado. O valor vem de fora e e ecoado no cabecalho de
# resposta; sem corte, um proxy mal configurado (ou alguem testando) injeta
# kilobytes que voltam para todo cliente. `traceparent` do W3C tem 55 caracteres.
_MAX_ID = 200


def _sanear(bruto: bytes) -> str:
    """So o que cabe num cabecalho HTTP, e curto.

    Um id de correlacao e eco de entrada do usuario. Deixar passar CR/LF seria
    permitir injecao de cabecalho na resposta; deixar passar qualquer byte alto
    quebraria o encode latin-1 do ASGI. Sobra o imprimivel ASCII, cortado.
    """
    texto = bruto.decode("latin-1", "ignore")
    limpo = "".join(c for c in texto if 32 <= ord(c) < 127)
    return limpo.strip()[:_MAX_ID]


def id_de_correlacao(scope) -> str:
    """Devolve o id da borda, se houver, ou cria um. Nunca vazio."""
    for nome, valor in scope.get("headers") or []:
        if nome in _ENTRADAS_DE_CORRELACAO:
            limpo = _sanear(valor)
            if limpo:
                return limpo
    return uuid.uuid4().hex


class TelemetryMiddleware:
    """Mede a duracao por rota — e carimba a requisicao com um id de correlacao.

    Sem o id, rastrear um incidente entre o nginx do ingress, esta app e o daemon
    e arqueologia: tres logs sem nada em comum alem do relogio. Com ele, um `grep`
    liga os tres. E o mesmo motivo de a regua listar isso como sinal de
    maturidade — nao muda o que a app faz, muda o que da para descobrir depois.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.monotonic()
        status = [200]
        correlacao = id_de_correlacao(scope)
        # Guardado no scope para que rota e log possam citar o MESMO id.
        scope["id_correlacao"] = correlacao

        async def _send(event):
            if event["type"] == "http.response.start":
                status[0] = event.get("status", 200)
                cabecalhos = list(event.get("headers") or [])
                if not any(n.lower() == b"x-request-id" for n, _ in cabecalhos):
                    cabecalhos.append((b"x-request-id", correlacao.encode("latin-1")))
                event["headers"] = cabecalhos
            await send(event)

        try:
            await self.app(scope, receive, _send)
        except Exception:
            status[0] = 500
            raise
        finally:
            dur = time.monotonic() - start
            route = scope.get("route", None)
            if route:
                route_tpl = getattr(route, "path", None) or getattr(route, "name", "") or scope.get("path", "?")
            else:
                path = scope.get("path", "?")
                route_tpl = path
            key = f"{scope.get('method', '?')} {route_tpl}"
            _histogram.setdefault(key, []).append((dur, status[0]))


async def flush_telemetry_loop():
    global _last_flush
    while True:
        try:
            await asyncio.sleep(3600)
            hist_copy = _histogram.copy()
            _histogram.clear()
            if hist_copy:
                from db import flush_telemetry
                await flush_telemetry(hist_copy)
        except asyncio.CancelledError:
            if _histogram:
                from db import flush_telemetry
                await flush_telemetry(_histogram)
                _histogram.clear()
            break
        except Exception:
            import traceback
            traceback.print_exc()


def get_histogram_snapshot():
    return dict(_histogram)
