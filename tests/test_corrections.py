"""Tests for passive correction learning (app/corrections.py).

The detector must be PRECISE: a missed correction is harmless, a false
positive stores a bogus lesson in Orynn's permanent memory.
"""
from __future__ import annotations

import pytest

from app import corrections
from app.corrections import lesson_text, looks_like_correction, record_correction


# ── detector: true corrections ────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "no, not that one",
    "No no, I meant Chrome",
    "not that window, the other one",
    "I meant the downloads folder",
    "I said notepad, not wordpad",
    "that's wrong, close it",
    "wrong app, I wanted Spotify",
    "don't open that, open Discord",
    "that's not what I asked for",
    "undo that please",
])
def test_detects_real_corrections(text):
    assert looks_like_correction(text) is True


# ── detector: must NOT fire on these ─────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "no thanks",
    "no, thank you",
    "no worries",
    "no problem at all",
    "nothing else",
    "never mind",
    "that's all for now",
    "that's perfect",
    "open notepad",
    "what's the weather",
    "note down my address",          # starts with 'no' inside a word
    "no",                            # bare no carries no lesson
    "",
])
def test_ignores_non_corrections(text):
    assert looks_like_correction(text) is False


# ── lesson formatting ─────────────────────────────────────────────────────────
def test_lesson_pairs_context_with_correction():
    msg = lesson_text("Opening Wordpad now", "no, I meant Notepad")
    assert "Wordpad" in msg and "Notepad" in msg
    assert "correct" in msg.lower()


def test_lesson_without_context_still_useful():
    msg = lesson_text("", "wrong one, use Chrome")
    assert "Chrome" in msg


# ── storage + prune ───────────────────────────────────────────────────────────
def test_record_and_prune(tmp_path, monkeypatch):
    from app import knowledge
    monkeypatch.setattr(knowledge, "store_path", lambda: tmp_path / "kb.json")

    assert record_correction("Opening Wordpad", "no, I meant Notepad") is True
    facts = knowledge.all_facts()
    assert any(f.get("category") == "correction" for f in facts)
    # Corrections render in the memory prompt (owner=assistant branch).
    block = knowledge.as_prompt_block()
    assert "Notepad" in block

    # Prune: flood with corrections; only the newest _MAX_KEPT survive.
    for i in range(corrections._MAX_KEPT + 5):
        record_correction(f"did thing {i}", f"no, I meant target-{i} instead")
    kept = [f for f in knowledge.all_facts()
            if f.get("category") == "correction"]
    assert len(kept) <= corrections._MAX_KEPT
    # Newest survived.
    assert any(f"target-{corrections._MAX_KEPT + 4}" in f.get("text", "")
               for f in kept)
