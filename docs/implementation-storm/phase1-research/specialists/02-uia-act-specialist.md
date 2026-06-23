# Lane A02: UIA Act Specialist (`desktop_control`)

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`backoffice/08-desktop-control-route-review.md`](../../subagent-storm/backoffice/08-desktop-control-route-review.md), [`backoffice/02-tools-uia-click-review.md`](../../subagent-storm/backoffice/02-tools-uia-click-review.md).

## Current code paths
- Declaration: `gemini_live._function_declarations` → `desktop_control`
- Execution: `textbox_overlay._desktop_control_route` (~1761), `_live_desktop_control` with `fast_invoke_only=True`
- Escalation to full task on UIA miss (~1848 "Trying the full agent")

## Gap analysis
Specialist exists as a tool, not a profile. Raw UIA diagnostics can still leak on failure paths. Model batches with `start_desktop_task`.

## Proposed implementation
Formalize `uia_act` specialist: allowed actions enum, max 1 gesture, humanized `live_tool` labels (`LIVE_DESKTOP_ACTION_LABELS`), structured `{ok, action, user_message, escalate?}`. Enforce mutual exclusion at registry level.

## Files to touch (Phase 2)
- `app/widget/textbox_overlay.py`
- `app/widget/gemini_live.py`
- `app/tools.py` — `uia_click` ladder

## Test strategy
- `tests/test_gemini_live.py` — desktop_control contracts
- `tests/test_computer_control_regressions.py`

## Estimated complexity
**S** (mostly contract + labeling)

## Phase 2 workstream hint
WS2 Live Front Desk & Specialists
