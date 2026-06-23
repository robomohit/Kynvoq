# Lane C04: UIA Tree Cache MVP

**Category:** tools  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
[`proposals/02-uia-tree-cache.md`](../../subagent-storm/proposals/02-uia-tree-cache.md).

## Current code paths
- `_uia_find_cache` on ToolExecutor (`tools.py:508`)
- Per-session dict

## Gap analysis
Cache not shared across tools; no TTL; full tree walks on hot paths.

## Proposed implementation
MVP: hwnd-keyed cache, 2s TTL, invalidate on focus change; wire into `uia_click` tier-1.

## Files to touch (Phase 2)
- `app/tools.py`

## Test strategy
- Benchmark test optional

## Estimated complexity
**M**

## Phase 2 workstream hint
WS6 Back Office Tools
