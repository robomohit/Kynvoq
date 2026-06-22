"""Central bubble text sanitizer (WS4) — denylist before every emit."""
from __future__ import annotations

import re

# Patterns that must never appear in the user-facing bubble while Live runs.
_BUBBLE_DENY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Server\s+restarted\s+or\s+task\s+was\s+abandoned", re.I),
    re.compile(r"Failed:\s*Server\s+restarted", re.I),
    re.compile(r"\bAutomationId\b|\bControlType\b|\bBoundingRectangle\b"),
    re.compile(r"^\s*\{[\s\S]*\}\s*$"),
    re.compile(r"^\s*\[[\s\S]*\]\s*$"),
)

_UIA_DUMP_RE = re.compile(
    r"(Name|AutomationId|ControlType|ClassName)\s*[:=]",
    re.I,
)


def sanitize_bubble_text(text: str, *, source: str = "") -> str:
    """Return user-safe bubble text, or empty string if denied."""
    label = re.sub(r"\s+", " ", str(text or "")).strip()
    if not label:
        return ""
    for pat in _BUBBLE_DENY_PATTERNS:
        if pat.search(label):
            return "Couldn't complete that" if label.lower().startswith("failed:") else ""
    if _UIA_DUMP_RE.search(label) and source not in ("live_tool",):
        return ""
    if label.lower().startswith("failed:") and source not in (
        "live_error",
        "live_stop",
    ):
        return "Couldn't complete that"
    if "abandoned" in label.lower() and "task" in label.lower():
        return ""
    return label
