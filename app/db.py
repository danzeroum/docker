import hashlib
import os
import re
import secrets
import aiosqlite
from datetime import datetime, timedelta, timezone

_DB_PATH = os.getenv("COCKPIT_DB", "/data/cockpit.db")
_connection = None

# TTL da sessao de destravamento (F5). Unico lugar que define os 30 min.
UNLOCK_TTL_SECONDS = 1800


def _env_int(nome: str, padrao: int, minimo: int) -> int:
    """Env numerica com piso. Valor ilegivel volta ao padrao em vez de explodir.

    Retencao entra por env, mas um `RETENTION_RAW_HOURS=0` num .env mal editado
    apagaria a serie inteira no primeiro ciclo do coletor. O piso e o que
    impede uma variavel de ambiente de virar perda de dado.
    """
    try:
        valor = int(os.getenv(nome, "") or padrao)
    except (TypeError, ValueError):
        return padrao
    return max(minimo, valor)


# Retencao de container_samples em dois niveis (v10). host_samples segue em 30 d
# de raw porque e a fonte da projecao por minimos quadrados da F4.
RETENTION_RAW_HOURS = _env_int("RETENTION_RAW_HOURS", 24, 1)
RETENTION_ROLLUP_DAYS = _env_int("RETENTION_ROLLUP_DAYS", 30, 1)
RETENTION_HOST_DAYS = _env_int("RETENTION_HOST_DAYS", 30, 7)

# Teto de pontos por resposta de historico. A tela desenha sparkline; mandar
# 1440 pontos para 200 px de largura gasta banda e nao muda um pixel.
MAX_HISTORY_POINTS = 500

# Teto de linhas por leitura de log. Vizinho do de cima pelo mesmo motivo — os
# dois sao teto de RESPOSTA e nao de armazenamento — mas este tem uma segunda
# razao, e ela nao e banda.
#
# Log e stdout de aplicacao de terceiro: o cockpit nao decide o que entra ali, e
# dado pessoal chega sem ninguem ter coletado. Mascarar nao resolve, porque nao
# ha chave para casar em texto livre e adivinhar produz falso negativo silencioso
# — o que sobra e reduzir o que se expoe de uma vez.
#
# O valor antigo era `min(tail, 5000)` embutido no handler, com o parametro
# pedindo 500 por padrao: o pior caso por requisicao era dez vezes o caso comum,
# e o numero nao aparecia em lugar nenhum que alguem revisasse. Agora e declarado,
# entra por env como as retencoes, e o piso do _env_int impede que um .env mal
# editado o zere.
#
# Quem precisa de mais para depurar sobe a variavel deliberadamente.
LOG_TAIL_MAX = _env_int("LOG_TAIL_MAX", 500, 1)

def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def _parse_iso(value):
    """ISO com Z ou offset -> datetime aware. None se ilegivel."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None

def _hash_token(token: str) -> str:
    """So o hash vai para o banco — vazamento do arquivo nao devolve token usavel."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def _parse_row(row, desc):
    if row is None:
        return None
    cols = [d[0] for d in desc]
    return dict(zip(cols, row))

def _parse_rows(rows, desc):
    cols = [d[0] for d in desc]
    return [dict(zip(cols, r)) for r in rows]

async def get_db():
    global _connection
    if _connection is None:
        _connection = await aiosqlite.connect(_DB_PATH)
        _connection.row_factory = aiosqlite.Row
        await _connection.execute("PRAGMA journal_mode=WAL")
        await _connection.execute("PRAGMA foreign_keys=ON")
    return _connection

