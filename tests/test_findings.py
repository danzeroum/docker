"""Testes de regras de achados (OOM, restart_loop) e SUPERSEDES."""

import pytest
import importlib
import os
import sys

# Ensure app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


def _make_container(
    name="test_container",
    oom_killed=False,
    exit_code=0,
    restart_count=0,
    running=True,
    image="test:latest",
):
    return {
        "Name": f"/{name}",
        "State": {
            "OOMKilled": oom_killed,
            "ExitCode": exit_code,
            "RestartCount": restart_count,
            "Running": running,
            "Status": "running" if running else "exited",
            "FinishedAt": "",
        },
        "Config": {"Image": image},
    }


class FakeCtx:
    pass


def test_oom_com_restart_inclui_fatos_de_reinicio():
    """OOM rule inclui RestartCount nos facts quando > 0."""
    from findings.rules import oom as oom_mod
    importlib.reload(oom_mod)

    ctx = FakeCtx()
    ctx.containers = [
        _make_container(oom_killed=True, exit_code=137, restart_count=5, running=True)
    ]

    result = oom_mod.evaluate(ctx)
    assert result is not None
    assert len(result) == 1
    f = result[0]
    assert f["target"] == "test_container"
    facts = f.get("facts", [])
    restart_facts = [x for x in facts if "Restart" in x.get("key", "")]
    assert len(restart_facts) == 1
    assert restart_facts[0]["value"] == "5"


def test_oom_com_restart_zero_sem_fato_redundante():
    """OOM rule NAO inclui RestartCount nos facts quando 0."""
    from findings.rules import oom as oom_mod
    importlib.reload(oom_mod)

    ctx = FakeCtx()
    ctx.containers = [
        _make_container(oom_killed=True, exit_code=137, restart_count=0, running=True)
    ]

    result = oom_mod.evaluate(ctx)
    assert result is not None
    assert len(result) == 1
    facts = result[0].get("facts", [])
    restart_facts = [x for x in facts if "Restart" in x.get("key", "")]
    assert len(restart_facts) == 0


def test_oom_salta_container_parado_ha_mais_de_1h():
    """OOM rule NAO dispara para container parado ha mais de FINISHED_RECENCY_HOURS."""
    from findings.rules import oom as oom_mod
    importlib.reload(oom_mod)

    from datetime import datetime, timezone, timedelta

    old_finished = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")

    ctx = FakeCtx()
    ctx.containers = [
        {
            "Name": "/old_oom",
            "State": {
                "OOMKilled": True,
                "ExitCode": 137,
                "RestartCount": 0,
                "Running": False,
                "Status": "exited",
                "FinishedAt": old_finished,
            },
            "Config": {"Image": "test:latest"},
        }
    ]

    result = oom_mod.evaluate(ctx)
    assert result is None


def test_oom_dispara_para_container_parado_recente():
    """OOM rule dispara para container parado ha menos de FINISHED_RECENCY_HOURS."""
    from findings.rules import oom as oom_mod
    importlib.reload(oom_mod)

    from datetime import datetime, timezone, timedelta

    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")

    ctx = FakeCtx()
    ctx.containers = [
        {
            "Name": "/recent_oom",
            "State": {
                "OOMKilled": True,
                "ExitCode": 137,
                "RestartCount": 0,
                "Running": False,
                "Status": "exited",
                "FinishedAt": recent,
            },
            "Config": {"Image": "test:latest"},
        }
    ]

    result = oom_mod.evaluate(ctx)
    assert result is not None
    assert len(result) == 1
    assert result[0]["target"] == "recent_oom"


def test_restart_loop_suprime_com_oom():
    """restart_loop NAO dispara quando container tem OOMKilled."""
    from findings.rules import restart_loop as rl_mod
    importlib.reload(rl_mod)

    rl_mod._prev_restart = {}

    ctx = FakeCtx()
    ctx.containers = [
        _make_container(oom_killed=True, exit_code=137, restart_count=5, running=True)
    ]

    result = rl_mod.evaluate(ctx)
    assert result is None


def test_restart_loop_fire_sem_oom():
    """restart_loop dispara quando container tem RestartCount > 0 sem OOM."""
    from findings.rules import restart_loop as rl_mod
    importlib.reload(rl_mod)

    rl_mod._prev_restart = {}

    ctx = FakeCtx()
    ctx.containers = [
        _make_container(oom_killed=False, exit_code=0, restart_count=5, running=True)
    ]

    result = rl_mod.evaluate(ctx)
    assert result is not None
    assert len(result) == 1
    assert result[0]["target"] == "test_container"


def _make_health_log(start, exit_code=1, output="curl failed"):
    return {
        "Start": start,
        "End": start.replace("Z", "") + "Z",
        "ExitCode": exit_code,
        "Output": output,
    }


