"""Regression tests for the LLM HTTP hardening.

Backstory: the provider used a persistent ``httpx.Client(timeout=300)``. After the
backend ran for hours, a request reused a dead pooled connection and hung the full
300s before failing — desktop tasks "stuck for 5 minutes on step 1", fixed only by
restarting. These tests pin the fix so it can't silently regress:

* the client timeout is bounded (not a flat 300s) and connect/pool fail fast,
* idle connections are capped so a stale one is never reused,
* connection/timeout errors (httpx.TransportError) are RETRIED, not fatal,
* providers close their sockets idempotently.
"""
import httpx
import pytest

from app import providers


# ── client configuration ─────────────────────────────────────────────────────

def test_llm_client_timeout_is_bounded_not_300(monkeypatch):
    monkeypatch.delenv("ORYNN_LLM_TIMEOUT", raising=False)
    c = providers._build_llm_http_client()
    try:
        # The old flat 300s read timeout is the bug we're guarding against.
        assert c.timeout.read is not None and c.timeout.read <= 180
        assert c.timeout.connect is not None and c.timeout.connect <= 15
        assert c.timeout.pool is not None and c.timeout.pool <= 15
    finally:
        c.close()


def test_llm_client_caps_idle_connections_and_retries():
    c = providers._build_llm_http_client()
    try:
        pool = c._transport._pool
        # Idle connections must expire quickly so an hours-old one is never reused.
        assert pool._keepalive_expiry is not None and pool._keepalive_expiry <= 30
        # Transport-level retries let a dead connection self-heal on a fresh socket.
        assert getattr(pool, "_retries", 0) >= 1
    finally:
        c.close()


def test_llm_read_timeout_env_override_and_blank_default(monkeypatch):
    monkeypatch.setenv("ORYNN_LLM_TIMEOUT", "45")
    assert providers._llm_read_timeout() == 45.0
    # Blank value -> default (the recurring empty-.env trap), not a crash.
    monkeypatch.setenv("ORYNN_LLM_TIMEOUT", "")
    assert providers._llm_read_timeout() == 120.0
    monkeypatch.setenv("ORYNN_LLM_TIMEOUT", "garbage")
    assert providers._llm_read_timeout() == 120.0
    monkeypatch.setenv("ORYNN_LLM_TIMEOUT", "0")  # non-positive -> default
    assert providers._llm_read_timeout() == 120.0


def test_provider_close_is_idempotent():
    p = providers.PlannerProvider(model="openrouter/openai/gpt-oss-120b:free")
    p.close()
    p.close()  # must not raise


# ── transport-error resilience (the actual hang) ─────────────────────────────

class _FakeResp:
    status_code = 200
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "opened notepad"}}]}


class _FlakyClient:
    """Raises a connection/timeout error N times, then returns a good response."""

    def __init__(self, fail_times: int, exc: Exception):
        self.calls = 0
        self.fail_times = fail_times
        self.exc = exc

    def post(self, *a, **k):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp()

    def close(self):
        pass


def test_openrouter_retries_transport_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(providers.time, "sleep", lambda *a, **k: None)  # no real backoff
    p = providers.PlannerProvider(model="openrouter/openai/gpt-oss-120b:free")
    p._openrouter_key = "test-key"
    monkeypatch.setattr(p, "_openrouter_models_to_try",
                        lambda *a, **k: ["openai/gpt-oss-120b:free"])
    p._http_client = _FlakyClient(fail_times=1, exc=httpx.ConnectTimeout("dead pool conn"))

    out = p._chat_openrouter("system", "open notepad")
    assert "opened notepad" in out
    assert p._http_client.calls == 2  # failed once, retried on a fresh attempt, succeeded


def test_single_provider_loop_retries_transport_error(monkeypatch):
    """The shared 3-try loop (openai/anthropic/...) must retry on a timeout
    instead of letting it crash the task. _chat_openai uses self._http_client."""
    monkeypatch.setattr(providers.time, "sleep", lambda *a, **k: None)
    p = providers.PlannerProvider(model="gpt-4o-mini")
    p._openai_key = "test-key"
    p._http_client = _FlakyClient(fail_times=1, exc=httpx.ReadTimeout("slow model"))

    out = p._chat_openai("system", "hi")
    assert "opened notepad" in out  # second attempt returned the fake good response
    assert p._http_client.calls == 2
