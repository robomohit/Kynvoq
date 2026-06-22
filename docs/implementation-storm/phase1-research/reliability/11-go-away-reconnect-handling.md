# Lane B11: `go_away` Reconnect Handling

**Category:** reliability  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`reliability/07-go-away-reconnect-storm.md`](../../subagent-storm/reliability/07-go-away-reconnect-storm.md).

## Current code paths
- `_handle_message:go_away` logging (`gemini_live.py`)
- `session_resumption` handle

## Gap analysis
Reconnect drops in-flight tool results; generation guard stale errors.

## Proposed implementation
On reconnect: replay pending task outcomes; extend generation token; don't fail active desktop tasks.

## Files to touch (Phase 2)
- `gemini_live.py`

## Test strategy
- Simulated reconnect unit test

## Estimated complexity
**M**

## Phase 2 workstream hint
WS3 (P2)
