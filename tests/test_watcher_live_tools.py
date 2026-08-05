"""System watchers, creatable by voice, firing through the escalation ladder.

Pins the awareness design: add_watcher / list_watchers / remove_watcher give
Gemini Live persistent deterministic senses, and _on_watcher_event maps
severity onto the ladder — info = amber glow + toast (silent), notice = + the
reminder chime, critical = + Orynn speaks. Only critical may interrupt.
"""
from __future__ import annotations

import importlib
import threading

import pytest

watchers = importlib.import_module("app.watchers")
tbo = importlib.import_module("app.widget.textbox_overlay")
voice = importlib.import_module("app.widget.voice")


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    eng = watchers.WatcherEngine(path=tmp_path / "watchers.json",
                                 snapshot_fn=lambda: {})
    monkeypatch.setattr(watchers, "_ENGINE", eng)
    return eng


@pytest.fixture()
def controller():
    return tbo.OverlayController(8000)


# ── Live tool handlers ───────────────────────────────────────────────────────

def test_add_watcher_creates_persistent_watcher(controller, engine):
    res = controller._live_add_watcher({
        "kind": "process_exit", "name": "obs64.exe",
        "label": "OBS closing", "severity": "critical",
    })
    assert res["ok"]
    assert "Confirm this to the user" in res["message"]
    assert "out loud" in res["message"]        # critical rung explained
    items = engine.list()
    assert len(items) == 1
    assert items[0]["params"]["name"] == "obs64.exe"
    assert items[0]["severity"] == "critical"


def test_add_watcher_rejects_bad_input_helpfully(controller, engine):
    res = controller._live_add_watcher({"kind": "psychic_vision"})
    assert not res["ok"]
    assert "cpu_load" in res["message"]        # valid kinds are listed
    res = controller._live_add_watcher({"kind": "process_exit"})
    assert not res["ok"] and "name" in res["message"]
    assert engine.list() == []


def test_list_watchers_reports_state_and_recent_fires(controller, engine):
    assert "No watchers" in controller._live_list_watchers()["message"]
    controller._live_add_watcher({"kind": "battery_low"})
    res = controller._live_list_watchers()
    assert res["ok"] and res["count"] == 1
    assert res["watchers"][0]["kind"] == "battery_low"
    assert res["watchers"][0]["status"] == "armed"


def test_remove_watcher_refuses_ambiguity(controller, engine):
    controller._live_add_watcher({"kind": "process_exit", "name": "a.exe",
                                  "label": "game one"})
    controller._live_add_watcher({"kind": "process_exit", "name": "b.exe",
                                  "label": "game two"})
    res = controller._live_remove_watcher({"query": "game"})
    assert not res["ok"] and "Ask the user" in res["message"]
    res = controller._live_remove_watcher({"query": "game two"})
    assert res["ok"]
    assert len(engine.list()) == 1


# ── escalation ladder ────────────────────────────────────────────────────────

def _ladder_probe(controller, monkeypatch):
    """Capture glow states, toasts, chimes, speech from one watcher event."""
    seen = {"glow": [], "toast": [], "cue": [], "spoke": [],
            "done": threading.Event()}
    controller.glowStateRequested.connect(seen["glow"].append)
    controller.notifyRequested.connect(
        lambda title, msg: seen["toast"].append(msg))
    monkeypatch.setattr(voice, "cue", lambda kind: seen["cue"].append(kind))

    def fake_speak(text, **kw):
        seen["spoke"].append(text)
        seen["done"].set()
        return True
    monkeypatch.setattr(voice, "speak", fake_speak)
    monkeypatch.setattr(tbo.time, "sleep", lambda s: None)
    return seen


def test_info_event_is_silent_glow_plus_toast(controller, monkeypatch):
    seen = _ladder_probe(controller, monkeypatch)
    controller._on_watcher_event({
        "severity": "info", "label": "downloads",
        "message": "New file in Downloads: notes.pdf"})
    assert "attention" in seen["glow"]
    assert seen["toast"] and "notes.pdf" in seen["toast"][0]
    assert seen["cue"] == []                   # bottom rung: no sound at all
    assert seen["spoke"] == []


def test_notice_event_adds_chime_but_no_voice(controller, monkeypatch):
    seen = _ladder_probe(controller, monkeypatch)
    controller._on_watcher_event({
        "severity": "notice", "label": "disk",
        "message": "Drive C:\\ is down to 9.0 GB free."})
    assert "attention" in seen["glow"]
    assert seen["cue"] == ["reminder"]
    assert seen["spoke"] == []


def test_critical_event_speaks_the_message(controller, monkeypatch):
    seen = _ladder_probe(controller, monkeypatch)
    controller._on_watcher_event({
        "severity": "critical", "label": "battery",
        "message": "Battery at 5% and unplugged."})
    assert seen["done"].wait(timeout=3.0), "voice rung never fired"
    assert seen["cue"] == ["reminder"]
    assert seen["spoke"] == ["Battery at 5% and unplugged."]


def test_attention_state_exists_in_glow_palettes():
    from app.widget.taskbar_glow import TaskbarGlow
    assert "attention" in TaskbarGlow.PALETTES
    # It must auto-revert — an unglanced ping can't become a permanent nag.
    assert TaskbarGlow._TRANSIENT_S.get("attention", 0) > 0
    # And it must not collide with the semantic status colors.
    assert TaskbarGlow.PALETTES["attention"] != TaskbarGlow.PALETTES["error"]
    assert TaskbarGlow.PALETTES["attention"] != TaskbarGlow.PALETTES["working"]


def test_engine_dispatch_reaches_overlay_listener(tmp_path, controller,
                                                  monkeypatch):
    """Full path: sensor condition → engine.tick() → _on_watcher_event."""
    seen = _ladder_probe(controller, monkeypatch)
    eng = watchers.WatcherEngine(
        on_event=controller._on_watcher_event,
        path=tmp_path / "watchers.json",
        snapshot_fn=lambda: {"battery": {"pct": 6.0, "plugged": False}})
    eng.add("battery_low", label="battery")
    fired = eng.tick()
    assert len(fired) == 1
    assert "attention" in seen["glow"]
    assert seen["toast"] and "Battery" in seen["toast"][0]
