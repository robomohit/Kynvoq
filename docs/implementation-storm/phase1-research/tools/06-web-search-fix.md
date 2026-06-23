# Lane C06: `web_search` Fix

**Category:** tools  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`logs/07-web-search-failures.md`](../../subagent-storm/logs/07-web-search-failures.md).

## Current code paths
- Live `web_search` in `textbox_overlay._live_web_search` (~2608)
- ~75% fail rate in logs

## Gap analysis
SSRF guards, empty query, provider errors surfaced poorly.

## Proposed implementation
Validate query non-empty; retry once; return `sources` + summary; honest failure message; consider Google Search tool when `GEMINI_LIVE_SEARCH=1`.

## Files to touch (Phase 2)
- `textbox_overlay.py`
- `app/providers.py`

## Test strategy
- `tests/test_ssrf_guards.py`

## Estimated complexity
**M**

## Phase 2 workstream hint
WS5
