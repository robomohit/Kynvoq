"""Tests for the local planner-proxy supervisor (app/proxy_supervisor.py).

The proxy bridges the desktop planner to its free DeepSeek model; if it's down,
multi-step desktop tasks fail over to a rate-limited model. These tests pin the
self-healing contract without ever spawning a real process or opening :8080.
"""
from __future__ import annotations

import app.proxy_supervisor as ps


def test_noop_when_planner_does_not_use_local_proxy(monkeypatch):
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
    started = {"spawned": False}

    def _fake_popen(*a, **k):
        started["spawned"] = True

    monkeypatch.setattr(ps.subprocess, "Popen", _fake_popen)
    # Even if the probe would say "down", we must not spawn anything.
    monkeypatch.setattr(ps, "proxy_is_up", lambda timeout=0.5: False)
    assert ps.ensure_proxy_running() is True
    assert started["spawned"] is False


def test_noop_when_proxy_already_up(monkeypatch):
    monkeypatch.setenv("OPENROUTER_BASE_URL", "http://127.0.0.1:8080/v1/chat/completions")
    started = {"spawned": False}
    monkeypatch.setattr(ps.subprocess, "Popen", lambda *a, **k: started.__setitem__("spawned", True))
    monkeypatch.setattr(ps, "proxy_is_up", lambda timeout=0.5: True)
    assert ps.ensure_proxy_running() is True
    assert started["spawned"] is False


def test_starts_proxy_when_configured_and_down(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_BASE_URL", "http://localhost:8080/v1/chat/completions")
    # Pretend the script exists.
    script = tmp_path / "deepseek_proxy.py"
    script.write_text("# stub")
    monkeypatch.setattr(ps, "_proxy_script", lambda: script)

    calls = {"spawned": False}

    def _fake_popen(argv, **kwargs):
        calls["spawned"] = True
        calls["argv"] = argv
        return object()

    monkeypatch.setattr(ps.subprocess, "Popen", _fake_popen)
    # First probe (pre-spawn) down; after spawn, report up.
    seq = iter([False, True])
    monkeypatch.setattr(ps, "proxy_is_up", lambda timeout=0.5: next(seq, True))

    assert ps.ensure_proxy_running(wait=0.5) is True
    assert calls["spawned"] is True
    assert str(script) in calls["argv"]


def test_returns_false_when_script_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_BASE_URL", "http://127.0.0.1:8080/v1/chat/completions")
    monkeypatch.setattr(ps, "_proxy_script", lambda: tmp_path / "does_not_exist.py")
    monkeypatch.setattr(ps, "proxy_is_up", lambda timeout=0.5: False)
    spawned = {"v": False}
    monkeypatch.setattr(ps.subprocess, "Popen", lambda *a, **k: spawned.__setitem__("v", True))
    assert ps.ensure_proxy_running() is False
    assert spawned["v"] is False
