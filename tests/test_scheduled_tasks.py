"""Scheduled reminders AND tasks, creatable by voice.

Pins the fix for: "I asked it to send a message at 3am and it said it can only
remind, not schedule actions." Live now has schedule_task / list_scheduled_tasks
/ cancel_scheduled_task, backed by the persistent scheduled-recipes daemon, with
one-shot ("once …") support so clock-time requests work without a recurrence.
"""
import importlib
from datetime import datetime

import pytest

df = importlib.import_module("app.widget.desktop_features")
tbo = importlib.import_module("app.widget.textbox_overlay")


# ── time-spec validation ─────────────────────────────────────────────────────
@pytest.mark.parametrize("when", [
    "09:00", "23:59", "mon 09:00", "sun 07:30", "every 30m", "every 1m",
    "once 03:00", "once 2026-07-05 03:00", "ONCE 03:00", " 09:00 ",
])
def test_valid_when_formats(when):
    assert df.schedule_when_is_valid(when)


@pytest.mark.parametrize("when", [
    "", "3am", "once", "once 3am", "every x", "every 0m", "noon 09:00",
    "25:00", "09:61", "once 2026-13-01 03:00", "mon tue 09:00",
])
def test_invalid_when_formats(when):
    assert not df.schedule_when_is_valid(when)


# ── due logic ────────────────────────────────────────────────────────────────
def test_once_fires_at_matching_time_only():
    at3 = datetime(2026, 7, 5, 3, 0)
    assert df.schedule_item_due("once 03:00", at3, 0)
    assert not df.schedule_item_due("once 03:00", datetime(2026, 7, 5, 3, 1), 0)
    # Date-qualified one-shot only fires on that date.
    assert df.schedule_item_due("once 2026-07-05 03:00", at3, 0)
    assert not df.schedule_item_due("once 2026-07-06 03:00", at3, 0)


def test_daily_weekly_and_interval_due():
    now = datetime(2026, 7, 6, 9, 0)   # a Monday
    assert df.schedule_item_due("09:00", now, 0)
    assert df.schedule_item_due("mon 09:00", now, 0)
    assert not df.schedule_item_due("tue 09:00", now, 0)
    assert df.schedule_item_due("every 30m", now, 0)


# ── Live tool handlers ───────────────────────────────────────────────────────
@pytest.fixture()
def sched_store(tmp_path, monkeypatch):
    monkeypatch.setattr(df, "_sched_path", lambda: tmp_path / "sched.json")
    return tmp_path


@pytest.fixture()
def controller():
    return tbo.OverlayController(8000)


def test_schedule_task_creates_persistent_item(controller, sched_store):
    res = controller._live_schedule_task({
        "when": "once 03:00",
        "goal": "send Alex a message saying good morning",
        "name": "3am message",
    })
    assert res["ok"]
    assert "One-time" in res["message"]
    items = df.list_scheduled()
    assert len(items) == 1
    assert items[0]["when"] == "once 03:00"
    # An action goal (not "remind me to…") is reported as a runnable task.
    assert "task" in res["message"]


def test_schedule_task_rejects_bad_input(controller, sched_store):
    assert not controller._live_schedule_task({"when": "3am", "goal": "x"})["ok"]
    assert not controller._live_schedule_task({"when": "09:00", "goal": ""})["ok"]
    assert df.list_scheduled() == []


def test_list_and_cancel_scheduled(controller, sched_store):
    controller._live_schedule_task({"when": "09:00", "goal": "remind me to stretch"})
    controller._live_schedule_task({"when": "mon 10:00", "goal": "open my dashboard"})
    listed = controller._live_list_scheduled()
    assert listed["ok"] and listed["count"] == 2

    # Ambiguous query → refuse, tell the model to ask.
    both = controller._live_cancel_scheduled({"query": "o"})
    assert not both["ok"] and "Several match" in both["message"]

    ok = controller._live_cancel_scheduled({"query": "stretch"})
    assert ok["ok"]
    assert df.list_scheduled()[0]["goal"] == "open my dashboard"

    none = controller._live_cancel_scheduled({"query": "stretch"})
    assert not none["ok"]


def test_live_declares_schedule_tools():
    src = open("app/widget/gemini_live.py", encoding="utf-8").read()
    for tool in ("schedule_task", "list_scheduled_tasks", "cancel_scheduled_task"):
        assert f'name="{tool}"' in src


def test_schedule_task_merges_runtime_context(controller, sched_store):
    res = controller._live_schedule_task({
        "when": "once 03:00",
        "goal": "send Alex a message",
        "context": "use WhatsApp, say 'happy birthday!'",
    })
    assert res["ok"]
    goal = df.list_scheduled()[0]["goal"]
    assert "send Alex a message" in goal
    assert "happy birthday" in goal


# ── silent scheduled actions vs. audible reminders ──────────────────────────
@pytest.fixture()
def wired(controller, monkeypatch):
    """Controller with sound + submission + signals instrumented."""
    voice = importlib.import_module("app.widget.voice")
    calls = {"cue": [], "speak": [], "submit": [], "glow": [], "toast": []}
    monkeypatch.setattr(voice, "cue", lambda kind: calls["cue"].append(kind))
    monkeypatch.setattr(voice, "speak", lambda text: calls["speak"].append(text))
    monkeypatch.setattr(
        controller, "_submit_voice_task",
        lambda text, scheduled=False: calls["submit"].append((text, scheduled)))
    controller.glowStateRequested.connect(calls["glow"].append)
    controller.notifyRequested.connect(lambda t, m: calls["toast"].append(m))
    return controller, calls


def test_scheduled_action_is_silent_with_working_glow(wired):
    controller, calls = wired
    controller._on_scheduled_due("send Alex a message saying good morning", "auto")
    assert calls["cue"] == []            # no chime — user is likely asleep
    assert calls["speak"] == []          # no voice
    assert "working" in calls["glow"]    # violet status light instead
    assert calls["toast"] and "scheduled task" in calls["toast"][0].lower()
    assert calls["submit"] == [("send Alex a message saying good morning", True)]


def test_scheduled_reminder_still_chimes_green(wired):
    controller, calls = wired
    controller._on_scheduled_due("remind me to stretch", "auto")
    assert calls["cue"] == ["reminder"]  # audible — being heard is the point
    assert "reminder" in calls["glow"]   # green, not the speaking blue
    assert calls["submit"] == []         # nothing to execute


def test_finalize_scheduled_task_flashes_and_toasts_silently(wired):
    controller, calls = wired
    controller._scheduled_task_ids.add("t-1")
    controller._maybe_finalize({"type": "done", "task_id": "t-1",
                                "reason": "message sent"})
    assert calls["cue"] == []                       # still silent
    assert calls["glow"][-1] == "success"           # green flash
    assert any("message sent" in m for m in calls["toast"])
    assert "t-1" not in controller._scheduled_task_ids

    controller._scheduled_task_ids.add("t-2")
    controller._maybe_finalize({"type": "failed", "task_id": "t-2"})
    assert calls["glow"][-1] == "error"             # light red flash


def test_finalize_voice_task_keeps_chime_and_gains_flash(wired):
    controller, calls = wired
    controller._voice_task_ids.add("t-3")
    controller._maybe_finalize({"type": "done", "task_id": "t-3"})
    assert calls["cue"] == ["done"]                 # user was present — chime
    assert calls["glow"][-1] == "success"
    assert calls["toast"] == []                     # no toast needed
