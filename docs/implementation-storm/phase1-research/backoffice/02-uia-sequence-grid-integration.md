# Lane D02: `uia_click_sequence` + Grid Integration

**Category:** backoffice  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`backoffice/03-tools-uia-sequence-review.md`](../../subagent-storm/backoffice/03-tools-uia-sequence-review.md); [`05-grid-locate-improvements.md`](../../subagent-storm/backoffice/05-grid-locate-improvements.md).

## Current code paths
- `uia_click_sequence` orchestration
- `grid_locate.py` vision tier

## Gap analysis
Sequence aborts don't report which step failed; grid not used in sequence fallback.

## Proposed implementation
Per-step HandoffResult; on UIA miss in sequence, try grid for that step only.

## Files to touch (Phase 2)
- `app/tools.py`
- `app/grid_locate.py`

## Test strategy
- `tests/test_grid_locate.py`

## Estimated complexity
**M**

## Phase 2 workstream hint
WS6
