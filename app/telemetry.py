import asyncio
import time
from datetime import datetime, timezone

_histogram: dict = {}
_last_flush: float = 0


class TelemetryMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.monotonic()
        status = [200]

        async def _send(event):
            if event["type"] == "http.response.start":
                status[0] = event.get("status", 200)
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
