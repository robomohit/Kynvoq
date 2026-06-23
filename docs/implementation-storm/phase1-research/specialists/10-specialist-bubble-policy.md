# Lane A10: Specialist Bubble Policy

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`reliability/03-bubble-leak-regression.md`](../../subagent-storm/reliability/03-bubble-leak-regression.md).

## Current code paths
- `_set_label` mute rule (`textbox_overlay.py:873-884`)
- `_LIVE_LABEL_SOURCES` / `_TASK_CHURN_SOURCES`

## Gap analysis
Per-specialist bubble rules not encoded; workers can still set `live_tool` with raw output.

## Proposed implementation
Each `SpecialistSpec.bubble_policy`: `user_message_only | tool_label | mute`. Central sanitizer strips `Failed:`, JSON, UIA dumps before emit.

## Files to touch (Phase 2)
- `app/widget/textbox_overlay.py`
- `app/specialists/registry.py`

## Test strategy
- `tests/test_quiet_companion.py`
- `tests/test_gemini_live.py`

## Estimated complexity
**S**

## Phase 2 workstream hint
WS4 Bubble & Speech Sanitization