_MIGRATIONS = [
    (1, [
        "CREATE TABLE IF NOT EXISTS findings ("
        "id TEXT PRIMARY KEY,"
        "rule TEXT NOT NULL,"
        "target TEXT NOT NULL,"
        "scope TEXT NOT NULL,"
        "severity TEXT NOT NULL,"
        "score INTEGER NOT NULL,"
        "caused_by TEXT,"
        "status TEXT NOT NULL DEFAULT 'open',"
        "ack_reason TEXT,"
        "ack_note TEXT,"
        "ack_until TEXT,"
        "first_seen TEXT NOT NULL,"
        "last_seen TEXT NOT NULL,"
        "resolved_at TEXT,"
        "occurrences INTEGER NOT NULL DEFAULT 1,"
        "payload TEXT NOT NULL"
        ")",
        "CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status, score DESC)",
    ]),
    (2, [
        "ALTER TABLE findings ADD COLUMN targets TEXT",
    ]),
    (3, [
        "CREATE TABLE IF NOT EXISTS findings_v3 ("
        "id TEXT PRIMARY KEY,"
        "rule TEXT NOT NULL,"
        "target TEXT,"
        "targets TEXT,"
        "scope TEXT NOT NULL,"
        "severity TEXT NOT NULL,"
        "score INTEGER NOT NULL,"
        "caused_by TEXT,"
        "status TEXT NOT NULL DEFAULT 'open',"
        "ack_reason TEXT,"
        "ack_note TEXT,"
        "ack_until TEXT,"
        "first_seen TEXT NOT NULL,"
        "last_seen TEXT NOT NULL,"
        "resolved_at TEXT,"
        "occurrences INTEGER NOT NULL DEFAULT 1,"
        "payload TEXT NOT NULL"
        ")",
        "INSERT OR IGNORE INTO findings_v3 "
        "(id, rule, target, scope, severity, score, caused_by, status, "
        "ack_reason, ack_note, ack_until, first_seen, last_seen, "
        "resolved_at, occurrences, payload) "
        "SELECT id, rule, target, scope, severity, score, caused_by, "
        "status, ack_reason, ack_note, ack_until, first_seen, last_seen, "
        "resolved_at, occurrences, payload FROM findings",
        "DROP TABLE findings",
        "ALTER TABLE findings_v3 RENAME TO findings",
        "CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status, score DESC)",
    ]),
    (4, [
        "CREATE TABLE IF NOT EXISTS audit_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "action TEXT NOT NULL,"
        "project TEXT NOT NULL,"
        "result TEXT NOT NULL,"
        "token_label TEXT NOT NULL DEFAULT '',"
        "ip TEXT NOT NULL DEFAULT '',"
        "created_at TEXT NOT NULL"
        ")",
    ]),
    (5, [
        "CREATE TABLE IF NOT EXISTS unlock_state ("
        "token TEXT PRIMARY KEY,"
        "remote_user TEXT NOT NULL DEFAULT '',"
        "ip TEXT NOT NULL DEFAULT '',"
        "motivo TEXT NOT NULL DEFAULT '',"
        "created_at TEXT NOT NULL"
        ")",
    ]),
    (6, [
        "CREATE TABLE IF NOT EXISTS host_samples ("
        "sampled_at TEXT PRIMARY KEY,"
        "cpu_pct REAL NOT NULL,"
        "mem_pct REAL NOT NULL,"
        "mem_used INTEGER NOT NULL,"
        "mem_total INTEGER NOT NULL,"
        "disk_pct REAL NOT NULL,"
        "swap_pct REAL NOT NULL DEFAULT 0"
        ")",
        "CREATE TABLE IF NOT EXISTS container_samples ("
        "sampled_at TEXT NOT NULL,"
        "container_id TEXT NOT NULL,"
        "name TEXT NOT NULL,"
        "cpu_pct REAL NOT NULL DEFAULT 0,"
        "mem_usage INTEGER NOT NULL DEFAULT 0,"
        "mem_limit INTEGER,"
        "PRIMARY KEY (sampled_at, container_id)"
        ")",
    ]),
    (7, [
        "CREATE TABLE IF NOT EXISTS api_telemetry ("
        "route TEXT NOT NULL,"
        "hour TEXT NOT NULL,"
        "total INTEGER NOT NULL DEFAULT 0,"
        "errors INTEGER NOT NULL DEFAULT 0,"
        "durations_total REAL NOT NULL DEFAULT 0,"
        "durations_squared REAL NOT NULL DEFAULT 0,"
        "durations_max REAL NOT NULL DEFAULT 0,"
        "PRIMARY KEY (route, hour)"
        ")",
    ]),
    # v8 — unlock_state deixa de ser chaveada pelo token em texto claro.
    # As linhas antigas sao chaveadas pelo UNLOCK_TOKEN estatico: carrega-las
    # para a frente preservaria exatamente a credencial que esta migracao revoga.
    # Por isso a tabela e recriada VAZIA, de proposito — nao e perda acidental
    # de dado (cf. v3/v5 e first_seen). Janela aberta no deploy fecha; o
    # operador refaz o unlock e a linha nova ja nasce com usuario e prazo.
    (8, [
        "DROP TABLE IF EXISTS unlock_state",
        "CREATE TABLE unlock_state ("
        "token_hash TEXT PRIMARY KEY,"
        "remote_user TEXT NOT NULL DEFAULT '',"
        "ip TEXT NOT NULL DEFAULT '',"
        "motivo TEXT NOT NULL DEFAULT '',"
        "created_at TEXT NOT NULL,"
        "expires_at TEXT NOT NULL"
        ")",
        "CREATE INDEX IF NOT EXISTS idx_unlock_expires ON unlock_state(expires_at)",
    ]),
    # v9 — tarefas (board do diagnostico).
    # `origem` e COLUNA, nao inferida de finding_id IS NULL: uma tarefa manual
    # pode legitimamente apontar para um achado, e e `origem` que decide se o
    # motor tem permissao de mover o cartao.
    (9, [
        "CREATE TABLE IF NOT EXISTS tasks ("
        "id TEXT PRIMARY KEY,"
        "title TEXT NOT NULL,"
        "detail TEXT NOT NULL DEFAULT '',"
        "col TEXT NOT NULL DEFAULT 'todo',"
        "origem TEXT NOT NULL DEFAULT 'manual',"
        "finding_id TEXT,"
        "target TEXT,"
        "owner TEXT NOT NULL DEFAULT '',"
        "due TEXT,"
        "note TEXT NOT NULL DEFAULT '',"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL"
        ")",
        "CREATE INDEX IF NOT EXISTS idx_tasks_col ON tasks(col, updated_at DESC)",
        # No maximo UM cartao automatico por achado. E o que impede o ciclo de
        # 10 s do motor de duplicar cartao a cada reabertura.
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_auto_finding "
        "ON tasks(finding_id) WHERE origem = 'auto'",
    ]),
    # v10 — retencao em dois niveis para container_samples.
    #
    # A PK (sampled_at, container_id) da v6 serve a escrita e o purge por
    # tempo, mas NAO serve a leitura por container: perguntar "historico do
    # container X" com ela varre a tabela inteira. Dai o indice invertido.
    #
    # A tabela horaria existe porque raw a cada 60 s por 30 dias sao ~43 mil
    # linhas POR container — o banco cresce justamente no disco que o
    # /api/storage monitora. Raw agora vive 24 h (RETENTION_RAW_HOURS) e o
    # que passa disso sobrevive agregado por hora (RETENTION_ROLLUP_DAYS).
    #
    # host_samples fica de fora de proposito: e a fonte da projecao de disco
    # da F4, que precisa de 30 dias de serie para rodar minimos quadrados.
    # Cortar o raw dela em 24 h mataria /api/metrics/history sem erro nenhum.
    (10, [
        "CREATE INDEX IF NOT EXISTS idx_container_samples_cid "
        "ON container_samples(container_id, sampled_at)",
        "CREATE TABLE IF NOT EXISTS container_samples_hourly ("
        "hour TEXT NOT NULL,"
        "container_id TEXT NOT NULL,"
        "name TEXT NOT NULL DEFAULT '',"
        "cpu_pct_avg REAL NOT NULL DEFAULT 0,"
        "cpu_pct_max REAL NOT NULL DEFAULT 0,"
        "mem_usage_avg INTEGER NOT NULL DEFAULT 0,"
        "mem_usage_max INTEGER NOT NULL DEFAULT 0,"
        "mem_limit INTEGER,"
        "samples INTEGER NOT NULL DEFAULT 0,"
        "PRIMARY KEY (hour, container_id)"
        ")",
        "CREATE INDEX IF NOT EXISTS idx_csh_cid "
        "ON container_samples_hourly(container_id, hour)",
    ]),
    # v11 — timeline de eventos do daemon (B3).
    #
    # O stream `/events` ja existia e ja alimentava o SSE; o que faltava era
    # sobreviver a um restart do cockpit. Sem persistencia, a pergunta "esse
    # container reiniciou quantas vezes hoje?" so tinha resposta se alguem
    # estivesse com a aba aberta na hora.
    #
    # `id` AUTOINCREMENT em vez de chave por timestamp: o daemon emite varios
    # eventos no mesmo segundo (die + stop + start de um restart chegam juntos),
    # e uma PK temporal descartaria justamente a sequencia que a timeline existe
    # para mostrar. O AUTOINCREMENT tambem da o corte do ring de graca.
    #
    # Os indices sao os dois eixos da tela: filtro por container e filtro por
    # tipo de acao, ambos sempre em ordem cronologica reversa.
    (11, [
        "CREATE TABLE IF NOT EXISTS docker_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ts TEXT NOT NULL,"
        "type TEXT NOT NULL DEFAULT '',"
        "action TEXT NOT NULL DEFAULT '',"
        "actor_id TEXT NOT NULL DEFAULT '',"
        "actor_name TEXT NOT NULL DEFAULT '',"
        "stack TEXT NOT NULL DEFAULT '',"
        "exit_code TEXT NOT NULL DEFAULT '',"
        "severity TEXT NOT NULL DEFAULT 'info'"
        ")",
        "CREATE INDEX IF NOT EXISTS idx_events_ts ON docker_events(id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_events_actor ON docker_events(actor_name, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_events_action ON docker_events(action, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_events_stack ON docker_events(stack, id DESC)",
    ]),
    # v12 — auditoria gravada ANTES de executar (B10).
    #
    # Ate aqui `_mutate_container` chamava `add_audit_entry` DEPOIS do proxy
    # retornar, ou no except. Isso perde exatamente o caso grave: acao que trava
    # o daemon nao gera linha nenhuma, e o incidente fica sem rastro de quem
    # pediu o que. Auditar depois audita o que deu certo.
    #
    # `started_at` e `finished_at` sao colunas NOVAS; `created_at` fica onde
    # esta, com os dados antigos intactos. As linhas anteriores a esta migracao
    # tem `started_at` NULL de proposito: elas nasceram no modelo antigo e
    # afirmar um inicio que ninguem mediu seria inventar dado. `status` nasce
    # 'done' para elas, porque toda linha antiga so existia se a acao terminou.
    (12, [
        "ALTER TABLE audit_log ADD COLUMN status TEXT NOT NULL DEFAULT 'done'",
        "ALTER TABLE audit_log ADD COLUMN started_at TEXT",
        "ALTER TABLE audit_log ADD COLUMN finished_at TEXT",
        "CREATE INDEX IF NOT EXISTS idx_audit_status ON audit_log(status, id DESC)",
    ]),
    # v13 — busca full-text em logs (B5).
    #
    # FTS5 externo-conteudo NAO: a tabela `logs_fts` guarda o texto ela mesma.
    # Conteudo externo economizaria espaco, mas exigiria uma tabela espelho e
    # triggers de sincronia — mais peca para manter do que o ganho justifica
    # numa VPS com retencao de 7 dias.
    #
    # `container` e `ts` sao UNINDEXED: entram como coluna para voltarem no
    # resultado, mas nao viram termo de busca. Sem isso, procurar "api" acharia
    # toda linha do container chamado api, e a busca por texto viraria busca por
    # nome — que ja e o filtro, nao a pergunta.
    #
    # `tokenize=porter unicode61`: log tem acento (mensagem em portugues) e o
    # operador digita "erro" esperando achar "erros".
    (13, [
        "CREATE VIRTUAL TABLE IF NOT EXISTS logs_fts USING fts5("
        "  linha,"
        "  container UNINDEXED,"
        "  ts UNINDEXED,"
        "  stream UNINDEXED,"
        "  tokenize='porter unicode61'"
        ")",
        # Marca d'agua por container: de onde continuar a ingestao. Tabela
        # comum, nao FTS — e chave-valor, e FTS5 nao tem indice unico.
        "CREATE TABLE IF NOT EXISTS logs_ingest ("
        "container TEXT PRIMARY KEY,"
        "last_ts TEXT NOT NULL DEFAULT '',"
        "last_run TEXT NOT NULL DEFAULT '',"
        "linhas INTEGER NOT NULL DEFAULT 0"
        ")",
    ]),
    # v14 — verificacao de imagem desatualizada (B6).
    #
    # Persistido, e nao so cache em memoria, por duas razoes: o job roda uma vez
    # por dia e um restart do cockpit nao pode zerar o resultado (a UI ficaria
    # sem badge ate a manha seguinte), e o `summary` le daqui via cache quente,
    # como as outras chaves.
    #
    # `consultado_em` e coluna, nao derivado: a idade do dado E o dado quando a
    # fonte e uma API externa com rate limit. Um "desatualizada" de tres dias
    # atras nao e a mesma afirmacao que um de agora.
    (14, [
        "CREATE TABLE IF NOT EXISTS image_updates ("
        "image TEXT PRIMARY KEY,"          # repo:tag como aparece no RepoTag
        "namespace TEXT NOT NULL DEFAULT '',"
        "repo TEXT NOT NULL DEFAULT '',"
        "tag TEXT NOT NULL DEFAULT '',"
        "digest_local TEXT NOT NULL DEFAULT '',"
        "digest_remoto TEXT NOT NULL DEFAULT '',"
        "status TEXT NOT NULL DEFAULT 'desconhecido',"
        "remoto_em TEXT NOT NULL DEFAULT '',"   # last_updated da tag no Hub
        "consultado_em TEXT NOT NULL DEFAULT '',"
        "erro TEXT NOT NULL DEFAULT ''"
        ")",
        "CREATE INDEX IF NOT EXISTS idx_updates_status ON image_updates(status)",
    ]),
    # v15 — historico de notificacoes (B7).
    #
    # A tabela existe por causa do DEDUP, e nao para virar relatorio. Dedup em
    # memoria some no restart, e o restart e exatamente o momento em que tudo
    # reavalia ao mesmo tempo: o cockpit reconecta ao stream, o sampler colhe a
    # primeira amostra e o job de imagens roda — tres regras disparando juntas
    # para fatos que ja tinham sido notificados antes de o processo cair.
    #
    # `enviado_em` vazio significa "nenhum canal aceitou". Distinguir isso de
    # entregue e o que impede o dedup de silenciar um alerta que o operador
    # nunca recebeu: falha total nao inicia a janela de 30 min.
    (15, [
        "CREATE TABLE IF NOT EXISTS notificacoes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "regra TEXT NOT NULL,"
        "alvo TEXT NOT NULL DEFAULT '',"
        "ts TEXT NOT NULL,"                      # quando o fato aconteceu
        "enviado_em TEXT NOT NULL DEFAULT '',"   # vazio = nenhum canal aceitou
        "canais TEXT NOT NULL DEFAULT '',"       # canais que aceitaram
        "falhas TEXT NOT NULL DEFAULT '',"       # canal:motivo curto, sem segredo
        "detalhe TEXT NOT NULL DEFAULT ''"       # texto humano, nunca payload bruto
        ")",
        "CREATE INDEX IF NOT EXISTS idx_notif_dedup "
        "ON notificacoes(regra, alvo, enviado_em)",
    ]),
]

