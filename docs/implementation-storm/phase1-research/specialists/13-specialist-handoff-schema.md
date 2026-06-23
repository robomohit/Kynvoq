# Lane A13: Specialist Handoff Schema

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
SYNTHESIS sanitized handoff; [`reliability/03-structured-handoff`](../../subagent-storm/reliability/03-bubble-leak-regression.md) (related).

## Current code paths
- Ad hoc dict keys in tool responses
- Task `reason` field freeform

## Gap analysis
No stable contract between worker and Live; JSON leaks in `reason`.

## Proposed implementation
Standardize `HandoffResult` TypedDict: `user_message: str`, `status: success|failed|partial`, `debug_reason: str`, `task_id?: str`. All specialists return this; bubble/voice read `user_message` only.

## Files to touch (Phase 2)
- `app/models/handoff.py` (new)
- `textbox_overlay._capture_live_task_outcome`

## Test strategy
- Schema validation tests
- Golden Spotify handoff

## Estimated complexity
**M**

## Phase 2 workstream hint
WS3 Task Lifecycle & Handoff
