# Lane G01: Bubble Sanitization Test Map

**Category:** tests  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
storm tests/01-gemini-live; reliability/03.

## Current code paths
- `test_quiet_companion.py`
- `test_gemini_live.py`
- `test_voice_and_env.py`

## Gap analysis
Missing: sanitizer unit tests for denylist patterns.

## Proposed implementation
Add `test_bubble_sanitizer.py` with table cases from storm leak table.

## Files to touch (Phase 2)
- `tests/test_bubble_sanitizer.py` (Phase 2)

## Test strategy
pytest offline

## Estimated complexity
**S**

## Phase 2 workstream hint
WS4