def test_healthcheck_never_passed_dispara():
    from findings.rules import healthcheck_never_passed as hc_mod
    importlib.reload(hc_mod)
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    uptime_h = 47
    started = (now - timedelta(hours=uptime_h)).isoformat().replace("+00:00", "Z")
    interval_s = 30
    streak = int(uptime_h * 3600 / interval_s)
    log_entries = []
    for i in range(5):
        ts = (now - timedelta(seconds=(5 - i) * interval_s)).isoformat().replace("+00:00", "Z")
        log_entries.append(_make_health_log(ts))

    ctx = FakeCtx()
    ctx.containers = [{
        "Name": "/test_hc",
        "State": {
            "Status": "running",
            "Running": True,
            "StartedAt": started,
            "Health": {
                "Status": "unhealthy",
                "FailingStreak": streak,
                "Log": log_entries,
            },
        },
        "Config": {"Image": "test:latest"},
    }]

    result = hc_mod.evaluate(ctx)
    assert result is not None
    assert len(result) == 1
    f = result[0]
    assert f["target"] == "test_hc"
    assert f.get("supersedes") == ["unhealthy.test_hc"]


def test_healthcheck_never_passed_com_exit0_nao_dispara():
    from findings.rules import healthcheck_never_passed as hc_mod
    importlib.reload(hc_mod)
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    uptime_h = 47
    started = (now - timedelta(hours=uptime_h)).isoformat().replace("+00:00", "Z")
    interval_s = 30
    streak = int(uptime_h * 3600 / interval_s)
    log_entries = []
    for i in range(5):
        ts = (now - timedelta(seconds=(5 - i) * interval_s)).isoformat().replace("+00:00", "Z")
        ec = 0 if i == 2 else 1
        log_entries.append(_make_health_log(ts, exit_code=ec))

    ctx = FakeCtx()
    ctx.containers = [{
        "Name": "/test_hc",
        "State": {
            "Status": "running",
            "Running": True,
            "StartedAt": started,
            "Health": {
                "Status": "unhealthy",
                "FailingStreak": streak,
                "Log": log_entries,
            },
        },
        "Config": {"Image": "test:latest"},
    }]

    result = hc_mod.evaluate(ctx)
    assert result is None


def test_healthcheck_never_passed_streak_baixo_nao_dispara():
    from findings.rules import healthcheck_never_passed as hc_mod
    importlib.reload(hc_mod)
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    started = (now - timedelta(hours=47)).isoformat().replace("+00:00", "Z")
    log_entries = []
    for i in range(5):
        ts = (now - timedelta(seconds=(5 - i) * 30)).isoformat().replace("+00:00", "Z")
        log_entries.append(_make_health_log(ts))

    ctx = FakeCtx()
    ctx.containers = [{
        "Name": "/test_hc",
        "State": {
            "Status": "running",
            "Running": True,
            "StartedAt": started,
            "Health": {
                "Status": "unhealthy",
                "FailingStreak": 3,
                "Log": log_entries,
            },
        },
        "Config": {"Image": "test:latest"},
    }]

    result = hc_mod.evaluate(ctx)
    assert result is None


# ---------------------------------------------------------------------------
# Regras de ingress (no_http2, no_gzip, body_size_default, upstream_missing, ssl, server_tokens, autoindex)
# ---------------------------------------------------------------------------

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name):
    path = os.path.join(FIXTURES, name)
    with open(path) as f:
        return f.read()


def _parse_inverted():
    from ingress.parser import parse_nginx
    text = _load_fixture("nginx-inverted.conf")
    return parse_nginx(text)


def _parse_vps():
    from ingress.parser import parse_nginx
    text = _load_fixture("nginx-vps.conf")
    return parse_nginx(text)


def test_no_http2_fire_contra_vps():
    from findings.rules import no_http2 as mod
    importlib.reload(mod)
    cat = _parse_vps()
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is not None
    assert "targets" in result
    assert len(result["targets"]) == 13


def test_no_http2_nao_dispara_quando_http2_presente():
    from findings.rules import no_http2 as mod
    importlib.reload(mod)
    cat = _parse_inverted()
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is None


def test_no_gzip_fire_contra_vps():
    from findings.rules import no_gzip as mod
    importlib.reload(mod)
    cat = _parse_vps()
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is not None
    assert "targets" in result
    assert len(result["targets"]) == 13


def test_no_gzip_nao_dispara_quando_gzip_on():
    from findings.rules import no_gzip as mod
    importlib.reload(mod)
    cat = _parse_inverted()
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is None


def test_body_size_default_fire_contra_vps():
    from findings.rules import body_size_default as mod
    importlib.reload(mod)
    cat = _parse_vps()
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is not None
    assert "targets" in result
    assert len(result["targets"]) == 12


def _make_internal_only_cat():
    from ingress.parser import parse_nginx
    text = """
    http {
        server {
            listen 80;
            server_name internal.only.local localhost;
            location / { return 200 "ok"; }
        }
    }
    """
    return parse_nginx(text)


