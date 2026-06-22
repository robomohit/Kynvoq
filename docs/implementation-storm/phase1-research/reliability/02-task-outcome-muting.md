# Lane B02: Task Outcome Muting Under Live

**Category:** reliability  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
03-bubble-leak § task_result mute.

## Current code paths
- `task_outcome_under_live` mute reason (`textbox_overlay.py:880-884`)
- `ORYNN_LABEL_LOG` diagnostics (`textbox_overlay.py:341-345`)

## Gap analysis
Poll thread may still update internal state shown elsewhere; `task_prime` timing edge cases.

## Proposed implementation
Ensure ALL terminal paths (`failed`, `complete`, `cancelled`) use mute + `_capture_live_task_outcome` only.

## Files to touch (Phase 2)
- `textbox_overlay.py` poll loop

## Test strategy
- Label log assertions in `test_quiet_companion`

## Estimated complexity
**S**

## Phase 2 workstream hint
WS4