# Versao de esquema no topo da lista. Os testes de migracao conferem "banco
# totalmente migrado" contra isto em vez de um numero literal — a v9 quebrou
# quatro testes de uma vez so por estarem escritos como `== 9`.
SCHEMA_VERSION = _MIGRATIONS[-1][0]

async def init_db():
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    cur = await db.execute("SELECT MAX(version) FROM schema_version")
    row = await cur.fetchone()
    current = row[0] if row and row[0] else 0
    for ver, stmts in _MIGRATIONS:
        if ver > current:
            for stmt in stmts:
                await db.execute(stmt)
            await db.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (ver, _now()),
            )
    await db.commit()

async def close_db():
    global _connection
    if _connection:
        await _connection.close()
        _connection = None

async def upsert_finding(finding: dict) -> str:
    """Devolve o que aconteceu: "created", "reopened" ou "updated".

    Achado observado de novo REABRE, sempre. A janela de 30 min decide se e o
    mesmo incidente ou um novo, nao se ele volta para a fila:

    - reaberto em menos de 30 min: oscilacao do mesmo problema, `first_seen`
      preservado — a duracao continua contando de quando comecou.
    - reaberto depois disso: incidente novo, `first_seen` recomeca. Dizer que o
      problema existe "desde ha duas semanas" quando ele ficou resolvido no meio
      inventa uma duracao que nunca houve.

    Antes daqui, passados os 30 min o achado caia no UPDATE de baixo, que mexe
    em last_seen e occurrences e NAO no status: ele ficava `resolved` para
    sempre, sumido da fila, enquanto os proprios dados mostravam que a regra
    seguia emitindo. Foi assim que 22 achados de ingress viraram invisiveis em
    producao.
    """
    db = await get_db()
    cur = await db.execute("SELECT * FROM findings WHERE id = ?", (finding["id"],))
    existing = await cur.fetchone()
    now = _now()
    targets_json = finding.get("targets")
    target_val = finding.get("target")
    if existing:
        existing = dict(existing)
        if existing["status"] == "resolved":
            resolved_dt = _parse_iso(existing.get("resolved_at"))
            now_dt = _parse_iso(now)
            if resolved_dt and now_dt:
                delta = (now_dt - resolved_dt).total_seconds()
            else:
                delta = 9999
            mesmo_incidente = delta < 1800
            if mesmo_incidente:
                await db.execute("""
                    UPDATE findings SET
                        last_seen = ?, status = 'open', resolved_at = NULL,
                        targets = ?, target = ?, payload = ?
                    WHERE id = ?
                """, (now, targets_json, target_val,
                      finding.get("payload", "{}"), finding["id"]))
            else:
                # Incidente novo: first_seen recomeca e a contagem zera.
                await db.execute("""
                    UPDATE findings SET
                        first_seen = ?, last_seen = ?, status = 'open',
                        resolved_at = NULL, occurrences = 1,
                        targets = ?, target = ?, payload = ?
                    WHERE id = ?
                """, (now, now, targets_json, target_val,
                      finding.get("payload", "{}"), finding["id"]))
            await db.commit()
            return "reopened"
        await db.execute("""
            UPDATE findings SET
                last_seen = ?, occurrences = occurrences + 1, payload = ?,
                targets = ?, target = ?
            WHERE id = ?
        """, (now, finding.get("payload", "{}"), targets_json, target_val, finding["id"]))
        await db.commit()
        return "updated"
    else:
        await db.execute("""
            INSERT INTO findings (id, rule, target, targets, scope, severity, score,
                caused_by, status, first_seen, last_seen, occurrences, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, 1, ?)
        """, (
            finding["id"], finding["rule"], target_val, targets_json,
            finding["scope"], finding["severity"], finding.get("score", 0),
            finding.get("caused_by"), now, now, finding.get("payload", "{}"),
        ))
        await db.commit()
        return "created"

