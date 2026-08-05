"""Promotion pipeline — repeated verified successes become offered commands.

The growth half of the kernel doctrine: Orynn starts with a few deterministic
primitives, and everything it learns must EARN its way up. A task goal that
has finished successfully — and passed the post-task verifier with real
checkable evidence, not just the model claiming "done" — three separate times
is a habit worth naming. At that point Orynn appends one short offer to the
completion message: save it as a workflow, and next time it runs as a
one-line voice command.

Precision over recall, everywhere:
* only VERIFIED successes count (``verified and checked > 0`` — chat replies
  and unverifiable runs never inflate the tally);
* goals match by exact normalized text, not fuzzy similarity — a wrong offer
  costs trust, a missed one costs nothing;
* a goal that already has a matching workflow is never offered;
* one offer per goal per week, max — an ignored offer is an answer.

Like the verifier, this must never be a tax: one small JSON read/write on the
task-completion path, no LLM, and every caller wraps it in try/except.
"""
from __future__ import annotations

import re
import time
from typing import Any

from .state_store import read_json, workspace_state_path, write_json

PROMOTE_AT = 3            # verified successes before the offer
REOFFER_AFTER_S = 7 * 24 * 3600   # an ignored offer sleeps a week
MAX_TALLY = 200           # keep the store tiny; oldest goals fall off
MIN_WORDS = 2             # "hi" is not a habit


def _tally_path():
    return workspace_state_path("promotion_tally.json")


def normalize_goal(goal: str) -> str:
    """Collapse a goal to its comparable core: lowercase words only. Exact
    match on this is deliberately strict — near-duplicates stay separate."""
    words = re.findall(r"[a-z0-9]+", str(goal or "").lower())
    if len(words) < MIN_WORDS:
        return ""
    return " ".join(words)


def _has_matching_workflow(norm: str) -> bool:
    try:
        from . import workflows
        for wf in workflows.all_workflows():
            if normalize_goal(wf.get("title") or "") == norm:
                return True
            if any(normalize_goal(t) == norm for t in wf.get("triggers") or []):
                return True
    except Exception:
        pass
    return False


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def note_verified_success(goal: str, now: float | None = None) -> str | None:
    """Record one verified success for this goal. Returns the offer line to
    append to the completion message when the goal just earned promotion,
    else None (the overwhelmingly common case)."""
    norm = normalize_goal(goal)
    if not norm:
        return None
    ts = time.time() if now is None else float(now)
    path = _tally_path()
    data = read_json(path, {"version": 1, "tally": {}})
    tally = data.get("tally")
    if not isinstance(tally, dict):
        tally = {}
        data = {"version": 1, "tally": tally}
    entry = tally.get(norm)
    if not isinstance(entry, dict):
        entry = {"count": 0, "example": "", "last_ts": 0.0, "offered_ts": 0.0}
        tally[norm] = entry
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["example"] = str(goal)[:200]
    entry["last_ts"] = ts

    offer: str | None = None
    offered_ts = float(entry.get("offered_ts", 0.0))
    offer_ok = offered_ts <= 0.0 or ts - offered_ts >= REOFFER_AFTER_S
    if (entry["count"] >= PROMOTE_AT
            and offer_ok
            and not _has_matching_workflow(norm)):
        entry["offered_ts"] = ts
        offer = (
            f"By the way — that's the {_ordinal(entry['count'])} time this has "
            "worked. Say 'save this as a workflow' and it becomes a one-line "
            "command."
        )

    if len(tally) > MAX_TALLY:
        for stale in sorted(tally, key=lambda k: tally[k].get("last_ts", 0.0))[
                :len(tally) - MAX_TALLY]:
            tally.pop(stale, None)
    write_json(path, data)
    return offer


def success_count(goal: str) -> int:
    """How many verified successes this goal has banked (0 if unseen)."""
    norm = normalize_goal(goal)
    if not norm:
        return 0
    data = read_json(_tally_path(), {})
    entry = (data.get("tally") or {}).get(norm) if isinstance(data, dict) else None
    return int(entry.get("count", 0)) if isinstance(entry, dict) else 0
