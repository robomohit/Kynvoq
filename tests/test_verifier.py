"""Tests for the post-task verification gate (app/verifier.py).

The contract: a task may only claim clean success when its evidence targets
check out against reality; otherwise the completion reason is rewritten to an
honest caveat. Checks are read-only and cheap.
"""
from __future__ import annotations

import os

import pytest

from app.verifier import dedupe_evidence, honest_reason, run_checks


def test_dedupe_keeps_newest_and_caps():
    ev = [("window", "a")] * 3 + [("file", f"f{i}") for i in range(9)]
    out = dedupe_evidence(ev)
    assert len(out) <= 6
    # Newest-first: the last files recorded are audited.
    assert ("file", "f8") in out
    # Duplicates collapse.
    assert sum(1 for k, t in out if (k, t) == ("window", "a")) <= 1


def test_file_check_passes_for_real_file(tmp_path):
    p = tmp_path / "out.txt"
    p.write_text("hello", encoding="utf-8")
    result = run_checks([("file", str(p))])
    assert result["verified"] is True
    assert result["checked"] == 1


def test_file_check_fails_for_missing_or_empty(tmp_path):
    missing = tmp_path / "nope.txt"
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    result = run_checks([("file", str(missing)), ("file", str(empty))])
    assert result["verified"] is False
    assert len(result["failed"]) == 2
    assert "could not confirm" in result["summary"]


def test_honest_reason_rewrites_only_on_failure(tmp_path):
    ok = run_checks([])
    assert honest_reason("Done.", ok) == "Done."
    missing = tmp_path / "gone.txt"
    bad = run_checks([("file", str(missing))])
    msg = honest_reason("Done.", bad)
    assert "double-check" in msg
    assert "gone.txt" in msg


@pytest.mark.skipif(os.name != "nt", reason="window enumeration is Windows-only")
def test_window_check_fails_for_absent_window():
    from app.widget.desktop_features import _visible_top_level_windows
    try:
        wins = _visible_top_level_windows(include_untitled=False)
    except Exception:
        pytest.skip("window enumeration unavailable")
    if not wins:
        pytest.skip("no visible windows to test against")
    result = run_checks([("window", "zzz-orynn-definitely-not-a-window-xyz")])
    assert result["verified"] is False


@pytest.mark.skipif(os.name != "nt", reason="needs live window enumeration")
def test_verifier_feeds_adaptive_learning(tmp_path, monkeypatch):
    """Verification outcomes are tallied per-app in the adaptive memory, and a
    repeat-offender app earns a caution line for future task prompts."""
    from app import adaptive_windows as aw
    from app.verifier import learn_from_result, verify_caution

    store = tmp_path / "profiles.json"
    monkeypatch.setattr(aw, "_profile_path", lambda: store, raising=False)
    # adaptive_windows resolves the path via workspace_state_path(_PROFILE_FILE)
    monkeypatch.setattr(aw, "workspace_state_path", lambda name: store, raising=False)

    missing = str(tmp_path / "ghost.txt")
    ev = [("window", "fakeapp"), ("file", missing)]
    result = run_checks(ev)      # both fail (no such window, no such file)
    assert result["verified"] is False

    # One unconfirmed run: not enough history → no caution yet.
    learn_from_result(ev, result)
    assert verify_caution("fakeapp") == ""
    # Second unconfirmed run crosses the threshold → caution kicks in.
    learn_from_result(ev, result)
    caution = verify_caution("fakeapp")
    assert "fakeapp" in caution and "VERIFY" in caution
    # A clean app stays quiet.
    assert verify_caution("someotherapp") == ""


def test_executor_note_evidence_records_success_targets(tmp_path):
    from app.tools import ToolExecutor
    ex = ToolExecutor(tmp_path)
    ex.verify_evidence = []
    ex.write_file("proof.txt", "content")
    assert any(k == "file" and t.endswith("proof.txt")
               for k, t in ex.verify_evidence)
    # And the recorded file actually verifies.
    assert run_checks(ex.verify_evidence)["verified"] is True