async def resolve_finding(finding_id: str):
    db = await get_db()
    now = _now()
    await db.execute("""
        UPDATE findings SET status = 'resolved', resolved_at = ?
        WHERE id = ? AND status != 'resolved'
    """, (now, finding_id))
    await db.commit()

async def get_findings(status=None, scope=None):
    db = await get_db()
    parts = ["SELECT * FROM findings WHERE 1=1"]
    params = []
    if status:
        parts.append("AND status = ?")
        params.append(status)
    if scope:
        parts.append("AND scope = ?")
        params.append(scope)
    parts.append("ORDER BY score DESC, last_seen DESC")
    cur = await db.execute(" ".join(parts), params)
    rows = await cur.fetchall()
    return _parse_rows(rows, cur.description)

async def get_finding(finding_id: str):
    db = await get_db()
    cur = await db.execute("SELECT * FROM findings WHERE id = ?", (finding_id,))
    row = await cur.fetchone()
    return _parse_row(row, cur.description)

async def ack_finding(finding_id: str, reason: str, note: str = "", until: str = ""):
    db = await get_db()
    now = _now()
    ack_until = until or ""
    await db.execute("""
        UPDATE findings SET status = 'acked', ack_reason = ?, ack_note = ?, ack_until = ?, last_seen = ?
        WHERE id = ? AND status != 'resolved'
    """, (reason, note, ack_until, now, finding_id))
    await db.commit()

async def add_audit_entry(action: str, project: str, result: str, token_label: str = "", ip: str = ""):
    db = await get_db()
    now = _now()
    await db.execute(
        "INSERT INTO audit_log (action, project, result, token_label, ip, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (action, project, result, token_label, ip, now),
    )
    await db.commit()

async def audit_iniciar(action: str, project: str, token_label: str = "", ip: str = "") -> int:
    """Grava a INTENCAO e devolve o id da linha. Chamar ANTES de executar.

    E o ponto do B10: a linha existe a partir do momento em que a acao foi
    autorizada, nao a partir do momento em que ela terminou. Se o daemon travar,
    a linha fica em `running` para sempre — e essa linha orfa e o rastro do
    incidente, nao sujeira.
    """
    db = await get_db()
    agora = _now()
    cur = await db.execute(
        "INSERT INTO audit_log (action, project, result, token_label, ip, created_at,"
        " status, started_at, finished_at) VALUES (?, ?, '', ?, ?, ?, 'running', ?, NULL)",
        (action, project, token_label, ip, agora, agora),
    )
    await db.commit()
    return cur.lastrowid


async def audit_concluir(audit_id: int, result: str, status: str = "done"):
    """Fecha a linha aberta por `audit_iniciar`.

    Nao levanta: uma falha ao registrar o RESULTADO nao pode mascarar o
    resultado real da acao para quem chamou. A linha fica em `running`, que ja
    conta a historia.
    """
    if not audit_id:
        return
    try:
        db = await get_db()
        await db.execute(
            "UPDATE audit_log SET result = ?, status = ?, finished_at = ? WHERE id = ?",
            (result, status, _now(), audit_id),
        )
        await db.commit()
    except Exception:
        return


async def get_audit_log(limit: int = 100):
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    rows = await cur.fetchall()
    return _parse_rows(rows, cur.description)

async def cleanup_expired_sessions():
    """Housekeeping. Nao e o gate: a validade e reconferida em Python no read."""
    db = await get_db()
    cur = await db.execute("SELECT token_hash, expires_at FROM unlock_state")
    rows = await cur.fetchall()
    now = datetime.now(timezone.utc)
    dead = []
    for row in rows:
        expires = _parse_iso(dict(row)["expires_at"])
        if expires is None or expires <= now:
            dead.append(dict(row)["token_hash"])
    for token_hash in dead:
        await db.execute("DELETE FROM unlock_state WHERE token_hash = ?", (token_hash,))
    if dead:
        await db.commit()

async def create_unlock_session(remote_user: str, ip: str, motivo: str,
                                ttl_seconds: int = UNLOCK_TTL_SECONDS):
    """Cria uma sessao de destravamento e devolve (token, expires_at).

    O token e gerado aqui, aleatorio por sessao, e devolvido UMA vez — o banco
    guarda so o hash. Nao existe token derivado de configuracao.
    """
    token = secrets.token_urlsafe(32)
    db = await get_db()
    await cleanup_expired_sessions()
    now = datetime.now(timezone.utc)
    expires_at = _iso(now + timedelta(seconds=ttl_seconds))
    await db.execute(
        "INSERT OR REPLACE INTO unlock_state "
        "(token_hash, remote_user, ip, motivo, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_hash_token(token), remote_user, ip, motivo, _iso(now), expires_at),
    )
    await db.commit()
    return token, expires_at

async def get_valid_unlock_session(token: str):
    """Devolve a sessao viva do token apresentado, ou None.

    Unico caminho de validacao de escrita. Comparacao pelo hash, o que ja e
    de tempo constante no lookup por chave primaria.
    """
    if not token:
        return None
    await cleanup_expired_sessions()
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM unlock_state WHERE token_hash = ?",
        (_hash_token(token),),
    )
    row = await cur.fetchone()
    if not row:
        return None
    session = dict(row)
    expires = _parse_iso(session.get("expires_at"))
    if expires is None or expires <= datetime.now(timezone.utc):
        return None
    return session

async def revoke_unlock_session(token: str):
    db = await get_db()
    await db.execute("DELETE FROM unlock_state WHERE token_hash = ?", (_hash_token(token),))
    await db.commit()


async def insert_host_sample(sample: dict):
    db = await get_db()
    cpu = sample.get("cpu", {}) or {}
    mem = sample.get("memory", {}) or {}
    swap = sample.get("swap", {}) or {}
    disks = sample.get("disks", []) or []
    root = next((d for d in disks if d.get("mountpoint") == "/"), None) or (disks[0] if disks else {})
    sampled_at = sample.get("sampled_at", _now())
    await db.execute(
        "INSERT OR IGNORE INTO host_samples (sampled_at, cpu_pct, mem_pct, mem_used, mem_total, disk_pct, swap_pct)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            sampled_at,
            round(cpu.get("percent", 0), 1),
            round(mem.get("percent", 0), 1),
            mem.get("used", 0) or 0,
            mem.get("total", 0) or 0,
            round(root.get("percent", 0), 1),
            round(swap.get("percent", 0), 1),
        ),
    )
    await db.commit()


async def insert_container_samples(stats: dict):
    db = await get_db()
    now = _now()
    for cid, data in stats.items():
        if not isinstance(data, dict):
            continue
        name = data.get("inspect", {}) if isinstance(data.get("inspect"), dict) else {}
        cname = ""
        if isinstance(name, dict):
            cname = ((name.get("Name") or "").lstrip("/") or "")
        mem_limit = data.get("mem_limit")
        await db.execute(
            "INSERT OR IGNORE INTO container_samples (sampled_at, container_id, name, cpu_pct, mem_usage, mem_limit)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                now,
                cid,
                cname,
                round(data.get("cpu_pct", 0), 1),
                data.get("mem_usage", 0) or 0,
                mem_limit if mem_limit and mem_limit > 0 else None,
            ),
        )
    await db.commit()


