# Lane B05: Abandon Race (`main.py`)

**Category:** reliability  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`reliability/01-task-abandon-race.md`](../../subagent-storm/reliability/01-task-abandon-race.md); [`proposals/05-task-spawn-fix.md`](../../subagent-storm/proposals/05-task-spawn-fix.md).

## Current code paths
- `_serialize_task_record` grace (`main.py:608-646`, `_TASK_START_GRACE`)
- `_task_done_exception` for honest reasons

## Gap analysis
Grace window may be too short on slow disks; GET still persists terminal in edge cases.

## Proposed implementation
Verify grace constant; add `startup_phase` flag on record until first agent signal; never persist failed on GET without agent verdict.

## Files to touch (Phase 2)
- `app/main.py`

## Test strategy
- `tests/test_task_abandon_grace.py` (extend)

## Estimated complexity
**M**

## Phase 2 workstream hint
WS3 Task Lifecycle & Handoff
