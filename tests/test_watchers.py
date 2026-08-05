"""Tests for the always-on watcher engine (app/watchers.py).

The contract: watchers are deterministic sensors evaluated against ONE shared
snapshot per tick, with re-arm + cooldown guards so a persistent condition
fires once, not every poll. No LLM, no sleeps in tests — snapshot and clocks
are injected.
"""
from __future__ import annotations

import pytest

from app.watchers import (
    DEFAULT_COOLDOWN_S,
    KINDS,
    SEVERITIES,
    WatcherEngine,
    evaluate,
)


def make_engine(tmp_path, snapshots, on_event=None, clock=None):
    """Engine with a scripted snapshot sequence and a manual clock."""
    state = {"i": 0, "now": 0.0}

    def snapshot_fn():
        i = min(state["i"], len(snapshots) - 1)
        state["i"] += 1
        return dict(snapshots[i])

    engine = WatcherEngine(
        on_event=on_event,
        path=tmp_path / "watchers.json",
        snapshot_fn=snapshot_fn,
        clock=(clock if clock is not None else lambda: state["now"]),
        wall=lambda: 1_000_000.0 + state["now"],
    )
    return engine, state


# ── evaluation rules ─────────────────────────────────────────────────────────

def test_cpu_load_requires_sustain_and_rearms():
    watcher = {"id": "w1", "kind": "cpu_load", "severity": "notice",
               "params": {"threshold_pct": 90.0, "sustain_s": 60.0}}
    state: dict = {}
    hot = {"cpu_pct": 97.0}
    # First observation starts the sustain window — no instant fire.
    assert evaluate(watcher, hot, state, now=0.0) is None
    # Still above threshold but sustain not yet met.
    assert evaluate(watcher, hot, state, now=30.0) is None
    # Sustain satisfied → fires once.
    event = evaluate(watcher, hot, state, now=61.0)
    assert event is not None and "CPU" in event["message"]
    # Condition persists → does NOT fire again (disarmed).
    assert evaluate(watcher, hot, state, now=120.0) is None
    # Drops below → re-arms; a fresh sustained spike fires again.
    assert evaluate(watcher, {"cpu_pct": 20.0}, state, now=130.0) is None
    assert evaluate(watcher, hot, state, now=140.0) is None
    assert evaluate(watcher, hot, state, now=201.0) is not None


def test_battery_low_escalates_to_critical_and_ignores_plugged():
    watcher = {"id": "w2", "kind": "battery_low", "severity": "notice",
               "params": {"threshold_pct": 20.0, "critical_pct": 8.0}}
    state: dict = {}
    # Plugged in → never fires, stays armed.
    plugged = {"battery": {"pct": 5.0, "plugged": True}}
    assert evaluate(watcher, plugged, state, now=0.0) is None
    # Unplugged at 15% → notice.
    event = evaluate(watcher, {"battery": {"pct": 15.0, "plugged": False}},
                     state, now=1.0)
    assert event is not None and event["severity"] == "notice"
    # Re-arm (charge above threshold), then drain to 5% → critical.
    evaluate(watcher, {"battery": {"pct": 50.0, "plugged": True}}, state, now=2.0)
    event = evaluate(watcher, {"battery": {"pct": 5.0, "plugged": False}},
                     state, now=3.0)
    assert event is not None and event["severity"] == "critical"


def test_disk_low_uses_snapshot_cache_and_critical_threshold():
    watcher = {"id": "w3", "kind": "disk_low", "severity": "notice",
               "params": {"drive": "X:\\", "min_free_gb": 10.0,
                          "critical_free_gb": 2.0}}
    state: dict = {}
    # Pre-seeded snapshot cache means psutil is never touched.
    event = evaluate(watcher, {"disks": {"X:\\": 1.5}}, state, now=0.0)
    assert event is not None and event["severity"] == "critical"
    # Recovered → re-arms; mild shortage → plain notice severity.
    assert evaluate(watcher, {"disks": {"X:\\": 50.0}}, state, now=1.0) is None
    event = evaluate(watcher, {"disks": {"X:\\": 8.0}}, state, now=2.0)
    assert event is not None and event["severity"] == "notice"


def test_process_exit_needs_baseline_then_disappearance():
    watcher = {"id": "w4", "kind": "process_exit", "severity": "notice",
               "params": {"name": "obs64.exe"}}
    state: dict = {}
    # First sighting only baselines.
    assert evaluate(watcher, {"process_names": {"obs64.exe"}}, state, 0.0) is None
    # Still running → nothing.
    assert evaluate(watcher, {"process_names": {"obs64.exe"}}, state, 1.0) is None
    # Gone → fires.
    event = evaluate(watcher, {"process_names": {"chrome.exe"}}, state, 2.0)
    assert event is not None and "obs64.exe" in event["message"]
    # process_start is the mirror image.
    starter = {"id": "w5", "kind": "process_start", "severity": "info",
               "params": {"name": "game.exe"}}
    s2: dict = {}
    assert evaluate(starter, {"process_names": set()}, s2, 0.0) is None
    event = evaluate(starter, {"process_names": {"game.exe"}}, s2, 1.0)
    assert event is not None and event["severity"] == "info"