async def rollup_container_samples(window_hours: int = 3):
    """Agrega container_samples raw em container_samples_hourly.

    Incremental de proposito: reagrega apenas as ultimas `window_hours` horas em
    vez de varrer a tabela toda a cada ciclo de 60 s. A hora corrente e
    reescrita a cada passada (INSERT OR REPLACE) porque ela ainda esta
    recebendo amostras — o valor final so estabiliza quando a hora fecha.

    `window_hours` maior existe para o catch-up de boot: se o cockpit ficou
    fora do ar mais que a janela, as horas do meio nunca teriam sido agregadas
    e o purge de raw as levaria embora. O coletor chama com a janela cheia de
    raw na primeira passada.
    """
    db = await get_db()
    desde = (
        datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))
    ).isoformat().replace("+00:00", "Z")
    await db.execute(
        "INSERT OR REPLACE INTO container_samples_hourly "
        "(hour, container_id, name, cpu_pct_avg, cpu_pct_max,"
        " mem_usage_avg, mem_usage_max, mem_limit, samples) "
        "SELECT substr(sampled_at, 1, 13) || ':00:00Z' AS hour,"
        " container_id,"
        " MAX(name),"
        " ROUND(AVG(cpu_pct), 2),"
        " MAX(cpu_pct),"
        " CAST(AVG(mem_usage) AS INTEGER),"
        " MAX(mem_usage),"
        " MAX(mem_limit),"
        " COUNT(*)"
        " FROM container_samples WHERE sampled_at >= ?"
        " GROUP BY hour, container_id",
        (desde,),
    )
    await db.commit()


async def purge_samples():
    """Expurgo dos tres niveis de serie temporal.

    Ordem importa: quem chama precisa ter rodado `rollup_container_samples`
    antes, senao o raw sai da tabela sem ter virado agregado.
    """
    db = await get_db()
    agora = datetime.now(timezone.utc)
    corte_host = (agora - timedelta(days=RETENTION_HOST_DAYS)).isoformat().replace("+00:00", "Z")
    corte_raw = (agora - timedelta(hours=RETENTION_RAW_HOURS)).isoformat().replace("+00:00", "Z")
    corte_rollup = (agora - timedelta(days=RETENTION_ROLLUP_DAYS)).isoformat().replace("+00:00", "Z")
    await db.execute("DELETE FROM host_samples WHERE sampled_at < ?", (corte_host,))
    await db.execute("DELETE FROM container_samples WHERE sampled_at < ?", (corte_raw,))
    await db.execute("DELETE FROM container_samples_hourly WHERE hour < ?", (corte_rollup,))
    await db.commit()


def _downsample(pontos: list, teto: int = MAX_HISTORY_POINTS) -> list:
    """Reduz a serie a no maximo `teto` pontos preservando o primeiro e o ultimo.

    Passo fixo em vez de media movel: a tela precisa que o ultimo ponto seja o
    valor real mais recente, nao uma media que suaviza justamente o pico que o
    operador abriu a tela para ver.
    """
    total = len(pontos)
    if teto <= 0 or total <= teto:
        return pontos
    passo = total / teto
    amostrados = [pontos[int(i * passo)] for i in range(teto)]
    if amostrados[-1] is not pontos[-1]:
        amostrados[-1] = pontos[-1]
    return amostrados


async def get_container_history(container_id: str, hours: int = 24, max_points: int = MAX_HISTORY_POINTS):
    """Serie de um container, escolhendo a tabela pela idade do intervalo.

    Devolve `{"points": [...], "resolution": "raw"|"hourly", ...}`. A resolucao
    sai no payload porque a tela precisa dizer ao operador que 30 dias sao
    medias horarias, nao leituras de 60 s — omitir isso e apresentar agregado
    como se fosse medida.
    """
    db = await get_db()
    hours = max(1, int(hours))
    usar_raw = hours <= RETENTION_RAW_HOURS
    corte = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")

    if usar_raw:
        cur = await db.execute(
            "SELECT sampled_at AS ts, cpu_pct, mem_usage, mem_limit"
            " FROM container_samples WHERE container_id = ? AND sampled_at >= ?"
            " ORDER BY sampled_at",
            (container_id, corte),
        )
        rows = await cur.fetchall()
        pontos = [
            {
                "ts": r[0],
                "cpu_pct": r[1],
                "mem_bytes": r[2],
                "mem_limit": r[3],
            }
            for r in rows
        ]
    else:
        cur = await db.execute(
            "SELECT hour AS ts, cpu_pct_avg, cpu_pct_max, mem_usage_avg, mem_usage_max, mem_limit, samples"
            " FROM container_samples_hourly WHERE container_id = ? AND hour >= ?"
            " ORDER BY hour",
            (container_id, corte),
        )
        rows = await cur.fetchall()
        pontos = [
            {
                "ts": r[0],
                "cpu_pct": r[1],
                "cpu_pct_max": r[2],
                "mem_bytes": r[3],
                "mem_bytes_max": r[4],
                "mem_limit": r[5],
                "samples": r[6],
            }
            for r in rows
        ]

    total_bruto = len(pontos)
    pontos = _downsample(pontos, max_points)
    return {
        "container_id": container_id,
        "resolution": "raw" if usar_raw else "hourly",
        "range_hours": hours,
        "points": pontos,
        "point_count": len(pontos),
        "downsampled_from": total_bruto if total_bruto != len(pontos) else None,
        "retention": {
            "raw_hours": RETENTION_RAW_HOURS,
            "rollup_days": RETENTION_ROLLUP_DAYS,
        },
    }


async def get_host_series(metric: str, days: int = 30, step: str = "1d") -> list:
    db = await get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    col = {"cpu_pct": "cpu_pct", "mem_pct": "mem_pct", "disk_pct": "disk_pct", "swap_pct": "swap_pct"}.get(metric, "disk_pct")
    if step == "1d":
        cur = await db.execute(
            f"SELECT DATE(sampled_at) AS ts, ROUND(AVG({col}), 2) AS v"
            " FROM host_samples WHERE sampled_at >= ?"
            " GROUP BY DATE(sampled_at) ORDER BY ts",
            (cutoff,),
        )
    else:
        cur = await db.execute(
            f"SELECT sampled_at AS ts, {col} AS v FROM host_samples WHERE sampled_at >= ? ORDER BY sampled_at",
            (cutoff,),
        )
    rows = await cur.fetchall()
    return [{"ts": r[0], "v": r[1]} for r in rows]


async def get_container_samples_since(hours: int = 24):
    db = await get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    cur = await db.execute(
        "SELECT container_id, name, MAX(cpu_pct) as cpu_pct,"
        " AVG(mem_usage) as mem_usage, MAX(mem_limit) as mem_limit"
        " FROM container_samples WHERE sampled_at >= ?"
        " GROUP BY container_id ORDER BY name",
        (cutoff,),
    )
    rows = await cur.fetchall()
    return _parse_rows(rows, cur.description)


# --- eventos do daemon (v11) ----------------------------------------------

# Ring por contagem. 10 mil eventos numa VPS de 15 containers cobrem semanas de
# operacao normal e alguns dias de crash loop — que e justamente quando a
# timeline importa e quando o volume explode.
EVENTS_RING = _env_int("EVENTS_RING", 10000, 100)

