# Lane D08: `main.py` Task Lifecycle

**Category:** backoffice  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`backoffice/04-main-task-lifecycle-review.md`](../../subagent-storm/backoffice/04-main-task-lifecycle-review.md); proposals/05.

## Current code paths
- Spawn, poll, serialize, abandon, queue (`main.py`)
- Watchdog `_TASK_MAX_RUNTIME`

## Gap analysis
Complex state machine; GET side effects persist terminal.

## Proposed implementation
State diagram doc + reduce persist-on-GET; explicit transitions only via agent completion.

## Files to touch (Phase 2)
- `app/main.py`

## Test strategy
- `tests/test_task_abandon_grace.py`
- `tests/test_stream_terminal.py`

## Estimated complexity
**L**

## Phase 2 workstream hint
WS3
