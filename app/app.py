import os
import asyncio
import html
import mimetypes
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from routers._proxy import configure as configure_proxy
from routers.containers import router as containers_router, busca_router as logs_busca_router
from routers.system import router as system_router
from routers.overview import router as overview_router
from routers.findings import router as findings_router
from routers.ingress import router as ingress_router
from routers.projects import router as projects_router
from routers.audit import router as audit_router
from routers.session import router as session_router
from routers.metrics import router as metrics_router
from routers.events import router as events_router
from routers.backend import router as backend_router
from routers.tasks import router as tasks_router
from routers.executive import router as executive_router
from routers.storage import router as storage_router
from routers.security import router as security_router
from routers.prune import router as prune_router
from routers.metrics_prom import router as metrics_prom_router
from routers.updates import router as updates_router
from routers.drift import router as drift_router
from routers.certs import router as certs_router
from routers.notificacoes import router as notificacoes_router
from sampler import sampler_loop
from findings.engine import findings_loop
from db import init_db, close_db
from telemetry import TelemetryMiddleware, flush_telemetry_loop
from events import events_loop
from summary import aquecer_loop
from logs_ingest import ingest_loop
from updates import updates_loop
from notify import despachante_loop, notify_loop
from backup import backup_loop
from compressao import GzipJsonMiddleware
from cache_http import CacheControlMiddleware
from cabecalhos_seguranca import SegurancaHeadersMiddleware, hash_de_estilo, montar_csp

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")

# O `mimetypes` do Python nao conhece .woff2, e o `StaticFiles` cai no default:
# as fontes saiam como `text/plain`. Duas consequencias, as duas medidas aqui:
# o tipo declarado estava errado, e — por casar com `text/plain` — elas entravam
# no gzip, que economizou 7 bytes em 48 256 (WOFF2 ja e Brotli por dentro) e
# cobrou CPU dos dois lados. Registrar o tipo certo resolve as duas de uma vez.
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

SOCKET_PROXY = os.getenv("SOCKET_PROXY", "http://docker-socket-proxy:2375")
ENABLE_TERMINAL = os.getenv("ENABLE_TERMINAL", "").lower() in ("1", "true", "yes")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else []


@asynccontextmanager
def _avisa_se_nginx_ausente():
    """Grita se o nginx.conf do ingress nao estiver onde o codigo procura.

    Sem o arquivo, o parser devolve None, as 11 regras de ingress nunca emitem,
    a tela Ingress & TLS fica vazia e o Resumo executivo nao lista servico
    nenhum — tudo sem erro nenhum no log. Falha silenciosa e o modo de errar
    mais caro deste produto, entao ela deixa de ser silenciosa aqui.
    """
    import logging
    caminho = os.getenv("NGINX_CONFIG_PATH", "/etc/nginx/nginx.conf")
    if os.path.isfile(caminho):
        return
    logging.getLogger(__name__).warning(
        "nginx.conf do ingress nao encontrado em %s — as regras de ingress e a "
        "lista de servicos do Resumo executivo ficarao VAZIAS. Ajuste "
        "NGINX_CONFIG_PATH para o caminho dentro do container (o compose monta "
        "/opt/btv/ingress/nginx em /etc/nginx-ingress).",
        caminho,
    )


async def lifespan(app: FastAPI):
    configure_proxy(SOCKET_PROXY, ENABLE_TERMINAL)
    _avisa_se_nginx_ausente()
    from sampler import take_sample
    await take_sample()
    await init_db()
    interval = float(os.getenv("SAMPLER_INTERVAL", "5"))
    container_interval = float(os.getenv("SAMPLER_CONTAINER_INTERVAL", "10"))
    sampler_task = asyncio.create_task(sampler_loop(interval, container_interval))
    findings_interval = float(os.getenv("FINDINGS_INTERVAL", "10"))
    findings_task = asyncio.create_task(findings_loop(findings_interval))
    events_task = asyncio.create_task(events_loop())
    telemetry_flush_task = asyncio.create_task(flush_telemetry_loop())
    # Aquece os caches que a régua lê. Sem isto, o chip de um módulo oculto
    # nunca teria dado — ninguém dispararia a busca — e o invariante 3 do doc 10
    # ("módulo oculto não oculta o dado") viraria letra morta.
    summary_warm_task = asyncio.create_task(aquecer_loop())
    # Ingestao do indice de busca. Fora do caminho de request: montar o
    # indice custa uma chamada por container ao daemon.
    logs_task = asyncio.create_task(ingest_loop())
    # Job diario de updates. O Hub tem rate limit anonimo apertado; uma VPS
    # com 20 imagens o estoura facil se a consulta virar por request.
    updates_task = asyncio.create_task(updates_loop())
    # Motor de notificacoes (B7), em duas tarefas de proposito: o despachante
    # consome a fila e faz o I/O de rede; o laco de varredura so olha o que nao
    # chega por evento (disco, imagens). Juntar os dois faria uma entrega lenta
    # atrasar a proxima deteccao.
    despachante_task = asyncio.create_task(despachante_loop())
    notify_task = asyncio.create_task(notify_loop())
    # Backup diario pela API de backup do SQLite. `cp` de arquivo quente pega o
    # banco no meio de uma transacao: o arquivo abre e falha depois, que e a
    # pior propriedade possivel num backup.
    backup_task = asyncio.create_task(backup_loop())
    yield
    backup_task.cancel()
    notify_task.cancel()
    despachante_task.cancel()
    updates_task.cancel()
    logs_task.cancel()
    summary_warm_task.cancel()
    sampler_task.cancel()
    findings_task.cancel()
    events_task.cancel()
    telemetry_flush_task.cancel()
    try:
        await sampler_task
    except asyncio.CancelledError:
        pass
    try:
        await findings_task
    except asyncio.CancelledError:
        pass
    try:
        await events_task
    except asyncio.CancelledError:
        pass
    try:
        await telemetry_flush_task
    except asyncio.CancelledError:
        pass
    try:
        await summary_warm_task
    except asyncio.CancelledError:
        pass
    try:
        await logs_task
    except asyncio.CancelledError:
        pass
    try:
        await updates_task
    except asyncio.CancelledError:
        pass
    try:
        await despachante_task
    except asyncio.CancelledError:
        pass
    try:
        await notify_task
    except asyncio.CancelledError:
        pass
    try:
        await backup_task
    except asyncio.CancelledError:
        pass
    await close_db()