# Acoes que valem uma linha na timeline. O daemon emite dezenas de tipos por
# minuto (exec_create, exec_start, health_status a cada 30s); guardar tudo
# encheria o ring com ruido e expulsaria os `die` que o operador procura.
EVENTS_ACOES = {
    "create", "start", "stop", "die", "kill", "restart", "destroy", "oom",
    "pause", "unpause", "rename", "update", "health_status",
}

# Severidade por acao — a timeline colore por isto e o `summary.events` procura
# o ultimo critico. Nao e opiniao: `oom` e `die` com exit != 0 sao os dois
# eventos que respondem "por que caiu".
#
# `die` NAO entra nesta lista: ele tem regra propria logo abaixo, porque o mesmo
# evento significa coisas opostas conforme o exit code. `docker stop` emite
# `die` com exit 0 — parada limpa, pedida por alguem. Marcar isso como `warn`
# encheria a timeline de alarme falso toda vez que o operador desliga um
# servico, e o alarme que sempre toca deixa de ser lido.
_EVENTOS_DE_ALERTA = {"kill", "destroy"}


def _severidade_evento(action: str, exit_code: str) -> str:
    if action == "oom":
        return "critical"
    if action == "die":
        # exit vazio = daemon nao informou; nao da para afirmar que foi falha.
        return "critical" if exit_code not in ("", "0") else "info"
    if action in _EVENTOS_DE_ALERTA:
        return "warn"
    if action == "health_status" and "unhealthy" in (exit_code or ""):
        return "warn"
    return "info"


async def insert_event(event: dict):
    """Grava um evento do daemon. Devolve o dict gravado, ou None se ignorado.

    Ignorar silenciosamente acao fora de EVENTS_ACOES e proposital: o consumidor
    chama isto para TODO evento do stream, e o filtro tem de estar aqui e nao no
    chamador — senao cada novo consumidor reimplementaria a mesma lista.
    """
    tipo = str(event.get("Type") or "")
    acao = str(event.get("Action") or "")
    # `health_status: unhealthy` chega como acao composta.
    acao_base = acao.split(":")[0].strip()
    if tipo != "container" or acao_base not in EVENTS_ACOES:
        return None

    ator = event.get("Actor") if isinstance(event.get("Actor"), dict) else {}
    attrs = ator.get("Attributes") if isinstance(ator.get("Attributes"), dict) else {}
    detalhe = acao.split(":", 1)[1].strip() if ":" in acao else str(attrs.get("exitCode") or "")

    quando = event.get("time")
    ts = (
        datetime.fromtimestamp(quando, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        if isinstance(quando, (int, float)) else _now()
    )

    linha = {
        "ts": ts,
        "type": tipo,
        "action": acao_base,
        "actor_id": str(ator.get("ID") or "")[:64],
        "actor_name": str(attrs.get("name") or ""),
        "stack": str(attrs.get("com.docker.compose.project") or ""),
        "exit_code": str(detalhe),
        "severity": _severidade_evento(acao_base, str(detalhe)),
    }

    db = await get_db()
    await db.execute(
        "INSERT INTO docker_events (ts, type, action, actor_id, actor_name, stack, exit_code, severity)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        tuple(linha[k] for k in
              ("ts", "type", "action", "actor_id", "actor_name", "stack", "exit_code", "severity")),
    )
    await db.commit()
    return linha


async def purge_events(ring: int = None):
    """Corta o ring por CONTAGEM, no ciclo de retencao que ja existe.

    Por contagem e nao por idade porque o problema que o ring resolve e volume,
    nao antiguidade: um crash loop gera em uma hora o que a operacao normal gera
    em semanas. Cortar por data deixaria o pior caso sem teto.
    """
    teto = ring or EVENTS_RING
    db = await get_db()
    await db.execute(
        "DELETE FROM docker_events WHERE id <= ("
        "  SELECT MAX(id) - ? FROM docker_events"
        ")",
        (teto,),
    )
    await db.commit()


async def get_events(container: str = None, stack: str = None, action: str = None,
                     severity: str = None, limit: int = 100, before_id: int = None):
    """Historico paginado. Filtros SEMPRE no servidor.

    Paginacao por `before_id` (keyset) e nao por OFFSET: a tabela recebe escrita
    continua, e OFFSET numa lista que cresce pela frente devolve linha repetida
    ou pulada entre duas paginas.
    """
    db = await get_db()
    partes = ["SELECT * FROM docker_events WHERE 1=1"]
    params = []
    if container:
        partes.append("AND actor_name = ?")
        params.append(container)
    if stack:
        partes.append("AND stack = ?")
        params.append(stack)
    if action:
        partes.append("AND action = ?")
        params.append(action)
    if severity:
        partes.append("AND severity = ?")
        params.append(severity)
    if before_id:
        partes.append("AND id < ?")
        params.append(before_id)
    partes.append("ORDER BY id DESC LIMIT ?")
    params.append(max(1, min(int(limit or 100), 500)))

    cur = await db.execute(" ".join(partes), tuple(params))
    rows = await cur.fetchall()
    return _parse_rows(rows, cur.description)


async def get_events_resumo():
    """Para `summary.events`: contagem e o ultimo critico.

    A regua precisa do chip do modulo Eventos vivo mesmo com o modulo oculto —
    e este resumo nasce junto com a fonte, nao numa passada depois.
    """
    db = await get_db()
    cur = await db.execute("SELECT COUNT(*), MAX(ts) FROM docker_events")
    total, ultimo = (await cur.fetchone()) or (0, None)
    cur = await db.execute(
        "SELECT ts, action, actor_name, exit_code FROM docker_events"
        " WHERE severity = 'critical' ORDER BY id DESC LIMIT 1"
    )
    row = await cur.fetchone()
    critico = None
    if row:
        critico = {"ts": row[0], "action": row[1], "container": row[2], "exit_code": row[3]}
    return {"total": total or 0, "last_at": ultimo, "last_critical": critico}


# --- logs full-text (v13) -------------------------------------------------

RETENTION_LOGS_DAYS = _env_int("RETENTION_LOGS_DAYS", 7, 1)

# Piso do termo de busca. Menos de 3 caracteres num indice de milhoes de linhas
# devolve tudo e nao responde nada — e o custo cai no SQLite, nao no operador.
BUSCA_MINIMA = 3


def sanitiza_fts(q: str) -> str:
    """Transforma a consulta do usuario em uma expressao FTS5 LITERAL.

    Todo operador vira texto. `erro NEAR/2 falha` procura essas tres palavras,
    nao invoca o operador NEAR; `"api"` procura api, nao uma frase exata.

    Sanitizar e nao escapar: FTS5 nao tem escape universal, e uma sintaxe
    invalida nao devolve zero resultados — ela LEVANTA, e a busca inteira morre
    por causa de uma aspa que o operador digitou sem querer. Aqui a query e
    reconstruida a partir dos tokens, entao nao existe entrada que quebre.
    """
    if not q:
        return ""
    # Mantem letra, numero e o que costuma compor identificador em log.
    tokens = re.findall(r"[\w\-./:@]+", q, flags=re.UNICODE)
    limpos = [t for t in tokens if t.strip('-./:@')]
    if not limpos:
        return ""
    # Cada token entre aspas duplas (com as internas dobradas) = termo literal.
    # AND implicito: quem digita duas palavras quer as duas.
    return " ".join('"{}"'.format(t.replace('"', '""')) for t in limpos)


async def get_log_watermark(container: str) -> str:
    db = await get_db()
    cur = await db.execute("SELECT last_ts FROM logs_ingest WHERE container = ?", (container,))
    row = await cur.fetchone()
    return (row[0] if row else "") or ""


