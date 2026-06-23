# Lane B06: `send_task_update` Proactive Speech

**Category:** reliability  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`reliability/04-proactive-speech-gaps.md`](../../subagent-storm/reliability/04-proactive-speech-gaps.md).

## Current code paths
- `gemini_live.send_task_update` (`gemini_live.py:634`)
- Called from `_capture_live_task_outcome` (`textbox_overlay.py:2420+`)

## Gap analysis
Silent turns when task completes but Live doesn't speak; user stares at muted bubble.

## Proposed implementation
Always call `send_task_update(user_message)` on terminal task; include `force_speak` for failures; debounce duplicates.

## Files to touch (Phase 2)
- `gemini_live.py`
- `textbox_overlay.py`

## Test strategy
- `tests/test_live_robustness.py`

## Estimated complexity
**S**

## Phase 2 workstream hint
WS4
