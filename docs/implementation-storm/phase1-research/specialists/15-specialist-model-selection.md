# Lane A15: Specialist Model Selection

**Category:** specialists  
**Status:** complete  
**Date:** 2026-06-22

## Storm lineage
SYNTHESIS model flexibility; `GEMINI_LIVE_THINKING_LEVEL`.

## Current code paths
- Single Live model session
- Back-office uses provider routing in `providers.py`

## Gap analysis
Cannot use fast cheap model for explore/verify while keeping strong model for desktop_job.

## Proposed implementation
Add `model_tier: fast|standard` per specialist; vision_peek/verify may use lighter describe model; desktop_job unchanged.

## Files to touch (Phase 2)
- `app/providers.py`
- `app/specialists/registry.py`

## Test strategy
- Mock provider selection assertions

## Estimated complexity
**M** (P2)

## Phase 2 workstream hint
WS2 or defer
