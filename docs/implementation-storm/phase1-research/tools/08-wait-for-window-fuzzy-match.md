# Lane C08: `wait_for_window` Fuzzy Match

**Category:** tools  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`logs/03-failed-wait-for-window.md`](../../subagent-storm/logs/03-failed-wait-for-window.md).

## Current code paths
- Agent tool `wait_for_window` exact title match

## Gap analysis
Fails on "Spotify Premium" vs "Spotify", localized titles.

## Proposed implementation
Normalize titles; substring + Levenshtein; configurable timeout; return best match hwnd.

## Files to touch (Phase 2)
- `app/tools.py`

## Test strategy
- Unit tests with title pairs

## Estimated complexity
**S**

## Phase 2 workstream hint
WS6