async def insert_log_lines(container: str, linhas: list, stream: str = "stdout"):
    """Grava linhas no indice e avanca a marca d'agua.

    `linhas` e uma lista de (ts, texto). Stack trace chega como VARIAS linhas
    com o MESMO ts — e cada uma entra como registro proprio, de proposito: o
    `oom` que o operador procura costuma estar no meio do traceback, e juntar
    tudo num registro so faria o highlight apontar para um bloco de 40 linhas.
    """
    if not linhas:
        return 0
    db = await get_db()
    await db.executemany(
        "INSERT INTO logs_fts (linha, container, ts, stream) VALUES (?, ?, ?, ?)",
        [(texto, container, ts, stream) for ts, texto in linhas if texto],
    )
    ultimo = max((ts for ts, _ in linhas if ts), default="")
    await db.execute(
        "INSERT INTO logs_ingest (container, last_ts, last_run, linhas) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(container) DO UPDATE SET"
        "   last_ts = CASE WHEN excluded.last_ts > logs_ingest.last_ts"
        "                  THEN excluded.last_ts ELSE logs_ingest.last_ts END,"
        "   last_run = excluded.last_run,"
        "   linhas = logs_ingest.linhas + excluded.linhas",
        (container, ultimo, _now(), len(linhas)),
    )
    await db.commit()
    return len(linhas)


async def purge_logs(dias: int = None):
    """Expurgo por idade, no ciclo de retencao que ja existe."""
    corte = (
        datetime.now(timezone.utc) - timedelta(days=dias or RETENTION_LOGS_DAYS)
    ).isoformat().replace("+00:00", "Z")
    db = await get_db()
    await db.execute("DELETE FROM logs_fts WHERE ts < ?", (corte,))
    await db.commit()


async def search_logs(q: str, container: str = None, limit: int = 50, offset: int = 0):
    """Busca com trecho destacado. Devolve (linhas, expressao_usada).

    O highlight vem do proprio FTS5 (`snippet`), com marcadores que NAO sao
    HTML: a UI recebe texto e monta a marcacao por cima. Mandar `<mark>` daqui
    obrigaria o cliente a confiar no conteudo do log, que e texto arbitrario
    vindo de dentro dos containers.
    """
    expressao = sanitiza_fts(q)
    if not expressao:
        return [], ""
    db = await get_db()
    partes = [
        "SELECT container, ts, stream,"
        " snippet(logs_fts, 0, ?, ?, ' … ', 20) AS trecho,"
        " linha"
        " FROM logs_fts WHERE logs_fts MATCH ?"
    ]
    params = [MARCA_INICIO, MARCA_FIM, expressao]
    if container:
        partes.append("AND container = ?")
        params.append(container)
    partes.append("ORDER BY ts DESC LIMIT ? OFFSET ?")
    params.extend([max(1, min(int(limit or 50), 200)), max(0, int(offset or 0))])

    cur = await db.execute(" ".join(partes), tuple(params))
    rows = await cur.fetchall()
    return _parse_rows(rows, cur.description), expressao


# Marcadores do trecho. Deliberadamente NAO sao HTML: sao sequencias que nao
# ocorrem em log real e que a UI troca por marcacao propria depois de escapar o
# texto. Um `<mark>` vindo daqui obrigaria o cliente a injetar HTML de log.
MARCA_INICIO = "\u2062<"
MARCA_FIM = ">\u2062"


# --- imagens desatualizadas (v14) -----------------------------------------

async def upsert_image_update(image, namespace, repo, tag, digest_local,
                              digest_remoto="", status="desconhecido",
                              remoto_em="", erro=""):
    db = await get_db()
    await db.execute(
        "INSERT INTO image_updates (image, namespace, repo, tag, digest_local,"
        " digest_remoto, status, remoto_em, consultado_em, erro)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(image) DO UPDATE SET"
        "   namespace=excluded.namespace, repo=excluded.repo, tag=excluded.tag,"
        "   digest_local=excluded.digest_local, digest_remoto=excluded.digest_remoto,"
        "   status=excluded.status, remoto_em=excluded.remoto_em,"
        "   consultado_em=excluded.consultado_em, erro=excluded.erro",
        (image, namespace, repo, tag, digest_local, digest_remoto, status,
         remoto_em, _now(), erro),
    )
    await db.commit()


async def get_image_update(image: str):
    db = await get_db()
    cur = await db.execute("SELECT * FROM image_updates WHERE image = ?", (image,))
    row = await cur.fetchone()
    return _parse_row(row, cur.description)


async def get_image_updates():
    db = await get_db()
    cur = await db.execute(
        # Desatualizada primeiro: e a unica linha sobre a qual ha o que fazer.
        "SELECT * FROM image_updates ORDER BY"
        "  CASE status WHEN 'desatualizada' THEN 0 WHEN 'pendente' THEN 1"
        "              WHEN 'atualizada' THEN 2 ELSE 3 END, image"
    )
    rows = await cur.fetchall()
    return _parse_rows(rows, cur.description)


async def contar_desatualizadas() -> int:
    db = await get_db()
    cur = await db.execute("SELECT COUNT(*) FROM image_updates WHERE status = 'desatualizada'")
    row = await cur.fetchone()
    return (row[0] if row else 0) or 0


async def get_updates_resumo():
    """Para `summary.updates`. None quando o job NUNCA rodou.

    None e nao zero: zero afirma "nenhuma imagem desatualizada", que e uma
    conclusao — e o job pode simplesmente ainda nao ter rodado. Mesmo padrao de
    `certs_expiring`, ja firmado.
    """
    db = await get_db()
    cur = await db.execute("SELECT COUNT(*), MAX(consultado_em) FROM image_updates")
    total, ultimo = (await cur.fetchone()) or (0, None)
    if not total:
        return None
    return {
        "outdated_count": await contar_desatualizadas(),
        "checked": total,
        "consultado_em": ultimo,
    }


# --- notificacoes (B7) ----------------------------------------------------

async def registrar_notificacao(regra, alvo, ts, canais, falhas, detalhe):
    """Grava a tentativa. `canais` vazio => `enviado_em` vazio => nao deduplica.

    Registrar tambem a falha total (e nao so o sucesso) e o que da ao operador
    como saber que o alerta EXISTIU e nao chegou. Sem esta linha, canal quebrado
    e ausencia de problema tem a mesma aparencia: silencio.
    """
    entregues = ",".join(sorted(canais or []))
    db = await get_db()
    cur = await db.execute(
        "INSERT INTO notificacoes (regra, alvo, ts, enviado_em, canais, falhas, detalhe)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(regra), str(alvo or ""), str(ts or _now()),
         _now() if entregues else "", entregues, str(falhas or ""), str(detalhe or "")),
    )
    await db.commit()
    return cur.lastrowid


async def ultima_entrega(regra, alvo):
    """Instante da ultima ENTREGA para o par (regra, alvo). None se nunca houve."""
    db = await get_db()
    cur = await db.execute(
        "SELECT MAX(enviado_em) FROM notificacoes"
        " WHERE regra = ? AND alvo = ? AND enviado_em != ''",
        (str(regra), str(alvo or "")),
    )
    row = await cur.fetchone()
    return (row[0] if row and row[0] else None)


async def get_notificacoes(limit: int = 100, regra: str = None):
    db = await get_db()
    sql = "SELECT * FROM notificacoes"
    params = []
    if regra:
        sql += " WHERE regra = ?"
        params.append(regra)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit or 100), 500)))
    cur = await db.execute(sql, tuple(params))
    return _parse_rows(await cur.fetchall(), cur.description)


