# Lane B03: Structured Handoff Worker → Live

**Category:** reliability  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
SYNTHESIS P0 #1; proposals/05-task-spawn-fix.

## Current code paths
- `_await_task_outcome` builds tool response
- `send_task_update` for proactive speech

## Gap analysis
Freeform `reason` and `message` fields; Live improvises from raw failure strings.

## Proposed implementation
Map task terminal → `HandoffResult`; `message` field = `user_message`; never pass `record.reason` to bubble.

## Files to touch (Phase 2)
- `textbox_overlay._capture_live_task_outcome`
- `app/models/handoff.py`

## Test strategy
- Golden handoff fixtures from `tasks/clicky-c6beede9be.json`

## Estimated complexity
**M**

## Phase 2 workstream hint
WS3
