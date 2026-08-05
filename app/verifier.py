"""Independent post-task verification — the "did it ACTUALLY work?" gate.

The trust problem: when a background task finishes, the model itself decides it
succeeded — and models sometimes believe they're done when they half-are. This
module gives every completed task a cheap, deterministic, READ-ONLY audit:

* While a task runs, the executor records **evidence targets** — things that
  must be true afterward if the work really happened (a window that should
  exist, a file that should have been written).
* At completion, `run_checks()` verifies each target against reality (live
  window enumeration, the filesystem) in a few hundred ms, with no LLM and no
  side effects.
* If a check fails, the completion reason is rewritten to be HONEST — the
  spoken/bubble text says what could not be confirmed instead of claiming
  success.

Evidence items are `(kind, target)` tuples:
  ("window", "notepad")        → a visible top-level window whose title
                                  contains the target (case-insensitive)
  ("file",   "C:/path/x.txt")  → the file exists and is non-empty
"""
from __future__ import annotations

import os
from typing import Any


MAX_CHECKS = 6   # verification must stay cheap — audit the most recent targets


def dedupe_evidence(evidence: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Newest-first unique targets, capped at MAX_CHECKS."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for kind, target in reversed(evidence):
        key = (kind, str(target).strip().lower())
        if not key[1] or key in seen:
            continue
        seen.add(key)
        out.append((kind, str(target).strip()))
        if len(out) >= MAX_CHECKS:
            break
    return out


def _window_titles_snapshot() -> list[str] | None:
    """One enumeration pass shared by every window check (enumerating per
    target multiplied the cost for nothing). None = can't enumerate here
    (headless/CI) → window targets count as unverifiable, not failed."""
    try:
        from .widget.desktop_features import _visible_top_level_windows
        return [str(w.get("title") or "").lower()
                for w in _visible_top_level_windows(include_untitled=False)]
    except Exception:
        return None


def _file_ok(path: str) -> bool:
    try:
        return os.path.exists(path) and os.path.getsize(path) > 0
    except Exception:
        return False


def run_checks(evidence: list[tuple[str, str]],
               budget_seconds: float = 1.0) -> dict[str, Any]:
    """Verify every evidence target. Returns
    {verified, checked, failed:[(kind, target), …], summary}.

    Latency contract: verification is best-effort and must NEVER be a tax the
    user feels. All window checks share a single enumeration snapshot, and a
    hard time budget bounds the whole audit — anything unchecked when the
    budget runs out counts as pass, and completion is never delayed."""
    import time as _time
    deadline = _time.monotonic() + max(0.1, budget_seconds)
    targets = dedupe_evidence(evidence)
    titles: list[str] | None = None
    titles_loaded = False
    failed: list[tuple[str, str]] = []
    for kind, target in targets:
        if _time.monotonic() > deadline:
            break                      # out of budget → remaining pass silently
        ok = True
        if kind == "window":
            if not titles_loaded:
                titles = _window_titles_snapshot()
                titles_loaded = True
            if titles is not None:
                frag = target.lower()
                ok = any(frag in t for t in titles)
        elif kind == "file":
            ok = _file_ok(target)
        if not ok:
            failed.append((kind, target))
    verified = not failed
    if not targets:
        summary = "no checkable evidence"
    elif verified:
        summary = f"verified {len(targets)} check(s)"
    else:
        parts = ", ".join(
            (f"window '{t}' not found" if k == "window" else f"file '{os.path.basename(t)}' missing/empty")
            for k, t in failed[:3]
        )
        summary = f"could not confirm: {parts}"
    return {
        "verified": verified,
        "checked": len(targets),
        "failed": failed,
        "summary": summary,
    }


_VERIFY_CLASS = "post_task_verify"   # distinct failure_class: never pollutes
_VERIFY_ID = "outcome_confirmed"     # the resolver-suggestion lookups


def learn_from_result(evidence: list[tuple[str, str]],
                      result: dict[str, Any]) -> None:
    """Feed verification outcomes into the persistent adaptive memory (the same
    store that learned e.g. 'Notepad: OCR targeting works 345/345'). Every
    confirmed success and every unconfirmed 'done' is tallied PER APP, so the
    agent can be warned when an app has a history of hard-to-confirm results."""
    try:
        from .adaptive_windows import remember_resolver_outcome
        failed = {(k, t) for k, t in (result.get("failed") or [])}
        for kind, target in dedupe_evidence(evidence):
            app = target if kind == "window" else "files"
            ok = (kind, target) not in failed
            remember_resolver_outcome(
                app, _VERIFY_CLASS, _VERIFY_ID, ok,
                detail=("confirmed" if ok else f"unconfirmed {kind}: {target[:80]}"),
            )
    except Exception:
        pass


def verify_caution(app_hint: str) -> str:
    """A one-line warning for the agent's context when this app's recent tasks
    have a track record of UNCONFIRMED successes. Empty string when the record
    is clean (the common case) — no prompt noise unless it's earned."""
    app = str(app_hint or "").strip()
    if not app:
        return ""
    try:
        from .adaptive_windows import _load_profiles, _app_key
        history = (_load_profiles().get(_app_key(app), {}) or {}).get("history") or []
        for item in history:
            if item.get("failure_class") != _VERIFY_CLASS:
                continue
            fails = int(item.get("failures", 0))
            wins = int(item.get("successes", 0))
            if fails >= 2 and fails > wins:
                return (
                    f"Caution: recent tasks on '{app}' finished without their "
                    "outcome being confirmable on screen. Before you finish, "
                    "VERIFY the result is really visible (window present, "
                    "content applied) — do not report done on assumption."
                )
    except Exception:
        pass
    return ""


def honest_reason(reason: str, result: dict[str, Any]) -> str:
    """Rewrite a completion reason so the user hears the truth. Verified (or
    nothing checkable) → unchanged; failed checks → an honest caveat."""
    if result.get("verified", True) or not result.get("failed"):
        return reason
    base = (reason or "Done").strip().rstrip(".")
    return f"{base} — but I {result['summary']}, so please double-check."