async def get_notificacoes_resumo():
    """Para `summary.notifications`. None quando nada foi notificado ainda.

    None e nao zero, pelo mesmo motivo de `certs_expiring` e `updates`: zero
    afirma "nada digno de nota aconteceu", e a verdade pode ser "nenhum canal
    esta configurado".
    """
    db = await get_db()
    cur = await db.execute(
        "SELECT COUNT(*), SUM(enviado_em = ''), MAX(enviado_em) FROM notificacoes"
    )
    total, falhadas, ultimo = (await cur.fetchone()) or (0, 0, None)
    if not total:
        return None
    return {
        "total": total,
        "sem_entrega": falhadas or 0,
        "ultima_entrega": ultimo or None,
    }


async def purge_notificacoes(teto: int = 2000):
    """Ring por contagem, como o de eventos: o historico existe para o dedup."""
    db = await get_db()
    await db.execute(
        "DELETE FROM notificacoes WHERE id <= (SELECT MAX(id) - ? FROM notificacoes)",
        (int(teto),),
    )
    await db.commit()


async def get_first_sample_time():
    db = await get_db()
    cur = await db.execute("SELECT MIN(sampled_at) FROM host_samples")
    row = await cur.fetchone()
    return row[0] if row and row[0] else None


async def flush_telemetry(hist: dict):
    """Flush in-memory histogram to api_telemetry table."""
    db = await get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00:00Z")
    for key, vals in hist.items():
        if not vals:
            continue
        n = len(vals)
        errors = sum(1 for v in vals if v[1] >= 400 or v[1] == 0)
        total_dur = sum(v[2] for v in vals)
        sq_dur = sum(v[2] * v[2] for v in vals)
        max_dur = max(v[2] for v in vals)
        route = key
        await db.execute(
            "INSERT INTO api_telemetry (route, hour, total, errors, durations_total, durations_squared, durations_max)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(route, hour) DO UPDATE SET"
            " total = total + ?, errors = errors + ?, durations_total = durations_total + ?,"
            " durations_squared = durations_squared + ?, durations_max = MAX(durations_max, ?)",
            (route, now, n, errors, total_dur, sq_dur, max_dur, n, errors, total_dur, sq_dur, max_dur),
        )
    await db.commit()


async def get_telemetry_summary(hours: int = 1):
    """Return aggregate telemetry per route for recent hours."""
    db = await get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:00:00Z")
    cur = await db.execute(
        "SELECT route, SUM(total) as total, SUM(errors) as errors,"
        " SUM(durations_total) as dur_sum, SUM(durations_squared) as dur_sq, MAX(durations_max) as dur_max"
        " FROM api_telemetry WHERE hour >= ?"
        " GROUP BY route ORDER BY total DESC",
        (cutoff,),
    )
    rows = await cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        n = d["total"] or 0
        dur = d.pop("dur_sum", 0) or 0
        dur_sq = d.pop("dur_sq", 0) or 0
        d["avg_ms"] = round((dur / n) * 1000, 1) if n else 0
        d["p95_ms"] = round(((dur_sq / n) ** 0.5) * 1000, 1) if n else 0
        d["dur_max_ms"] = round((d.pop("dur_max", 0) or 0) * 1000, 1)
        d["error_rate"] = round((d["errors"] / n) * 100, 1) if n else 0
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Tarefas (v9) — board do diagnostico
#
# Regra de sincronia (01-contrato-de-dados.md §9): o motor so mexe em cartao
# `origem = 'auto'`. Tarefa manual nunca e movida pelo sistema, mesmo quando
# aponta para o mesmo achado.
# ---------------------------------------------------------------------------

TASK_COLUNAS = ("todo", "doing", "blocked", "done")


async def create_task(title: str, detail: str = "", col: str = "todo",
                      origem: str = "manual", finding_id: str = None,
                      target: str = None, owner: str = "", due: str = None,
                      note: str = "", task_id: str = None):
    db = await get_db()
    now = _now()
    tid = task_id or f"task-{secrets.token_hex(8)}"
    await db.execute(
        "INSERT INTO tasks (id, title, detail, col, origem, finding_id, target, "
        "owner, due, note, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tid, title, detail, col, origem, finding_id, target, owner, due, note, now, now),
    )
    await db.commit()
    return await get_task(tid)


async def get_task(task_id: str):
    db = await get_db()
    cur = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = await cur.fetchone()
    return _parse_row(row, cur.description)


async def get_tasks(col: str = None, origem: str = None):
    db = await get_db()
    parts = ["SELECT * FROM tasks WHERE 1=1"]
    params = []
    if col:
        parts.append("AND col = ?")
        params.append(col)
    if origem:
        parts.append("AND origem = ?")
        params.append(origem)
    parts.append("ORDER BY updated_at DESC")
    cur = await db.execute(" ".join(parts), params)
    rows = await cur.fetchall()
    return _parse_rows(rows, cur.description)


async def update_task(task_id: str, **campos):
    """Atualiza so os campos passados. Devolve a tarefa depois, ou None."""
    permitidos = ("title", "detail", "col", "owner", "due", "note")
    sets, params = [], []
    for k, v in campos.items():
        if k in permitidos and v is not None:
            sets.append(f"{k} = ?")
            params.append(v)
    if not sets:
        return await get_task(task_id)
    db = await get_db()
    sets.append("updated_at = ?")
    params.append(_now())
    params.append(task_id)
    await db.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params)
    await db.commit()
    return await get_task(task_id)


async def get_auto_task_for_finding(finding_id: str):
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM tasks WHERE finding_id = ? AND origem = 'auto'", (finding_id,)
    )
    row = await cur.fetchone()
    return _parse_row(row, cur.description)


async def create_task_from_finding(finding: dict):
    """Cria o cartao automatico de um achado. Idempotente.

    O motor chama isto a cada ciclo de 10 s; sem a guarda o board encheria de
    cartoes iguais. O indice unico parcial e a rede: mesmo com corrida, so um
    cartao 'auto' sobrevive por finding_id.
    """
    finding_id = finding.get("id")
    if not finding_id:
        return None
    existente = await get_auto_task_for_finding(finding_id)
    if existente:
        return existente
    try:
        return await create_task(
            title=finding.get("title") or finding.get("rule") or finding_id,
            detail=finding.get("recommendation") or "",
            col="todo",
            origem="auto",
            finding_id=finding_id,
            target=finding.get("target"),
        )
    except aiosqlite.IntegrityError:
        # perdeu a corrida do indice unico — o cartao do outro serve
        return await get_auto_task_for_finding(finding_id)


async def resolve_task_for_finding(finding_id: str, quando: str = None):
    """Achado deixou de reincidir -> cartao automatico vai para done.

    So 'auto', e so o cartao DESTE achado. Cartao manual do mesmo alvo fica
    exatamente onde esta.
    """
    db = await get_db()
    now = _now()
    nota = f"resolvido: achado nao reincide desde {quando or now}"
    cur = await db.execute(
        "UPDATE tasks SET col = 'done', note = ?, updated_at = ? "
        "WHERE finding_id = ? AND origem = 'auto' AND col != 'done'",
        (nota, now, finding_id),
    )
    await db.commit()
    return cur.rowcount


async def reopen_task_for_finding(finding_id: str):
    """Achado voltou dentro da janela de 30 min -> cartao sai de done.

    Volta para `doing`, nao para `todo`: o trabalho ja tinha comecado, e um
    cartao ressuscitado em todo perde essa informacao. Nunca duplica — mexe no
    cartao que ja existe.
    """
    db = await get_db()
    now = _now()
    cur = await db.execute(
        "UPDATE tasks SET col = 'doing', note = ?, updated_at = ? "
        "WHERE finding_id = ? AND origem = 'auto' AND col = 'done'",
        ("reaberto: o achado voltou a ocorrer", now, finding_id),
    )
    await db.commit()
    return cur.rowcount
