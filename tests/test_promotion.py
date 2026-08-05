"""Tests for the promotion pipeline (app/promotion.py).

The contract: only VERIFIED, repeated successes earn a workflow offer; the
offer is precise (exact normalized goal), single-shot per week, and never
fires for goals that already have a matching workflow.
"""
from __future__ import annotations

from app import promotion
from app.promotion import (
    PROMOTE_AT,
    REOFFER_AFTER_S,
    normalize_goal,
    note_verified_success,
    success_count,
)


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(promotion, "_tally_path",
                        lambda: tmp_path / "promotion_tally.json")


def test_normalize_strips_noise_and_rejects_trivial():
    assert normalize_goal("  Open Notepad, please!  ") == "open notepad please"
    assert normalize_goal("Open Notepad please") == "open notepad please"
    # Sub-two-word goals are not habits.
    assert normalize_goal("hi") == ""
    assert normalize_goal("") == ""


def test_offer_appears_exactly_at_threshold(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    goal = "open notepad and type the daily standup template"
    for i in range(1, PROMOTE_AT):
        assert note_verified_success(goal, now=float(i)) is None
    offer = note_verified_success(goal, now=float(PROMOTE_AT))
    assert offer is not None
    assert "workflow" in offer
    assert "3rd" in offer
    assert success_count(goal) == PROMOTE_AT


def test_offer_not_repeated_within_a_week(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    goal = "resize my wallpaper folder images"
    for i in range(PROMOTE_AT):
        note_verified_success(goal, now=float(i))
    # Next verified success the same day: no nagging.
    assert note_verified_success(goal, now=100.0) is None
    # A week later, still un-saved → one gentle re-offer.
    again = note_verified_success(goal, now=100.0 + REOFFER_AFTER_S + 1)
    assert again is not None and "workflow" in again


def test_different_goals_tally_separately(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert note_verified_success("open notepad and write A", now=1.0) is None
    assert note_verified_success("open notepad and write B", now=2.0) is None
    assert note_verified_success("open notepad and write A", now=3.0) is None
    assert success_count("open notepad and write A") == 2
    assert success_count("open notepad and write B") == 1


def test_existing_workflow_suppresses_offer(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    goal = "tidy the downloads folder"
    monkeypatch.setattr(
        promotion, "_has_matching_workflow",
        lambda norm: norm == normalize_goal(goal))
    for i in range(PROMOTE_AT + 2):
        assert note_verified_success(goal, now=float(i)) is None
    # An unrelated goal still gets its offer.
    other = "rename my screenshot files by date"
    for i in range(PROMOTE_AT - 1):
        note_verified_success(other, now=float(i))
    assert note_verified_success(other, now=99.0) is not None


def test_workflow_title_and_trigger_matching(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from app import workflows

    monkeypatch.setattr(
        workflows, "all_workflows",
        lambda: [{"title": "Tidy the Downloads folder!",
                  "triggers": ["clean downloads now"]}])
    assert promotion._has_matching_workflow(
        normalize_goal("tidy the downloads folder")) is True
    assert promotion._has_matching_workflow(
        normalize_goal("clean downloads now")) is True
    assert promotion._has_matching_workflow(
        normalize_goal("something entirely else")) is False


def test_tally_is_capped(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(promotion, "MAX_TALLY", 10)
    for i in range(15):
        note_verified_success(f"unique goal number {i} with words", now=float(i))
    from app.state_store import read_json
    data = read_json(tmp_path / "promotion_tally.json", {})
    assert len(data["tally"]) <= 10
    # Newest survive, oldest fell off.
    assert success_count("unique goal number 14 with words") == 1
    assert success_count("unique goal number 0 with words") == 0


def test_trivial_or_empty_goal_never_offers(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    for _ in range(10):
        assert note_verified_success("hi", now=1.0) is None
        assert note_verified_success("", now=1.0) is None
    assert success_count("hi") == 0


def test_finalize_appends_offer_on_third_verified_success(
        tmp_path, monkeypatch, workspace):
    """End-to-end through agent._finalize: three verified 'done's for the same
    goal → the third completion reason carries the workflow offer, and the
    _verify_note channel (which feeds the done SSE payload) carries it too."""
    from types import SimpleNamespace
    from app.agent import AgentService
    from app.log_emitter import log_emitter

    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(promotion, "_has_matching_workflow", lambda norm: False)
    s = AgentService(workspace, log_emitter=log_emitter)
    completions: list = []
    s._on_task_complete = lambda tid, status, reason: \
        completions.append((tid, status, reason))
    proof = tmp_path / "proof.txt"
    proof.write_text("real evidence", encoding="utf-8")
    goal = "open notepad and save the meeting notes"
    for i in range(3):
        tid = f"promo-{i}"
        if not hasattr(s, "_verify_ctx"):
            s._verify_ctx = {}
        if not hasattr(s, "_task_goals"):
            s._task_goals = {}
        s._verify_ctx[tid] = SimpleNamespace(
            verify_evidence=[("file", str(proof))])
        s._task_goals[tid] = goal
        s._finalize(tid, "done", "Done.")
    reasons = [r for _, _, r in completions]
    assert all("workflow" not in r for r in reasons[:2])
    assert "workflow" in reasons[2]
    assert "workflow" in s._verify_note["promo-2"]
    # The goal stash never leaks.
    assert s._task_goals == {}


def test_finalize_ignores_unverifiable_and_failed_runs(
        tmp_path, monkeypatch, workspace):
    """Chat replies (no evidence) and failed verifications never feed the
    tally — the promotion signal stays honest."""
    from types import SimpleNamespace
    from app.agent import AgentService
    from app.log_emitter import log_emitter

    _isolate(tmp_path, monkeypatch)
    s = AgentService(workspace, log_emitter=log_emitter)
    s._on_task_complete = lambda *a: None
    goal = "open notepad and save the meeting notes"
    for i in range(5):
        tid = f"chat-{i}"
        if not hasattr(s, "_verify_ctx"):
            s._verify_ctx = {}
        if not hasattr(s, "_task_goals"):
            s._task_goals = {}
        # No checkable evidence → verified-but-vacuous → must not count.
        s._verify_ctx[tid] = SimpleNamespace(verify_evidence=[])
        s._task_goals[tid] = goal
        s._finalize(tid, "done", "Done.")
    for i in range(5):
        tid = f"fail-{i}"
        s._verify_ctx[tid] = SimpleNamespace(
            verify_evidence=[("file", str(tmp_path / "ghost.txt"))])
        s._task_goals[tid] = goal
        s._finalize(tid, "done", "Done.")   # verification FAILS
    assert success_count(goal) == 0
