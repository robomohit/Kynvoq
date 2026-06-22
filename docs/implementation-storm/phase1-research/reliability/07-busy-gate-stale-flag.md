# Lane B07: Busy Gate Stale Flag

**Category:** reliability  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`reliability/06-busy-gate-stale-flag.md`](../../subagent-storm/reliability/06-busy-gate-stale-flag.md).

## Current code paths
- `_active_task_running` / busy checks in `_live_tool`
- Label "Busy:" (`textbox_overlay.py:2168`)

## Gap analysis
Flag not cleared on crash/restart; blocks fast path clicks.

## Proposed implementation
Clear busy on terminal poll, server restart, and `stop_current_task`; TTL watchdog 30s; expose `busy_reason` in tool response.

## Files to touch (Phase 2)
- `textbox_overlay.py`
- `main.py` task terminal webhook optional

## Test strategy
- `tests/test_queue_resilience.py`

## Estimated complexity
**S**

## Phase 2 workstream hint
WS3
