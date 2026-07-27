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
