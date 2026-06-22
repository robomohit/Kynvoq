# Lane C09: `detect_app_launch_intent` Hardening

**Category:** tools  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
Storm reliability/10; `tools.py:471-488`.

## Current code paths
Regex verb match + exact registry only.

## Gap analysis
"Open Spotify and play" correctly rejected but "open spotify" fails if not in dict.

## Proposed implementation
After registry expansion, add fuzzy app name match; telemetry on None returns.

## Files to touch (Phase 2)
- `app/tools.py`

## Test strategy
- `tests/test_fast_path.py`

## Estimated complexity
**S**

## Phase 2 workstream hint
WS1
