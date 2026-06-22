# Lane A16: Resume Idle Worker by Task ID

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
SYNTHESIS Antigravity idle→running; task retry ad hoc.

## Current code paths
- Task poll by ID in overlay
- `session_resumption` for Live WS only

## Gap analysis
User "yeah sure" retriggers new task instead of resuming `clicky-*`.

## Proposed implementation
Add `resume_desktop_task(task_id, message)` Live tool; backend appends goal to paused/running task context.

## Files to touch (Phase 2)
- `app/main.py` task API
- `gemini_live.py`

## Test strategy
- API tests for resume endpoint

## Estimated complexity
**L** (P2)

## Phase 2 workstream hint
WS3 Task Lifecycle
