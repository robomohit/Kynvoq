# Lane E01: Phase 3 Browser Agent Scenarios

**Category:** live-test-plan  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
LOAD-TEST-PLAN; browser specialist lane A06.

## Current code paths
Scripts: `scripts/live_tool_smoke.py`, `tests/test_browser_plugin.py` (offline).

## Gap analysis
No Live browser E2E script.

## Proposed implementation
Scenarios: (1) open example.com read title (2) form fill with consent (3) search result citation. Env: `GEMINI_API_KEY`, `ORYNN_LABEL_LOG=1`. Success: handoff summary spoken, no raw DOM in bubble.

## Files to touch (Phase 2)
- `scripts/live_browser_matrix.py` (new in Phase 3)

## Test strategy
Manual Phase 3; 1 agent sequential

## Estimated complexity
**M**

## Phase 2 workstream hint
Phase 3 only
