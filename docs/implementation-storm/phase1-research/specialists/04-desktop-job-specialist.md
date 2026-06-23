# Lane A04: Desktop Job Specialist (`start_desktop_task`)

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
SYNTHESIS generic worker; [`backoffice/04-main-task-lifecycle-review.md`](../../subagent-storm/backoffice/04-main-task-lifecycle-review.md).

## Current code paths
- `textbox_overlay._live_start_desktop_task` → POST `/api/tasks`
- `_await_task_outcome` poll loop (`textbox_overlay.py:2646+`)
- Backend: `agent.py` ReAct loop, `main.py` lifecycle

## Gap analysis
Full agent is default bucket for everything multi-step. No structured handoff schema; `reason` field leaks to bubble if gates fail.

## Proposed implementation
Wrap as `desktop_job` specialist: always background, returns `{task_id, user_message, status, debug_reason}`; Live uses `send_task_update` for narration; bubble policy mutes `task_result`.

## Files to touch (Phase 2)
- `app/widget/textbox_overlay.py`
- `app/main.py`
- `app/agent.py`

## Test strategy
- `tests/test_task_abandon_grace.py`
- `tests/test_live_robustness.py`

## Estimated complexity
**L**

## Phase 2 workstream hint
WS3 Task Lifecycle & Handoff
