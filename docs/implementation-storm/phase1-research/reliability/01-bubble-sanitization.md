# Lane B01: Bubble Sanitization

**Category:** reliability  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`reliability/03-bubble-leak-regression.md`](../../subagent-storm/reliability/03-bubble-leak-regression.md).

## Current code paths
- `_set_label` arbitration (`textbox_overlay.py:853-893`)
- `VirtualCursorOverlay` companion lock
- Humanized `LIVE_DESKTOP_ACTION_LABELS`

## Gap analysis
Edge leaks: raw `output` on desktop_control fail, `Started:` goal echo, agent STEP lines if source mis-tagged.

## Proposed implementation
Central `_sanitize_bubble_text(text, source)` denylist: `Failed:`, `Server restarted`, UIA regex, JSON blobs. Apply before any emit.

## Files to touch (Phase 2)
- `app/widget/textbox_overlay.py`
- `app/widget/virtual_cursor.py`

## Test strategy
- `tests/test_quiet_companion.py`
- `tests/test_gemini_live.py`

## Estimated complexity
**S**

## Phase 2 workstream hint
WS4 Bubble & Speech Sanitization
