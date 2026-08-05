"""Passive learning from spoken corrections.

When the user pushes back mid-conversation — "no, not that one", "I meant
Chrome", "that's the wrong file" — that's free, high-value training signal.
Nobody says "remember this", so nothing used to be captured. This module
detects correction-shaped utterances and quietly stores a compact lesson in
the knowledge store (owner="assistant" so it renders in Orynn's memory block),
pairing what Orynn had just said/done with how the user corrected it.

Design bias: PRECISION over recall. A missed correction costs nothing (the
user repeats themselves anyway); a false positive pollutes the prompt with a
bogus "lesson" forever. So the detector only fires on unambiguous correction
openers, and explicitly ignores polite-"no" idioms ("no thanks", "no worries").
Stored lessons are capped — newest _MAX_KEPT survive.
"""
from __future__ import annotations

import re

_MAX_KEPT = 10
_CATEGORY = "correction"

# Unambiguous correction openers. Anchored at the start of the utterance.
_CORRECTION_RE = re.compile(
    r"^(?:"
    r"no+[,.\s]|nope[,.\s]|"
    r"not (?:that|this|there|the one)|"
    r"i (?:meant|said|asked for|wanted)\b|"
    r"that'?s (?:wrong|not (?:it|right|what i))|"
    r"wrong (?:one|app|window|file|folder|tab|button)|"
    r"don'?t (?:do|open|close|type) that|"
    r"stop[,.\s]+(?:that|it|no)\b|"
    r"undo that\b|go back[,.\s]+i (?:meant|said)"
    r")",
    re.IGNORECASE,
)

# Polite/negative idioms that start with "no" but are NOT corrections.
_NOT_CORRECTION_RE = re.compile(
    r"^(?:no+[,.\s]+)?(?:thanks|thank you|worries|problem|i'?m (?:good|fine|okay|ok)|"
    r"that'?s (?:all|it|fine|okay|ok|great|perfect)|never ?mind|nothing)\b",
    re.IGNORECASE,
)


def looks_like_correction(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 4:
        return False
    if _NOT_CORRECTION_RE.match(t):
        return False
    if not _CORRECTION_RE.match(t):
        return False
    # A bare "no." carries no lesson — require some corrective content.
    return len(t.split()) >= 2


def lesson_text(orynn_context: str, correction: str) -> str:
    ctx = re.sub(r"\s+", " ", (orynn_context or "")).strip()[:140]
    corr = re.sub(r"\s+", " ", (correction or "")).strip()[:140]
    if ctx:
        return (f"Auto-learned correction: after Orynn said/did \"{ctx}\", "
                f"the user corrected: \"{corr}\". Apply this next time.")
    return f"Auto-learned correction: the user corrected Orynn: \"{corr}\". Apply this next time."


def record_correction(orynn_context: str, correction: str) -> bool:
    """Store the lesson (deduped by the knowledge store) and prune old ones.
    Returns True if something new was stored."""
    try:
        from . import knowledge
        fact = knowledge.add_fact(
            lesson_text(orynn_context, correction),
            owner="assistant",          # renders under "learned on your own"
            category=_CATEGORY,
        )
        _prune(knowledge)
        return fact is not None
    except Exception:
        return False


def _prune(knowledge) -> None:
    """Keep only the newest _MAX_KEPT corrections so the prompt never bloats."""
    try:
        facts = knowledge._load()
        corrections = [f for f in facts
                       if (f.get("category") or "") == _CATEGORY]
        if len(corrections) <= _MAX_KEPT:
            return
        corrections.sort(key=lambda f: float(f.get("created_at") or 0.0))
        drop = {id(f) for f in corrections[:len(corrections) - _MAX_KEPT]}
        knowledge._save([f for f in facts if id(f) not in drop])
    except Exception:
        pass


__all__ = ["looks_like_correction", "lesson_text", "record_correction"]
