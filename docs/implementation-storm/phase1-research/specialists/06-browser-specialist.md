# Lane A06: Browser Specialist

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
SYNTHESIS missing built-in; [`proposals/07-playwright-connectors.md`](../../subagent-storm/proposals/07-playwright-connectors.md); `agent.py` headless browser mode.

## Current code paths
- Back-office `browser_*` tools in `agent.py` / `ToolExecutor`
- Not exposed as Live built-in with Antigravity `/browser` contract

## Gap analysis
Web tasks route to generic desktop_job or failing `web_search` (~75% fail in logs).

## Proposed implementation
Expose `browser_task` Live tool → spawns readonly/write browser sub-loop with Playwright; summary-only handoff; sandbox domain allowlist.

## Files to touch (Phase 2)
- `app/agent.py` browser profile
- `app/widget/gemini_live.py`
- `tests/test_browser_plugin.py`

## Test strategy
- Extend `test_browser_plugin.py`
- Phase 3 browser scenarios (live-test-plan/01)

## Estimated complexity
**L**

## Phase 2 workstream hint
WS5 Browser & Web (optional P1)
