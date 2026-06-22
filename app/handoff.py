"""Structured handoff from desktop worker → Live / bubble (WS3)."""
from __future__ import annotations

import re
from typing import Any, Literal, Optional, TypedDict


class HandoffResult(TypedDict, total=False):
    user_message: str
    status: Literal["success", "failed", "partial"]
    debug_reason: str
    task_id: Optional[str]
    ok: bool


_ABANDONED_RE = re.compile(
    r"server\s+restarted|task\s+was\s+abandoned|abandoned",
    re.IGNORECASE,
)


def humanize_reason(reason: str) -> str:
    """Map backend failure text to a user-safe phrase — never opaque abandon strings."""
    text = re.sub(r"\s+", " ", str(reason or "")).strip()
    if not text:
        return "the task ended before it could run"
    if _ABANDONED_RE.search(text):
        return "the task ended before it could run"
    if text.lower().startswith("failed:"):
        text = text[7:].strip() or text
    return text[:300]


def handoff_from_terminal_event(
    ev: dict[str, Any],
    *,
    goal: str = "",
) -> HandoffResult:
    """Build a HandoffResult from a terminal task SSE/poll event."""
    task_id = str(ev.get("task_id") or "")
    et = str(ev.get("type") or "")
    raw = str(ev.get("reason") or ev.get("message") or "").strip()
    debug = raw or "no reason recorded"
    complete = ev.get("complete")
    ok = et in ("done", "complete") and complete is not False
    if et in ("failed", "error", "cancelled"):
        ok = False
    human = humanize_reason(raw) if not ok else (raw or f"Finished: {goal or 'the task'}")
    if ok:
        user = f"Done — {human}" if human else f"Finished {goal or 'the task'}."
        status: Literal["success", "failed", "partial"] = "success"
    else:
        user = human or "Couldn't complete that."
        status = "failed"
    return HandoffResult(
        ok=ok,
        status=status,
        user_message=user,
        debug_reason=debug,
        task_id=task_id or None,
    )


def launch_handoff(
    *,
    ok: bool,
    app_name: str,
    window_title: str = "",
    debug_reason: str = "",
) -> HandoffResult:
    """Handoff for sync launch specialist — bubble sees user_message only."""
    title = window_title or app_name
    if ok:
        return HandoffResult(
            ok=True,
            status="success",
            user_message=f"Opened {title}.",
            debug_reason=debug_reason or f"foreground:{title}",
        )
    return HandoffResult(
        ok=False,
        status="failed",
        user_message=f"Couldn't open {app_name}.",
        debug_reason=debug_reason or "launch_verify_failed",
    )
