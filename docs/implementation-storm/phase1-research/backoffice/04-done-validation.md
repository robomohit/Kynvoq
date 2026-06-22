# Lane D04: Done / Complete Validation

**Category:** backoffice  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`logs/08-complete-honesty-patterns.md`](../../subagent-storm/logs/08-complete-honesty-patterns.md).

## Current code paths
- `_task_complete_from_log` in `main.py`
- Agent `complete` tool

## Gap analysis
Ultra-short tasks (≤6 lines) false-complete.

## Proposed implementation
Minimum step count OR explicit verify action before `complete: true`; skepticism for launch-only goals.

## Files to touch (Phase 2)
- `app/agent.py`
- `app/main.py`

## Test strategy
- `tests/test_finish_reason.py`

## Estimated complexity
**M**

## Phase 2 workstream hint
WS6
