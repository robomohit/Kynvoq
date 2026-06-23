# Lane D05: `build_task_payload`

**Category:** backoffice  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`backoffice/09-task-payload-build-review.md`](../../subagent-storm/backoffice/09-task-payload-build-review.md).

## Current code paths
- `_build_task_payload` in overlay
- POST body schema

## Gap analysis
TASK: prefix added inconsistently; metadata missing mode.

## Proposed implementation
Single builder function; fields: user_goal, prompt_goal, mode, source=live, parent_session_id.

## Files to touch (Phase 2)
- `textbox_overlay.py`
- `main.py`

## Test strategy
- Payload contract tests

## Estimated complexity
**S**

## Phase 2 workstream hint
WS3