def test_new_download_waits_for_stable_size(tmp_path):
    folder = tmp_path / "dl"
    folder.mkdir()
    watcher = {"id": "w6", "kind": "new_download", "severity": "info",
               "params": {"folder": str(folder)}}
    state: dict = {}
    # First scan baselines the folder.
    assert evaluate(watcher, {}, state, 0.0) is None
    # A file appears — not announced yet (size may still be growing).
    f = folder / "movie.mkv"
    f.write_bytes(b"x" * 100)
    assert evaluate(watcher, {}, state, 1.0) is None
    # Size unchanged on the next tick → announced.
    event = evaluate(watcher, {}, state, 2.0)
    assert event is not None and "movie.mkv" in event["message"]
    # Partial-download extensions are invisible.
    (folder / "big.iso.crdownload").write_bytes(b"y" * 10)
    assert evaluate(watcher, {}, state, 3.0) is None
    assert evaluate(watcher, {}, state, 4.0) is None


def test_missing_sensor_data_never_fires():
    empty: dict = {"cpu_pct": None, "battery": None, "process_names": None}
    for kind in ("cpu_load", "battery_low", "process_exit"):
        watcher = {"id": "x", "kind": kind, "severity": "notice",
                   "params": dict(KINDS[kind]["params"], name="a.exe")}
        assert evaluate(watcher, dict(empty), {}, 0.0) is None


# ── engine: cooldown, dispatch, persistence ──────────────────────────────────

def test_tick_fires_once_then_respects_cooldown(tmp_path):
    events: list = []
    engine, state = make_engine(
        tmp_path, [{"battery": {"pct": 10.0, "plugged": False}}],
        on_event=events.append)
    engine.add("battery_low", label="battery")
    assert len(engine.tick()) == 1
    # Condition persists: re-arm guard blocks refire regardless of cooldown.
    assert engine.tick() == []
    # Even after recovery + re-trigger, the COOLDOWN blocks a second fire…
    state_snap = [{"battery": {"pct": 90.0, "plugged": True}},
                  {"battery": {"pct": 10.0, "plugged": False}}]
    engine._snapshot_fn = lambda: state_snap.pop(0) if state_snap else \
        {"battery": {"pct": 10.0, "plugged": False}}
    engine.tick()                      # re-arms
    state["now"] = 60.0
    assert engine.tick() == []         # fires suppressed: still cooling down
    # …until the cooldown elapses.
    state["now"] = DEFAULT_COOLDOWN_S + 61.0
    state_snap2 = [{"battery": {"pct": 90.0, "plugged": True}},
                   {"battery": {"pct": 10.0, "plugged": False}}]
    engine._snapshot_fn = lambda: state_snap2.pop(0) if state_snap2 else \
        {"battery": {"pct": 10.0, "plugged": False}}
    engine.tick()                      # re-arm
    assert len(engine.tick()) == 1
    assert len(events) == 2
    assert all(e["label"] == "battery" for e in events)


def test_add_validates_kind_params_severity(tmp_path):
    engine, _ = make_engine(tmp_path, [{}])
    with pytest.raises(ValueError):
        engine.add("volcano_watch")
    with pytest.raises(ValueError):
        engine.add("cpu_load", params={"bogus_knob": 1})
    with pytest.raises(ValueError):
        engine.add("cpu_load", severity="apocalyptic")
    with pytest.raises(ValueError):
        engine.add("process_exit")     # needs a process name
    watcher = engine.add("process_exit", params={"name": "obs64.exe"},
                         label="OBS closing", severity="critical")
    assert watcher["severity"] == "critical"
    assert watcher["params"]["name"] == "obs64.exe"
    assert all(s in SEVERITIES for s in ("info", "notice", "critical"))


def test_watchers_persist_across_engine_restarts(tmp_path):
    engine, _ = make_engine(tmp_path, [{}])
    engine.add("disk_low", params={"drive": "D:\\", "min_free_gb": 25},
               label="games drive")
    reborn = WatcherEngine(path=tmp_path / "watchers.json",
                           snapshot_fn=lambda: {})
    labels = [w["label"] for w in reborn.list()]
    assert "games drive" in labels
    # Removal persists too.
    wid = next(w["id"] for w in reborn.list())
    assert reborn.remove(wid) is True
    third = WatcherEngine(path=tmp_path / "watchers.json",
                          snapshot_fn=lambda: {})
    assert third.list() == []


def test_ensure_defaults_seeds_once_and_respects_deletion(tmp_path):
    engine, _ = make_engine(tmp_path, [{}])
    engine.ensure_defaults()
    kinds = {w["kind"] for w in engine.list()}
    assert {"cpu_load", "disk_low", "battery_low", "memory_low"} <= kinds
    # User deletes one → a later ensure_defaults must NOT resurrect it.
    victim = next(w["id"] for w in engine.list() if w["kind"] == "battery_low")
    engine.remove(victim)
    engine.ensure_defaults()
    assert "battery_low" not in {w["kind"] for w in engine.list()}


def test_bad_listener_and_bad_sensor_never_kill_the_tick(tmp_path):
    def explode(_event):
        raise RuntimeError("listener bug")
    engine, _ = make_engine(
        tmp_path, [{"battery": {"pct": 5.0, "plugged": False}}],
        on_event=explode)
    engine.add("battery_low")
    # Watcher with a kind evaluate() raises on: params drive=None → TypeError
    # inside evaluate is swallowed per-watcher.
    engine.add("disk_low", params={"drive": ""})
    fired = engine.tick()              # must not raise
    assert len(fired) == 1
    assert engine.recent_events(5)[0]["kind"] == "battery_low"


def test_disabled_watcher_is_skipped(tmp_path):
    engine, _ = make_engine(
        tmp_path, [{"battery": {"pct": 5.0, "plugged": False}}])
    watcher = engine.add("battery_low")
    engine.set_enabled(watcher["id"], False)
    assert engine.tick() == []
    assert engine.list()[0]["status"] == "disabled"
