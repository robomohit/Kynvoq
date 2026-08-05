"""Tests for reasoned proactivity (app/proactivity.py).

The contract under test: deterministic sensors still detect, but WHETHER and
HOW something surfaces is judged — an LLM triages fired events (with the old
deterministic ladder as the floor for every failure mode), and proactive
offers are mined from the user's own history instead of hand-authored rules.
The guards are deterministic and the model can never loosen them: critical
never waits on or is silenced by an LLM, suppression is confidence-gated,
nothing can be escalated to the voice rung, and suggestions pass a cooldown +
daily budget + ignored-strikes + mute-list gauntlet before the user hears a
word. No sleeps except the (tiny, bounded) timeout test; no network ever.
"""
from __future__ import annotations

import importlib
import threading
import time

import pytest

pro = importlib.import_module("app.proactivity")


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    """Per-test stores, and the real-LLM path hard-off so a forgotten stub can
    never turn into an HTTP call (conftest's fake keys would otherwise make
    llm_enabled() true)."""
    monkeypatch.setenv("ORYNN_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("ORYNN_PROACTIVE_LLM", "0")


def T(day: int, hour: int, minute: int = 0) -> float:
    """A deterministic local-time timestamp in August 2026."""
    return time.mktime((2026, 8, day, hour, minute, 0, 0, 0, -1))


def task(ts: float, text: str) -> dict:
    return {"ts": ts, "kind": "task", "text": text}


def notice(message: str = "Drive C:\\ is down to 9.0 GB free.") -> dict:
    return {"id": "e1", "kind": "disk_low", "label": "disk",
            "severity": "notice", "message": message}


def llm_json(payload: str):
    """An llm stub returning a fixed reply, recording every call."""
    calls: list = []

    def fn(system: str, prompt: str) -> str:
        calls.append((system, prompt))
        return payload
    fn.calls = calls
    return fn


# ── observation journal ──────────────────────────────────────────────────────

def test_note_observation_persists_normalizes_and_caps(monkeypatch):
    monkeypatch.setattr(pro, "OBS_MAX", 5)
    assert pro.note_observation("task", "   ") is None      # empty → dropped
    for i in range(8):
        pro.note_observation("task", f"open   obs {i}", ts=float(i))
    events = pro.observations()
    assert len(events) == 5                                  # capped
    assert events[-1]["text"] == "open obs 7"                # whitespace folded
    assert events[0]["text"] == "open obs 3"                 # oldest fell off


# ── triage: the rule floor ───────────────────────────────────────────────────

def test_critical_bypasses_llm_and_renders_instantly():
    def exploding_llm(system, prompt):
        raise AssertionError("critical must never consult the LLM")
    rendered = []
    event = dict(notice(), severity="critical",
                 message="Battery at 5% and unplugged.")
    pro.decide(event, rendered.append, llm=exploding_llm, block=True)
    assert rendered == [event]
    last = pro.recent_decisions(1)[0]
    assert last["source"] == "rule" and last["action"] == "surfaced"


def test_no_llm_available_falls_back_to_deterministic():
    rendered = []
    pro.decide(notice(), rendered.append, block=True)        # env kills the LLM
    assert len(rendered) == 1
    assert rendered[0]["message"] == notice()["message"]
    assert pro.recent_decisions(1)[0]["source"] == "fallback"


@pytest.mark.parametrize("reply", [
    "sorry, no json here",
    '{"surface": "not-even-a-bool", "confidence": "high"',   # broken JSON
])
def test_unusable_verdict_falls_back(reply):
    rendered = []
    pro.decide(notice(), rendered.append, llm=llm_json(reply), block=True)
    assert len(rendered) == 1 and rendered[0]["message"] == notice()["message"]
    assert pro.recent_decisions(1)[0]["source"] == "fallback"


def test_llm_exception_falls_back():
    def bad_llm(system, prompt):
        raise RuntimeError("provider down")
    rendered = []
    pro.decide(notice(), rendered.append, llm=bad_llm, block=True)
    assert len(rendered) == 1


def test_llm_timeout_falls_back():
    def slow_llm(system, prompt):
        time.sleep(0.5)
        return '{"surface": false, "confidence": 0.99}'
    rendered = []
    pro.decide(notice(), rendered.append, llm=slow_llm, block=True,
               timeout_s=0.05)
    assert len(rendered) == 1                                # deadline → floor


# ── triage: the judged path and its leash ────────────────────────────────────

def test_confident_suppression_is_honored_and_journaled():
    stub = llm_json('{"surface": false, "confidence": 0.9, '
                    '"reason": "user was just told"}')
    rendered = []
    pro.decide(notice(), rendered.append, llm=stub, block=True)
    assert rendered == []
    last = pro.recent_decisions(1)[0]
    assert last["action"] == "suppressed" and last["source"] == "llm"
    assert last["confidence"] == 0.9
    # The fired event still landed in the observation journal.
    assert any(e["kind"] == "watcher" for e in pro.observations())


def test_low_confidence_suppression_is_overruled():
    stub = llm_json('{"surface": false, "confidence": 0.3}')
    rendered = []
    pro.decide(notice(), rendered.append, llm=stub, block=True)
    assert len(rendered) == 1                                # surfaced anyway
    assert pro.recent_decisions(1)[0]["source"] == "fallback"


def test_llm_may_refine_message_and_downgrade_but_never_escalate():
    stub = llm_json('{"surface": true, "severity": "critical", '
                    '"message": "Disk almost full — want me to clear temp '
                    'files?", "suggestion": "run disk cleanup", '
                    '"confidence": 0.8}')
    rendered = []
    pro.decide(notice(), rendered.append, llm=stub, block=True)
    out = rendered[0]
    assert out["severity"] == "notice"          # escalation refused
    assert "clear temp files" in out["message"]  # rephrasing accepted
    assert out["suggestion"] == "run disk cleanup"
    stub2 = llm_json('{"surface": true, "severity": "info", '
                     '"confidence": 0.7}')
    rendered2 = []
    pro.decide(notice(), rendered2.append, llm=stub2, block=True)
    assert rendered2[0]["severity"] == "info"   # downgrade accepted
    assert rendered2[0]["message"] == notice()["message"]  # no override given


def test_decide_nonblocking_renders_from_background_thread():
    stub = llm_json('{"surface": true, "confidence": 0.9}')
    done = threading.Event()
    pro.decide(notice(), lambda ev: done.set(), llm=stub, block=False)
    assert done.wait(timeout=3.0), "background triage never rendered"


def test_llm_enabled_kill_switch(monkeypatch):
    assert pro.llm_enabled() is False            # fixture set the env to 0
    monkeypatch.delenv("ORYNN_PROACTIVE_LLM")
    assert pro.llm_enabled() is True             # conftest's fake keys exist
    for key in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                "GOOGLE_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert pro.llm_enabled() is False            # no key → no LLM, ever


# ── pattern mining: triggers derived from the user's own history ─────────────

def _habit_history(goal="open obs studio"):
    """The same goal at ~9:00 on four distinct days."""
    return [task(T(d, 9, m), goal) for d, m in ((1, 0), (2, 5), (3, 55), (4, 10))]


def test_habit_fires_inside_its_window_only():
    events = _habit_history()
    found = pro.mine_patterns(events, now=T(5, 9, 10))
    assert [s["kind"] for s in found] == ["habit"]
    assert found[0]["key"] == "habit:open obs studio"
    assert "usually" in found[0]["text"] and found[0]["confidence"] >= 0.6
    # Same day, wrong hour → silence.
    assert pro.mine_patterns(events, now=T(5, 15, 0)) == []


def test_habit_already_done_today_stays_silent():
    events = _habit_history() + [task(T(5, 9, 0), "open obs studio")]
    assert pro.mine_patterns(events, now=T(5, 9, 30)) == []


def test_scattered_times_are_not_a_habit():
    events = [task(T(d, h, 0), "open obs studio")
              for d, h in ((1, 6), (2, 12), (3, 18), (4, 23))]
    assert pro.mine_patterns(events, now=T(5, 12, 0)) == []


def test_stale_fires_only_when_well_overdue():
    # Varied hours (no time-of-day habit) but a steady ~2-day cadence.
    events = [task(T(d, h, 0), "back up my documents")
              for d, h in ((1, 10), (3, 16), (5, 22))]
    # ~2 days later is NOT overdue…
    assert pro.mine_patterns(events, now=T(7, 10, 0)) == []
    # …6 days later is.
    found = pro.mine_patterns(events, now=T(11, 10, 0))
    assert [s["kind"] for s in found] == ["stale"]
    assert "back up my documents" in found[0]["text"]


def test_sequence_offers_the_follow_up_after_its_antecedent():
    events = []
    for d in (1, 2, 3):
        events.append(task(T(d, 9, 0), "open obs studio"))
        events.append(task(T(d, 9, 20), "open capcut"))
    events.append(task(T(7, 9, 0), "open obs studio"))       # A just happened
    found = pro.mine_patterns(events, now=T(7, 9, 10))
    keys = {s["key"] for s in found}
    assert "seq:open obs studio>open capcut" in keys
    seq = next(s for s in found if s["kind"] == "sequence")
    assert "open capcut" in seq["text"] and "after" in seq["text"]
    # An hour after the antecedent the moment has passed.
    assert not any(s["kind"] == "sequence"
                   for s in pro.mine_patterns(events, now=T(7, 10, 30)))


# ── the gauntlet: cooldown, budget, strikes, mute, feedback ──────────────────

def test_cooldown_and_ignored_strikes_and_acceptance_reset():
    events = _habit_history()
    now1 = T(5, 9, 10)
    due = pro.pending_suggestions(now1, events)
    assert len(due) == 1
    key = due[0]["key"]
    pro._mark_surfaced(key, now1, counted=True)
    assert pro.pending_suggestions(now1 + 600, events) == []     # 24 h cooldown
    now2 = T(6, 9, 10)                                           # next day
    assert len(pro.pending_suggestions(now2, events)) == 1       # strike 1 < 2
    pro._mark_surfaced(key, now2, counted=True)
    now3 = T(7, 9, 10)
    assert pro.pending_suggestions(now3, events) == []           # 2 strikes → sleep
    pro.record_feedback(key, accepted=True)                      # "yes" resets
    assert len(pro.pending_suggestions(now3, events)) == 1


def test_declined_feedback_sleeps_a_week_and_mute_is_final():
    events = _habit_history()
    now = T(5, 9, 10)
    key = pro.pending_suggestions(now, events)[0]["key"]
    pro.record_feedback(key, accepted=False, now=now)
    assert pro.pending_suggestions(T(6, 9, 10), events) == []    # asleep
    assert len(pro.pending_suggestions(T(13, 9, 10), events)) == 1  # wakes
    pro.mute(key)
    assert pro.pending_suggestions(T(20, 9, 10), events) == []   # forever
    pro.unmute(key)
    assert len(pro.pending_suggestions(T(20, 9, 10), events)) == 1


def test_daily_budget_caps_suggestions(monkeypatch):
    monkeypatch.setattr(pro, "SUGGEST_DAILY_BUDGET", 1)
    events = _habit_history("open obs studio") + _habit_history("check my email")
    now = T(5, 9, 10)
    assert len(pro.pending_suggestions(now, events)) == 1        # room for one
    key = pro.pending_suggestions(now, events)[0]["key"]
    pro._mark_surfaced(key, now, counted=True)
    assert pro.pending_suggestions(now + 60, events) == []       # budget spent
    # A new local day refills the budget.
    assert len(pro.pending_suggestions(T(6, 9, 10), events)) == 1


# ── emitting offers ──────────────────────────────────────────────────────────

def test_offers_surface_on_the_silent_info_rung():
    events = _habit_history()
    seen = []
    emitted = pro.emit_due_suggestions(seen.append, now=T(5, 9, 10),
                                       events=events)
    assert len(emitted) == len(seen) == 1
    offer = seen[0]
    assert offer["kind"] == "suggestion" and offer["severity"] == "info"
    assert offer["suggestion_key"] == "habit:open obs studio"
    assert "Want me to" in offer["message"]                  # an offer, not an act
    # Cooldown + budget consumed: an immediate second pass is silent.
    assert pro.emit_due_suggestions(seen.append, now=T(5, 9, 15),
                                    events=events) == []


def test_llm_judge_can_veto_an_offer_without_burning_budget():
    events = _habit_history()
    stub = llm_json('{"surface": false, "confidence": 0.9, '
                    '"reason": "user is mid-game"}')
    seen = []
    assert pro.emit_due_suggestions(seen.append, llm=stub, now=T(5, 9, 10),
                                    events=events) == []
    assert seen == [] and len(stub.calls) == 1
    # Vetoed → cooldown starts (no re-ask this cycle) but no budget burned.
    brain = pro._load_brain()
    assert int(brain["budget"].get("used", 0)) == 0
    assert pro.pending_suggestions(T(5, 9, 20), events) == []
    last = pro.recent_decisions(1)[0]
    assert last["action"] == "suppressed" and "mid-game" in last["reason"]


def test_llm_judge_can_rephrase_an_offer():
    events = _habit_history()
    stub = llm_json('{"surface": true, "confidence": 0.85, "message": '
                    '"OBS time? I can open it and your usual scene."}')
    seen = []
    pro.emit_due_suggestions(seen.append, llm=stub, now=T(5, 9, 10),
                             events=events)
    assert seen[0]["message"] == "OBS time? I can open it and your usual scene."


def test_suggestions_preference_is_a_kill_switch(monkeypatch):
    prefs = importlib.import_module("app.preferences")
    monkeypatch.setattr(prefs, "get_all",
                        lambda: {"proactive_suggestions": False})
    seen = []
    assert pro.emit_due_suggestions(seen.append, now=T(5, 9, 10),
                                    events=_habit_history()) == []
    assert seen == []


def test_broken_listener_never_raises():
    def explode(_ev):
        raise RuntimeError("listener bug")
    emitted = pro.emit_due_suggestions(explode, now=T(5, 9, 10),
                                       events=_habit_history())
    assert len(emitted) == 1                     # emission survived the listener


# ── the voice feedback loop: spoken answers to surfaced offers ───────────────

def _surface_one(now=None):
    """Surface the habit offer and return (key, now_ts)."""
    now_ts = T(5, 9, 10) if now is None else now
    events = _habit_history()
    emitted = pro.emit_due_suggestions(lambda e: None, now=now_ts, events=events)
    assert len(emitted) == 1
    return emitted[0]["suggestion_key"], now_ts


def test_surfaced_offers_are_remembered_and_expire():
    key, now_ts = _surface_one()
    offers = pro.recent_offers(now_ts + 60)
    assert [o["key"] for o in offers] == [key]
    assert offers[0]["goal"] == "open obs studio"
    # Past the TTL a stale "yes" resolves to nothing.
    assert pro.recent_offers(now_ts + pro.OFFER_TTL_S + 1) == []


def test_normalize_response_handles_natural_speech():
    for spoken in ("yes", "Yeah", "do it", "GO AHEAD", "accept", "sure"):
        assert pro.normalize_response(spoken) == "accept"
    for spoken in ("not now", "not_now", "later", "no", "dismiss"):
        assert pro.normalize_response(spoken) == "not_now"
    for spoken in ("mute", "stop suggesting that", "never again", "Stop"):
        assert pro.normalize_response(spoken) == "mute"
    assert pro.normalize_response("what's the weather") is None


def test_accept_consumes_offer_and_resets_strikes():
    key, now_ts = _surface_one()
    offer, action, err = pro.respond_to_offer("yes", now=now_ts + 60)
    assert err == "" and action == "accept" and offer["key"] == key
    # Consumed: the same yes can't apply twice.
    _, _, err2 = pro.respond_to_offer("yes", now=now_ts + 120)
    assert "no recent suggestion" in err2
    # Accepted → ignore strikes reset (the habit is confirmed, keeps offering
    # after the cooldown).
    rec = pro._load_brain()["surfaced"][key]
    assert rec["ignored"] == 0 and rec["accepted"] == 1
    assert pro.recent_decisions(1)[0]["action"] == "user_accept"


def test_not_now_sleeps_a_week_via_the_same_gauntlet():
    key, now_ts = _surface_one()
    offer, action, err = pro.respond_to_offer("not now", now=now_ts + 60)
    assert err == "" and action == "not_now"
    events = _habit_history()
    assert pro.pending_suggestions(T(6, 9, 10), events) == []      # asleep
    assert len(pro.pending_suggestions(T(13, 9, 10), events)) == 1  # wakes


def test_mute_by_voice_is_permanent():
    key, now_ts = _surface_one()
    offer, action, err = pro.respond_to_offer("stop suggesting that",
                                              now=now_ts + 60)
    assert err == "" and action == "mute"
    assert pro.pending_suggestions(T(20, 9, 10), _habit_history()) == []
    pro.unmute(key)
    assert len(pro.pending_suggestions(T(20, 9, 10), _habit_history())) == 1


def test_query_picks_the_right_offer_and_ambiguity_defaults_to_newest():
    now_ts = T(5, 9, 10)
    events = (_habit_history("open obs studio")
              + _habit_history("check my email"))
    emitted = pro.emit_due_suggestions(lambda e: None, now=now_ts,
                                       events=events)
    assert len(emitted) == 2
    offer, action, err = pro.respond_to_offer("yes", query="email",
                                              now=now_ts + 60)
    assert err == "" and offer["goal"] == "check my email"
    # No query → the most recent remaining offer.
    offer2, _, err2 = pro.respond_to_offer("yes", now=now_ts + 90)
    assert err2 == "" and offer2["goal"] == "open obs studio"


def test_unmatched_query_lists_pending_offers():
    _surface_one()
    offer, action, err = pro.respond_to_offer("yes", query="quantum blender",
                                              now=T(5, 9, 20))
    assert offer is None and "pending" in err


def test_unrecognized_response_is_a_helpful_error():
    _surface_one()
    offer, action, err = pro.respond_to_offer("purple", now=T(5, 9, 20))
    assert offer is None and "accept" in err


def test_offers_prompt_block_teaches_the_routing():
    assert pro.offers_prompt_block(T(5, 9, 10)) == ""        # nothing pending
    _, now_ts = _surface_one()
    block = pro.offers_prompt_block(now_ts + 120)
    assert "ORYNN PROACTIVE OFFERS" in block
    assert "suggestion_feedback" in block
    assert "open obs studio" in block


# ── wiring: the overlay routes fired events through the judgment layer ───────

def test_overlay_routes_watcher_events_through_decide(monkeypatch):
    pytest.importorskip("PySide6")
    tbo = importlib.import_module("app.widget.textbox_overlay")
    controller = tbo.OverlayController(8000)
    routed = {}

    def fake_decide(event, render, **kw):
        routed["event"] = event
        routed["render"] = render
    monkeypatch.setattr(pro, "decide", fake_decide)
    event = notice()
    controller._route_watcher_event(event)
    assert routed["event"] == event
    assert routed["render"] == controller._on_watcher_event


# ── wiring: voice is the response channel (Live tool → feedback paths) ───────

def _controller():
    pytest.importorskip("PySide6")
    tbo = importlib.import_module("app.widget.textbox_overlay")
    return tbo.OverlayController(8000)


def _seed_offer(goal="open obs studio", kind="habit"):
    """Plant a fresh pending offer at REAL wall time — the Live handler runs
    on time.time(), so fixed 2026 timestamps would fall outside the offer TTL
    depending on when the suite runs."""
    key = f"{kind}:{goal}"
    pro._remember_offer({
        "key": key, "kind": kind, "goal": goal,
        "message": f"Around this time you usually “{goal}”. Want me to?",
        "ts": time.time()})
    return key


def test_live_accept_runs_the_goal_and_feeds_learning(monkeypatch):
    controller = _controller()
    key = _seed_offer()
    submitted = []
    monkeypatch.setattr(controller, "_submit_voice_task", submitted.append)
    res = controller._live_suggestion_feedback({"response": "yes"})
    assert res["ok"] and res["action"] == "accept"
    assert submitted == ["open obs studio"]          # the offer became a task
    assert "underway" in res["message"]              # model told to confirm
    rec = pro._load_brain()["surfaced"][key]
    assert rec["accepted"] == 1 and rec["ignored"] == 0


def test_live_not_now_and_mute_never_run_anything(monkeypatch):
    controller = _controller()
    key = _seed_offer()
    submitted = []
    monkeypatch.setattr(controller, "_submit_voice_task", submitted.append)
    res = controller._live_suggestion_feedback({"response": "not now"})
    assert res["ok"] and res["action"] == "not_now" and submitted == []
    assert "week" in res["message"]
    assert pro._load_brain()["muted"].get(key)       # the same week-sleep path
    _seed_offer()                                    # a fresh offer later
    res2 = controller._live_suggestion_feedback(
        {"response": "mute", "query": "obs"})
    assert res2["ok"] and res2["action"] == "mute" and submitted == []
    assert "never suggest" in res2["message"]
    assert pro._load_brain()["muted"].get(key) == -1.0   # permanent


def test_live_feedback_with_nothing_pending_degrades_gracefully(monkeypatch):
    controller = _controller()
    submitted = []
    monkeypatch.setattr(controller, "_submit_voice_task", submitted.append)
    res = controller._live_suggestion_feedback({"response": "yes"})
    assert not res["ok"] and submitted == []
    assert "respond normally" in res["message"]      # model told to just talk


def test_suggestion_surfacing_slips_context_into_running_live(monkeypatch):
    controller = _controller()
    notes = []

    class FakeLive:
        def send_context_update(self, text):
            notes.append(text)
    controller._live = FakeLive()
    monkeypatch.setattr(controller, "_live_is_running", lambda: True)
    tbo = importlib.import_module("app.widget.textbox_overlay")
    monkeypatch.setattr(tbo.time, "sleep", lambda s: None)
    controller._on_watcher_event({
        "kind": "suggestion", "label": "habit", "severity": "info",
        "message": "Around this time you usually open OBS. Want me to?"})
    assert len(notes) == 1
    assert "SILENTLY" in notes[0] and "suggestion_feedback" in notes[0]
    assert "open OBS" in notes[0]
    # A plain watcher event does NOT get the offer note.
    controller._on_watcher_event({
        "kind": "disk_low", "label": "disk", "severity": "info",
        "message": "Drive C:\\ is down to 9 GB."})
    assert len(notes) == 1


def test_live_context_block_includes_pending_offers():
    controller = _controller()
    _seed_offer()
    block = controller._live_context_block()
    assert "ORYNN PROACTIVE OFFERS" in block
    assert "open obs studio" in block
