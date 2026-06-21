"""Adversarial robustness: NO input to a Gemini Live tool handler may crash it.

Every Live tool the model can call is driven here with malformed / empty / huge /
unicode / wrong-type / non-dict arguments and unknown tool names. The contract:
the handler always returns a dict (with an 'ok' key) and NEVER raises — so a
confused or adversarial model turn degrades to a clean error the model can read,
never an unhandled exception that drops the session. This is the "bugless" floor
for trusting Live to operate the computer.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ORYNN_LIVE_TASK_WAIT", "0")


class _FakeResult:
    def __init__(self, ok=True, output="ok", data=None):
        self.ok = ok
        self.output = output
        self.data = data or {}


class _FakeTools:
    """Permissive desktop tools: every method the handlers call returns a benign
    result, so the test exercises the HANDLERS' input handling, not the OS."""
    def uia_click(self, *a, **k): return _FakeResult(output="clicked", data={"verified": True})
    def uia_type(self, *a, **k): return _FakeResult(output="typed", data={"verified": True})
    def uia_find(self, *a, **k): return _FakeResult(output="found", data={"items": []})
    def adaptive_observe(self, *a, **k): return _FakeResult(output="map", data={"graph": {}})
    def focus_window(self, *a, **k): return _FakeResult(output="focused")
    def wait_for_window(self, *a, **k): return _FakeResult(output="window")
    def uia_wait(self, *a, **k): return _FakeResult(output="waited")
    def key(self, *a, **k): return _FakeResult(output="key")
    def scroll(self, *a, **k): return _FakeResult(output="scrolled")
    def run_command(self, *a, **k): return _FakeResult(output="ran")
    def web_search(self, *a, **k): return _FakeResult(output="results")
    def screenshot(self, *a, **k): return _FakeResult(output="shot", data={})


class _FakeClient:
    def request(self, method, path, data=None, timeout=4.0, **kw):
        if path == "/api/tasks/preflight":
            return {"blocked": False}
        if "/api/active-tasks" in path:
            return {"tasks": []}
        if "/api/memory/facts" in path:
            return {"facts": [], "prompt_block": ""}
        if "/api/memory/forget" in path:
            return {"removed": 0}
        return {}


def _controller():
    try:
        from PySide6.QtWidgets import QApplication
        from app.widget.textbox_overlay import OverlayController
    except Exception:
        pytest.skip("PySide6 not importable")
    QApplication.instance() or QApplication([])
    c = OverlayController(8000)
    c.client = _FakeClient()
    c._desktop_tools = _FakeTools()
    return c


# A nasty grab-bag of argument payloads.
_BAD_ARGS = [
    None, "", "a string", 123, 4.5, True, [], [1, 2, 3], {},
    {"action": None}, {"action": 123}, {"action": []},
    {"action": "click"}, {"action": "click", "query": None}, {"action": "click", "query": ""},
    {"action": "type", "query": "x"}, {"action": "type", "query": "x", "text": None},
    {"action": "type", "query": "x", "text": "y", "submit": "notabool"},
    {"action": "press_keys", "keys": None}, {"action": "press_keys", "keys": "alt+f4"},
    {"action": "scroll", "amount": "notanumber"},
    {"action": "observe", "cap": "huge"}, {"action": "find", "query": "x", "limit": -5},
    {"action": "unknown_action_xyz"},
    {"goal": None}, {"goal": ""}, {"goal": "x" * 50000}, {"goal": "héllo 🌍 \x00\n\t"},
    {"command": None}, {"command": ""}, {"command": "x" * 20000}, {"command": "héllo 🌍"},
    {"query": None}, {"query": ""}, {"query": "x" * 10000},
    {"fact": None}, {"fact": ""}, {"fact": "x" * 20000, "owner": 9, "category": []},
    {"question": None}, {"question": "x" * 5000},
    {"text": "no action key"}, {"weird": {"nested": {"deep": [1, {"k": "v"}]}}},
]

_TOOL_NAMES = [
    "desktop_control", "start_desktop_task", "look_at_screen", "run_terminal",
    "web_search", "stop_current_task", "get_companion_status", "remember", "forget",
    "", None, 123, "unknown_tool_xyz", "DESKTOP_CONTROL",
]


def test_no_live_tool_input_ever_raises():
    """Every (tool, args) combination returns a dict and never raises."""
    c = _controller()
    failures = []
    for name in _TOOL_NAMES:
        for args in _BAD_ARGS:
            try:
                res = c._live_tool(name, args)
                if not isinstance(res, dict) or "ok" not in res:
                    failures.append((name, args, f"bad shape: {res!r}"[:120]))
            except Exception as exc:  # noqa: BLE001
                failures.append((name, repr(args)[:60], f"{type(exc).__name__}: {exc}"[:120]))
    assert not failures, "Live tool handlers must never raise / return non-dict:\n" + \
        "\n".join(f"  {n} {a} -> {e}" for n, a, e in failures[:40])


def test_no_model_path_input_ever_raises():
    """The model-dispatch path (_live_tool_for_generation, incl. the click/type route)
    must also never raise on adversarial input."""
    c = _controller()
    failures = []
    for name in _TOOL_NAMES:
        for args in _BAD_ARGS:
            try:
                res = c._live_tool_for_generation(None, name, args)
                if not isinstance(res, dict) or "ok" not in res:
                    failures.append((name, args, f"bad shape: {res!r}"[:120]))
            except Exception as exc:  # noqa: BLE001
                failures.append((name, repr(args)[:60], f"{type(exc).__name__}: {exc}"[:120]))
    assert not failures, "model-path dispatch must never raise / return non-dict:\n" + \
        "\n".join(f"  {n} {a} -> {e}" for n, a, e in failures[:40])