app = FastAPI(title="Docker Cockpit", docs_url=None, redoc_url=None, lifespan=lifespan)

# ---------- erro 404 ----------
# Um 404 sem saida e um beco: quem digitou errado, ou seguiu link velho, fica sem
# rota de volta. Mas HTML so serve para quem NAVEGA — cliente de API que pede
# /api/containers/inexistente precisa do JSON de sempre, com o detalhe que a rota
# levantou. Por isso o tratador ramifica pelo caminho em vez de devolver o mesmo
# corpo para os dois; trocar o JSON por HTML aqui quebraria o front do proprio
# cockpit, que le `detail` para mostrar o erro na tela.
_PAGINA_404 = """<!DOCTYPE html>
<html lang="pt-BR" data-tema="cockpit">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Página não encontrada — Cockpit Docker</title>
<link rel="icon" type="image/svg+xml" href="/static/assets/icon.svg">
<link rel="stylesheet" href="/static/css/base.css">
<link rel="stylesheet" href="/static/css/themes.css">
<style>
  .erro-404{min-height:100vh;display:flex;flex-direction:column;align-items:center;
    justify-content:center;gap:1rem;padding:2rem;text-align:center;
    background:var(--bg);color:var(--text)}
  .erro-404 h1{font-size:1.4rem;margin:0}
  .erro-404 p{color:var(--text-mute);margin:0;max-width:38rem;line-height:1.6}
  .erro-404 a{color:var(--accent);font-weight:600}
</style>
</head>
<body>
<main class="erro-404">
  <h1>Esta página não existe</h1>
  <p>O endereço <code>__CAMINHO__</code> não corresponde a nenhuma tela do cockpit.
     Pode ter sido digitado errado, ou ser um link antigo.</p>
  <p><a href="/">Voltar para o cockpit</a></p>
</main>
</body>
</html>
"""


cors_origins = ALLOWED_ORIGINS if ALLOWED_ORIGINS else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.add_middleware(TelemetryMiddleware)

# Declara a politica de cache do que sai. Sem ela, cada navegador e cada proxy
# inventa a propria heuristica a partir do Last-Modified, e "no meu nao
# atualizou" vira comportamento legitimo. As tres faixas e o porque de cada uma
# estao em cache_http.py.
app.add_middleware(CacheControlMiddleware)

# Cabecalhos de seguranca. O CSP e montado com o hash do <style> da pagina 404,
# calculado da MESMA string que e servida — hash escrito a mao viraria mentira no
# dia em que alguem editasse aquele CSS, e o sintoma seria uma 404 sem estilo que
# ninguem ligaria ao CSP. Ver cabecalhos_seguranca.py para o porque de cada
# diretiva, e para o porque de isto morar na app e nao no nginx.
app.add_middleware(
    SegurancaHeadersMiddleware,
    csp=montar_csp((hash_de_estilo(_PAGINA_404),)),
)

# Por ULTIMO, e portanto o mais externo: comprime a resposta final, depois de
# todo mundo ter escrito nela. Compacta por LISTA de content-type — as duas
# rotas que transmitem sao text/event-stream, e gzip num stream poe buffer entre
# o evento acontecer e a tela mostra-lo.
app.add_middleware(GzipJsonMiddleware)


# ---------- health ----------
@app.get("/health")
async def health():
    return {"ok": True}


# ---------- static ----------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """O navegador pede /favicon.ico por conta propria, independente do <link>.

    Servimos o mesmo SVG que o manifest ja declarava, com o content-type certo: o
    navegador segue o tipo declarado, nao a extensao da URL. Melhor um icone servido
    num caminho de nome historico do que um 404 em toda carga de pagina.
    """
    return FileResponse(
        os.path.join(STATIC_DIR, "assets", "icon.svg"),
        media_type="image/svg+xml",
    )




@app.exception_handler(404)
async def nao_encontrado(request: Request, exc):
    if request.url.path.startswith("/api/"):
        detalhe = getattr(exc, "detail", None) or "Not Found"
        return JSONResponse({"detail": detalhe}, status_code=404)
    # escape: o caminho vem do visitante e e ecoado na pagina.
    caminho = html.escape(request.url.path)[:200]
    return HTMLResponse(_PAGINA_404.replace("__CAMINHO__", caminho), status_code=404)


# ---------- routers ----------
app.include_router(containers_router)
app.include_router(logs_busca_router)
app.include_router(system_router)
app.include_router(overview_router)
app.include_router(findings_router)
app.include_router(ingress_router)
app.include_router(projects_router)
app.include_router(audit_router)
app.include_router(session_router)
app.include_router(tasks_router)
app.include_router(executive_router)
app.include_router(metrics_router)
app.include_router(events_router)
app.include_router(backend_router)
app.include_router(storage_router)
app.include_router(security_router)
app.include_router(prune_router)
app.include_router(metrics_prom_router)
app.include_router(updates_router)
app.include_router(drift_router)
app.include_router(certs_router)
app.include_router(notificacoes_router)
