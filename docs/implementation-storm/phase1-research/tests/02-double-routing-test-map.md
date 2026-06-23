# Lane G02: Double Routing Test Map

**Category:** tests  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
reliability/02; test_gemini_live.

## Current code paths
Batch gate tests partial.

## Gap analysis
No test for launch+desktop_control batch.

## Proposed implementation
Extend test_gemini_live with multi-tool batches per exclusion group.

## Files to touch (Phase 2)
- `tests/test_gemini_live.py`

## Test strategy
pytest

## Estimated complexity
**S**

## Phase 2 workstream hint
WS2