def test_agregados_nao_disparam_para_host_interno():
    from findings.rules import no_http2 as m1
    from findings.rules import no_gzip as m2
    from findings.rules import body_size_default as m3
    importlib.reload(m1); importlib.reload(m2); importlib.reload(m3)
    cat = _make_internal_only_cat()
    class Ctx: pass
    ctx = Ctx()
    ctx.ingress = cat
    assert m1.evaluate(ctx) is None
    assert m2.evaluate(ctx) is None
    assert m3.evaluate(ctx) is None


def test_body_size_default_nao_dispara_contra_inverted():
    from findings.rules import body_size_default as mod
    importlib.reload(mod)
    cat = _parse_inverted()
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is None


def test_upstream_missing_encontra_ghost():
    from findings.rules import upstream_missing as mod
    importlib.reload(mod)
    cat = _parse_inverted()
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    ctx.containers = []
    result = mod.evaluate(ctx)
    assert result is not None
    names = [f["target"] for f in result]
    assert "missing-upstream.btv.local" in names


def test_upstream_missing_com_container_existente_nao_dispara():
    from findings.rules import upstream_missing as mod
    importlib.reload(mod)
    cat = _parse_inverted()
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    ctx.containers = [{"Name": "/existing-container"}]
    result = mod.evaluate(ctx)
    assert result is not None
    targets = [f["target"] for f in result]
    assert "missing-upstream.btv.local" in targets
    assert "normal.btv.local" not in targets


def test_upstream_missing_nao_dispara_contra_vps():
    from findings.rules import upstream_missing as mod
    importlib.reload(mod)
    from ingress.parser import parse_nginx
    text = _load_fixture("nginx-vps.conf")
    cat = parse_nginx(text)
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    ctx.containers = [{"Name": f"/{name}"} for name in (
        "executagent-studio", "familia-web", "central-inteligencia-juridica",
        "criptotrade-app", "criptotrade-frontend", "btv-squad-dashboard",
        "docker-cockpit", "conciliaai-backend", "btvchatcorp-frontend-1",
        "prompte-frontend", "btv-governance", "giva-api-1", "giva-frontend-1",
        "mixlirous-api",
    )]
    result = mod.evaluate(ctx)
    assert result is None


def test_ssl_protocols_weak_encontra_old_tls():
    from findings.rules import ssl_protocols_weak as mod
    importlib.reload(mod)
    cat = _parse_inverted()
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is not None
    names = [f["target"] for f in result]
    assert "old-tls.btv.local" in names


def test_ssl_protocols_weak_nao_dispara_contra_vps():
    from findings.rules import ssl_protocols_weak as mod
    importlib.reload(mod)
    from ingress.parser import parse_nginx
    text = _load_fixture("nginx-vps.conf")
    cat = parse_nginx(text)
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is None


def test_ssl_ciphers_weak_encontra_weak_cipher():
    from findings.rules import ssl_ciphers_weak as mod
    importlib.reload(mod)
    cat = _parse_inverted()
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is not None
    names = [f["target"] for f in result]
    assert "weak-cipher.btv.local" in names


def test_ssl_ciphers_weak_nao_dispara_contra_vps():
    from findings.rules import ssl_ciphers_weak as mod
    importlib.reload(mod)
    from ingress.parser import parse_nginx
    text = _load_fixture("nginx-vps.conf")
    cat = parse_nginx(text)
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is None


def test_autoindex_enabled_encontra_files():
    from findings.rules import autoindex_enabled as mod
    importlib.reload(mod)
    cat = _parse_inverted()
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is not None
    names = [f["target"] for f in result]
    assert "autoindex.btv.local" in names


def test_autoindex_enabled_nao_dispara_contra_vps():
    from findings.rules import autoindex_enabled as mod
    importlib.reload(mod)
    from ingress.parser import parse_nginx
    text = _load_fixture("nginx-vps.conf")
    cat = parse_nginx(text)
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is None


def test_server_tokens_exposed_encontra_on():
    from findings.rules import server_tokens_exposed as mod
    importlib.reload(mod)
    cat = _parse_inverted()
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is not None
    assert result.get("target") == "_"


def test_server_tokens_exposed_nao_dispara_contra_vps():
    from findings.rules import server_tokens_exposed as mod
    importlib.reload(mod)
    from ingress.parser import parse_nginx
    text = _load_fixture("nginx-vps.conf")
    cat = parse_nginx(text)
    class Ctx:
        pass
    ctx = Ctx()
    ctx.ingress = cat
    result = mod.evaluate(ctx)
    assert result is None


def test_extract_container_from_upstream():
    from findings.engine import _extract_container_from_upstream as f
    assert f("http://executagent-studio:80") == "executagent-studio"
    assert f("http://familia-web:3000") == "familia-web"
    assert f("https://secure-backend:443") == "secure-backend"
    assert f("http://ghost:9000") == "ghost"
    assert f(None) is None
    assert f("") is None
