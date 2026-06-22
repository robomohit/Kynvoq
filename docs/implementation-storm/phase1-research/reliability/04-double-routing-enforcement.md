# Lane B04: Double Routing Enforcement

**Category:** reliability  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`reliability/02-double-routing-live.md`](../../subagent-storm/reliability/02-double-routing-live.md).

## Current code paths
- Batch gate `gemini_live.py:852-871`
- Overlay escalation paths

## Gap analysis
22 dual-tool batches in log; model ignores prompt.

## Proposed implementation
1. Keep batch gate. 2. Log metric `double_route_blocked`. 3. Consider collapsing to single `desktop_action` tool with `mode: fast|full`. 4. Prompt reinforcement with negative examples.

## Files to touch (Phase 2)
- `gemini_live.py`
- Optional declaration merge

## Test strategy
- `tests/test_gemini_live.py`
- Count metric in Phase 4 logs

## Estimated complexity
**M**

## Phase 2 workstream hint
WS2
